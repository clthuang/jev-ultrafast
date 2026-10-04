"""A fake page in Node behind browser.py's own CDP calls: production snapshot.js runs there unchanged.

Shared by the snapshot and readiness contract tests (pytest puts this directory on sys.path)."""

import json
import queue
import subprocess
import threading
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class NodePage:
    """One fake page in Node: every Runtime.evaluate runs browser.py's exact expression there. Records each call."""

    def __init__(self, **config):
        self.calls, self.reply_bytes = [], []
        self.process = subprocess.Popen(
            ["node", str(FIXTURES / "page_bridge.cjs"), str(FIXTURES / "dense_dom.cjs"), json.dumps(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def reply(self, expression):
        self.process.stdin.write(json.dumps({"expression": expression}) + "\n")
        self.process.stdin.flush()
        line = self.lines.get(timeout=60)
        assert line is not None, "the Node page exited"
        reply = json.loads(line)
        if "value" in reply:  # the exact UTF-8 bytes of JSON.stringify(value), as the page measures them
            self.reply_bytes.append(len(line.encode()) - len('{"value":}\n'))
        return reply

    def evaluate(self, expression):
        reply = self.reply(expression)
        assert "exception" not in reply, reply.get("exception")
        return reply.get("value")

    def cdp(self, method, session_id=None, **params):
        params.pop("_response_timeout", None)
        self.calls.append((method, params))
        if method == "Runtime.evaluate":
            reply = self.reply(params["expression"])
            if "exception" in reply:
                return {"exceptionDetails": {"text": reply["exception"]}}
            return {"result": {"value": reply["value"]} if "value" in reply else {}}
        if method == "Page.captureScreenshot":
            return {"data": "eA=="}
        return {}

    def inputs(self):
        return [params for method, params in self.calls if method.startswith("Input.")]

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
