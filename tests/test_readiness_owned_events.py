"""Offline draft transport tests. No browser, daemon, resolver, or provider is started."""

import json
import queue
import subprocess
import threading
import time

import pytest

from jev_ultrafast import readiness
from jev_ultrafast.readiness import OwnedNetworkEvents, ReadinessConnectionError, resolve_endpoint

PRIVATE_ENDPOINT = "ws://private.invalid/endpoint-canary"


class FakeSocket:
    def __init__(self, *, overrides=None, omitted=None, after_send=None):
        self.messages = queue.Queue()
        self.commands = []
        self.closed = False
        self.overrides = overrides or {}
        self.omitted = omitted or set()
        self.after_send = after_send

    def send(self, raw):
        command = json.loads(raw)
        self.commands.append(command)
        method = command["method"]
        if method not in self.omitted:
            result = {
                "Target.getTargetInfo": {"targetInfo": {"targetId": "page-target", "type": "page"}},
                "Target.attachToTarget": {"sessionId": "observer-session"},
                "Page.getFrameTree": {"frameTree": {"frame": {"id": "main-frame"}}},
                "Network.enable": {},
            }[method]
            self.messages.put(json.dumps({"id": command["id"], **self.overrides.get(method, {"result": result})}))
        if self.after_send:
            self.after_send(self, command)

    def recv(self, timeout):
        try:
            message = self.messages.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError from None
        if isinstance(message, BaseException):
            raise message
        return message

    def close(self):
        self.closed = True
        self.messages.put(OSError("endpoint-canary socket closed"))

    def event(self, method="Network.requestWillBeSent", *, session="observer-session", **params):
        self.messages.put(json.dumps({"method": method, "sessionId": session, "params": params}))


@pytest.fixture
def opened():
    sources = []

    def make(socket=None, **kwargs):
        socket = socket or FakeSocket()
        source = OwnedNetworkEvents(
            "page-target", resolver=lambda timeout: PRIVATE_ENDPOINT,
            connector=lambda endpoint, **options: socket, **kwargs,
        )
        sources.append(source)
        return source, socket

    yield make
    for source in sources:
        source.close()
        assert not source._receiver.is_alive()


def eventually(predicate):
    deadline = time.monotonic() + 1
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Owned receiver did not reach the expected state")
        time.sleep(0.001)


def test_observer_verifies_existing_target_then_enables_network_before_return(opened):
    source, socket = opened()
    assert [(command["method"], command.get("sessionId")) for command in socket.commands] == [
        ("Target.getTargetInfo", None), ("Target.attachToTarget", None),
        ("Page.getFrameTree", "observer-session"), ("Network.enable", "observer-session"),
    ]
    assert socket.commands[1]["params"] == {"targetId": "page-target", "flatten": True}
    assert source.main_frame_id == "main-frame"
    assert source.session_id == "observer-session"
    assert source.read_events() == ([], False)


def test_events_received_before_network_enable_ack_are_kept(opened):
    class EventBeforeAckSocket(FakeSocket):
        def send(self, raw):
            if json.loads(raw)["method"] == "Network.enable":
                self.event(requestId="during-enable", type="XHR", frameId="main-frame")
            super().send(raw)

    source, _ = opened(EventBeforeAckSocket())
    records, lost = source.read_events()
    assert not lost and [record["requestId"] for record in records] == ["during-enable"]


def test_other_sessions_do_not_consume_capacity_and_only_compact_fields_are_kept(opened):
    source, socket = opened()
    for index in range(601):
        socket.event(session="other-session", requestId=str(index), type="XHR", request={"url": "secret-url"})
    socket.event(requestId="ours", type="Fetch", frameId="main-frame", timestamp=123,
                 request={"url": "secret-url", "postData": "private-body"})
    eventually(lambda: len(source._events) == 1)
    records, lost = source.read_events()
    assert not lost
    assert records == [{"method": "Network.requestWillBeSent", "requestId": "ours", "type": "Fetch",
                        "frameId": "main-frame"}]
    assert "secret" not in json.dumps(records)
    assert "private-body" not in json.dumps(records)


@pytest.mark.parametrize("resource_type", ["XHR", "Image"])
def test_601_owned_records_preserve_newest_500_and_explicit_loss(opened, resource_type):
    source, socket = opened()
    for index in range(601):
        socket.event(requestId=str(index), type=resource_type, frameId="main-frame")
    eventually(lambda: bool(source._events) and source._events[-1]["requestId"] == "600")
    source.check_health()  # Health checks must not consume the loss marker.
    records, lost = source.read_events()
    assert lost and len(records) == 500
    assert records[0]["requestId"] == "101" and records[-1]["requestId"] == "600"
    assert source.read_events() == ([], False)


