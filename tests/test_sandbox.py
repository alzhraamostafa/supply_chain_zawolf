import os
import socket
from unittest.mock import patch

import pytest
from common.sandbox import SandboxViolation, check_external_call, is_sandbox, network_blocked


def test_sandbox_is_on_by_default():
    with patch.dict(os.environ, {}, clear=True):
        assert is_sandbox() is True


def test_sandbox_off_only_when_explicitly_false():
    with patch.dict(os.environ, {"SANDBOX_MODE": "false"}):
        assert is_sandbox() is False
    with patch.dict(os.environ, {"SANDBOX_MODE": "no"}):
        assert is_sandbox() is True


def test_external_call_blocked_in_sandbox_and_allowed_when_off():
    with patch.dict(os.environ, {"SANDBOX_MODE": "true"}):
        with pytest.raises(SandboxViolation):
            check_external_call("send_rfq_email")
    with patch.dict(os.environ, {"SANDBOX_MODE": "false"}):
        check_external_call("send_rfq_email")


def test_network_blocked_refuses_external_hosts():
    with network_blocked():
        with pytest.raises(SandboxViolation):
            socket.socket().connect(("example.com", 80))


def test_network_blocked_lets_local_connections_through():
    with network_blocked():
        with pytest.raises(OSError):
            socket.socket().connect(("127.0.0.1", 1))


def test_guard_is_removed_afterwards():
    before = socket.socket.connect
    with network_blocked():
        pass
    assert socket.socket.connect is before
