"""A tiny typed service container handed to stage factories.

Stage factories live in the business packages and cannot import the pipeline package that
builds them, so the pipeline passes its shared objects (repositories, providers, LLM pool...)
in a `Services` instead of a fixed signature:

    def build_data_update_stage(config: StageConfig, services: Services) -> Stage:
        repos = services.get("repos", Repositories)
"""

from __future__ import annotations

from typing import Any


class MissingServiceError(LookupError):
    pass


class Services:
    def __init__(self, **items: Any) -> None:
        self._items = dict(items)

    def get[T](self, name: str, kind: type[T]) -> T:
        try:
            item = self._items[name]
        except KeyError:
            known = ", ".join(sorted(self._items)) or "none"
            raise MissingServiceError(f"service {name!r} not provided (have: {known})") from None
        if not isinstance(item, kind):
            raise TypeError(f"service {name!r} is {type(item).__name__}, expected {kind.__name__}")
        return item

    def optional[T](self, name: str, kind: type[T]) -> T | None:
        return self.get(name, kind) if name in self._items else None

    def with_(self, **items: Any) -> Services:
        return Services(**{**self._items, **items})

    def __contains__(self, name: object) -> bool:
        return name in self._items
