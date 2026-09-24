from typing import Protocol, runtime_checkable

import pytest

from quant_core.services import MissingServiceError, Services


@runtime_checkable
class Greeter(Protocol):
    def greet(self) -> str: ...


class English:
    def greet(self) -> str:
        return "hi"


def test_get_checks_presence_and_type() -> None:
    services = Services(count=3, greeter=English())
    assert services.get("count", int) == 3
    assert services.get("greeter", Greeter).greet() == "hi"
    with pytest.raises(MissingServiceError, match=r"'repos' not provided \(have: count, greeter\)"):
        services.get("repos", object)
    with pytest.raises(TypeError, match="is int, expected str"):
        services.get("count", str)


def test_optional_and_with() -> None:
    services = Services(a=1)
    assert services.optional("b", int) is None
    extended = services.with_(b=2)
    assert extended.optional("b", int) == 2
    assert "b" in extended
    assert "b" not in services
    with pytest.raises(MissingServiceError, match="none"):
        Services().get("x", int)
