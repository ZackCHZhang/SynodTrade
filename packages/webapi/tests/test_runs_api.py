import asyncio
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from quant_account_sync import AccountSyncService, BrokerSnapshot
from quant_core.config import ConfigStore
from quant_database import Database, Repositories
from quant_market_data import FakeMarketDataProvider
from quant_webapi.app import WebSettings, create_app
from quant_webapi.data import jsonable, mask_url

AS_OF = "2026-09-30T14:00:00Z"
ENV = {"IBKR_ACCOUNT": "DU1234567", "ANTHROPIC_API_KEY": "test-key", "DEEPSEEK_API_KEY": "k"}


def wait_for(client: TestClient, job_id: str, timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("starting", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def start(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/jobs", json={"as_of": AS_OF, **body})
    assert response.status_code == 200, response.text
    job: dict[str, Any] = response.json()
    return job


def test_offline_run_goes_to_the_sandbox_with_live_events(client: TestClient) -> None:
    job = wait_for(
        client,
        start(client, pipeline="demo_all_modules", offline=True, offline_llm="bullish")["id"],
    )
    assert job["status"] == "succeeded", job
    run_id = job["run_id"]
    assert client.get("/api/runs").json()["total"] == 0  # main database untouched
    sandbox = client.get("/api/runs?db=offline").json()
    assert [r["run_id"] for r in sandbox["runs"]] == [run_id]

    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["database"] == "offline"
    assert detail["run"]["status"] == "succeeded"
    assert detail["stock_selection"]["selected"]
    assert detail["orders"]
    assert detail["llm_calls"]
    assert set(detail["progress"]) == set(detail["run"]["stages_run"])
    assert all(p["status"] == "ok" for p in detail["progress"].values())

    call = client.get(f"/api/llm_calls/{detail['llm_calls'][0]['id']}").json()
    assert call["request"]["messages"]

    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        body = "".join(stream.iter_text())
    assert '"event": "pipeline.stage_start"' in body
    assert '"event": "pipeline.finish"' in body
    assert body.rstrip().endswith("event: end\ndata: {}")


def test_rejected_runs_are_reported_immediately(client: TestClient) -> None:
    unknown = start(client, pipeline="does_not_exist", mode="dry_run")
    assert unknown["status"] == "error"
    assert "not found" in unknown["error"]
    assert client.post("/api/jobs", json={"pipeline": "x", "mode": "live"}).status_code == 422


def test_events_of_unknown_runs_end_at_once(client: TestClient) -> None:
    with client.stream("GET", "/api/runs/00000000-0000-0000-0000-000000000000/events") as s:
        assert "event: end" in "".join(s.iter_text())
    assert client.get("/api/runs/00000000-0000-0000-0000-000000000000").status_code == 404


class BlockingMarketData(FakeMarketDataProvider):
    async def connect(self) -> None:
        await asyncio.Event().wait()


def test_cancel_marks_the_run_failed(make_client: Callable[[dict[str, Any]], TestClient]) -> None:
    with make_client({"market_data": BlockingMarketData()}) as client:
        job = start(client, pipeline="long_term_stocks", offline=True)
        assert job["status"] == "running"
        assert job["run_id"]
        client.post(f"/api/jobs/{job['id']}/cancel")
        done = wait_for(client, job["id"])
        assert done["status"] == "cancelled"
        run = client.get(f"/api/runs/{job['run_id']}").json()["run"]
        assert run["status"] == "failed"
        assert run["error"] == "cancelled before completion"


def test_database_browser(client: TestClient) -> None:
    wait_for(client, start(client, pipeline="long_term_stocks", offline=True)["id"])
    tables = {t["name"]: t for t in client.get("/api/db/tables?db=offline").json()}
    assert tables["pipeline_runs"]["rows"] == 1
    assert tables["decisions"]["rows"] == 12
    page = client.get(
        "/api/db/tables/decisions",
        params={"db": "offline", "limit": 5, "sort": "symbol", "desc": "false"},
    ).json()
    assert page["total"] == 12
    assert len(page["rows"]) == 5
    assert page["rows"][0]["cells"]["symbol"] == "AAPL"
    filtered = client.get(
        "/api/db/tables/decisions",
        params={"db": "offline", "filters": '[{"column": "symbol", "op": "eq", "value": "MSFT"}]'},
    ).json()
    assert filtered["total"] == 3
    assert {r["cells"]["symbol"] for r in filtered["rows"]} == {"MSFT"}
    llm = client.get("/api/db/tables/llm_calls", params={"db": "offline", "limit": 1}).json()
    assert "request" in llm["rows"][0]["truncated"]  # long JSON is previewed in the grid
    pk = llm["rows"][0]["cells"]["id"]
    full = client.get(f"/api/db/tables/llm_calls/rows/{pk}", params={"db": "offline"}).json()
    assert isinstance(full["request"], dict)
    bad = client.get(
        "/api/db/tables/decisions", params={"filters": '[{"column": "nope", "op": "eq"}]'}
    )
    assert bad.status_code == 400


def test_overview_portfolio_market_and_kill_switch(client: TestClient) -> None:
    overview = client.get("/api/overview").json()
    assert overview["kill_switch"]["active"] is False
    assert overview["scheduler"]["running"] is False
    portfolio = client.get("/api/portfolio").json()
    assert {p["name"] for p in portfolio["pipelines"]} >= {"long_term_stocks"}
    assert client.get("/api/market/instruments").json() == []
    on = client.put("/api/system/kill-switch", json={"active": True, "reason": "test"}).json()
    assert on == {"active": True, "reason": "test"}
    assert client.get("/api/overview").json()["kill_switch"]["active"] is True
    assert client.put("/api/system/kill-switch", json={"active": False}).json()["active"] is False


def test_scheduler_plan_start_stop(client: TestClient) -> None:
    plan = client.get("/api/scheduler/plan?days=14").json()
    assert [j["id"] for j in plan["jobs"]] == ["long_term_stocks#0", "etf_allocation#0"]
    assert plan["jobs"][0]["upcoming"]
    started = client.post("/api/scheduler/start").json()
    assert started["running"] is True
    assert {j["id"] for j in started["jobs"]} == {"long_term_stocks#0", "etf_allocation#0"}
    assert all(j["next_run"]["utc"] for j in started["jobs"])
    assert client.post("/api/scheduler/stop").json()["running"] is False
    assert client.post("/api/scheduler/bogus").status_code == 404


def test_helpers() -> None:
    assert mask_url("postgresql+asyncpg://quant:secret@db:5432/quant") == (
        "postgresql+asyncpg://quant:***@db:5432/quant"
    )
    assert mask_url("sqlite+aiosqlite:///./x.db") == "sqlite+aiosqlite:///./x.db"
    assert jsonable({"a": Decimal("1.50"), "b": [Decimal("2")]}) == {"a": 1.5, "b": [2.0]}


def test_watchlist_api(client: TestClient) -> None:
    added = client.post(
        "/api/watchlists/demo_all_modules", json={"symbol": "nvda", "pinned": True, "note": "x"}
    )
    assert added.status_code == 200, added.text
    assert added.json()["symbol"] == "NVDA"
    assert added.json()["pinned"] is True
    lists = {p["pipeline"]: p["entries"] for p in client.get("/api/watchlists").json()}
    assert [e["symbol"] for e in lists["demo_all_modules"]] == ["NVDA"]
    assert lists["long_term_stocks"] == []
    assert client.post("/api/watchlists/nope", json={"symbol": "NVDA"}).status_code == 404
    assert (
        client.post("/api/watchlists/demo_all_modules", json={"symbol": "x;y"}).status_code == 422
    )
    assert client.delete("/api/watchlists/demo_all_modules/NVDA").json() == {"removed": "NVDA"}
    assert client.delete("/api/watchlists/demo_all_modules/NVDA").status_code == 404
    lists = {p["pipeline"]: p["entries"] for p in client.get("/api/watchlists").json()}
    [entry] = lists["demo_all_modules"]
    assert entry["active"] is False  # removed entries stay visible for 30 days
    assert entry["removed_reason"] == "removed by hand"


class DownReader:
    account_id = "DU1234567"

    async def connect(self) -> None:
        raise ConnectionRefusedError("gateway down")

    async def disconnect(self) -> None:
        return None

    async def snapshot(self, *, account: bool = True) -> BrokerSnapshot:
        raise AssertionError("not connected")


def test_account_sync_api(tmp_path: Path, configs: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'main.db'}")
    service = AccountSyncService(
        ConfigStore(configs, env=ENV),
        Repositories.create(db),
        reader_factory=lambda _: DownReader(),
    )
    settings = WebSettings(
        configs=configs,
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        env=ENV,
        create_tables=True,
        configure_logs=False,
        overrides={"account_sync": service},
        account_sync_loop=True,
    )
    with TestClient(create_app(settings)) as client:
        for _ in range(200):  # the loop synchronises once right after start-up
            status = client.get("/api/account-sync").json()
            if status["history"]:
                break
            time.sleep(0.02)
        assert status["running"]
        assert status["config"]["interval_minutes"] == 20
        assert status["next_due"] is not None
        [account] = status["accounts"]
        assert account["account_id"] == "DU1234567"
        [auto] = status["history"]
        assert (auto["trigger"], auto["status"]) == ("auto", "failed")
        assert "gateway down" in auto["error"]

        [manual] = client.post("/api/account-sync/run").json()
        assert manual["trigger"] == "manual"
        status = client.get("/api/account-sync").json()
        assert [s["trigger"] for s in status["history"]] == ["manual", "auto"]
        assert [s["trigger"] for s in status["latest"]] == ["manual"]
        overview = client.get("/api/overview").json()
        assert overview["account_sync"]["latest"][0]["status"] == "failed"

        kinds = {k["name"] for k in client.get("/api/meta").json()["kinds"]}
        assert "account_sync" in kinds
        text = client.get("/api/configs/account_sync/account_sync").json()["text"]
        bad = client.post(
            "/api/configs/account_sync/account_sync/validate",
            json={"text": text.replace("accounts: []", "accounts: [nope]")},
        ).json()
        assert not bad["ok"]
        assert "nope" in bad["errors"][0]["message"]
        assert client.portal is not None
        client.portal.call(db.dispose)  # in the app's event loop, where it was used
