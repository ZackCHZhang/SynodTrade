"""Name -> implementation registries used to build pipelines from YAML.

Packages register implementations through Python entry points so that core never has to
import them (which would break the package DAG), e.g. in packages/decision/pyproject.toml:

    [project.entry-points."quant.stages"]
    decision = "quant_decision.stage:build_decision_stage"

Explicit `register()` calls also work (handy in tests).
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any


class RegistryError(LookupError):
    pass


class Registry[T]:
    def __init__(self, kind: str, entry_point_group: str | None = None) -> None:
        self.kind = kind
        self.entry_point_group = entry_point_group
        self._items: dict[str, T] = {}
        self._entry_points_loaded = False

    def register(self, name: str, item: T, *, replace: bool = False) -> T:
        if name in self._items and not replace and self._items[name] is not item:
            raise RegistryError(f"{self.kind} {name!r} is already registered")
        self._items[name] = item
        return item

    def decorator(self, name: str) -> Callable[[T], T]:
        def wrap(item: T) -> T:
            return self.register(name, item)

        return wrap

    def unregister(self, name: str) -> None:
        self._items.pop(name, None)

    def load_entry_points(self) -> None:
        self._entry_points_loaded = True
        if self.entry_point_group is None:
            return
        for ep in entry_points(group=self.entry_point_group):
            if ep.name not in self._items:
                self._items[ep.name] = ep.load()

    def get(self, name: str) -> T:
        if name not in self._items and not self._entry_points_loaded:
            self.load_entry_points()
        try:
            return self._items[name]
        except KeyError:
            known = ", ".join(sorted(self._items)) or "none"
            raise RegistryError(f"unknown {self.kind} {name!r} (known: {known})") from None

    def names(self) -> list[str]:
        if not self._entry_points_loaded:
            self.load_entry_points()
        return sorted(self._items)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self.names()


# Factories take (stage/agent config, dependencies) and are typed loosely on purpose:
# their exact signatures are defined by the pipeline package that calls them.
STAGES: Registry[Callable[..., Any]] = Registry("stage", "quant.stages")
AGENTS: Registry[Callable[..., Any]] = Registry("agent", "quant.agents")
SENTIMENT_SOURCES: Registry[Callable[..., Any]] = Registry(
    "sentiment source", "quant.sentiment_sources"
)
CANDIDATE_SOURCES: Registry[Callable[..., Any]] = Registry(
    "candidate source", "quant.candidate_sources"
)
