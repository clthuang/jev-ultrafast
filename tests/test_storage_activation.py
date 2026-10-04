"""RELEASE-3: the review store's inventory, verified backup, migration and rollback exports, on disposable stores.

The rollback export is read by the baseline code itself (3efae4f's site_notes.py and review_runs.py, frozen byte for
byte in tests/fixtures/baseline/), never by a reimplementation of it. No process is launched or signalled, and no model
is called: a held lock is held by this test, and a running writer is a fake process list."""

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from test_review_batches import RUN_A, RUN_B, RUN_C, add_decision, apply_batch, recovery, write_run

import jev_ultrafast
from jev_ultrafast import review_records, run_store, site_notes
from scripts import migrate_review_storage as storage
from scripts import review_runs

BASELINE = Path(__file__).resolve().parent / "fixtures" / "baseline"
BASELINE_HASHES = {  # git show 3efae4f:<file> | sha256sum
    "site_notes.py": "cb6f7ec239fe72a06f2cf393cd6ce5ecb4614925c80ccc529cdf34179e9a8206",
    "review_runs.py": "ee6fb165b85cd8a1cd654df41f0f32a12b7fa24afd290a9560fd3e7fe2ec6cf9",
}
ARTIFACTS = Path("artifacts")


def store_bytes(root=ARTIFACTS):
    """Every file under the store, locks included, with its bytes: what "nothing changed" compares."""
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(Path(root).rglob("*")) if path.is_file()}


def legacy_store():
    """A store the baseline wrote: list notes with an approved and a retired note, a legacy digest, its state file."""
    approved = {**deepcopy(site_notes.SEEDS[0]), "id": "kept.example-1", "site": "kept.example",
                "approved": "2026-09-28", "shown": 4, "last_shown": "2026-09-30", "failed_after": 1}
    retired = {**deepcopy(site_notes.SEEDS[0]), "id": "old.example-1", "site": "old.example", "approved": None,
               "retired": "2026-09-28"}
    site_notes.NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    site_notes.NOTES_PATH.write_text(json.dumps([*site_notes.SEEDS, approved, retired]))
    review_runs.REVIEWS.mkdir(parents=True, exist_ok=True)
    (review_runs.REVIEWS / "20260927-100000.json").write_text(json.dumps(
        {"queue": {"runs": [RUN_C], "notes": {}}, "decisions": [], "flags": [], "proposals": [],
         "summary": "Old review.", "cost": 0.07}))
    site_notes.write_review_state({"last_start": "2026-09-28T09:00:00", "next_due": 0, "running": None,
                                   "failures": 1, "off": False})
    write_run(RUN_C)
    (review_runs.RUNS / f"{RUN_C}.jpg").write_bytes(b"\xff\xd8 screenshot")


@contextlib.contextmanager
def held(relative):
    path = ARTIFACTS / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def test_inventory_reads_a_store_without_writing():
    legacy_store()
    before = store_bytes()
    report = storage.inventory()
    assert store_bytes() == before  # not even a lock file
    approved = sum(note["approved"] is not None for note in site_notes.SEEDS) + 1
    assert report["notes"] == {"format": "legacy list", "notes": len(site_notes.SEEDS) + 2, "approved": approved,
                               "retired": 1, "pending_receipt": None}
    assert report["runs"] == {"files": 1, "screenshots": 1} and report["reviews"]["legacy_digests"] == 1
    assert report["blocking"] == [] and report["damaged"] == [] and set(report["locks"].values()) == {False}


@pytest.mark.parametrize("lock", [name for name, _relative in storage.LOCKS])
def test_a_held_lock_refuses_every_change_and_changes_nothing(tmp_path, lock):
    legacy_store()
    folder = storage.backup(tmp_path / "backup")
    assert folder["files"]
    relative = dict(storage.LOCKS)[lock]
    with held(relative):
        before = store_bytes()
        assert storage.inventory()["locks"][lock] is True
        for change in (lambda: storage.backup(tmp_path / "again"), lambda: storage.migrate(tmp_path / "backup"),
                       lambda: storage.export(tmp_path / "out"), lambda: storage.export(tmp_path / "old",
                                                                                        compatible=True)):
            with pytest.raises(storage.Refused, match=f"the {lock} lock is held"):
                change()
        assert store_bytes() == before
        assert not any((tmp_path / name).exists() for name in ("again", "out", "old"))


