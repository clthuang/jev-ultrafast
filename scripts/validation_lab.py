"""Own an isolated local Chrome/daemon for native tests; never discover a user's browser."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import functools
import http.client
import http.server
import json
import os
import re
import runpy
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCHEMA_VERSION = 1
SOURCE_ROOT = Path(__file__).resolve().parents[1]
MACOS_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
# Playwright's Chromium, preinstalled in Linux containers such as Claude Code on the web.
PLAYWRIGHT_CHROMIUM = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")) / "chromium"
PROCESS_WAIT_SECONDS = 5
STARTUP_SECONDS = 30
PROXY_LIMIT_BYTES = 4 * 1024 * 1024


def default_chrome():
    """An explicit lab Chrome: JEV_LAB_CHROME, else a fixed install path. Never the user's running browser."""
    configured = os.environ.get("JEV_LAB_CHROME")
    if configured:
        return Path(configured)
    for candidate in (MACOS_CHROME, PLAYWRIGHT_CHROMIUM):
        if candidate.is_file():
            return candidate
    return MACOS_CHROME


def chrome_sandbox_flags():
    """Chrome refuses to start as root with its sandbox; root here means a disposable container."""
    return ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []


def chrome_network_flags(proxy_port):
    """Force every browser HTTP/WebSocket context through the owned deny-by-default proxy."""
    return [
        f"--proxy-server=http://127.0.0.1:{proxy_port}", "--proxy-bypass-list=<-loopback>",
        "--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "--dns-prefetch-disable",
    ]


class LabSafetyError(AssertionError):
    """A test tried to cross the lab's process, network, or storage boundary."""


