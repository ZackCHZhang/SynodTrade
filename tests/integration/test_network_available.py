"""Sanity check that integration tests are exempt from the unit-test network block."""

import socket


def test_sockets_enabled_for_integration() -> None:
    # Creating a socket and resolving a public name must not be blocked here.
    socket.getaddrinfo("example.com", 443)
