"""Scheduler: trading calendar, timed pipeline wake-ups, re-entrancy guard, health checks"""

from quant_scheduler.app import SchedulerApp, run_scheduled_job, sync_jobstore_url
from quant_scheduler.config import JobConfig, SchedulesConfig, load_schedules
from quant_scheduler.health import HealthChecker, HealthReport, needs_ibkr, tcp_reachable
from quant_scheduler.notify import (
    CompositeNotifier,
    Level,
    LogNotifier,
    Notifier,
    TelegramNotifier,
    default_notifier,
)
from quant_scheduler.triggers import (
    MarketRelativeTrigger,
    TradingDayCronTrigger,
    build_trigger,
    upcoming,
)

__version__ = "0.1.0"

__all__ = [
    "CompositeNotifier",
    "HealthChecker",
    "HealthReport",
    "JobConfig",
    "Level",
    "LogNotifier",
    "MarketRelativeTrigger",
    "Notifier",
    "SchedulerApp",
    "SchedulesConfig",
    "TelegramNotifier",
    "TradingDayCronTrigger",
    "__version__",
    "build_trigger",
    "default_notifier",
    "load_schedules",
    "needs_ibkr",
    "run_scheduled_job",
    "sync_jobstore_url",
    "tcp_reachable",
    "upcoming",
]