class _BsdProcessInfo(ctypes.Structure):
    # Darwin PROC_PIDTBSDINFO, including the kernel's microsecond process birth time.
    _fields_ = [
        *[(name, ctypes.c_uint32) for name in (
            "flags", "status", "exit_status", "pid", "parent_pid", "uid", "gid", "real_uid", "real_gid",
            "saved_uid", "saved_gid", "reserved",
        )],
        ("command", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
        *[(name, ctypes.c_uint32) for name in ("files", "group", "jobs", "device", "terminal_group")],
        ("nice", ctypes.c_int32), ("start_seconds", ctypes.c_uint64), ("start_microseconds", ctypes.c_uint64),
    ]


def _linux_process_identity(pid):
    """Read /proc directly: ps truncates to COLUMNS and can catch an exiting process between its own reads."""
    proc = Path(f"/proc/{pid}")
    try:
        before = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        argv = (proc / "cmdline").read_bytes()
        status = (proc / "status").read_text()
        after = (proc / "stat").read_text().rsplit(")", 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    # An exiting process loses its argv before it becomes a zombie; a changed start time is a reused PID.
    if after[0] in {"Z", "X"} or not argv or before[19] != after[19]:
        return None
    uid = next(int(line.split()[1]) for line in status.splitlines() if line.startswith("Uid:"))
    command = " ".join(os.fsdecode(part) for part in argv.rstrip(b"\0").split(b"\0"))
    return {"pid": pid, "birth": after[19], "uid": uid, "command": command}


def process_identity(pid):
    """Read identity without trusting a PID file; None means the process has exited."""
    if type(pid) is not int or pid <= 1:
        raise LabSafetyError("Invalid lab process ID")
    if sys.platform == "darwin":
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        read_info = library.proc_pidinfo
        read_info.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        info = _BsdProcessInfo()
        proc_pid_bsd_info = 3
        if read_info(pid, proc_pid_bsd_info, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
            return None
        if info.status == 5:  # SZOMB: exited, waiting for its parent to reap it.
            return None
        birth = f"{info.start_seconds}:{info.start_microseconds}"
    elif sys.platform.startswith("linux"):
        return _linux_process_identity(pid)
    else:
        raise LabSafetyError("Native lab process verification supports macOS and Linux")
    result = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "uid=,command="], capture_output=True, text=True, timeout=2, check=False,
    )
    if not result.stdout.strip():
        return None
    uid, command = result.stdout.strip().split(None, 1)
    return {"pid": pid, "birth": birth, "uid": int(uid), "command": command}


def verify_process(record, *, allow_exited=False):
    current = process_identity(record["pid"])
    if current is None and allow_exited:
        return False
    if current != record or record["uid"] != os.getuid():
        raise LabSafetyError("Lab process identity changed; refusing to connect or signal it")
    return True


def _owned_path(root, value):
    path = Path(value)
    if path.is_symlink() or not path.is_absolute() or not path.resolve().is_relative_to(root):
        raise LabSafetyError("Lab path is outside its owned directory")
    return path


def _read_manifest(path, *, ready=True):
    manifest = json.loads(Path(path).read_text())
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise LabSafetyError("Unsupported lab manifest")
    if ready and manifest.get("status") != "ready":
        raise LabSafetyError("Lab is not ready")
    root = Path(manifest["root"])
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
        raise LabSafetyError("Lab directory ownership changed")
    root = root.resolve()
    if (root / ".jev-lab-owner").read_text() != manifest["lab_id"]:
        raise LabSafetyError("Lab ownership marker does not match")
    if Path(manifest["source_root"]).resolve() != SOURCE_ROOT:
        raise LabSafetyError("Lab belongs to a different source checkout")
    for key in ("profile", "runtime", "state", "fixtures"):
        _owned_path(root, manifest[key])
    return manifest


def _listener_owned(pid, port):
    lsof = shutil.which("lsof", path="/usr/sbin:/usr/bin:/sbin:/bin:/opt/homebrew/bin")
    if not lsof:
        raise LabSafetyError("lsof is required to verify native lab listener ownership")
    result = subprocess.run(
        [lsof, "-a", "-nP", "-p", str(pid), f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True, text=True, timeout=2, check=False,
    )
    if str(pid) not in result.stdout.split():
        raise LabSafetyError("Lab endpoint is not owned by the recorded process")


def _daemon_request(manifest, message):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(Path(manifest["runtime"]) / "bu.sock"))
        connection.sendall(json.dumps(message).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            part = connection.recv(65536)
            if not part:
                break
            data += part
        return json.loads(data)


def _validate_endpoints(manifest, live, *, complete):
    """Read-only endpoint checks after every process identity has passed validation."""
    if complete and set(manifest["processes"]) != {"chrome", "fixtures", "proxy", "daemon"}:
        raise LabSafetyError("Lab is missing an owned process")
    for role, key in (("fixtures", "fixture_port"), ("proxy", "proxy_port"), ("chrome", "cdp_port")):
        if role in live and (complete or key in manifest):
            _listener_owned(manifest["processes"][role]["pid"], manifest[key])
    if "fixtures" in live:
        for key in ("iframe_port", "canary_port"):
            if key in manifest:
                _listener_owned(manifest["processes"]["fixtures"]["pid"], manifest[key])
    if complete and ("iframe_port" not in manifest or
                     manifest.get("iframe_url") != f"http://localhost:{manifest['iframe_port']}"):
        raise LabSafetyError("Second owned fixture origin is missing or changed")
    if "proxy" in live and (complete or "proxy_port" in manifest):
        ready = json.loads((Path(manifest["root"]) / "proxy-ready.json").read_text())
        expected = {"lab_id": manifest["lab_id"], "port": manifest["proxy_port"],
                    "allowed_origins": list(fixture_origins(manifest["fixture_port"],
                                                            manifest.get("iframe_port")))}
        if ready != expected or manifest["fixture_url"] != f"http://127.0.0.1:{manifest['fixture_port']}":
            raise LabSafetyError("Proxy allowlist changed")
    if "chrome" in live:
        command = manifest["processes"]["chrome"]["command"]
        required = [f"--user-data-dir={manifest['profile']}", *chrome_network_flags(manifest["proxy_port"])]
        # ps output does not retain argument quoting; require complete flag boundaries.
        if any(f"{flag} " not in command + " " or command.count(flag) != 1 for flag in required):
            raise LabSafetyError("Chrome is missing the lab profile or enforced proxy configuration")
        if complete or "cdp_port" in manifest:
            active = (Path(manifest["profile"]) / "DevToolsActivePort").read_text().splitlines()
            expected_ws = f"ws://127.0.0.1:{int(active[0])}{active[1]}"
            if expected_ws != manifest["cdp_ws"] or int(active[0]) != manifest["cdp_port"]:
                raise LabSafetyError("Chrome endpoint changed")
    if "daemon" in live:
        socket_path = Path(manifest["runtime"]) / "bu.sock"
        if complete or socket_path.exists():
            ping = _daemon_request(manifest, {"meta": "ping"})
            if ping != {"pong": True, "pid": manifest["processes"]["daemon"]["pid"], "browser_kind": "cdp"}:
                raise LabSafetyError("Daemon is not the recorded isolated CDP process")


def validate_manifest(path):
    """Prove ownership before browser imports or native actions; perform no browser mutation."""
    manifest = _read_manifest(path)
    for record in manifest["processes"].values():
        verify_process(record)
    _validate_endpoints(manifest, set(manifest["processes"]), complete=True)
    return manifest


def isolated_environment(root, *, name="jev_test", cdp_ws="", source=None):
    """Set these BEFORE importing browser_harness: its environment is captured at import."""
    root = Path(root).resolve()
    environment = {
        "BH_HOME": str(root / "harness"), "BH_CONFIG_DIR": str(root / "harness" / "config"),
        "BH_RUNTIME_DIR": str(root / "runtime"), "BH_TMP_DIR": str(root / "harness" / "tmp"),
        "BH_AGENT_WORKSPACE": str(root / "harness" / "workspace"),
        "BH_RUNTIME_DIR_SHARED": "0", "BH_TMP_DIR_SHARED": "0", "BH_TELEMETRY": "0",
        "BU_NAME": name, "BU_CDP_WS": cdp_ws, "BU_CDP_URL": "", "BU_BROWSER_ID": "", "BU_AUTOSPAWN": "0",
        "JEV_AUTO_REVIEW": "0", "TYPESAFE_API_KEY": "", "TEXT_MODEL_API_KEY": "", "BROWSER_USE_API_KEY": "",
    }
    if source:
        environment["PYTHONPATH"] = str(source)
    return environment


def configure_native(path):
    if any(name.startswith("browser_harness") or name == "jev_ultrafast.browser" for name in sys.modules):
        raise LabSafetyError("Configure the lab before importing browser code")
    manifest = validate_manifest(path)
    os.environ.update(isolated_environment(
        manifest["root"], name=manifest["name"], cdp_ws=manifest["cdp_ws"], source=SOURCE_ROOT,
    ))
    return manifest


class RuntimeGuard:
    """Real I/O denial; tests can still replace clients/CDP/Popen with explicit fakes."""

    def __init__(self, manifest=None):
        self.manifest = manifest
        self.originals = []

    def check_address(self, address):
        manifest = self.manifest
        if manifest:
            socket_path = str(Path(manifest["runtime"]) / "bu.sock")
            if isinstance(address, (str, bytes)) and os.fsdecode(address) == socket_path:
                verify_process(manifest["processes"]["daemon"])
                return
            if isinstance(address, tuple) and address[0] == "127.0.0.1":
                for role, key in (("chrome", "cdp_port"), ("fixtures", "fixture_port"), ("fixtures", "iframe_port")):
                    if key in manifest and address[1] == manifest[key]:
                        verify_process(manifest["processes"][role])
                        return
        raise LabSafetyError("Tests may connect only to verified native lab endpoints; provider/browser I/O denied")

    @staticmethod
    def check_command(command, shell=False):
        if shell or not isinstance(command, (list, tuple)) or not command:
            raise LabSafetyError("Real shell/review/browser launch denied in tests")
        # These support process verification and offline snapshot.js fixtures only.
        if Path(os.fsdecode(command[0])).name not in {"ps", "lsof", "node"}:
            raise LabSafetyError("Real process launch denied in tests; use an explicit fake or prepare the owned lab")

    @staticmethod
    def check_cdp(method, params):
        if method == "Target.createBrowserContext" and {"proxyServer", "proxyBypassList"} & params.keys():
            raise LabSafetyError("Test CDP may not override the owned Chrome proxy")

    def _replace(self, owner, name, replacement):
        self.originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    def install(self):
        guard = self
        node_preload = Path(os.environ["BH_TMP_DIR"]) / "test-node-deny.cjs"
        node_preload.parent.mkdir(parents=True, exist_ok=True)
        node_preload.write_text(
            "const deny=()=>{throw Error('Node network/process I/O denied in tests')};\n"
            "require('node:net').Socket.prototype.connect=deny;\n"
            "require('node:dgram').Socket.prototype.send=deny;\n"
            "const child=require('node:child_process');\n"
            "for(const key of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']) "
            "child[key]=deny;\n"
        )
        for name in ("connect", "connect_ex"):
            original = getattr(socket.socket, name)

            def guarded_connect(connection, address, original=original):
                guard.check_address(address)
                return original(connection, address)

            self._replace(socket.socket, name, guarded_connect)
        original_popen = subprocess.Popen

        class GuardedPopen(original_popen):
            def __init__(self, command, *args, **kwargs):
                if not kwargs.get("shell") and command == [sys.executable, "-m", "jev_ultrafast.mcp_server"]:
                    # Existing stdio/shutdown smoke tests need a real child. Install denial in that child too.
                    command = [sys.executable, str(Path(__file__).resolve()), "run-offline-mcp"]
                else:
                    guard.check_command(command, kwargs.get("shell", False))
                    if Path(os.fsdecode(command[0])).name == "node":
                        command = [command[0], "--require", str(node_preload), *command[1:]]
                super().__init__(command, *args, **kwargs)

        self._replace(subprocess, "Popen", GuardedPopen)
        self._replace(os, "system", lambda *_: self.check_command([], True))
        if self.manifest:
            from browser_harness import helpers

            original_cdp = helpers.cdp

            def guarded_cdp(method, *args, **params):
                guard.check_cdp(method, params)
                return original_cdp(method, *args, **params)

            self._replace(helpers, "cdp", guarded_cdp)
        return self

    def close(self):
        for owner, name, original in reversed(self.originals):
            setattr(owner, name, original)
        self.originals.clear()


def _write_manifest(path, manifest):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(temporary, path)


def _wait_for(read, deadline):
    while time.monotonic() < deadline:
        try:
            value = read()
            if value:
                return value
        except (OSError, ValueError, IndexError, KeyError):
            pass
        time.sleep(0.05)
    raise LabSafetyError("Owned lab did not become ready before the startup deadline")


def _stop_direct_child(child):
    """Popen retains unreaped direct-child ownership even when identity capture failed."""
    if child.poll() is None:
        child.terminate()  # Popen rechecks waitpid before signalling; a reaped/reused PID is never signalled.
        try:
            child.wait(timeout=PROCESS_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=PROCESS_WAIT_SECONDS)


def _spawn_owned(role, command, *, root, environment, manifest, output, children):
    with (root / f"{role}.log").open("ab") as log:
        child = subprocess.Popen(command, env=environment, cwd=root / "state", stdout=log, stderr=log,
                                 start_new_session=True)
    children.append(child)
    try:
        record = _wait_for(lambda: process_identity(child.pid), time.monotonic() + 2)
        manifest["processes"][role] = record
        _write_manifest(output, manifest)
    except BaseException:
        _stop_direct_child(child)
        raise


def prepare(output, chrome=None, fixtures=None):
    """The sole browser-launch path. Record owned processes immediately for bounded cleanup."""
    output, chrome = Path(output).absolute(), Path(chrome or default_chrome()).resolve()
    if output.exists() or not chrome.is_file():
        raise LabSafetyError("Refusing an existing manifest or a missing Chrome executable")
    output.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="jev-lab-", dir="/tmp")).resolve()
    lab_id = secrets.token_hex(12)
    (root / ".jev-lab-owner").write_text(lab_id)
    for name in ("profile", "runtime", "state", "fixtures"):
        (root / name).mkdir(mode=0o700)
    if len(os.fsencode(str(root / "runtime" / "bu.sock"))) >= 100:
        raise LabSafetyError("Lab Unix socket path is too long")
    if fixtures:
        fixtures = Path(fixtures).resolve()
        if not fixtures.is_dir() or any(p.is_symlink() for p in fixtures.rglob("*")):
            raise LabSafetyError("Fixture source must be a directory with no symbolic links")
        shutil.copytree(fixtures, root / "fixtures", dirs_exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION, "status": "preparing", "lab_id": lab_id, "root": str(root),
        "source_root": str(SOURCE_ROOT), "name": "jev_lab_" + lab_id, "python": sys.executable,
        **{name: str(root / name) for name in ("profile", "runtime", "state", "fixtures")}, "processes": {},
    }
    _write_manifest(output, manifest)
    environment = {k: v for k, v in os.environ.items() if not any(
        sensitive in k.upper() for sensitive in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PROXY")
    )}
    environment.update(isolated_environment(root, name=manifest["name"]))
    children = []

    def spawn(role, command):
        _spawn_owned(role, command, root=root, environment=environment, manifest=manifest, output=output,
                     children=children)

    try:
        ready_path = root / "fixture-ready.json"
        spawn("fixtures", [sys.executable, str(Path(__file__).resolve()), "serve-fixtures", "--root",
                           manifest["fixtures"], "--identity", lab_id, "--ready", str(ready_path)])
        ready = _wait_for(lambda: json.loads(ready_path.read_text()), time.monotonic() + STARTUP_SECONDS)
        if ready["lab_id"] != lab_id:
            raise LabSafetyError("Fixture server identity does not match")
        manifest.update(fixture_port=ready["port"], fixture_url=f"http://127.0.0.1:{ready['port']}",
                        iframe_port=ready["iframe_port"], iframe_url=f"http://localhost:{ready['iframe_port']}",
                        canary_port=ready["canary_port"])
        _listener_owned(manifest["processes"]["fixtures"]["pid"], manifest["fixture_port"])
        _listener_owned(manifest["processes"]["fixtures"]["pid"], manifest["iframe_port"])
        proxy_ready = root / "proxy-ready.json"
        spawn("proxy", [sys.executable, str(Path(__file__).resolve()), "serve-proxy", "--fixture-port",
                        str(manifest["fixture_port"]), "--iframe-port", str(manifest["iframe_port"]),
                        "--identity", lab_id, "--ready", str(proxy_ready),
                        "--audit", str(root / "proxy-audit.jsonl")])
        ready = _wait_for(lambda: json.loads(proxy_ready.read_text()), time.monotonic() + STARTUP_SECONDS)
        if (ready["lab_id"] != lab_id or ready["allowed_origins"] !=
                list(fixture_origins(manifest["fixture_port"], manifest["iframe_port"]))):
            raise LabSafetyError("Proxy server identity or allowlist does not match")
        manifest["proxy_port"] = ready["port"]
        _listener_owned(manifest["processes"]["proxy"]["pid"], manifest["proxy_port"])
        _write_manifest(output, manifest)
        spawn("chrome", [str(chrome), *chrome_sandbox_flags(), "--headless=new", "--enable-automation",
                         "--no-first-run", "--no-default-browser-check", "--disable-sync",
                         "--disable-background-networking",
                         "--disable-component-update", "--remote-debugging-address=127.0.0.1",
                         "--remote-debugging-port=0", f"--user-data-dir={manifest['profile']}",
                         *chrome_network_flags(manifest["proxy_port"]), "about:blank"])
        active = _wait_for(lambda: (root / "profile" / "DevToolsActivePort").read_text().splitlines(),
                           time.monotonic() + STARTUP_SECONDS)
        port = int(active[0])
        if not 0 < port < 65536 or not active[1].startswith("/devtools/browser/"):
            raise LabSafetyError("Invalid owned Chrome endpoint")
        manifest.update(cdp_port=port, cdp_ws=f"ws://127.0.0.1:{port}{active[1]}")
        _listener_owned(manifest["processes"]["chrome"]["pid"], port)
        environment["BU_CDP_WS"] = manifest["cdp_ws"]
        spawn("daemon", [sys.executable, "-m", "browser_harness.daemon"])
        _wait_for(lambda: _daemon_request(manifest, {"meta": "ping"}), time.monotonic() + STARTUP_SECONDS)
        manifest["status"] = "ready"
        _write_manifest(output, manifest)
        validate_manifest(output)
    except BaseException:
        manifest["status"] = "failed"
        # Failed persistence must not skip cleanup of the children this process still owns.
        with contextlib.suppress(Exception):
            _write_manifest(output, manifest)
        with contextlib.suppress(Exception):
            close(output)
        for child in children:
            _stop_direct_child(child)
        raise
    finally:
        # Reap only children that already exited; ready lab processes intentionally outlive this command.
        for child in children:
            child.poll()
    return manifest


