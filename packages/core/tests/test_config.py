from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from quant_core.config import (
    AgentRole,
    ConfigError,
    ConfigStore,
    LLMProvidersConfig,
    OnError,
    PipelineConfig,
    ProviderKind,
    StructuredOutputMode,
    config_hash,
    interpolate_env,
    load_model,
)
from quant_core.models import RunMode

ENV = {"IBKR_ACCOUNT": "DU123"}
WriteYaml = Callable[[Path, Any], Path]


# ------------------------------------------------------------------ interpolation


def test_interpolate_env_nested() -> None:
    data = {"a": "${X}", "b": ["pre-${Y:-dflt}-post", 3], "c": {"d": "$${LITERAL}"}, "e": None}
    out = interpolate_env(data, {"X": "1"})
    assert out == {"a": "1", "b": ["pre-dflt-post", 3], "c": {"d": "${LITERAL}"}, "e": None}


def test_interpolate_env_empty_value_uses_default() -> None:
    assert interpolate_env("${X:-d}", {"X": ""}) == "d"


def test_interpolate_env_reports_all_missing() -> None:
    with pytest.raises(ConfigError, match="missing environment variables: A, B"):
        interpolate_env({"x": "${B}", "y": ["${A}"]}, {})


# ------------------------------------------------------------------ store


def test_load_full_pipeline(configs_dir: Path) -> None:
    store = ConfigStore(configs_dir, env=ENV)
    pipeline = store.validate_pipeline("long_term_stocks")
    assert pipeline.mode is RunMode.PAPER
    assert pipeline.universe == ["AAPL", "MSFT"]
    assert pipeline.budget.max_capital == Decimal(5000)
    decision = pipeline.stage("decision")
    assert decision is not None
    assert decision.agents[0].count == 2
    assert pipeline.stage("missing") is None
    assert store.list("pipelines") == ["long_term_stocks"]


def test_account_env_interpolation(configs_dir: Path) -> None:
    account = ConfigStore(configs_dir, env=ENV).account("ibkr_main")
    assert account.account_id == "DU123"
    assert account.host == "127.0.0.1"


def test_missing_env_names_file(configs_dir: Path) -> None:
    with pytest.raises(ConfigError, match=r"ibkr_main\.yaml: missing environment variables"):
        ConfigStore(configs_dir, env={}).account("ibkr_main")


def test_agent_loaded_and_prompt_checked(configs_dir: Path) -> None:
    store = ConfigStore(configs_dir, env=ENV)
    agent = store.agent("value_investor")
    assert agent.role is AgentRole.DECISION
    assert agent.registry_key == "decision"
    (configs_dir / "agents" / "prompts" / "test_v1.j2").unlink()
    with pytest.raises(ConfigError, match="prompt template"):
        store.agent("value_investor")


def test_file_name_must_match_id(
    configs_dir: Path, write_yaml: WriteYaml, agent_yaml: Callable[[str, str], dict[str, Any]]
) -> None:
    write_yaml(configs_dir / "agents" / "other.yaml", agent_yaml("value_investor", "decision"))
    with pytest.raises(ConfigError, match="must match the file name"):
        ConfigStore(configs_dir, env=ENV).agent("other")


