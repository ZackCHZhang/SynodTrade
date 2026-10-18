import pickle
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from quant_core.config import ConfigError, ConfigStore
from quant_scheduler import (
    JobConfig,
    MarketRelativeTrigger,
    SchedulesConfig,
    TradingDayCronTrigger,
    build_trigger,
    load_schedules,
    upcoming,
)


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ------------------------------------------------------------------ market_relative


def test_open_plus_30_on_a_normal_week() -> None:
    trigger = MarketRelativeTrigger("open", 30)
    times = upcoming(trigger, utc(2026, 9, 30, 20), utc(2026, 10, 7))
    assert times == [utc(2026, 10, d, 14) for d in (1, 2, 5, 6)]  # 10:00 New York (EDT)


def test_before_the_time_fires_the_same_day_and_exact_time_counts() -> None:
    trigger = MarketRelativeTrigger("open", 30)
    assert trigger.get_next_fire_time(None, utc(2026, 10, 1, 9)) == utc(2026, 10, 1, 14)
    assert trigger.get_next_fire_time(None, utc(2026, 10, 1, 14)) == utc(2026, 10, 1, 14)
    # after it has fired, the next one is strictly later
    assert trigger.get_next_fire_time(utc(2026, 10, 1, 14), utc(2026, 10, 1, 14)) == utc(
        2026, 10, 2, 14
    )


def test_holidays_half_days_and_dst() -> None:
    open30 = MarketRelativeTrigger("open", 30)
    # Thanksgiving (Thu 26 Nov) is closed
    assert open30.get_next_fire_time(None, utc(2026, 11, 25, 16)) == utc(2026, 11, 27, 15)
    # the day after closes early at 13:00 New York: close - 15 min = 17:45 UTC
    close15 = MarketRelativeTrigger("close", -15)
    assert close15.get_next_fire_time(None, utc(2026, 11, 27, 12)) == utc(2026, 11, 27, 17, 45)
    # after the switch to winter time (1 Nov) the open is 14:30 UTC
    assert open30.get_next_fire_time(None, utc(2026, 11, 2, 0)) == utc(2026, 11, 2, 15)


def test_trigger_validation_and_repr() -> None:
    with pytest.raises(ValueError, match="anchor"):
        MarketRelativeTrigger("noon")
    assert str(MarketRelativeTrigger("close", -15)) == "market_relative[XNYS close-15m]"
    assert "open+30m" in repr(MarketRelativeTrigger("open", 30))


def test_nothing_after_the_calendar_ends() -> None:
    trigger = MarketRelativeTrigger("open", 0)
    assert trigger.get_next_fire_time(None, utc(2100, 1, 1)) is None


# ------------------------------------------------------------------ cron


def test_cron_in_exchange_time_skips_holidays() -> None:
    mondays = TradingDayCronTrigger("0 11 * * MON")
    times = upcoming(mondays, utc(2026, 8, 30), utc(2026, 9, 22))
    # Labor Day (7 Sep) is skipped; 11:00 New York is 15:00 UTC in summer
    assert [t.astimezone(UTC) for t in times] == [
        utc(2026, 8, 31, 15),
        utc(2026, 9, 14, 15),
        utc(2026, 9, 21, 15),
    ]
    keep_all = TradingDayCronTrigger("0 11 * * MON", skip_non_trading_days=False)
    assert len(upcoming(keep_all, utc(2026, 8, 30), utc(2026, 9, 22))) == 4
    assert str(mondays) == "cron[0 11 * * MON America/New_York trading days]"
    assert "cron[" in repr(keep_all)


def test_triggers_are_picklable_for_the_job_store() -> None:
    for trigger in (MarketRelativeTrigger("open", 30), TradingDayCronTrigger("0 11 * * MON")):
        clone = pickle.loads(pickle.dumps(trigger))
        now = utc(2026, 10, 1)
        assert clone.get_next_fire_time(None, now) == trigger.get_next_fire_time(None, now)


# ------------------------------------------------------------------ config


def test_job_config_validation() -> None:
    JobConfig(pipeline="p", trigger="market_relative", anchor="open", offset_minutes=30)
    JobConfig(pipeline="p", trigger="cron", cron="0 11 * * MON")
    for bad, message in [
        ({"trigger": "market_relative"}, "need an anchor"),
        (
            {"trigger": "market_relative", "anchor": "open", "cron": "* * * * *"},
            "do not take a cron",
        ),
        ({"trigger": "cron"}, "need a cron"),
        ({"trigger": "cron", "cron": "0 11 * * MON", "anchor": "open"}, "do not take an anchor"),
        ({"trigger": "cron", "cron": "every monday"}, "Wrong number of fields"),
        ({"trigger": "hourly"}, "trigger"),
    ]:
        with pytest.raises(ValidationError, match=message):
            JobConfig.model_validate({"pipeline": "p", **bad})
    with pytest.raises(ValidationError, match="unknown timezone"):
        SchedulesConfig(timezone="Mars/Olympus")


def test_job_ids_and_build_trigger() -> None:
    schedules = SchedulesConfig.model_validate(
        {
            "jobs": [
                {
                    "pipeline": "a",
                    "trigger": "market_relative",
                    "anchor": "open",
                    "offset_minutes": 30,
                },
                {
                    "pipeline": "a",
                    "trigger": "market_relative",
                    "anchor": "close",
                    "offset_minutes": -10,
                },
                {"pipeline": "b", "trigger": "cron", "cron": "0 11 * * MON"},
            ]
        }
    )
    assert schedules.job_ids() == ["a#0", "a#1", "b#0"]
    triggers = [build_trigger(j, schedules) for j in schedules.jobs]
    assert isinstance(triggers[0], MarketRelativeTrigger)
    assert isinstance(triggers[2], TradingDayCronTrigger)


def test_load_repo_schedules(store: ConfigStore) -> None:
    schedules = load_schedules(store)
    assert [j.pipeline for j in schedules.jobs][:2] == ["long_term_stocks", "etf_allocation"]
    arena = [j for j in schedules.jobs if j.pipeline.startswith("arena_")]
    assert len(arena) == 30  # 5 multi-agent and 5 single-agent pipelines, 3 runs a day each
    assert all(j.enabled for j in arena)


def test_unknown_or_invalid_pipelines_are_reported(configs: Path) -> None:
    path = configs / "schedules.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["jobs"].append({"pipeline": "ghost", "trigger": "cron", "cron": "0 9 * * *"})
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="schedule for ghost"):
        load_schedules(ConfigStore(configs, env={}), strict=False)
    # strict mode also needs the env of what pipelines reference (e.g. the account)
    data["jobs"].pop()
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    load_schedules(ConfigStore(configs, env={}), strict=False)
    with pytest.raises(ConfigError, match="IBKR_ACCOUNT"):
        load_schedules(ConfigStore(configs, env={}), strict=True)