def close(path):
    """Signal only independently verified recorded processes, never a process name/group."""
    path = Path(path)
    manifest = _read_manifest(path, ready=False)
    # A foreign/reused PID anywhere aborts the entire shutdown before even the valid daemon stops.
    live = {role for role, record in manifest["processes"].items() if verify_process(record, allow_exited=True)}
    _validate_endpoints(manifest, live, complete=manifest["status"] == "ready")
    for role in ("daemon", "chrome", "proxy", "fixtures"):
        record = manifest["processes"].get(role)
        if record is None or not verify_process(record, allow_exited=True):
            continue
        if role == "daemon":
            with contextlib.suppress(OSError, ValueError):
                ping = _daemon_request(manifest, {"meta": "ping"})
                if ping != {"pong": True, "pid": record["pid"], "browser_kind": "cdp"}:
                    raise LabSafetyError("Refusing shutdown of a different daemon")
                verify_process(record)
                _daemon_request(manifest, {"meta": "shutdown"})
        if verify_process(record, allow_exited=True):
            os.kill(record["pid"], signal.SIGTERM)
        deadline = time.monotonic() + PROCESS_WAIT_SECONDS
        while time.monotonic() < deadline and verify_process(record, allow_exited=True):
            time.sleep(0.05)
        if verify_process(record, allow_exited=True):
            os.kill(record["pid"], signal.SIGKILL)
            _wait_for(lambda: not verify_process(record, allow_exited=True), time.monotonic() + PROCESS_WAIT_SECONDS)
    manifest["status"] = "closed"
    _write_manifest(path, manifest)
    return manifest