def test_missing_file_and_bad_yaml(configs_dir: Path) -> None:
    store = ConfigStore(configs_dir, env=ENV)
    with pytest.raises(ConfigError, match="not found"):
        store.pipeline("nope")
    (configs_dir / "pipelines" / "broken.yaml").write_text("a: [1, 2", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        store.pipeline("broken")


def test_validate_pipeline_collects_reference_errors(
    configs_dir: Path, pipeline_data: dict[str, Any], write_yaml: WriteYaml
) -> None:
    data = pipeline_data
    data["account"] = "nope"
    data["stages"][2]["agents"] = [{"agent": "retail_mood"}, {"agent": "ghost"}]
    write_yaml(configs_dir / "pipelines" / "long_term_stocks.yaml", data)
    with pytest.raises(ConfigError) as info:
        ConfigStore(configs_dir, env=ENV).validate_pipeline("long_term_stocks")
    message = str(info.value)
    assert "nope.yaml" in message
    assert "ghost.yaml" in message
    assert "stage decision cannot use sentiment agent retail_mood" in message


def test_llm_providers_loaded(configs_dir: Path) -> None:
    providers = ConfigStore(configs_dir, env=ENV).llm_providers().providers
    assert set(providers) == {"anthropic", "deepseek"}
    assert providers["deepseek"].kind is ProviderKind.OPENAI_COMPATIBLE
    assert providers["deepseek"].structured_output is StructuredOutputMode.JSON_OBJECT
    assert providers["anthropic"].base_url is None


def test_agent_with_unknown_provider_is_reported(
    configs_dir: Path, write_yaml: WriteYaml, agent_yaml: Callable[[str, str], dict[str, Any]]
) -> None:
    data = agent_yaml("value_investor", "decision")
    data["model"]["provider"] = "mystery"
    write_yaml(configs_dir / "agents" / "value_investor.yaml", data)
    with pytest.raises(ConfigError, match="unknown LLM provider 'mystery'"):
        ConfigStore(configs_dir, env=ENV).validate_pipeline("long_term_stocks")


def test_missing_provider_file_is_reported(configs_dir: Path) -> None:
    (configs_dir / "llm_providers.yaml").unlink()
    with pytest.raises(ConfigError, match=r"llm_providers\.yaml"):
        ConfigStore(configs_dir, env=ENV).validate_pipeline("long_term_stocks")


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        ({"kind": "grok"}, "kind"),
        ({"kind": "anthropic", "base_url": "api.x.com"}, "must start with http"),
        ({"kind": "anthropic", "api_key_env": "has space"}, "pattern"),
        ({"kind": "anthropic", "api_key": "sk-inline"}, "Extra inputs"),
    ],
)
def test_provider_config_validation(provider: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        LLMProvidersConfig.model_validate({"providers": {"p": provider}})


def test_provider_names_must_be_snake_case() -> None:
    with pytest.raises(ValidationError, match="lower_snake_case"):
        LLMProvidersConfig.model_validate({"providers": {"DeepSeek": {"kind": "anthropic"}}})


def test_load_model_wraps_validation_error(tmp_path: Path, write_yaml: WriteYaml) -> None:
    class M(BaseModel):
        x: int

    path = write_yaml(tmp_path / "m.yaml", {"x": "not-an-int"})
    with pytest.raises(ConfigError, match="invalid M"):
        load_model(path, M, env={})


# ------------------------------------------------------------------ pipeline rules


def _pipeline(base: dict[str, Any], **changes: Any) -> PipelineConfig:
    return PipelineConfig.model_validate({**base, **changes})


def _stages(*types: str, **overrides: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"type": t, **overrides.get(t, {})} for t in types]


def test_default_mode_is_dry_run(pipeline_data: dict[str, Any]) -> None:
    del pipeline_data["mode"]
    assert PipelineConfig.model_validate(pipeline_data).mode is RunMode.DRY_RUN


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"universe": []}, "at least 1"),
        ({"universe": ["AAPL", "aapl"]}, "duplicate symbols"),
        ({"universe": ["AAPL", " "]}, "empty symbol"),
        ({"budget": {"max_capital": 0}}, "greater than 0"),
        ({"name": "Bad-Name"}, "pattern"),
        ({"mode": "yolo"}, "mode"),
        ({"stages": _stages("decision", "decision")}, "duplicate stage types"),
        ({"stages": _stages("decision", "sentiment")}, "out of order"),
        ({"stages": _stages("decision", "trading")}, "requires an enabled risk stage"),
        ({"stages": _stages("decision", "trading", "risk")}, "out of order"),
        (
            {"stages": _stages("decision", "risk", "trading", risk={"enabled": False})},
            "requires an enabled risk stage",
        ),
        (
            {"stages": _stages("risk", "trading", risk={"on_error": "skip"})},
            "may not use on_error: skip",
        ),
    ],
)
def test_pipeline_validation_errors(
    pipeline_data: dict[str, Any], changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _pipeline(pipeline_data, **changes)


def test_disabled_stages_and_custom_stages_are_ignored_for_order(
    pipeline_data: dict[str, Any],
) -> None:
    p = _pipeline(
        pipeline_data,
        stages=_stages("my_custom", "decision", "sentiment", sentiment={"enabled": False}),
    )
    assert [s.type for s in p.stages] == ["my_custom", "decision", "sentiment"]


def test_stage_options(pipeline_data: dict[str, Any]) -> None:
    class TradingOptions(BaseModel):
        order_type: str
        limit_offset_bps: int
        on_error: OnError

    stage = _pipeline(pipeline_data).stage("trading")
    assert stage is not None
    opts = stage.options(TradingOptions)
    assert opts.limit_offset_bps == 5
    assert opts.on_error is OnError.ABORT


def test_config_hash_is_stable_and_sensitive(pipeline_data: dict[str, Any]) -> None:
    a, b = _pipeline(pipeline_data), _pipeline(pipeline_data)
    assert config_hash(a) == config_hash(b)
    assert len(config_hash(a)) == 64
    assert config_hash(a) != config_hash(_pipeline(pipeline_data, universe=["AAPL"]))


def test_store_load_generic_kind(configs_dir: Path, write_yaml: WriteYaml) -> None:
    class Limits(BaseModel):
        name: str
        max_trades: int

    write_yaml(configs_dir / "risk" / "tight.yaml", {"name": "tight", "max_trades": "${N:-3}"})
    assert ConfigStore(configs_dir, env={}).load("risk", "tight", Limits).max_trades == 3
    with pytest.raises(ConfigError, match="not found"):
        ConfigStore(configs_dir, env={}).load("risk", "missing", Limits)
