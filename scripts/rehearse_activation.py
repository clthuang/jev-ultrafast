"""Rehearse the review store's activation and rollback on disposable stores (RELEASE-3), never on a real one.

For a store as the baseline left it, and a mixed one with v2 attempts and a pending receipt: owned dummy writers block
every change; stopped, the store is backed up and read back, migrated, read and written by today's code, refused a stale
backup, and exported for a rollback that the baseline code itself (3efae4f, frozen in tests/fixtures/baseline/) reads.
Every command runs as an operator runs it, from the disposable checkout. A fake `claude` first on PATH records any paid
launch; there must be none. Evidence: <root>/rehearsal.json.

    uv run python scripts/rehearse_activation.py [--root <a new folder>]
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "migrate_review_storage.py"
BASELINE = ROOT / "tests" / "fixtures" / "baseline"
RUN_A, RUN_B, RUN_C, RELABELLED, LATE = ("20261003-100000-0001", "20261003-100100-0002", "20261003-100200-0003",
                                         "20261003-100300-0004", "20261003-100400-0005")

# Builds a store in the working directory with today's code and, for the mixed store, a fake launcher in this process
# only: what the candidate would have left, with no binary or model.
BUILD = textwrap.dedent('''
    import json, sys
    from copy import deepcopy
    from pathlib import Path
    sys.path.append(sys.argv[1])
    from jev_ultrafast import site_notes
    from scripts import review_runs
    kind = sys.argv[2]
    RUNS = review_runs.RUNS

    def run(run_id, **changes):
        RUNS.mkdir(parents=True, exist_ok=True)
        value = {"goal": "Search", "page": {"url": "https://example.com/", "title": "Search"}, "history": [],
                 "text_calls": [], "decisions": [], "previous_run": None,
                 "result": {"status": "blocked", "notes": ["Jev answered BLOCKED"]},
                 "outcome": [{"passed": False, "by": "claude", "evidence": "No results", "at": "2026-10-03T10:00:00"}],
                 **changes}
        (RUNS / f"{run_id}.json").write_text(json.dumps(value))

    approved = {**deepcopy(site_notes.SEEDS[0]), "id": "kept.example-1", "site": "kept.example",
                "approved": "2026-09-28", "shown": 4, "last_shown": "2026-09-30", "failed_after": 1}
    retired = {**deepcopy(site_notes.SEEDS[0]), "id": "old.example-1", "site": "old.example", "approved": None,
               "retired": "2026-09-28"}
    site_notes.NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    site_notes.NOTES_PATH.write_text(json.dumps([*site_notes.SEEDS, approved, retired]))
    review_runs.REVIEWS.mkdir(parents=True, exist_ok=True)
    (review_runs.REVIEWS / "20260927-100000.json").write_text(json.dumps(
        {"queue": {"runs": [sys.argv[5]], "notes": {}}, "decisions": [], "flags": [], "proposals": [],
         "summary": "Old review.", "cost": 0.07}))
    site_notes.write_review_state({"last_start": "2026-09-28T09:00:00", "next_due": 0, "running": None,
                                   "failures": 1, "off": False})
    run(sys.argv[3])
    run(sys.argv[4], previous_run=sys.argv[3], result={"status": "done", "notes": []}, outcome=[
        {"passed": False, "by": "claude", "evidence": "Looked wrong", "at": "2026-10-03T11:00:00"},
        {"passed": True, "by": "user", "evidence": "Corrected: it worked", "at": "2026-10-03T11:05:00"}])
    run(sys.argv[5])
    (RUNS / f"{sys.argv[5]}.jpg").write_bytes(b"\\xff\\xd8 screenshot")
    run(sys.argv[6])  # failed: reviewed in the mixed store, relabelled after activation in both
    if kind == "mixed":
        site_notes.update(lambda notes: None)
        reply = {"decisions": [], "flags": [], "proposals": [], "summary": "Reviewed"}

        def fake_launch(text, budget, quote=str, *, before_spawn=None, on_spawn=None, on_exit=None):
            class Child:
                pid = 2 ** 22 - 7
            before_spawn()
            on_spawn(Child())
            on_exit(Child())
            return {}, {"subtype": "success", "structured_output": reply, "total_cost_usd": 0.0123}, None

        review_runs.launch = fake_launch
        review_runs.process_identity = lambda pid: {"state": "present", "pid": pid, "birth": "1:1",
                                                    "uid": review_runs.os.getuid(), "pgid": pid}
        review_runs.group_alive = lambda pid: False
        assert review_runs.once_command(None) == 0
        run(sys.argv[7])  # a later failure, whose review commits but whose digest is not yet written
        batch = review_runs.prepare_batch()
        def fail(receipt):
            raise OSError("disk full")
        review_runs.ensure_digest = fail
        try:
            review_runs.record_review(reply, batch)
        except OSError:
            pass
        assert site_notes.read_envelope(site_notes.NOTES_PATH)["pending_review"]["batch_id"] == batch["batch_id"]
''')

# Today's code after activation: what still waits for a review, then a new note and a new label.
WRITE = textwrap.dedent('''
    import json, sys
    sys.path.append(sys.argv[1])
    from jev_ultrafast import run_store, site_notes
    from scripts import review_runs
    waiting = review_runs.build_queue()
    site_notes.add_note({"site": "new.example", "hint": "scroll_first", "detail": "Added after activation",
                         "url": None, "failure": None, "runs": {"failed": [], "recovered": None}})
    run_store.append_outcome(review_runs.RUNS / f"{sys.argv[2]}.json",
                             {"passed": True, "by": "user", "evidence": "Relabelled after activation",
                              "at": "2026-10-05T10:00:00"})
    waiting = review_runs.build_queue()
    notes = site_notes.read_envelope(site_notes.NOTES_PATH)["notes"]
    print(json.dumps({"runs": sorted(waiting["runs"]), "notes": sorted(waiting["notes"]),
                      "note_ids": [note["id"] for note in notes]}))
''')

# The baseline itself, from its frozen copies, run in a checkout whose artifacts/ is the rollback export.
BASELINE_READ = textwrap.dedent('''
    import importlib.util, json, sys, types
    from pathlib import Path
    folder = Path(sys.argv[1])
    package = types.ModuleType("jev_ultrafast")
    package.__path__ = []
    sys.modules["jev_ultrafast"] = package
    modules = {}
    for module, name in (("jev_ultrafast.site_notes", "site_notes.py"), ("baseline_review_runs", "review_runs.py")):
        spec = importlib.util.spec_from_file_location(module, folder / name)
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[module] = loaded
        if module == "jev_ultrafast.site_notes":
            package.site_notes = loaded
        spec.loader.exec_module(loaded)
        modules[name] = loaded
    notes, error = modules["site_notes.py"].load(create=False)
    reviewed_runs, reviewed_notes = modules["review_runs.py"].reviewed()
    queue = modules["review_runs.py"].build_queue()
    print(json.dumps({"error": error, "note_ids": [note["id"] for note in notes],
                      "well_formed": all(map(modules["site_notes.py"].well_formed, notes)),
                      "reviewed_runs": sorted(reviewed_runs), "runs": sorted(queue["runs"]),
                      "notes": sorted(queue["notes"]), "state": modules["site_notes.py"].read_review_state()}))
''')

DUMMY = textwrap.dedent('''
    import fcntl, sys, time
    from pathlib import Path
    if len(sys.argv) > 1:
        Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
        handle = open(sys.argv[1], "a")
        fcntl.flock(handle, fcntl.LOCK_EX)
    print("ready", flush=True)
    while True:
        time.sleep(1)
''')

FAKE_CLAUDE = '#!/bin/sh\necho "$0 $*" >> "$(dirname "$0")/claude-calls.log"\nexit 1\n'


def sha_tree(folder):
    """Each state file's checksum; a lock file, which any writer may create, is no state."""
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(folder).rglob("*")) if path.is_file() and not path.name.endswith(".lock")}


