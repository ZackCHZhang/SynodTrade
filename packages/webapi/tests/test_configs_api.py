from pathlib import Path

from fastapi.testclient import TestClient

from quant_webapi.configs import BACKUP_DIR, ConfigFiles

PIPELINE = "long_term_stocks"


def test_meta_has_a_schema_for_every_stage(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert set(meta["schemas"]["stages"]) == set(meta["stage_order"])
    assert set(meta["registry"]["stages"]) >= set(meta["stage_order"])
    assert {"ibkr_scanner", "static"} <= set(meta["schemas"]["candidate_sources"])
    assert {"reddit", "stocktwits", "ibkr_news"} <= set(meta["schemas"]["sentiment_sources"])
    assert meta["env"]["DEEPSEEK_API_KEY"] is True  # presence only, never the value
    assert "k" not in str(meta["env"].values())
    assert meta["offline_db"] is True


def test_list_and_read(client: TestClient) -> None:
    listing = client.get("/api/configs").json()
    assert {e["name"] for e in listing["pipelines"]} >= {PIPELINE, "demo_all_modules"}
    agent = next(e for e in listing["agents"] if e["name"] == "value_investor")
    assert agent["role"] == "decision"
    assert agent["avatar"].startswith("https://")
    plain = next(e for e in listing["agents"] if e["name"] == "kelly_sizer")
    assert plain["avatar"] is None  # no picture configured: the console draws a placeholder
    assert listing["schedules"][0]["name"] == "schedules"
    file = client.get("/api/configs/agents/value_investor").json()
    assert "persona:" in file["text"]
    assert [u for u in file["used_by"] if not u.startswith("pipelines/arena_")] == [
        "pipelines/demo_all_modules",
        "pipelines/etf_allocation",
        f"pipelines/{PIPELINE}",
    ]
    assert client.get("/api/configs/agents/nope").status_code == 404


def test_names_cannot_escape_the_configs_dir(client: TestClient) -> None:
    assert client.get("/api/configs/pipelines/..%2F..%2Fsecret").status_code in (400, 404)
    assert (
        client.post("/api/configs/pipelines", json={"name": "../x", "text": ""}).status_code == 400
    )


def test_every_repo_config_validates(client: TestClient) -> None:
    for kind, entries in client.get("/api/configs").json().items():
        for entry in entries:
            text = client.get(f"/api/configs/{kind}/{entry['name']}").json()["text"]
            result = client.post(
                f"/api/configs/{kind}/{entry['name']}/validate", json={"text": text}
            ).json()
            assert result["ok"], (kind, entry["name"], result["errors"])


def test_validation_reports_located_problems(client: TestClient) -> None:
    text = """name: long_term_stocks
account: nope
budget: {max_capital: 5}
universe: [AAPL]
stages:
  - type: decision
    agents: [{agent: retail_mood, model: {provider: deepseek, name: x}}]
    aggregation: {method: bogus}
    typo_key: 1
  - type: risk
    rules: missing
"""
    result = client.post(f"/api/configs/pipelines/{PIPELINE}/validate", json={"text": text}).json()
    locs = {tuple(p["loc"]) for p in result["errors"]}
    assert ("account",) in locs
    assert ("stages", 0, "aggregation", "method") in locs
    assert ("stages", 0, "agents", 0, "agent") in locs  # sentiment agent in a decision stage
    assert ("stages", 1, "rules") in locs
    assert [tuple(w["loc"]) for w in result["warnings"]] == [("stages", 0, "typo_key")]


def test_yaml_and_template_syntax_errors(client: TestClient) -> None:
    bad = client.post(f"/api/configs/pipelines/{PIPELINE}/validate", json={"text": "a: [1,"})
    assert bad.json()["errors"][0]["line"] is not None
    tpl = client.post(
        "/api/configs/prompts/decision_v1/validate", json={"text": "{{ symbol }} {% if x %}"}
    ).json()
    assert not tpl["ok"]
    ok = client.post(
        "/api/configs/prompts/decision_v1/validate", json={"text": "{{ symbol }} {{ as_of }}"}
    ).json()
    assert ok["info"]["variables"] == ["as_of", "symbol"]


def test_save_checks_version_validity_and_keeps_line_endings(
    client: TestClient, configs: Path
) -> None:
    path = configs / "pipelines" / f"{PIPELINE}.yaml"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    file = client.get(f"/api/configs/pipelines/{PIPELINE}").json()
    text = file["text"].replace("max_capital: 5000", "max_capital: 6000")

    stale = client.put(f"/api/configs/pipelines/{PIPELINE}", json={"text": text, "etag": "0" * 16})
    assert stale.status_code == 409

    invalid = client.put(
        f"/api/configs/pipelines/{PIPELINE}",
        json={"text": text.replace("account: ibkr_main", "account: nope"), "etag": file["etag"]},
    )
    assert invalid.status_code == 422
    assert invalid.json()["diagnostics"]["errors"]

    saved = client.put(
        f"/api/configs/pipelines/{PIPELINE}", json={"text": text, "etag": file["etag"]}
    )
    assert saved.status_code == 200
    raw = path.read_bytes()
    assert b"max_capital: 6000" in raw
    assert raw.count(b"\r\n") == raw.count(b"\n")  # still CRLF everywhere
    backups = list((configs / BACKUP_DIR / "pipelines").glob(f"{PIPELINE}.yaml.*"))
    assert len(backups) == 1
    assert b"max_capital: 5000" in backups[0].read_bytes()


def test_force_saves_semantic_errors_but_never_broken_yaml(client: TestClient) -> None:
    file = client.get(f"/api/configs/pipelines/{PIPELINE}").json()
    text = file["text"].replace("account: ibkr_main", "account: nope")
    forced = client.put(
        f"/api/configs/pipelines/{PIPELINE}",
        json={"text": text, "etag": file["etag"], "force": True},
    )
    assert forced.status_code == 200
    broken = client.put(f"/api/configs/pipelines/{PIPELINE}", json={"text": "a: [", "force": True})
    assert broken.status_code == 422


def test_create_and_delete(client: TestClient, configs: Path) -> None:
    text = (
        client.get("/api/configs/risk/default")
        .json()["text"]
        .replace("name: default", "name: tight")
    )
    created = client.post("/api/configs/risk", json={"name": "tight", "text": text})
    assert created.status_code == 200
    assert (configs / "risk" / "tight.yaml").is_file()
    assert client.post("/api/configs/risk", json={"name": "tight", "text": text}).status_code == 409
    wrong_key = client.post("/api/configs/risk", json={"name": "other", "text": text})
    assert wrong_key.status_code == 422  # name must match the file name
    assert client.delete("/api/configs/risk/tight").status_code == 200
    assert not (configs / "risk" / "tight.yaml").exists()
    assert list((configs / BACKUP_DIR / "risk").glob("tight.yaml.*"))
    assert client.delete("/api/configs/schedules/schedules").status_code == 400


def test_missing_env_is_a_warning_not_an_error(configs: Path) -> None:
    files = ConfigFiles(configs, env={})
    text = (configs / "accounts" / "ibkr_main.yaml").read_text(encoding="utf-8")
    result = files.validate("accounts", "ibkr_main", text)
    assert result.ok
    assert "IBKR_ACCOUNT" in result.warnings[0].message
    providers = files.validate(
        "llm_providers",
        "llm_providers",
        (configs / "llm_providers.yaml").read_text(encoding="utf-8"),
    )
    assert any("ANTHROPIC_API_KEY" in w.message for w in providers.warnings)