def test_idle_disconnect_is_terminal_without_any_outstanding_command(opened):
    source, socket = opened()
    socket.messages.put(OSError("endpoint-canary idle connection closed"))
    eventually(lambda: source._error is not None)
    for read in (source.check_health, source.read_events):
        with pytest.raises(ReadinessConnectionError, match="^Loading event connection disconnected$"):
            read()


@pytest.mark.parametrize("raw", ["not JSON endpoint-canary", "[]", "{}", '{"method":"x","params":[]}'])
def test_malformed_transport_is_terminal_and_redacted(opened, raw):
    source, socket = opened()
    socket.messages.put(raw)
    eventually(lambda: source._error is not None)
    with pytest.raises(ReadinessConnectionError, match="^Loading event connection returned malformed data$"):
        source.read_events()


@pytest.mark.parametrize("method,outer_session,params", [
    ("Target.detachedFromTarget", None, {"sessionId": "observer-session"}),
    ("Inspector.detached", "observer-session", {"reason": "endpoint-canary"}),
])
def test_owned_session_detach_is_terminal(opened, method, outer_session, params):
    source, socket = opened()
    socket.event(method, session=outer_session, **params)
    eventually(lambda: source._error is not None)
    with pytest.raises(ReadinessConnectionError, match="observer session detached"):
        source.check_health()


def test_detach_immediately_after_attach_response_cannot_escape_ownership():
    def detach(socket, command):
        if command["method"] == "Target.attachToTarget":
            socket.event("Target.detachedFromTarget", session=None, sessionId="observer-session")

    socket = FakeSocket(after_send=detach)
    with pytest.raises(ReadinessConnectionError, match="observer session detached"):
        OwnedNetworkEvents("page-target", resolver=lambda timeout: PRIVATE_ENDPOINT,
                           connector=lambda *args, **kwargs: socket)
    assert socket.closed


@pytest.mark.parametrize("override", [
    {"targetInfo": {"targetId": "different-target", "type": "page"}},
    {"targetInfo": {"targetId": "page-target", "type": "iframe"}},
    {"targetInfo": []},
])
def test_identity_mismatch_closes_source_before_network_enable(override):
    socket = FakeSocket(overrides={"Target.getTargetInfo": {"result": override}})
    with pytest.raises(ReadinessConnectionError, match="target identity changed"):
        OwnedNetworkEvents("page-target", resolver=lambda timeout: PRIVATE_ENDPOINT,
                           connector=lambda *args, **kwargs: socket)
    assert socket.closed
    assert [command["method"] for command in socket.commands] == ["Target.getTargetInfo"]


def test_network_enable_requires_acknowledgment_and_setup_timeout_joins_receiver(monkeypatch):
    monkeypatch.setattr(readiness, "SETUP_TIMEOUT_SECONDS", 0.025)
    before = {thread.ident for thread in threading.enumerate()}
    socket = FakeSocket(omitted={"Network.enable"})
    with pytest.raises(ReadinessConnectionError, match="setup timed out"):
        OwnedNetworkEvents("page-target", resolver=lambda timeout: PRIVATE_ENDPOINT,
                           connector=lambda *args, **kwargs: socket)
    assert socket.closed
    assert {thread.ident for thread in threading.enumerate()} <= before


def test_transport_receives_finite_timeouts_no_proxy_and_private_disabled_logger(opened):
    captured = {}
    socket = FakeSocket()

    def connector(endpoint, **options):
        captured.update(options)
        assert endpoint == PRIVATE_ENDPOINT
        return socket

    source = OwnedNetworkEvents("page-target", resolver=lambda timeout: PRIVATE_ENDPOINT,
                                connector=connector, remaining_budget=lambda: 0.5)
    try:
        assert 0 < captured["open_timeout"] <= 0.5
        assert captured["close_timeout"] == 0.2
        assert captured["proxy"] is None and captured["logger"].disabled
    finally:
        source.close()


def test_connection_errors_do_not_include_endpoint_or_raw_exception(caplog):
    def failing_connector(*args, **kwargs):
        raise OSError(PRIVATE_ENDPOINT)

    with pytest.raises(ReadinessConnectionError) as error:
        OwnedNetworkEvents("page-target", resolver=lambda timeout: PRIVATE_ENDPOINT,
                           connector=failing_connector)
    assert str(error.value) == "Loading event connection could not open"
    assert "endpoint-canary" not in caplog.text