def test_a_running_writer_or_an_unsettled_review_refuses(tmp_path, monkeypatch):
    legacy_store()
    monkeypatch.setattr(storage, "writer_candidates", lambda: [
        (4242, ["/opt/venv/bin/python", "-m", "jev_ultrafast.mcp_server"], str(tmp_path)),
        (4343, ["/opt/venv/bin/jev-mcp"], "/elsewhere/checkout")])  # another checkout's server writes its own store
    report = storage.inventory()
    assert [item["pid"] for item in report["writers"]] == [4242]
    with pytest.raises(storage.Refused, match="process 4242 writes this store"):
        storage.backup(tmp_path / "backup")
    monkeypatch.setattr(storage, "writer_candidates", lambda: [])
    state = site_notes.read_review_state()
    site_notes.write_review_state({**state, "running": "2026-10-04T09:00:00"})
    with pytest.raises(storage.Refused, match="a review may be in flight"):
        storage.backup(tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


def test_writers_are_recognised_by_what_runs_them():
    writers = [["/x/.venv/bin/python", "-m", "jev_ultrafast.mcp_server"],
               ["uv", "run", "--directory", "/x", "jev-mcp"], ["/x/.venv/bin/jev-mcp"],
               ["/x/.venv/bin/jev", "--port", "8000"], ["python3.13", "scripts/review_runs.py", "auto"],
               ["uv", "run", "python", "/x/scripts/record_flights.py", "out"], ["python", "examples/flights.py"]]
    others = [["grep", "jev-mcp"], ["vim", "scripts/review_runs.py"], ["python", "-m", "pytest"], [],
              ["python", "scripts/report_runs.py"], ["bash", "-c", "uv run jev-mcp"]]
    assert all(storage.is_writer(argv) for argv in writers)
    assert not any(storage.is_writer(argv) for argv in others)


def test_a_missing_store_is_refused_and_never_created(tmp_path):
    assert storage.inventory()["present"] is False
    for change in (lambda: storage.backup(tmp_path / "backup"), lambda: storage.export(tmp_path / "out")):
        with pytest.raises(storage.Refused, match="no review store here"):
            change()
    assert not ARTIFACTS.exists() and not (tmp_path / "backup").exists()


def test_a_backup_copies_every_file_and_reads_it_back(tmp_path):
    legacy_store()
    (review_runs.REVIEWS / "auto.log").write_text("an earlier automatic review\n")
    (review_runs.RUNS / ".run.json.123.tmp").write_text("{")  # a crashed write's leftover: not state
    site_notes.NOTES_PATH.write_text("{ not json")  # damaged: a backup keeps it as evidence
    report = storage.inventory()
    assert report["damaged"] and report["temporaries"] == ["runs/.run.json.123.tmp"]
    record = storage.backup(tmp_path / "backup")
    live = {str(path.relative_to(ARTIFACTS)): path for path in storage.store_files()}
    assert set(record["files"]) == set(live) and "runs/.run.json.123.tmp" not in record["files"]
    assert {"site-notes.json", "reviews/auto.log", f"runs/{RUN_C}.jpg", "reviews/state.json"} <= set(live)
    for relative, path in live.items():
        copy = tmp_path / "backup" / relative
        assert copy.read_bytes() == path.read_bytes()
        assert hashlib.sha256(copy.read_bytes()).hexdigest() == record["files"][relative]
    assert storage.read_backup(tmp_path / "backup") == record
    with pytest.raises(storage.Refused, match="exists"):
        storage.backup(tmp_path / "backup")
    with pytest.raises(storage.Refused, match="outside the store"):
        storage.backup(ARTIFACTS / "inside")
    (tmp_path / "backup" / f"runs/{RUN_C}.json").write_text("{}")  # a backup changed after it was taken
    with pytest.raises(storage.Refused, match="does not match its manifest"):
        storage.read_backup(tmp_path / "backup")


def test_a_migration_needs_a_backup_of_exactly_this_state(tmp_path):
    legacy_store()
    storage.backup(tmp_path / "backup")
    run_store.append_outcome(review_runs.RUNS / f"{RUN_C}.json",
                             {"passed": True, "by": "user", "evidence": "Later label", "at": "2026-10-04T10:00:00"})
    before = store_bytes()
    with pytest.raises(storage.Refused, match="not of this store's current state"):
        storage.migrate(tmp_path / "backup")
    assert store_bytes() == before and isinstance(json.loads(site_notes.NOTES_PATH.read_text()), list)


def test_a_migration_keeps_every_note_and_never_touches_runs(tmp_path):
    legacy_store()
    def run_files():  # a lock file is no run
        return {path.name: path.read_bytes() for path in review_runs.RUNS.iterdir() if path.name != ".metadata.lock"}

    notes, runs = json.loads(site_notes.NOTES_PATH.read_text()), run_files()
    storage.backup(tmp_path / "backup")
    assert storage.migrate(tmp_path / "backup") == {"notes_before": "legacy list", "notes_after": "envelope 2",
                                                    "receipt_recovered": None}
    envelope = site_notes.read_envelope(site_notes.NOTES_PATH)
    assert envelope["notes"] == notes and envelope["pending_review"] is None  # approvals, retirement, counters kept
    assert run_files() == runs
    assert (review_runs.REVIEWS / "20260927-100000.json").exists()  # history kept as it was


def test_a_migration_recovers_a_pending_receipt_without_applying_it_again(tmp_path, monkeypatch):
    legacy_store()
    storage.migrate_storage(ARTIFACTS)
    recovery()
    batch = review_runs.prepare_batch()
    ensure = review_runs.ensure_digest
    monkeypatch.setattr(review_runs, "ensure_digest", lambda receipt: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        apply_batch(batch, {"decisions": [add_decision()], "flags": [], "proposals": [], "summary": "Reviewed"})
    monkeypatch.setattr(review_runs, "ensure_digest", ensure)
    assert storage.inventory()["notes"]["pending_receipt"] == batch["batch_id"]
    notes = site_notes.read_envelope(site_notes.NOTES_PATH)["notes"]  # the decision is already in the notes
    with pytest.raises(storage.Refused, match="a review receipt is pending"):
        storage.export(tmp_path / "old", compatible=True)
    storage.backup(tmp_path / "backup")
    assert storage.migrate(tmp_path / "backup")["receipt_recovered"] == batch["batch_id"]
    envelope = site_notes.read_envelope(site_notes.NOTES_PATH)
    assert envelope["pending_review"] is None and envelope["notes"] == notes  # nothing applied twice
    [(path, digest)] = review_records.committed(review_runs.REVIEWS)
    assert digest["batch_id"] == batch["batch_id"] and RUN_B in digest["acknowledged"]["runs"]


def test_an_unreadable_store_is_never_migrated(tmp_path):
    legacy_store()
    site_notes.NOTES_PATH.write_text("[ not json")
    storage.backup(tmp_path / "backup")
    before = store_bytes()
    with pytest.raises(storage.Refused, match="site-notes.json is unreadable"):
        storage.migrate(tmp_path / "backup")
    with pytest.raises(storage.Refused, match="site-notes.json is unreadable"):
        storage.export(tmp_path / "old", compatible=True)
    assert store_bytes() == before


def load_baseline(monkeypatch):
    """The baseline's own notes store and reviewer, imported fresh from their frozen copies, in place of today's."""
    for name, expected in BASELINE_HASHES.items():
        assert hashlib.sha256((BASELINE / name).read_bytes()).hexdigest() == expected, name
    modules = {}
    for module, name in (("jev_ultrafast.site_notes", "site_notes.py"), ("baseline_review_runs", "review_runs.py")):
        spec = importlib.util.spec_from_file_location(module, BASELINE / name)
        loaded = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module, loaded)
        if module == "jev_ultrafast.site_notes":
            monkeypatch.setattr(jev_ultrafast, "site_notes", loaded)  # what the baseline reviewer imports
        spec.loader.exec_module(loaded)
        modules[name.removesuffix(".py")] = loaded
    return modules


def test_a_compatible_export_is_what_the_baseline_code_reads(tmp_path, monkeypatch):
    """After activation and new work, the rollback export loses no note, label or receipt, and the baseline reviewer
    neither reviews again what committed reviews acknowledged at its current version nor skips what changed since."""
    legacy_store()
    storage.backup(tmp_path / "backup")
    storage.migrate(tmp_path / "backup")
    recovery()  # RUN_A failed, RUN_B recovered: both wait for a review
    write_run("20261003-100300-0004")  # a failed run, reviewed and then relabelled
    first = review_runs.prepare_batch()
    apply_batch(first, {"decisions": [add_decision()], "flags": [], "proposals": [], "summary": "Reviewed"})
    run_store.append_outcome(review_runs.RUNS / "20261003-100300-0004.json",
                             {"passed": True, "by": "user", "evidence": "It worked", "at": "2026-10-04T10:00:00"})
    new_note = {"site": "new.example", "hint": "scroll_first", "detail": "Added after the review", "url": None,
                "failure": None, "runs": {"failed": [], "recovered": None}}
    site_notes.add_note(new_note)
    current = site_notes.read_envelope(site_notes.NOTES_PATH)["notes"]
    waiting = review_runs.build_queue()  # what today's code would review next, at today's versions
    assert RUN_C in first["runs"] and "20261003-100300-0004" in waiting["runs"]
    record = storage.export(tmp_path / "rollback", compatible=True)
    exported = tmp_path / "rollback"
    for relative, expected in record["files"].items():
        assert hashlib.sha256((exported / relative).read_bytes()).hexdigest() == expected
    assert record["compatible"]["acknowledged_runs"] >= 2

    # The baseline, run in a checkout whose artifacts/ is the export.
    rollback = tmp_path / "checkout"
    rollback.mkdir()
    (rollback / "artifacts").symlink_to(exported, target_is_directory=True)
    monkeypatch.chdir(rollback)
    with monkeypatch.context() as patched:
        old = load_baseline(patched)
        notes, error = old["site_notes"].load(create=False)
        assert error is None and notes == current  # every note, the post-migration one included, as a list
        assert all(old["site_notes"].well_formed(note) for note in notes)
        reviewed_runs, reviewed_notes = old["review_runs"].reviewed()
        assert {RUN_A, RUN_B, RUN_C} <= reviewed_runs  # acknowledged now, or by the legacy digest
        assert "20261003-100300-0004" not in reviewed_runs  # relabelled after its review: it waits again
        # The baseline waits for exactly what today's code waits for: no acknowledged item again, none skipped.
        queue = old["review_runs"].build_queue()
        assert set(queue["runs"]) == set(waiting["runs"]) and set(queue["notes"]) == set(waiting["notes"])
        new_id = next(note["id"] for note in notes if note["site"] == "new.example")
        assert new_id in queue["notes"] and queue["note_reasons"][new_id] == "new"
        assert not set(queue["notes"]) & set(first["notes"])  # the notes the review acknowledged
        state = old["site_notes"].read_review_state()
        # The baseline's keys only, the carried failure count kept (a manual apply never clears it).
        assert state == {"last_start": "2026-09-28T09:00:00", "next_due": 0, "running": None, "failures": 1,
                         "off": False}
    # Today's code still reads the export too: the committed reviews and their acknowledgments are all there.
    assert review_records.committed(exported / "reviews")[0][1]["batch_id"] == first["batch_id"]
    assert (exported / "reviews" / "20260927-100000.json").read_bytes() == (
        tmp_path / "backup" / "reviews" / "20260927-100000.json").read_bytes()


def test_the_cli_reports_and_refuses_without_changing_anything(tmp_path, capsys):
    legacy_store()
    assert storage.main(["inventory"]) == 0
    assert json.loads(capsys.readouterr().out)["notes"]["format"] == "legacy list"
    with held("reviews/.lock"):
        before = store_bytes()
        assert storage.main(["backup", "--to", str(tmp_path / "backup")]) == 2
        assert "refused, nothing changed: the review lock is held" in capsys.readouterr().err
        assert storage.main(["inventory"]) == 1
        assert store_bytes() == before
    assert storage.main(["backup", "--to", str(tmp_path / "backup")]) == 0
    capsys.readouterr()
    assert storage.main(["migrate", "--backup", str(tmp_path / "backup")]) == 0
    assert json.loads(capsys.readouterr().out)["notes_after"] == "envelope 2"
    assert site_notes.read_envelope(site_notes.NOTES_PATH)["schema_version"] == 2
