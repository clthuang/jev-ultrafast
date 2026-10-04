"""The loading wait's own DevTools connection, never the browser daemon's shared event buffer.

Browser Harness 0.1.13 keeps one 500-event buffer per daemon, and drain_events() empties it for every client. So the
loading wait (docs/executor-improvements.md §4; docs/robustness-efficiency/status.md §4.3) follows a tab's Network
events on a WebSocket of this process's own: an observer session of its own on the exact target, a bounded queue, and
loss recorded, never hidden. No endpoint is ever logged, raised or saved."""

import contextlib
import json
import os
import threading
from collections import deque

from websockets.sync.client import connect

from .contracts import RunStopped

EVENT_QUEUE = 500  # as the daemon's buffer: a read this long, or an event dropped from a full queue, is loss
SETUP_SECONDS = 5  # each setup request, as browser-harness bounds a reply
APPROVAL_SECONDS = 30  # your own Chrome's "Allow remote debugging?" answer, as ensure_daemon(wait=30) bounds it
MAX_MESSAGE_BYTES = 64 * 1024 * 1024  # an event can carry a request body; only four of its fields are kept
WATCHED = frozenset({"Network.requestWillBeSent", "Network.loadingFinished", "Network.loadingFailed"})


class EventConnectionLost(RunStopped):
    """The loading wait's own connection failed or closed: a terminal stop, never a page that looks quiet."""

    def __init__(self, reason):
        super().__init__("event_connection_lost", f"The loading wait's browser connection {reason}.")


def gate_mode(kind):
    """How this process follows a tab's loading, from the browser daemon's kind. "first input": a connection of its
    own at the first input, for an explicit endpoint (BU_CDP_WS or BU_CDP_URL), which asks no approval. "setup": one
    connection at browser setup, reused by every goal, when JEV_LOADING_GATE=1 opts your own Chrome in; Chrome 144+
    asks "Allow remote debugging?" once per connection, so once per server start. None: no loading wait, as before
    (JEV_LOADING_GATE=0, or your own Chrome without the opt-in). Decision recorded in status.md §4.3."""
    setting = os.environ.get("JEV_LOADING_GATE", "").strip()
    if setting == "0":
        return None
    if kind == "cdp":
        return "first input"
    return "setup" if setting == "1" else None


def endpoint(timeout):
    """The browser's DevTools WebSocket, found as the daemon finds it, within timeout seconds."""
    if url := os.environ.get("BU_CDP_WS"):
        return url
    found = {}

    def resolve():
        with contextlib.suppress(Exception):  # its text could hold the endpoint
            from browser_harness.daemon import get_ws_url  # loads .env without overriding, as the daemon does

            found["url"] = get_ws_url()

    worker = threading.Thread(target=resolve, name="jev-events-endpoint", daemon=True)
    worker.start()
    worker.join(timeout)
    if not isinstance(found.get("url"), str):
        raise EventConnectionLost("could not find the browser's endpoint")
    return found["url"]