class Rehearsal:
    def __init__(self, root):
        self.root, self.evidence, self.failures = Path(root), [], []
        self.bin = self.root / "bin"
        self.bin.mkdir(parents=True)
        (self.bin / "claude").write_text(FAKE_CLAUDE)
        (self.bin / "claude").chmod(0o755)
        self.environment = {**{key: value for key, value in os.environ.items() if not any(
            secret in key.upper() for secret in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))},
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", "JEV_AUTO_REVIEW": "0"}

    def check(self, condition, what):
        self.evidence.append({"check": what, "passed": bool(condition)})
        if not condition:
            self.failures.append(what)

    def run(self, checkout, *arguments, expect=0):
        started = time.monotonic()
        result = subprocess.run([sys.executable, *map(str, arguments)], cwd=checkout, env=self.environment,
                                capture_output=True, text=True, timeout=120, check=False)
        self.evidence.append({"command": " ".join(str(item) for item in arguments[:3]), "cwd": str(checkout),
                              "exit": result.returncode, "seconds": round(time.monotonic() - started, 2),
                              "stdout": result.stdout[-1500:], "stderr": result.stderr[-1500:]})
        self.check(result.returncode == expect, f"{' '.join(str(item) for item in arguments[:2])} exits {expect}")
        return result

    def tool(self, checkout, *arguments, expect=0):
        return self.run(checkout, TOOL, *arguments, expect=expect)

    @contextlib.contextmanager
    def dummy_writers(self, checkout):
        """Two owned stand-ins for old writers, working in the checkout as the real ones would: a server holding the
        review lock, and the review CLI. Their programs live outside the checkout, so nothing there shadows a module."""
        programs = self.root / "old-writers" / checkout.name
        (programs / "bin").mkdir(parents=True)
        server = programs / "bin" / "jev-mcp"
        server.write_text(f"#!{sys.executable}\n{DUMMY}")
        server.chmod(0o755)
        (programs / "scripts").mkdir()
        (programs / "scripts" / "review_runs.py").write_text(DUMMY)
        children = [subprocess.Popen([str(server), str(checkout / "artifacts" / "reviews" / ".lock")], cwd=checkout,
                                     stdout=subprocess.PIPE, text=True, start_new_session=True),
                    subprocess.Popen([sys.executable, str(programs / "scripts" / "review_runs.py")], cwd=checkout,
                                     stdout=subprocess.PIPE, text=True, start_new_session=True)]
        try:
            for child in children:
                assert child.stdout.readline().strip() == "ready"
            yield children
        finally:
            for child in children:
                if child.poll() is None:
                    os.kill(child.pid, signal.SIGTERM)  # our own children only, never a process found by name
                    child.wait(timeout=10)

    def rehearse(self, kind):
        checkout = self.root / kind
        (checkout / "artifacts").mkdir(parents=True)
        self.evidence.append({"store": kind})
        self.run(checkout, "-c", BUILD, ROOT, kind, RUN_A, RUN_B, RUN_C, RELABELLED, LATE)
        built = sha_tree(checkout / "artifacts")
        attempts = len(list((checkout / "artifacts" / "reviews" / "attempts").glob("*.json")))

        with self.dummy_writers(checkout) as children:
            inventory = json.loads(self.tool(checkout, "inventory", expect=1).stdout)
            self.check(len(inventory["writers"]) == 2 and inventory["locks"]["review"],
                       f"{kind}: the inventory names both old writers and the held review lock")
            self.tool(checkout, "backup", "--to", self.root / f"{kind}-refused", expect=2)
            self.check(sha_tree(checkout / "artifacts") == built and not (self.root / f"{kind}-refused").exists(),
                       f"{kind}: a refused backup changed nothing")
        self.check(all(child.returncode is not None for child in children), f"{kind}: the old writers exited")
        inventory = json.loads(self.tool(checkout, "inventory").stdout)
        self.check(inventory["blocking"] == [] and inventory["damaged"] == [], f"{kind}: quiescent once stopped")
        if kind == "mixed":
            self.check(inventory["notes"]["pending_receipt"] is not None, "mixed: a receipt is pending")

        backup = self.root / f"{kind}-backup"
        self.tool(checkout, "backup", "--to", backup)
        manifest = json.loads((backup / "backup-manifest.json").read_text())["files"]
        copies = sha_tree(backup)
        self.check(all(copies[relative] == expected == built[relative] for relative, expected in manifest.items())
                   and set(manifest) == set(built),
                   f"{kind}: the backup holds every store file, read back by its checksums")
        migrated = json.loads(self.tool(checkout, "migrate", "--backup", backup).stdout)
        self.check(migrated["notes_after"] == "envelope 2", f"{kind}: notes migrated to the envelope")
        if kind == "mixed":
            self.check(migrated["receipt_recovered"] is not None, "mixed: the pending receipt became its digest")

        # Today's code restarts: readers first, automatic review off, then a new note and a new label.
        self.run(checkout, ROOT / "scripts" / "report_runs.py", "--runs", "artifacts/runs", "--artifacts",
                 "artifacts")
        self.run(checkout, ROOT / "scripts" / "review_runs.py", "auto")
        waiting = json.loads(self.run(checkout, "-c", WRITE, ROOT, RELABELLED).stdout)
        self.tool(checkout, "migrate", "--backup", backup, expect=2)  # never over newer work
        self.check(sha_tree(checkout / "artifacts")[f"runs/{RELABELLED}.json"] != built.get(f"runs/{RELABELLED}.json"),
                   f"{kind}: the stale backup was refused and the newer label kept")

        export = self.root / f"{kind}-rollback"
        failures = json.loads((checkout / "artifacts" / "reviews" / "state.json").read_text()).get("failures", 0)
        self.tool(checkout, "export", "--to", export, "--compatible")
        rollback = self.root / f"{kind}-baseline-checkout"
        rollback.mkdir()
        (rollback / "artifacts").symlink_to(export, target_is_directory=True)
        old = json.loads(self.run(rollback, "-c", BASELINE_READ, BASELINE).stdout)
        self.check(old["error"] is None and old["well_formed"] and old["note_ids"] == waiting["note_ids"],
                   f"{kind}: the baseline reads every note, the one added after activation included")
        # Today's code reviews again what only a legacy digest lists (it reads committed v2 reviews alone); the
        # baseline does not. The export's own digest must mark nothing today's code still waits for.
        made = json.loads((export / "export-manifest.json").read_text())["compatible"]["digest"]
        legacy = set().union(*(json.loads(path.read_text())["queue"]["runs"]
                               for path in (export / "reviews").glob("*.json")
                               if re.fullmatch(r"\d{8}-\d{6}", path.stem) and f"reviews/{path.name}" != made))
        marked = set(json.loads((export / made).read_text())["queue"]["runs"])
        self.check(old["runs"] == sorted(set(waiting["runs"]) - legacy) and old["notes"] == waiting["notes"]
                   and not marked & set(waiting["runs"]),
                   f"{kind}: the baseline waits for what today's code waits for, less what its own digests reviewed")
        self.check(old["state"]["running"] is None and old["state"]["failures"] == failures,
                   f"{kind}: the baseline's review state, its failure count kept")
        self.check(len(list((checkout / "artifacts" / "reviews" / "attempts").glob("*.json"))) == attempts,
                   f"{kind}: no review attempt after the store was built")

    def finish(self):
        calls = self.bin / "claude-calls.log"
        self.check(not calls.exists(), "no paid launch: the fake claude was never run")
        record = {"root": str(self.root), "passed": not self.failures, "failures": self.failures,
                  "evidence": self.evidence}
        (self.root / "rehearsal.json").write_text(json.dumps(record, indent=2) + "\n")
        return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, help="a new folder for the disposable stores (default: a temporary one)")
    args = parser.parse_args(argv)
    root = args.root or Path(tempfile.mkdtemp(prefix="jev-rehearsal-"))
    if args.root:
        args.root.mkdir(parents=True)  # never an existing folder
    rehearsal = Rehearsal(root)
    try:
        for kind in ("baseline", "mixed"):
            rehearsal.rehearse(kind)
    except Exception as error:  # a crash is a failed rehearsal, with its evidence kept
        rehearsal.check(False, f"rehearsal stopped: {type(error).__name__}: {error}")
    record = rehearsal.finish()
    for item in record["evidence"]:
        if "check" in item:
            print(("PASS " if item["passed"] else "FAIL ") + item["check"])
    print(f"{'PASS' if record['passed'] else 'FAIL'}: rehearsal evidence in {root / 'rehearsal.json'}")
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
