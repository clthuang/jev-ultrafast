"""Offline proofs that test mode cannot reach providers, user Chrome, or reused PIDs."""

import json
import os
import socket
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import validation_lab as lab


def test_offline_mode_denies_network_and_browser():
    for address in (("127.0.0.1", 9222), ("api.typesafe.ai", 443), "/tmp/not-a-lab.sock"):
        with pytest.raises(lab.LabSafetyError):
            lab.RuntimeGuard().check_address(address)
    with socket.socket() as connection, pytest.raises(lab.LabSafetyError):
        connection.connect(("127.0.0.1", 9222))
    with pytest.raises(lab.LabSafetyError):
        subprocess.Popen(["browser-harness", "--reload"])


def test_offline_node_fixtures_cannot_connect_or_launch_processes():
    for code in ("require('node:net').connect(9222,'127.0.0.1')", "require('node:child_process').spawn('claude')"):
        result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=5, check=False)
        assert result.returncode != 0 and "Node network/process I/O denied in tests" in result.stderr


def test_native_mode_still_denies_model_and_review_dispatch(monkeypatch):
    from jev_ultrafast import model

    guard = lab.RuntimeGuard({"runtime": "/tmp/owned/runtime", "cdp_port": 4567, "fixture_port": 4568,
                              "processes": {"daemon": {"pid": 7}, "chrome": {"pid": 8}, "fixtures": {"pid": 9}}})
    checked = Mock()
    monkeypatch.setattr(lab, "verify_process", checked)
    guard.check_address(("127.0.0.1", 4567))
    guard.check_address(("127.0.0.1", 4568))
    guard.check_address("/tmp/owned/runtime/bu.sock")
    assert checked.call_count == 3
    for address in (("127.0.0.1", 9222), ("localhost", 4567), ("api.typesafe.ai", 443)):
        with pytest.raises(lab.LabSafetyError):
            guard.check_address(address)
    with pytest.raises(lab.LabSafetyError):
        model.CLIENT.post("http://127.0.0.1:4568/model")
    for command in (["claude", "-p", "review"], ["python", "scripts/review_runs.py", "auto"]):
        with pytest.raises(lab.LabSafetyError):
            guard.check_command(command)


def test_native_environment_isolated_before_browser_imports(tmp_path):
    environment = lab.isolated_environment(tmp_path, name="owned", cdp_ws="ws://127.0.0.1:9/devtools/browser/id")
    assert environment["BU_BROWSER_ID"] == environment["BU_CDP_URL"] == ""
    assert environment["BU_AUTOSPAWN"] == environment["BH_TELEMETRY"] == environment["JEV_AUTO_REVIEW"] == "0"
    for key in ("BH_HOME", "BH_CONFIG_DIR", "BH_RUNTIME_DIR", "BH_TMP_DIR", "BH_AGENT_WORKSPACE"):
        assert Path(environment[key]).is_relative_to(tmp_path)
    assert os.environ["BU_NAME"] != "default"


def test_mocked_client_and_process_remain_usable(monkeypatch):
    from jev_ultrafast import model

    client, process = Mock(), Mock()
    monkeypatch.setattr(model.CLIENT, "post", client)
    monkeypatch.setattr(subprocess, "Popen", process)
    model.CLIENT.post("https://example.invalid")
    subprocess.Popen(["claude", "fake test"])
    client.assert_called_once()
    process.assert_called_once()


def _manifest(tmp_path, status="ready"):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".jev-lab-owner").write_text("owned")
    manifest = {"schema_version": 1, "status": status, "lab_id": "owned", "root": str(root),
                "source_root": str(lab.SOURCE_ROOT), "processes": {}}
    for key in ("profile", "runtime", "state", "fixtures"):
        (root / key).mkdir()
        manifest[key] = str(root / key)
    path = tmp_path / "lab.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


@pytest.mark.parametrize("change", ["birth", "uid", "command"])
def test_reused_or_foreign_process_is_never_signalled(tmp_path, monkeypatch, change):
    path, manifest = _manifest(tmp_path)
    original = {"pid": 3456, "birth": "old", "uid": os.getuid(), "command": "owned chrome"}
    manifest["processes"]["chrome"] = original
    path.write_text(json.dumps(manifest))
    current = {**original, change: os.getuid() + 1 if change == "uid" else "changed"}
    monkeypatch.setattr(lab, "process_identity", lambda _pid: current)
    kill = Mock()
    monkeypatch.setattr(lab.os, "kill", kill)
    with pytest.raises(lab.LabSafetyError, match="identity changed"):
        lab.close(path)
    kill.assert_not_called()
    assert json.loads(path.read_text())["status"] == "ready"


