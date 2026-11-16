"""Sandbox guard: in the MVP nothing may reach the outside world (no emails, no real RFQs/POs)."""
import os
import socket
from contextlib import contextmanager

LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class SandboxViolation(RuntimeError):
    pass


def is_sandbox() -> bool:
    """Safe default: sandbox is ON unless SANDBOX_MODE is explicitly 'false'."""
    return os.environ.get("SANDBOX_MODE", "true").strip().lower() != "false"


def check_external_call(target: str) -> None:
    """Call this before any outbound action (email, supplier RFQ, external API)."""
    if is_sandbox():
        raise SandboxViolation(f"blocked in sandbox mode: {target}")


@contextmanager
def network_blocked(allowed_hosts=LOCAL_HOSTS):
    """Hard safety net: while active, sockets may only connect to local addresses."""
    original = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in allowed_hosts:
            raise SandboxViolation(f"network blocked in sandbox: {host}")
        return original(self, address)

    socket.socket.connect = guarded
    try:
        yield
    finally:
        socket.socket.connect = original