def test_stop_after_resolution_prevents_connection_without_replacing_stop_exception():
    class Cancelled(Exception):
        pass

    resolved = False
    connected = False

    def check_stop():
        if resolved:
            raise Cancelled("cancelled")

    def resolver(timeout):
        nonlocal resolved
        resolved = True
        return PRIVATE_ENDPOINT

    def connector(*args, **kwargs):
        nonlocal connected
        connected = True

    with pytest.raises(Cancelled):
        OwnedNetworkEvents("page-target", check_stop=check_stop, resolver=resolver, connector=connector)
    assert not connected


@pytest.mark.parametrize("close_failure", [False, True])
def test_stop_while_waiting_for_ack_closes_and_joins_receiver(close_failure):
    class Cancelled(Exception):
        pass

    cancelled = False

    def cancel(socket, command):
        nonlocal cancelled
        if command["method"] == "Network.enable":
            cancelled = True

    def check_stop():
        if cancelled:
            raise Cancelled("cancelled")

    before = {thread.ident for thread in threading.enumerate()}
    class ClosingSocket(FakeSocket):
        def close(self):
            super().close()
            if close_failure:
                raise OSError("endpoint-canary close failed")

    socket = ClosingSocket(omitted={"Network.enable"}, after_send=cancel)
    with pytest.raises(Cancelled) as error:
        OwnedNetworkEvents("page-target", check_stop=check_stop,
                           resolver=lambda timeout: PRIVATE_ENDPOINT,
                           connector=lambda *args, **kwargs: socket)
    assert socket.closed and {thread.ident for thread in threading.enumerate()} <= before
    assert getattr(error.value, "__notes__", []) == (["Loading event cleanup failed"] if close_failure else [])


class FakeResolver:
    def __init__(self, output=None, *, timeout=False, returncode=0):
        self.output = output or json.dumps({"endpoint": PRIVATE_ENDPOINT})
        self.timeout = timeout
        self.returncode = None
        self.finished_returncode = returncode
        self.killed = False
        self.waited = False

    def communicate(self, timeout):
        self.timeout_seconds = timeout
        if self.timeout:
            raise subprocess.TimeoutExpired("private resolver", timeout, stderr="endpoint-canary")
        self.returncode = self.finished_returncode
        return self.output, "endpoint-canary stderr"

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout):
        self.waited = True
        assert self.returncode is not None
        return self.returncode


def test_explicit_endpoint_never_launches_discovery():
    def forbidden(*args, **kwargs):
        raise AssertionError("Explicit endpoint launched discovery")

    assert resolve_endpoint(1, environment={"BU_CDP_WS": PRIVATE_ENDPOINT}, launcher=forbidden) == PRIVATE_ENDPOINT


def test_discovery_is_isolated_captured_bounded_and_reaped():
    process = FakeResolver()
    captured = {}

    def launcher(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return process

    assert resolve_endpoint(0.25, environment={}, launcher=launcher) == PRIVATE_ENDPOINT
    assert captured["argv"][1:3] == ["-I", "-c"]
    assert captured["stdout"] == subprocess.PIPE and captured["stderr"] == subprocess.PIPE
    assert process.timeout_seconds == 0.25 and process.waited and not process.killed


def test_discovery_timeout_kills_and_reaps_owned_child_and_redacts_error():
    process = FakeResolver(timeout=True)
    with pytest.raises(ReadinessConnectionError, match="^Loading event endpoint discovery timed out$"):
        resolve_endpoint(0.25, environment={}, launcher=lambda *args, **kwargs: process)
    assert process.killed and process.waited


def test_discovery_communication_failure_kills_and_reaps_without_raw_error():
    class BrokenResolver(FakeResolver):
        def communicate(self, timeout):
            raise OSError("endpoint-canary communication failed")

    process = BrokenResolver()
    with pytest.raises(ReadinessConnectionError, match="^Loading event endpoint discovery failed$"):
        resolve_endpoint(1, environment={}, launcher=lambda *args, **kwargs: process)
    assert process.killed and process.waited


@pytest.mark.parametrize("output,returncode", [
    ("endpoint-canary not JSON", 0), (json.dumps({"endpoint": 42}), 0),
    (json.dumps({"endpoint": "http://wrong-protocol/endpoint-canary"}), 0),
    (json.dumps({"endpoint": PRIVATE_ENDPOINT}), 1),
])
def test_discovery_failures_are_sanitized_and_reaped(output, returncode):
    process = FakeResolver(output, returncode=returncode)
    with pytest.raises(ReadinessConnectionError, match="^Loading event endpoint discovery failed$"):
        resolve_endpoint(1, environment={}, launcher=lambda *args, **kwargs: process)
    assert process.waited


def test_close_is_idempotent_and_joins_the_owned_receiver(opened):
    source, socket = opened()
    source.close()
    source.close()
    assert socket.closed and not source._receiver.is_alive()
    with pytest.raises(ReadinessConnectionError, match="connection is closed"):
        source.read_events()