def fixture_origins(fixture_port, iframe_port=None):
    """Canonical authorities map only to fixed owned loopback listeners; no DNS or arbitrary forwarding."""
    origins = {f"http://127.0.0.1:{fixture_port}": fixture_port}
    if iframe_port is not None:
        origins[f"http://localhost:{iframe_port}"] = iframe_port
    return origins


def proxy_target(method, target, headers, fixture_port, iframe_port=None):
    """Accept only exact named fixture origins, including the explicitly owned cross-site iframe origin."""
    if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
        raise LabSafetyError("Proxy method denied")
    if headers.get("Upgrade") or "upgrade" in headers.get("Connection", "").lower():
        raise LabSafetyError("WebSocket/upgrade denied")
    if headers.get("Transfer-Encoding"):
        raise LabSafetyError("Ambiguous proxy request framing denied")
    parsed = urlparse(target)
    origins = fixture_origins(fixture_port, iframe_port)
    if (f"{parsed.scheme}://{parsed.netloc}" not in origins or parsed.fragment
            or headers.get("Host") != parsed.netloc or any(character in target for character in "\r\n\x00")):
        raise LabSafetyError("Proxy destination denied: fixture origin only")
    try:
        length = int(headers.get("Content-Length", "0"))
    except ValueError as error:
        raise LabSafetyError("Invalid proxy request length") from error
    if not 0 <= length <= PROXY_LIMIT_BYTES:
        raise LabSafetyError("Proxy request too large")
    path = parsed.path or "/"
    if parsed.params:
        path += ";" + parsed.params
    return path + ("?" + parsed.query if parsed.query else ""), length


