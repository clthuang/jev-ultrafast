"""Owned, bounded, content-free network events for one existing browser target.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from websockets.sync.client import connect

EVENT_CAPACITY = 500
SETUP_TIMEOUT_SECONDS = 5.0
RECEIVE_POLL_SECONDS = 0.1
CLOSE_TIMEOUT_SECONDS = 0.2
RECEIVER_JOIN_SECONDS = 1.0
RESOLVER_REAP_SECONDS = 1.0
END_METHODS = frozenset({"Network.loadingFinished", "Network.loadingFailed"})
RESOLVER_PROGRAM = (
    "import json; from browser_harness.daemon import get_ws_url; "
    "print(json.dumps({'endpoint': get_ws_url()}))"
)


class ReadinessConnectionError(RuntimeError):
    """The owned event source cannot safely report whether content is loading."""


def _valid_endpoint(endpoint):
    if not isinstance(endpoint, str):
        return False
    try:
        parsed = urlsplit(endpoint)
        return parsed.scheme in {"ws", "wss"} and bool(parsed.hostname)
    except (TypeError, ValueError):
        return False


def resolve_endpoint(timeout, *, environment=None, launcher=None):
    """Resolve without starting Chrome and reap the discovery child on every path."""
    environment = os.environ if environment is None else environment
    endpoint = environment.get("BU_CDP_WS")
    if endpoint:
        if not _valid_endpoint(endpoint):
            raise ReadinessConnectionError("Loading event endpoint is invalid")
        return endpoint
    if timeout <= 0:
        raise ReadinessConnectionError("Loading event endpoint discovery timed out")
    launcher = subprocess.Popen if launcher is None else launcher
    try:
        process = launcher(
            [sys.executable, "-I", "-c", RESOLVER_PROGRAM],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=dict(environment),
        )
    except Exception:
        raise ReadinessConnectionError("Loading event endpoint discovery failed") from None
    try:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ReadinessConnectionError("Loading event endpoint discovery timed out") from None
        except Exception:
            raise ReadinessConnectionError("Loading event endpoint discovery failed") from None
        try:
            result = json.loads(output)
            endpoint = result["endpoint"]
        except (TypeError, ValueError, KeyError):
            raise ReadinessConnectionError("Loading event endpoint discovery failed") from None
        if process.returncode != 0 or not _valid_endpoint(endpoint):
            raise ReadinessConnectionError("Loading event endpoint discovery failed")
        return endpoint
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=RESOLVER_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            raise ReadinessConnectionError("Loading event endpoint discovery did not stop") from None


class OwnedNetworkEvents:
    """A private CDP connection and observer session, never a shared daemon drain."""

    def __init__(self, target_id, *, check_stop=None, remaining_budget=None,
                 connector=None, resolver=None, clock=time.monotonic):
        if not isinstance(target_id, str) or not target_id or len(target_id) > 256:
            raise ValueError("Loading event target must be an observed target identifier")
        self.target_id = target_id
        self.session_id = None
        self.main_frame_id = None
        self._clock = clock
        self._check_stop = check_stop or (lambda: None)
        self._remaining_budget = remaining_budget
        self._setup_deadline = clock() + SETUP_TIMEOUT_SECONDS
        self._condition = threading.Condition()
        self._events = deque(maxlen=EVENT_CAPACITY)
        self._responses = {}
        self._response_methods = {}
        self._next_request_id = 0
        self._lost = False
        self._error = None
        self._closed = False
        self._socket = None
        self._receiver = None
        connector = connect if connector is None else connector
        resolver = resolve_endpoint if resolver is None else resolver
        try:
            endpoint = resolver(self._setup_remaining())
            # This logger is private, unregistered and disabled: endpoint URLs and CDP
            # payloads must never enter the installed library's transport diagnostics.
            logger = logging.Logger("jev_ultrafast.readiness.private")
            logger.disabled = True
            open_timeout = self._setup_remaining()
            try:
                self._socket = connector(
                    endpoint, open_timeout=open_timeout,
                    close_timeout=CLOSE_TIMEOUT_SECONDS, proxy=None, logger=logger,
                    ping_interval=None, max_size=2**20,
                )
            except Exception:
                raise ReadinessConnectionError("Loading event connection could not open") from None
            self._receiver = threading.Thread(
                target=self._receive, name="jev-loading-events", daemon=True,
            )
            self._receiver.start()
            target = self._command("Target.getTargetInfo", {"targetId": target_id})
            info = target.get("targetInfo", {})
            if not isinstance(info, dict) or info.get("targetId") != target_id or info.get("type") != "page":
                raise ReadinessConnectionError("Loading event target identity changed")
            attached = self._command("Target.attachToTarget", {"targetId": target_id, "flatten": True})
            self.session_id = attached.get("sessionId")
            if not isinstance(self.session_id, str) or not self.session_id:
                raise ReadinessConnectionError("Loading event observer session is missing")
            tree = self._command("Page.getFrameTree", session_id=self.session_id)
            frame_tree = tree.get("frameTree", {})
            frame = frame_tree.get("frame", {}) if isinstance(frame_tree, dict) else {}
            self.main_frame_id = frame.get("id") if isinstance(frame, dict) else None
            if not isinstance(self.main_frame_id, str) or not self.main_frame_id:
                raise ReadinessConnectionError("Loading event main frame is missing")
            self._command("Network.enable", session_id=self.session_id)
            self.check_health()
        except BaseException as original:
            try:
                self.close()
            except Exception:
                # The shared stop reason has priority over a teardown failure.
                # Keep the failure visible without leaking a transport exception.
                original.add_note("Loading event cleanup failed")
            raise

    def _setup_remaining(self):
        self._check_stop()
        remaining = self._setup_deadline - self._clock()
        if self._remaining_budget is not None:
            remaining = min(remaining, self._remaining_budget())
        if remaining <= 0:
            raise ReadinessConnectionError("Loading event connection setup timed out")
        return remaining

    def _raise_if_failed(self):
        if self._error is not None:
            raise ReadinessConnectionError(self._error)
        if self._closed:
            raise ReadinessConnectionError("Loading event connection is closed")

    def _command(self, method, params=None, *, session_id=None):
        self._setup_remaining()
        with self._condition:
            self._raise_if_failed()
            self._next_request_id += 1
            request_id = self._next_request_id
            self._responses[request_id] = None
            self._response_methods[request_id] = method
        request = {"id": request_id, "method": method, "params": params or {}}
        if session_id is not None:
            request["sessionId"] = session_id
        try:
            try:
                self._socket.send(json.dumps(request))
            except Exception:
                self._fail("Loading event command could not be sent")
            while True:
                remaining = self._setup_remaining()
                with self._condition:
                    self._raise_if_failed()
                    response = self._responses[request_id]
                    if response is not None:
                        if "error" in response or not isinstance(response.get("result"), dict):
                            raise ReadinessConnectionError("Loading event command failed")
                        return response["result"]
                    self._condition.wait(min(RECEIVE_POLL_SECONDS, remaining))
        finally:
            with self._condition:
                self._responses.pop(request_id, None)
                self._response_methods.pop(request_id, None)

    def _fail(self, message):
        with self._condition:
            if not self._closed and self._error is None:
                self._error = message
                self._lost = True
            self._condition.notify_all()

    def _receive(self):
        while True:
            with self._condition:
                if self._closed or self._error is not None:
                    return
            try:
                raw = self._socket.recv(timeout=RECEIVE_POLL_SECONDS)
            except TimeoutError:
                continue
            except Exception:
                self._fail("Loading event connection disconnected")
                return
            try:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("CDP message must be an object")
                self._accept(message)
            except (TypeError, ValueError, KeyError):
                self._fail("Loading event connection returned malformed data")
                return

    def _accept(self, message):
        with self._condition:
            if self._closed or self._error is not None:
                return
            request_id = message.get("id")
            if isinstance(request_id, int):
                if request_id in self._responses:
                    if self._response_methods[request_id] == "Target.attachToTarget":
                        result = message.get("result")
                        session_id = result.get("sessionId") if isinstance(result, dict) else None
                        if isinstance(session_id, str) and session_id:
                            # Register ownership before processing any subsequent event,
                            # including an immediate session-detached notification.
                            self.session_id = session_id
                    self._responses[request_id] = message
                    self._condition.notify_all()
                return
            method = message.get("method")
            if not isinstance(method, str):
                raise ValueError("CDP event method must be a string")
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("CDP event params must be an object")
            detached = (
                method == "Target.detachedFromTarget" and self.session_id is not None
                and params.get("sessionId") == self.session_id
            )
            own_session = self.session_id is not None and message.get("sessionId") == self.session_id
            if detached or (own_session and method == "Inspector.detached"):
                self._fail("Loading event observer session detached")
                return
            if not own_session:
                return
            if method != "Network.requestWillBeSent" and method not in END_METHODS:
                return
            network_id = params.get("requestId")
            if not isinstance(network_id, str):
                raise ValueError("CDP network request ID must be a string")
            record = {"method": method, "requestId": network_id}
            if method == "Network.requestWillBeSent":
                resource_type = params.get("type")
                if resource_type is not None and not isinstance(resource_type, str):
                    raise ValueError("CDP resource type must be a string")
                # Queue pressure is observable even when the tracker later ignores
                # this resource type. Images can displace a content request.
                record["type"] = resource_type
                frame_id = params.get("frameId")
                if frame_id is not None and not isinstance(frame_id, str):
                    raise ValueError("CDP frame ID must be a string")
                record["frameId"] = frame_id
            if len(self._events) == EVENT_CAPACITY:
                self._lost = True
            self._events.append(record)

    def check_health(self):
        """Report terminal loss without consuming pending records or the loss marker."""
        with self._condition:
            self._raise_if_failed()

    def read_events(self):
        """Atomically consume this connection's compact records and overflow marker."""
        with self._condition:
            self._raise_if_failed()
            records, lost = list(self._events), self._lost
            self._events.clear()
            self._lost = False
            return records, lost

    def close(self):
        """Close this observer only, then join its receiver outside all queue locks."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        close_failed = False
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                close_failed = True
        if self._receiver is not None and self._receiver is not threading.current_thread():
            self._receiver.join(timeout=RECEIVER_JOIN_SECONDS)
            if self._receiver.is_alive():
                raise ReadinessConnectionError("Loading event receiver did not stop")
        if close_failed:
            raise ReadinessConnectionError("Loading event connection could not close") from None