def test_cleanup_targets_only_recorded_owned_processes(tmp_path, monkeypatch):
    path, manifest = _manifest(tmp_path, "preparing")
    manifest["proxy_port"] = 9878
    record = {"pid": 3456, "birth": "same", "uid": os.getuid(), "command":
              "chrome --user-data-dir=" + manifest["profile"] + " " + " ".join(lab.chrome_network_flags(9878))}
    manifest["processes"]["chrome"] = record
    path.write_text(json.dumps(manifest))
    live = {"value": True}
    monkeypatch.setattr(lab, "process_identity", lambda _pid: record if live["value"] else None)
    killed = []

    def kill(pid, sig):
        killed.append((pid, sig))
        live["value"] = False

    monkeypatch.setattr(lab.os, "kill", kill)
    assert lab.close(path)["status"] == "closed"
    assert killed == [(3456, lab.signal.SIGTERM)]
    lab.close(path)
    assert len(killed) == 1


@pytest.mark.parametrize("change", ["missing", "schema", "marker", "path", "status"])
def test_native_runner_refuses_missing_or_foreign_manifest(tmp_path, monkeypatch, change):
    path, manifest = _manifest(tmp_path)
    if change == "schema":
        manifest["schema_version"] = 99
    elif change == "marker":
        (Path(manifest["root"]) / ".jev-lab-owner").write_text("different")
    elif change == "path":
        manifest["runtime"] = "/tmp/foreign"
    elif change == "status":
        manifest["status"] = "preparing"
    path.write_text(json.dumps(manifest))
    if change == "missing":
        path.unlink()
    request = Mock()
    monkeypatch.setattr(lab, "_daemon_request", request)
    with pytest.raises((lab.LabSafetyError, FileNotFoundError)):
        lab.validate_manifest(path)
    request.assert_not_called()


def test_manifest_rejects_mismatched_daemon_before_browser_use(tmp_path, monkeypatch):
    path, manifest = _manifest(tmp_path)
    record = {"pid": 3456, "birth": "same", "uid": os.getuid(),
              "command": "chrome --user-data-dir=" + manifest["profile"] + " "
              + " ".join(lab.chrome_network_flags(9878))}
    manifest.update(processes={"chrome": record, "daemon": {**record, "pid": 3457},
                               "fixtures": {**record, "pid": 3458}, "proxy": {**record, "pid": 3459}},
                    cdp_port=9876, cdp_ws="ws://127.0.0.1:9876/devtools/browser/id", fixture_port=9877,
                    fixture_url="http://127.0.0.1:9877", proxy_port=9878)
    (Path(manifest["profile"]) / "DevToolsActivePort").write_text("9876\n/devtools/browser/id\n")
    (Path(manifest["root"]) / "proxy-ready.json").write_text(json.dumps(
        {"lab_id": "owned", "port": 9878, "allowed_origin": manifest["fixture_url"]}))
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(lab, "verify_process", lambda _record: True)
    monkeypatch.setattr(lab, "_listener_owned", lambda *_: None)
    monkeypatch.setattr(lab, "_daemon_request", lambda *_: {"pong": True, "pid": 1, "browser_kind": "local"})
    with pytest.raises(lab.LabSafetyError, match="recorded isolated"):
        lab.validate_manifest(path)


def test_cleanup_prevalidates_every_identity_before_shutdown_or_signal(tmp_path, monkeypatch):
    path, manifest = _manifest(tmp_path)
    daemon = {"pid": 3456, "birth": "same", "uid": os.getuid(), "command": "owned daemon"}
    chrome = {**daemon, "pid": 3457, "command": "owned chrome"}
    manifest["processes"] = {"daemon": daemon, "chrome": chrome}
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(lab, "process_identity", lambda pid: daemon if pid == daemon["pid"] else
                        {**chrome, "birth": "reused"})
    request, kill = Mock(), Mock()
    monkeypatch.setattr(lab, "_daemon_request", request)
    monkeypatch.setattr(lab.os, "kill", kill)
    with pytest.raises(lab.LabSafetyError, match="identity changed"):
        lab.close(path)
    request.assert_not_called()
    kill.assert_not_called()