def relay_fixture_response(handler, response, hop_headers):
    """Stream only a bounded declared body; unknown lengths retain the existing bounded buffer."""
    declared = response.getheader("Content-Length")
    payload = None
    if declared is None:
        payload = response.read(PROXY_LIMIT_BYTES + 1)
        length = len(payload)
    else:
        try:
            length = int(declared)
        except ValueError:
            handler.send_error(502, "Invalid fixture response length")
            return
    if not 0 <= length <= PROXY_LIMIT_BYTES:
        handler.send_error(502, "Fixture response exceeds proxy bound")
        return
    handler.send_response(response.status)
    for name, value in response.getheaders():
        if name.lower() not in hop_headers | {"content-length"}:
            handler.send_header(name, value)
    handler.send_header("Content-Length", str(length))
    handler.end_headers()
    handler.response_started = True
    if handler.command == "HEAD":
        return
    if payload is not None:
        handler.wfile.write(payload)
        return
    remaining = length
    while remaining:
        block = response.read1(min(65536, remaining))
        if not block:
            raise http.client.IncompleteRead(b"", remaining)
        if len(block) > remaining:
            raise http.client.HTTPException("Fixture body exceeded its declared bound")
        handler.wfile.write(block)
        handler.wfile.flush()
        remaining -= len(block)


