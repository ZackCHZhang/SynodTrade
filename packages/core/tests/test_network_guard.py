"""Guard: unit tests must not be able to reach the network (pytest-socket, see root pyproject)."""

import socket

import pytest
from pytest_socket import SocketConnectBlockedError


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_external_connections_are_blocked() -> None:
    with (
        pytest.raises(SocketConnectBlockedError),
        socket.create_connection(("1.1.1.1", 443), timeout=1),
    ):
        pass


async def test_event_loop_still_works() -> None:
    # The asyncio loop on Windows builds a loopback socketpair; it must stay allowed.
    import asyncio

    await asyncio.sleep(0)
