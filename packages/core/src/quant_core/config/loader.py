"""YAML loading with ${ENV} interpolation and Pydantic validation.

Interpolation syntax (only inside string values, after YAML parsing):
    ${NAME}            value of NAME; error if unset
    ${NAME:-default}   value of NAME, or `default` if unset/empty
    $$                 a literal `$`
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from quant_core.config.schemas import (
    STAGE_AGENT_ROLE,
    AccountConfig,
    AgentConfig,
    PipelineConfig,
    resolve_model,
)
from quant_core.llm.config import LLMProvidersConfig

_ENV_REF = re.compile(r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    """Raised for any invalid or missing configuration; the message names the file."""


def interpolate_env(value: Any, env: Mapping[str, str]) -> Any:
    missing: set[str] = set()

    def sub(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            if match.group(0) == "$$":
                return "$"
            name, default = match.group(1), match.group(2)
            found = env.get(name)
            if found:
                return found
            if default is not None:
                return default
            missing.add(name)
            return ""

        return _ENV_REF.sub(repl, text)

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return sub(node)
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        return node

    result = walk(value)
    if missing:
        raise ConfigError(f"missing environment variables: {', '.join(sorted(missing))}")
    return result


def load_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc


def load_model[T: BaseModel](path: Path, model: type[T], env: Mapping[str, str] | None = None) -> T:
    data = load_yaml(path)
    try:
        data = interpolate_env(data, os.environ if env is None else env)
        return model.model_validate(data)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    except ValidationError as exc:
        raise ConfigError(f"{path}: invalid {model.__name__}:\n{exc}") from exc


def config_hash(*models: BaseModel) -> str:
    """Stable sha256 over the given configs, stored with each run for reproducibility."""
    payload = json.dumps(
        [m.model_dump(mode="json") for m in models], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class ConfigStore:
    """Typed access to the configs/ directory."""

    def __init__(self, root: Path, env: Mapping[str, str] | None = None) -> None:
        self.root = root
        self._env = env

    @property
    def agents_dir(self) -> Path:
        """Also the root for agent prompt templates."""
        return self.root / "agents"

    def path(self, kind: str, name: str) -> Path:
        return self.root / kind / f"{name}.yaml"

    def list(self, kind: str) -> list[str]:
        return sorted(p.stem for p in (self.root / kind).glob("*.yaml"))

    def load[T: BaseModel](self, kind: str, name: str, model: type[T]) -> T:
        """Load `configs/<kind>/<name>.yaml` as `model` (for package-specific configs,
        e.g. risk rules), with the same env interpolation and error reporting."""
        return load_model(self.path(kind, name), model, self._env)

    def _load[T: BaseModel](self, kind: str, name: str, model: type[T], key: str) -> T:
        cfg = load_model(self.path(kind, name), model, self._env)
        if getattr(cfg, key) != name:
            raise ConfigError(f"{self.path(kind, name)}: {key} must match the file name {name!r}")
        return cfg

    def pipeline(self, name: str) -> PipelineConfig:
        return self._load("pipelines", name, PipelineConfig, "name")

    def agent(self, agent_id: str) -> AgentConfig:
        cfg = self._load("agents", agent_id, AgentConfig, "agent_id")
        if not (self.agents_dir / cfg.prompt_template).is_file():
            raise ConfigError(f"agent {agent_id}: prompt template {cfg.prompt_template} not found")
        return cfg

    def account(self, name: str) -> AccountConfig:
        return self._load("accounts", name, AccountConfig, "name")

    def llm_providers(self) -> LLMProvidersConfig:
        return load_model(self.root / "llm_providers.yaml", LLMProvidersConfig, self._env)

    def validate_pipeline(self, name: str) -> PipelineConfig:
        """Load a pipeline plus everything it references; raise one error listing all problems."""
        pipeline = self.pipeline(name)
        problems: list[str] = []
        try:
            self.account(pipeline.account)
        except ConfigError as exc:
            problems.append(str(exc))
        providers: set[str] | None = None
        if any(stage.agents for stage in pipeline.stages):
            try:
                providers = set(self.llm_providers().providers)
            except ConfigError as exc:
                problems.append(str(exc))
        for stage in pipeline.stages:
            for ref in stage.agents:
                try:
                    agent = self.agent(ref.agent)
                except ConfigError as exc:
                    problems.append(str(exc))
                    continue
                try:
                    model = resolve_model(agent, ref.model)
                except ValueError as exc:
                    problems.append(f"pipeline {name}, stage {stage.type}: {exc}")
                else:
                    if providers is not None and model.provider not in providers:
                        problems.append(
                            f"agent {agent.agent_id}: unknown LLM provider {model.provider!r}"
                        )
                role = STAGE_AGENT_ROLE.get(stage.type)
                if role is not None and agent.role is not role:
                    problems.append(
                        f"pipeline {name}: stage {stage.type} cannot use {agent.role} "
                        f"agent {agent.agent_id}"
                    )
        if problems:
            raise ConfigError("\n".join(problems))
        return pipeline