class Connection:
    """One private DevTools WebSocket: a reader thread routes replies to their callers and Network events to the
    observer sessions it serves. Every call is bounded; a closed connection fails every caller and source."""

    def __init__(self, url, timeout):
        try:
            # No proxy: the endpoint is this machine's browser, never a destination an environment proxy should see.
            self.socket = connect(url, open_timeout=timeout, close_timeout=1, ping_interval=None, proxy=None,
                                  max_size=MAX_MESSAGE_BYTES, compression=None)
        except Exception as error:
            raise EventConnectionLost(f"could not open ({type(error).__name__})") from None
        self.lock, self.sending, self.pending, self.next_id, self.sources = (
            threading.Lock(), threading.Lock(), {}, 0, {})
        self.closed = threading.Event()
        self.reader = threading.Thread(target=self._read, name="jev-events", daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for raw in self.socket:
                message = json.loads(raw)
                if "id" in message:
                    with self.lock:
                        waiter = self.pending.pop(message["id"], None)
                    if waiter:
                        waiter["reply"] = message
                        waiter["done"].set()
                elif message.get("method") in WATCHED:
                    source = self.sources.get(message.get("sessionId"))
                    if source:
                        source.receive(message["method"], message.get("params") or {})
        except Exception:
            pass  # closed or broken: below, every waiter and source sees it closed
        finally:
            self.closed.set()
            with self.lock:
                waiters, self.pending = list(self.pending.values()), {}
            for waiter in waiters:
                waiter["done"].set()

    def call(self, method, params=None, *, session_id=None, timeout=SETUP_SECONDS):
        if self.closed.is_set():
            raise EventConnectionLost("closed")
        with self.lock:
            self.next_id += 1
            key, waiter = self.next_id, {"done": threading.Event(), "reply": None}
            self.pending[key] = waiter
        message = {"id": key, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        try:
            with self.sending:
                self.socket.send(json.dumps(message))
        except Exception:
            with self.lock:
                self.pending.pop(key, None)
            raise EventConnectionLost("closed") from None
        if not waiter["done"].wait(timeout):
            with self.lock:
                self.pending.pop(key, None)
            raise EventConnectionLost(f"did not answer {method} in time")
        reply = waiter["reply"]
        if reply is None:
            raise EventConnectionLost("closed")
        if "error" in reply:
            raise EventConnectionLost(f"refused {method}")
        return reply.get("result") or {}

    def close(self):
        with contextlib.suppress(Exception):
            self.socket.close()
        self.reader.join(2)


class OwnedEvents:
    """One tab's Network events on the process's own connection: an observer session of its own on the exact target
    (never another tab, never the daemon's session), Network enabled and acknowledged before any input runs, and a
    bounded queue whose overflow is loss."""

    def __init__(self, connection, target, timeout):
        self.connection, self.target, self.session = connection, target, None
        self.lock, self.queue, self.overflow = threading.Lock(), deque(maxlen=EVENT_QUEUE), False
        info = connection.call("Target.getTargetInfo", {"targetId": target}, timeout=timeout).get("targetInfo") or {}
        if info.get("targetId") != target or info.get("type") != "page":
            raise EventConnectionLost("could not find this run's tab")
        session = connection.call("Target.attachToTarget", {"targetId": target, "flatten": True},
                                  timeout=timeout).get("sessionId")
        if not isinstance(session, str) or not session:
            raise EventConnectionLost("could not attach to this run's tab")
        self.session = session
        connection.sources[session] = self
        try:
            connection.call("Network.enable", session_id=session, timeout=timeout)
        except BaseException:
            self.close()
            raise

    def receive(self, method, params):
        """The connection's reader thread: keep four fields, nothing of a request's headers, URL or body."""
        event = (method, params.get("requestId"), params.get("type"), params.get("frameId"))
        with self.lock:
            self.overflow = self.overflow or len(self.queue) == self.queue.maxlen
            self.queue.append(event)

    def read(self):
        """This tab's events since the last read, and whether any were dropped. A closed connection is never quiet."""
        if self.connection.closed.is_set():
            raise EventConnectionLost("closed")
        with self.lock:
            events, overflow = list(self.queue), self.overflow
            self.queue.clear()
            self.overflow = False
        return events, overflow

    def close(self):
        if self.session is None:
            return
        self.connection.sources.pop(self.session, None)
        if not self.connection.closed.is_set():
            with contextlib.suppress(Exception):  # the tab may already be gone
                self.connection.call("Target.detachFromTarget", {"sessionId": self.session}, timeout=1)
        self.session = None


SHARED = {"connection": None}
SHARED_LOCK = threading.Lock()


def shared_connection(timeout):
    """This process's one connection, opened on first use and reused by every tab and goal; opened again only after
    it closed. With your own Chrome, each opening asks for approval once."""
    with SHARED_LOCK:
        connection = SHARED["connection"]
        if connection is None or connection.closed.is_set():
            connection = SHARED["connection"] = Connection(endpoint(timeout), timeout)
        return connection


def open_events(target, timeout):
    """This tab's own event source on the shared connection. Tests replace it with a fake source."""
    return OwnedEvents(shared_connection(timeout), target, timeout)