def serve_proxy(fixture_port, identity, ready, audit, iframe_port=None):
    """Owned HTTP proxy: two exact fixture forwarders, no CONNECT, DNS, or arbitrary sockets."""
    origins = fixture_origins(fixture_port, iframe_port)
    hop_headers = {"connection", "proxy-connection", "proxy-authorization", "keep-alive", "te", "trailer",
                   "transfer-encoding", "upgrade"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def forward(self):
            self.response_started = False
            try:
                path, length = proxy_target(self.command, self.path, self.headers, fixture_port, iframe_port)
                destination = urlparse(self.path)
                port = origins[f"{destination.scheme}://{destination.netloc}"]
                if len(self.headers.get_all("Host", [])) != 1 or len(self.headers.get_all("Content-Length", [])) > 1:
                    raise LabSafetyError("Duplicate proxy framing header denied")
            except (LabSafetyError, ValueError) as error:
                self.record("denied", str(error))
                self.send_error(403, "Lab proxy permits only the owned HTTP fixture origin")
                return
            self.record("allowed")
            connection_tokens = {item.strip().lower() for item in self.headers.get("Connection", "").split(",")}
            headers = {name: value for name, value in self.headers.items()
                       if name.lower() not in hop_headers | connection_tokens}
            headers.update(Host=destination.netloc, Connection="close")
            self.connection.settimeout(12)
            try:
                body = self.rfile.read(length) if length else None
                with contextlib.closing(http.client.HTTPConnection("127.0.0.1", port, timeout=12)) as upstream:
                    upstream.request(self.command, path, body=body, headers=headers)
                    response = upstream.getresponse()
                    relay_fixture_response(self, response, hop_headers)
            except (OSError, http.client.HTTPException):
                if self.response_started:
                    self.close_connection = True  # Never write a second response into a truncated streamed body.
                else:
                    self.send_error(502, "Owned fixture unavailable")

        def record(self, outcome, reason=""):
            payload = json.dumps({"method": self.command, "target": self.path,
                                  "outcome": outcome, "reason": reason}) + "\n"
            descriptor = os.open(audit, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(descriptor, payload.encode())
            finally:
                os.close(descriptor)

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_CONNECT = forward

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Path(ready).write_text(json.dumps({"lab_id": identity, "port": server.server_port,
                                      "allowed_origins": list(origins)}))
    server.serve_forever()


class FixtureSubmissions:
    """Independent per-trial server counters count every submission, including accidental repeats."""

    def __init__(self):
        self.records, self.lock = {}, threading.Lock()

    def snapshot(self, trial):
        with self.lock:
            record = self.records.get(trial, {"submissions": 0, "completed": 0, "cancelled": 0,
                                               "active": 0, "kinds": []})
            return {**record, "kinds": list(record["kinds"])}

    def start(self, trial, kind):
        with self.lock:
            record = self.records.setdefault(trial, {"submissions": 0, "completed": 0, "cancelled": 0,
                                                     "active": 0, "kinds": []})
            record["submissions"] += 1
            record["active"] += 1
            record["kinds"].append(kind)
            return record["submissions"]

    def finish(self, trial, completed):
        with self.lock:
            self.records[trial]["active"] -= 1
            self.records[trial]["completed" if completed else "cancelled"] += 1


def serve_fixtures(root, identity, ready):
    # A third, forbidden origin in the same owned process detects any proxy bypass, including raw TLS handshakes.
    canary_connections = []
    document_streams, stream_lock = {}, threading.Lock()
    submissions = FixtureSubmissions()

    class CanaryServer(http.server.ThreadingHTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            canary_connections.append(address)
            connection.settimeout(2)
            return connection, address

    class CanaryHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

    canary = CanaryServer(("127.0.0.1", 0), CanaryHandler)
    threading.Thread(target=canary.serve_forever, daemon=True).start()
    forbidden = f"http://127.0.0.1:{canary.server_port}"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def trial(self, request):
            value = parse_qs(request.query).get("trial_id", ["native"])[0]
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", value):
                raise ValueError("Invalid local fixture trial ID")
            return value

        def do_POST(self):
            request = urlparse(self.path)
            if request.path != "/__readiness__/submit":
                self.send_error(404)
                return
            self.submit(request, "Fetch")

        def submit(self, request, kind):
            trial = self.trial(request)
            number = submissions.start(trial, kind)
            completed = False
            try:
                parameters = parse_qs(request.query)
                if parameters.get("hold") == ["1"]:
                    self.connection.settimeout(0.2)
                    while True:  # Deliberately no response; ownership cleanup or client disconnect ends the request.
                        try:
                            if not self.connection.recv(1, socket.MSG_PEEK):
                                return
                            time.sleep(0.2)
                        except TimeoutError:
                            continue
                time.sleep(min(10, max(0, float(parameters.get("seconds", ["1"])[0]))))
                if kind == "Document":
                    self.respond("<!doctype html><meta charset=utf-8><title>Owned navigation result</title>"
                                 "<p>Results ready after navigation</p><script>window.fixture=" +
                                 json.dumps({"inputCount": number, "status": "ready"}) + ";</script>", "text/html")
                else:
                    self.respond(json.dumps({"ready": True, "submission": number}), "application/json")
                completed = True
            finally:
                submissions.finish(trial, completed)

        def do_GET(self):
            request = urlparse(self.path)
            if request.path == "/__readiness__/submissions":
                self.respond(json.dumps(submissions.snapshot(self.trial(request))), "application/json")
                return
            if request.path == "/__readiness__/navigation":
                self.submit(request, "Document")
                return
            if request.path == "/__readiness__/stream-status":
                stream_id = parse_qs(request.query).get("stream_id", ["native"])[0]
                with stream_lock:
                    status = dict(document_streams.get(stream_id, {}))
                self.respond(json.dumps(status), "application/json")
                return
            if request.path == "/__readiness__/stream-frame":
                stream_id = parse_qs(request.query).get("stream_id", ["native"])[0]
                first = ("<!doctype html><meta charset=utf-8><title>Owned streaming child Document</title><body>"
                         "<script>window.childState={started:true,finished:false};</script>"
                         "<p>Initial document bytes received</p>" + " " * 4096).encode()
                last = b"<script>window.childState.finished=true;</script></body>"
                with stream_lock:
                    document_streams[stream_id] = {"started": True, "finished": False,
                                                   "initial_bytes": len(first), "remaining_bytes": len(last)}
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(first) + len(last)))
                self.end_headers()
                try:
                    self.wfile.write(first)
                    self.wfile.flush()
                    time.sleep(8)
                    self.wfile.write(last)
                    self.wfile.flush()
                finally:
                    with stream_lock:
                        document_streams[stream_id]["finished"] = True
                return
            if request.path == "/__egress__/status":
                self.respond(json.dumps({"connections": len(canary_connections), "canary_port": canary.server_port}),
                             "application/json")
                return
            if request.path == "/__egress__/redirect":
                self.send_response(302)
                self.send_header("Location", forbidden + "/redirect")
                self.end_headers()
                return
            if request.path == "/__egress__/page":
                self.respond("<!doctype html><title>Owned egress fixture</title>"
                             "<body>Local network boundary probe</body>", "text/html")
                return
            if request.path in {"/__egress__/worker.js", "/__egress__/shared.js", "/__egress__/service.js"}:
                kind = request.path.rsplit("/", 1)[1].removesuffix(".js")
                fetch = f"fetch({json.dumps(forbidden + '/' + kind)},{{mode:'no-cors'}}).catch(()=>null)"
                code = {"worker": f"{fetch}.then(()=>postMessage('done'));",
                        "shared": f"onconnect=e=>{{{fetch}.then(()=>e.ports[0].postMessage('done'))}};",
                        "service": f"oninstall=e=>e.waitUntil({fetch}.then(()=>self.skipWaiting()));"}[kind]
                self.respond(code, "text/javascript")
                return
            if request.path in {"/__lab__", "/delay"}:
                delay = min(10, max(0, float(parse_qs(request.query).get("seconds", ["0"])[0])))
                time.sleep(delay)
                payload = json.dumps({"lab_id": identity, "ready": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                super().do_GET()

        def respond(self, text, content_type):
            payload = text.encode()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=root))
    iframe = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=root))
    threading.Thread(target=iframe.serve_forever, daemon=True).start()
    Path(ready).write_text(json.dumps({"lab_id": identity, "port": server.server_port,
                                      "iframe_port": iframe.server_port, "canary_port": canary.server_port}))
    server.serve_forever()