def test_cleanup_prevalidates_endpoints_before_shutdown_or_signal(tmp_path, monkeypatch):
    path, manifest = _manifest(tmp_path, "preparing")
    daemon = {"pid": 3456, "birth": "same", "uid": os.getuid(), "command": "owned daemon"}
    manifest.update(processes={"daemon": daemon, "fixtures": {**daemon, "pid": 3457}}, fixture_port=12345)
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(lab, "verify_process", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(lab, "_listener_owned", Mock(side_effect=lab.LabSafetyError("foreign endpoint")))
    request, kill = Mock(), Mock()
    monkeypatch.setattr(lab, "_daemon_request", request)
    monkeypatch.setattr(lab.os, "kill", kill)
    with pytest.raises(lab.LabSafetyError, match="foreign endpoint"):
        lab.close(path)
    request.assert_not_called()
    kill.assert_not_called()


@pytest.mark.parametrize("fault", ["identity", "manifest"])
def test_unregistered_child_is_stopped_and_reaped(tmp_path, monkeypatch, fault):
    path, manifest = _manifest(tmp_path, "preparing")
    child = Mock(pid=3456)
    child.poll.return_value = None
    monkeypatch.setattr(lab.subprocess, "Popen", Mock(return_value=child))
    identity = {"pid": 3456, "birth": "same", "uid": os.getuid(), "command": "owned child"}
    monkeypatch.setattr(lab, "process_identity", Mock(return_value=identity,
                        side_effect=subprocess.TimeoutExpired("ps", 2) if fault == "identity" else None))
    if fault == "manifest":
        monkeypatch.setattr(lab, "_write_manifest", Mock(side_effect=OSError("full disk")))
    children = []
    with pytest.raises((subprocess.TimeoutExpired, OSError)):
        lab._spawn_owned("fixtures", ["fake-owned-child"], root=Path(manifest["root"]), environment={},
                         manifest=manifest, output=path, children=children)
    assert children == [child]
    child.terminate.assert_called_once()
    child.wait.assert_called_once_with(timeout=lab.PROCESS_WAIT_SECONDS)
    child.kill.assert_not_called()


@pytest.mark.parametrize(("method", "target", "extra"), [
    ("CONNECT", "127.0.0.1:4568", {}),
    ("GET", "https://127.0.0.1:4568/private", {}),
    ("GET", "http://example.invalid/private", {}),
    ("GET", "http://127.0.0.1:4569/private", {}),
    ("GET", "http://localhost:4568/private", {}),
    ("GET", "http://[::1]:4568/private", {}),
    ("GET", "http://127.0.0.1:4568@other.invalid/private", {}),
    ("GET", "http://127.0.0.1:4568/private", {"Upgrade": "websocket"}),
    ("GET", "http://127.0.0.1:4568/private", {"Host": "other.invalid"}),
    ("POST", "http://127.0.0.1:4568/private", {"Transfer-Encoding": "chunked"}),
    ("POST", "http://127.0.0.1:4568/private", {"Content-Length": "-1"}),
])
def test_proxy_denies_every_destination_except_exact_http_fixture(method, target, extra):
    with pytest.raises(lab.LabSafetyError):
        lab.proxy_target(method, target, {"Host": "127.0.0.1:4568", **extra}, 4568)


def test_proxy_forwards_only_observed_fixture_path():
    assert lab.proxy_target("GET", "http://127.0.0.1:4568/allowed?a=1", {"Host": "127.0.0.1:4568"}, 4568) == (
        "/allowed?a=1", 0)


def test_cdp_cannot_override_owned_proxy():
    for params in ({"proxyServer": "direct://"}, {"proxyBypassList": "*"}):
        with pytest.raises(lab.LabSafetyError, match="override"):
            lab.RuntimeGuard.check_cdp("Target.createBrowserContext", params)
    lab.RuntimeGuard.check_cdp("Target.createTarget", {"url": "about:blank"})


@pytest.mark.native
def test_native_browser_egress_uses_owned_proxy_across_contexts(lab_manifest):
    from jev_ultrafast.browser import Browser

    manifest = lab_manifest
    audit_path = Path(manifest["root"]) / "proxy-audit.jsonl"
    audit_start = len(audit_path.read_text().splitlines()) if audit_path.exists() else 0
    browser = Browser(manifest["fixture_url"] + "/__egress__/page")
    forbidden = f"http://127.0.0.1:{manifest['canary_port']}"
    expression = """(async forbidden => {
      const tasks=[];
      const attempt=url=>fetch(url,{mode:'no-cors'}).catch(()=>null);
      tasks.push(attempt(forbidden+'/fetch'),attempt(forbidden.replace('http:','https:')+'/https'));
      tasks.push(attempt('/__egress__/redirect'));
      for(const tag of ['iframe','img']) {
        tasks.push(new Promise(resolve=>{const e=document.createElement(tag);e.onload=e.onerror=resolve;
          e.src=forbidden+'/'+tag;document.body.append(e)}));
      }
      const popup=window.open(forbidden+'/popup');
      tasks.push(new Promise(resolve=>{const worker=new Worker('/__egress__/worker.js');
        worker.onmessage=()=>{worker.terminate();resolve()};worker.onerror=resolve}));
      tasks.push(new Promise(resolve=>{const worker=new SharedWorker('/__egress__/shared.js');
        worker.port.onmessage=()=>{worker.port.close();resolve()};worker.onerror=resolve}));
      tasks.push(navigator.serviceWorker.register('/__egress__/service.js').then(reg=>new Promise(resolve=>{
        const worker=reg.installing||reg.waiting||reg.active;
        const check=()=>{if(worker.state==='activated'||worker.state==='redundant')resolve(reg.unregister())};
        worker.addEventListener('statechange',check);check();
      })));
      tasks.push(new Promise(resolve=>{const ws=new WebSocket(forbidden.replace('http:','ws:')+'/websocket');
        ws.onerror=resolve;ws.onopen=()=>{ws.close();resolve()}}));
      const result=await Promise.race([Promise.all(tasks).then(()=>true),
        new Promise(r=>setTimeout(()=>r(false),8000))]);
      if(popup)popup.close();
      return {completed:result,positive:await fetch('/__lab__').then(r=>r.json()),
        canary:await fetch('/__egress__/status').then(r=>r.json())};
    })(""" + json.dumps(forbidden) + ")"
    try:
        response = browser.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True,
                                userGesture=True, _response_timeout=12)
        assert "exceptionDetails" not in response, response
        result = response["result"]["value"]
        assert result["completed"], result
        assert result["positive"] == {"lab_id": manifest["lab_id"], "ready": True}
        assert result["canary"] == {"connections": 0, "canary_port": manifest["canary_port"]}
        audit = [json.loads(line) for line in audit_path.read_text().splitlines()[audit_start:]]
        denied = [item for item in audit if item["outcome"] == "denied"]
        for suffix in ("fetch", "redirect", "iframe", "img", "popup", "worker", "shared", "service"):
            assert any(item["target"].endswith("/" + suffix) for item in denied), (suffix, denied)
        # Chrome tunnels even unencrypted ws:// through CONNECT, so the proxy sees its authority, not its path.
        assert sum(item["method"] == "CONNECT" and item["target"] == f"127.0.0.1:{manifest['canary_port']}"
                   for item in denied) >= 2
        (Path(manifest["root"]) / "network-proof.json").write_text(json.dumps(
            {"result": result, "proxy_requests": audit}, indent=2) + "\n")
    finally:
        browser.close_popups()
        browser.close()


def test_process_identity_uses_kernel_birth_time():
    current = lab.process_identity(os.getpid())
    assert current["pid"] == os.getpid() and current["uid"] == os.getuid()
    assert current["birth"] and current["command"]
    assert lab.process_identity(os.getpid()) == current


def test_production_trigger_cannot_reach_candidate_writers_or_state(tmp_path, monkeypatch):
    """A late production trigger resolves its own cwd script, not a nested candidate writer."""
    from jev_ultrafast import mcp_server

    production = tmp_path / "production"
    candidate = production / "artifacts" / "candidate"
    for source, contents in ((production, "baseline writer"), (candidate, "candidate envelope writer")):
        (source / "scripts").mkdir(parents=True)
        (source / "scripts/review_runs.py").write_text(contents)
        (source / "artifacts/reviews").mkdir(parents=True)
    production_notes = production / "artifacts/notes.json"
    production_notes.write_text('[{"legacy":true}]')
    before = production_notes.read_bytes()
    calls = []

    def fake_child(command, **options):
        cwd = Path(options.get("cwd", Path.cwd())).resolve()
        writer = (cwd / command[1]).resolve()
        calls.append((writer, writer.read_text(), cwd / "artifacts/reviews"))
        return Mock()

    monkeypatch.setattr(mcp_server.subprocess, "Popen", fake_child)
    monkeypatch.chdir(production)
    mcp_server.start_review()
    monkeypatch.chdir(candidate)
    mcp_server.start_review()
    assert calls == [
        (production / "scripts/review_runs.py", "baseline writer", production / "artifacts/reviews"),
        (candidate / "scripts/review_runs.py", "candidate envelope writer", candidate / "artifacts/reviews"),
    ]
    assert production_notes.read_bytes() == before
    assert not list((production / "artifacts/reviews").glob("*.json"))
    assert not list((candidate / "artifacts/reviews").glob("*.json"))