def run_native(pytest_args, chrome=None, fixtures=None):
    """Prepare a fresh owned lab, run the native suite against it, and close the lab even when tests fail."""
    output = SOURCE_ROOT / "artifacts" / "labs" / f"{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}.json"
    prepare(output, chrome, fixtures or SOURCE_ROOT / "tests" / "fixtures")
    try:
        command = [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", "-m", "native",
                   f"--lab-manifest={output}", *pytest_args]
        return subprocess.run(command, cwd=SOURCE_ROOT, check=False).returncode
    finally:
        close(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare")
    setup.add_argument("--output", required=True)
    setup.add_argument("--chrome", help="Chrome/Chromium executable; default: JEV_LAB_CHROME or a fixed install path")
    setup.add_argument("--fixtures")
    native = commands.add_parser("run", help="prepare a lab, run the native tests, always close the lab")
    native.add_argument("--chrome", help="Chrome/Chromium executable; default: JEV_LAB_CHROME or a fixed install path")
    native.add_argument("--fixtures")
    native.add_argument("pytest_args", nargs=argparse.REMAINDER, help="extra pytest arguments, after --")
    shutdown = commands.add_parser("close")
    shutdown.add_argument("--manifest", required=True)
    fixture = commands.add_parser("serve-fixtures")
    fixture.add_argument("--root", required=True)
    fixture.add_argument("--identity", required=True)
    fixture.add_argument("--ready", required=True)
    proxy = commands.add_parser("serve-proxy")
    proxy.add_argument("--fixture-port", required=True, type=int)
    proxy.add_argument("--iframe-port", required=True, type=int)
    proxy.add_argument("--identity", required=True)
    proxy.add_argument("--ready", required=True)
    proxy.add_argument("--audit", required=True)
    commands.add_parser("run-offline-mcp", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output, args.chrome, args.fixtures)
        print(f"Owned native lab ready: {Path(args.output).absolute()}")
    elif args.command == "run":
        raise SystemExit(run_native([arg for arg in args.pytest_args if arg != "--"], args.chrome, args.fixtures))
    elif args.command == "close":
        close(args.manifest)
        print("Owned native lab closed; retained disposable files for inspection")
    elif args.command == "serve-fixtures":
        serve_fixtures(args.root, args.identity, args.ready)
    elif args.command == "serve-proxy":
        serve_proxy(args.fixture_port, args.identity, args.ready, args.audit, args.iframe_port)
    else:
        RuntimeGuard().install()
        runpy.run_module("jev_ultrafast.mcp_server", run_name="__main__")


if __name__ == "__main__":
    main()
