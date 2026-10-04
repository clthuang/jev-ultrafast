"""Review storage activation, offline: an inventory, a verified backup, the migration, and exports a rollback can use.

Run from the checkout whose artifacts/ it serves, after every writer of that store was stopped through the application
that owns it (docs/robustness-efficiency/activation-runbook.md). Nothing here signals a process, launches a review or
calls a model. A changing command takes the store's locks in the pipeline's order (dispatch, review, metadata, notes)
without waiting: a held lock, a running writer or an unsettled attempt refuses it, and then nothing changed.

    uv run python scripts/migrate_review_storage.py inventory
    uv run python scripts/migrate_review_storage.py backup --to <a new folder outside artifacts/>
    uv run python scripts/migrate_review_storage.py migrate --backup <that folder>
    uv run python scripts/migrate_review_storage.py export --to <a new folder> [--compatible]
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # run as a script, scripts/ is on the path and the checkout may not be
from jev_ultrafast import review_records, site_notes, store_io  # noqa: E402
from scripts import review_runs  # noqa: E402

ARTIFACTS = Path("artifacts")  # relative to the working directory, as every writer of the store resolves it
# The pipeline's lock order: dispatch, review, metadata, notes (docs/robustness-efficiency/review-storage-notes.md).
LOCKS = (("dispatch", "reviews/.dispatch.lock"), ("review", "reviews/.lock"), ("metadata", "runs/.metadata.lock"),
         ("notes", "site-notes.lock"))
NOT_STATE = {Path(relative).name for _name, relative in LOCKS}
LIVE_ATTEMPTS = {"claimed", "spawning", "running", "returned"}
# A process that writes this store: the server, the inspector, their console scripts, the review CLI and the recorders,
# started by a Python interpreter, uv or the console script itself (an editor or grep naming them is not one).
WRITER_MODULES = {"jev_ultrafast.mcp_server", "jev_ultrafast.demo"}
WRITER_PROGRAMS = {"jev", "jev-mcp"}
WRITER_SCRIPTS = re.compile(
    r"(?:^|/)(?:scripts/(?:review_runs|record_flights|measure_flights|smoke)|examples/\w+)\.py$")
LAUNCHERS = re.compile(r"python[\d.]*|uv|uvx")


class Refused(Exception):
    """A precondition failed before anything changed."""


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def store_files(artifacts=ARTIFACTS):
    """Every file the store keeps, in order: run files and screenshots, review records, state and logs, the notes
    and the exclusions. Locks and in-flight temporaries are not state. A link refuses: a copy would follow it out."""
    artifacts, files = Path(artifacts), []
    candidates = [path for name in ("runs", "reviews") if (artifacts / name).is_dir()
                  for path in sorted((artifacts / name).rglob("*"))]
    candidates += [artifacts / name for name in ("site-notes.json", "review-exclude.txt")]
    for path in candidates:
        if path.is_symlink():
            raise Refused(f"{path} is a symbolic link; the store must hold regular files only")
        if path.is_file() and path.name not in NOT_STATE and not path.name.endswith(".tmp"):
            files.append(path)
    return files


def temporaries(artifacts=ARTIFACTS):
    """Temporaries a crashed write left: never state, but evidence an inventory reports."""
    artifacts = Path(artifacts)
    found = [*artifacts.glob("*.tmp"),
             *(path for name in ("runs", "reviews") for path in (artifacts / name).rglob("*.tmp"))]
    return sorted(str(path.relative_to(artifacts)) for path in found)


@contextlib.contextmanager
def hold(path, name):
    """One store lock, taken without waiting; a held one refuses."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused(f"the {name} lock is held: a writer of this store is running") from None
        yield


def lock_held(path):
    """True while another holder has this lock. Probing never creates a lock file."""
    if not Path(path).exists():
        return False
    with Path(path).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


@contextlib.contextmanager
def writers_stopped(artifacts=ARTIFACTS, *, notes=True):
    """Hold the store's locks in the pipeline's order without waiting; a held one refuses, holding nothing. With
    notes=False the notes lock is only probed, for a caller whose notes transaction then takes it."""
    artifacts = Path(artifacts)
    with contextlib.ExitStack() as held:
        for name, relative in LOCKS:
            if name == "notes" and not notes:
                if lock_held(artifacts / relative):
                    raise Refused("the notes lock is held: a writer of this store is running")
                continue
            held.enter_context(hold(artifacts / relative, name))
        yield


def is_writer(argv):
    """True for a writer's command line: its program is the console script, or a Python interpreter or uv running a
    writer module, console script or script."""
    if not argv:
        return False
    if Path(argv[0]).name in WRITER_PROGRAMS:
        return True
    return bool(LAUNCHERS.fullmatch(Path(argv[0]).name)) and any(
        argument in WRITER_MODULES or Path(argument).name in WRITER_PROGRAMS or WRITER_SCRIPTS.search(argument)
        for argument in argv[1:])


def writer_candidates():
    """[(pid, argv, cwd)] for this account's processes whose command line is a writer's; cwd is None where it cannot
    be read. Linux reads /proc; elsewhere ps lists the commands and lsof reads each candidate's working directory."""
    found = []
    if Path("/proc").is_dir():
        for entry in Path("/proc").iterdir():
            try:
                if not entry.name.isdigit() or entry.stat().st_uid != os.getuid():
                    continue
                argv = [os.fsdecode(part) for part in (entry / "cmdline").read_bytes().split(b"\0") if part]
            except OSError:
                continue
            if is_writer(argv):
                try:
                    cwd = os.readlink(entry / "cwd")
                except OSError:
                    cwd = None
                found.append((int(entry.name), argv, cwd))
        return found
    listing = subprocess.run(["ps", "-ww", "-U", str(os.getuid()), "-o", "pid=,command="], capture_output=True,
                             text=True, timeout=5, check=False).stdout
    lsof = shutil.which("lsof", path="/usr/sbin:/usr/bin:/sbin:/bin") or "lsof"
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        if not pid.isdigit() or not is_writer(command.split()):
            continue
        cwd = subprocess.run([lsof, "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=5,
                             check=False).stdout
        paths = [item[1:] for item in cwd.splitlines() if item.startswith("n")]
        found.append((int(pid), command.split(), paths[0] if paths else None))
    return found


def writer_processes(artifacts=ARTIFACTS):
    """This store's running writers: a writer's process whose working directory holds this artifacts/. Only reported,
    never signalled; an unreadable working directory counts as this store's, since it cannot be shown another's."""
    home = Path(artifacts).resolve().parent
    return [{"pid": pid, "command": " ".join(argv)[:200], "cwd": cwd} for pid, argv, cwd in writer_candidates()
            if pid != os.getpid() and (cwd is None or Path(cwd).resolve() == home)]


def notes_inventory(path):
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {"format": "missing"}
    except (OSError, ValueError) as error:
        return {"format": f"unreadable ({type(error).__name__})"}
    try:
        envelope = site_notes.read_envelope(path)
    except site_notes.NotesStoreError as error:
        return {"format": f"unreadable ({error})"}
    notes, receipt = envelope["notes"], envelope["pending_review"]
    return {"format": "legacy list" if isinstance(raw, list) else "envelope 2", "notes": len(notes),
            "approved": sum(note["approved"] is not None for note in notes),
            "retired": sum(note["retired"] is not None for note in notes),
            "pending_receipt": receipt["batch_id"] if receipt else None}


def reviews_inventory(reviews):
    reviews, report = Path(reviews), {"legacy_digests": 0, "committed_digests": 0, "batches": 0, "attempts": {},
                                      "unreadable": []}
    if not reviews.is_dir():
        return report
    for path in sorted(reviews.glob("*.json")):
        if review_records.LEGACY_DIGEST.fullmatch(path.stem):
            report["legacy_digests"] += 1
        elif review_records.ID.fullmatch(path.stem):
            report["committed_digests"] += 1
    report["batches"] = len(list((reviews / "batches").glob("*.json")))
    for path in sorted((reviews / "attempts").glob("*.json")):
        try:
            status = review_records.read(path, "attempt")["status"]
        except (OSError, ValueError, review_records.RecordError):
            report["unreadable"].append(str(path.relative_to(reviews)))
            continue
        report["attempts"][status] = report["attempts"].get(status, 0) + 1
    try:
        state = json.loads((reviews / "state.json").read_text())
        report["state"] = {key: state.get(key) for key in ("running", "failures", "off")} if isinstance(
            state, dict) else "unreadable"
    except FileNotFoundError:
        report["state"] = None
    except (OSError, ValueError):
        report["state"] = "unreadable"
    return report


def inventory(artifacts=ARTIFACTS):
    """What the store holds and what would stop a change, read without writing or waiting."""
    artifacts = Path(artifacts)
    report = {"artifacts": str(artifacts.resolve()), "present": artifacts.is_dir() and bool(
        (artifacts / "runs").is_dir() or (artifacts / "site-notes.json").exists() or (artifacts / "reviews").is_dir())}
    if not report["present"]:
        report["blocking"] = ["no review store here: run from the checkout whose artifacts/ holds it"]
        return report
    runs = artifacts / "runs"
    report.update(
        runs={"files": len(list(runs.glob("*.json"))), "screenshots": len(list(runs.glob("*.jpg")))},
        notes=notes_inventory(artifacts / "site-notes.json"), reviews=reviews_inventory(artifacts / "reviews"),
        locks={name: lock_held(artifacts / relative) for name, relative in LOCKS},
        temporaries=temporaries(artifacts), writers=writer_processes(artifacts))
    # Blocking: a writer may still change the store, so nothing may copy or change it. Damaged: a record no reader
    # accepts, which a backup keeps as evidence and which stops a migration or a compatible export.
    blocking = [f"the {name} lock is held" for name, held in report["locks"].items() if held]
    blocking += [f"process {item['pid']} writes this store: {item['command']}" for item in report["writers"]]
    live = {status: count for status, count in report["reviews"]["attempts"].items() if status in LIVE_ATTEMPTS}
    if live:
        blocking.append(f"unsettled review attempts {live}: settle them with {review_runs.RESOLVE_COMMAND}")
    state = report["reviews"].get("state")
    if isinstance(state, dict) and state.get("running"):
        blocking.append(f"the review state is running {state['running']}: a review may be in flight")
    damaged = [f"reviews/{name} cannot be read" for name in report["reviews"]["unreadable"]]
    if state == "unreadable":
        damaged.append("reviews/state.json cannot be read")
    if report["notes"]["format"].startswith("unreadable"):
        damaged.append(f"site-notes.json is {report['notes']['format']}")
    report["blocking"], report["damaged"] = blocking, damaged
    return report


def require_quiet(artifacts, *, intact=True):
    """The inventory, or Refused naming what blocks: a writer always; a damaged record unless only copying."""
    report = inventory(artifacts)
    problems = report["blocking"] + (report.get("damaged", []) if intact else [])
    if problems:
        raise Refused("; ".join(problems))
    return report


def outside(artifacts, destination):
    artifacts, destination = Path(artifacts).resolve(), Path(destination).resolve()
    if destination == artifacts or artifacts in destination.parents or destination in artifacts.parents:
        raise Refused("the destination must be outside the store")
    if destination.exists():
        raise Refused(f"{destination} exists; give a new folder, so no earlier copy is ever mixed in")
    return destination


def copy_store(artifacts, destination, manifest_name, extra=None):
    """Copy every store file, then read each copy back against the live file, both still under the caller's locks."""
    files = store_files(artifacts)
    destination.mkdir(parents=True)
    hashes = {}
    for source in files:
        relative = source.relative_to(artifacts)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[str(relative)] = sha256(source)
    for relative, expected in hashes.items():
        if sha256(destination / relative) != expected or sha256(Path(artifacts) / relative) != expected:
            raise Refused(f"{relative} did not read back as copied; the copy is not usable")
    record = {"schema_version": 1, "created_at": datetime.now().isoformat(timespec="seconds"),
              "source": str(Path(artifacts).resolve()), "files": hashes, **(extra or {})}
    (destination / manifest_name).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def backup(destination, artifacts=ARTIFACTS):
    """A complete copy of the quiescent store with a SHA-256 manifest, every copy read back under the locks. An
    unreadable notes file is copied as it is: the backup keeps the evidence."""
    artifacts = Path(artifacts)
    require_quiet(artifacts, intact=False)
    destination = outside(artifacts, destination)
    with writers_stopped(artifacts):
        return copy_store(artifacts, destination, "backup-manifest.json")


def read_backup(folder):
    folder = Path(folder)
    try:
        record = json.loads((folder / "backup-manifest.json").read_text())
    except (OSError, ValueError) as error:
        raise Refused(f"{folder} holds no readable backup manifest ({type(error).__name__})") from None
    if not isinstance(record, dict) or record.get("schema_version") != 1 or not isinstance(record.get("files"), dict):
        raise Refused(f"{folder} holds no backup this tool wrote")
    for relative, expected in record["files"].items():
        if not (folder / relative).is_file() or sha256(folder / relative) != expected:
            raise Refused(f"the backup's {relative} does not match its manifest")
    return record


def migrate_storage(artifacts):
    """The notes primitive: a legacy list becomes the schema-2 envelope, every note field kept; unknown versions fail
    closed. Callers that are not tests use migrate(), which checks the backup and the writers first."""
    site_notes.update(lambda notes: None, Path(artifacts) / "site-notes.json")


def recover_receipt(envelope, reviews):
    """Inside the notes transaction: publish a pending receipt's exact digest, then clear it. Its decisions are already
    in the notes; nothing is applied again."""
    receipt = envelope["pending_review"]
    if receipt is None:
        return None
    path = Path(reviews) / f"{receipt['batch_id']}.json"
    if path.exists():
        if review_records.read(path, "digest") != receipt["digest"]:
            raise Refused("a committed digest conflicts with the pending receipt; both are kept")
    else:
        store_io.publish(path, receipt["digest"], immutable=True)
    envelope["pending_review"] = None
    return receipt["batch_id"]


def migrate(backup_folder, artifacts=ARTIFACTS):
    """Migrate the quiescent store in place: the notes become the schema-2 envelope, and a pending receipt is
    recovered into its exact digest. Only after a backup of exactly this state, which the migration then checks
    against: every note is kept as it was, and no run file changes."""
    artifacts = Path(artifacts)
    record = read_backup(backup_folder)
    require_quiet(artifacts)
    notes_path = artifacts / "site-notes.json"
    before = notes_inventory(notes_path)

    def same_as_backup():
        live = {str(path.relative_to(artifacts)): sha256(path) for path in store_files(artifacts)}
        differ = sorted(key for key in set(live) | set(record["files"]) if live.get(key) != record["files"].get(key))
        if differ:
            raise Refused(f"the backup is not of this store's current state ({len(differ)} files differ, such as "
                          f"{differ[0]}); take a new backup")

    with writers_stopped(artifacts, notes=False):
        if before["format"] == "missing":  # no notes to migrate and no receipt: only the backup is checked
            with hold(artifacts / "site-notes.lock", "notes"):
                same_as_backup()
            recovered = None
        else:  # one notes transaction: the check, the receipt's digest and the envelope, or nothing at all
            recovered = site_notes.transaction(lambda envelope: (same_as_backup(), recover_receipt(
                envelope, artifacts / "reviews"))[1], notes_path)
    after = site_notes.read_envelope(notes_path)
    kept = read_notes_as_list(Path(backup_folder) / "site-notes.json")
    if after is not None and kept is not None and after["notes"] != kept:
        raise Refused("the migrated notes differ from the backup's; restore the backup and stop")
    for relative, expected in record["files"].items():
        if relative.startswith("runs/") and sha256(artifacts / relative) != expected:
            raise Refused(f"{relative} changed during the migration; restore the backup and stop")
    return {"notes_before": before["format"], "notes_after": notes_inventory(notes_path)["format"],
            "receipt_recovered": recovered}


def read_notes_as_list(path):
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None
    return raw if isinstance(raw, list) else raw["notes"]


def baseline_note_hash(note):
    """The baseline reviewer's own hash of a note (3efae4f scripts/review_runs.py note_hash), not today's canonical
    one: what its reviewed() compares a note against."""
    content = {key: value for key, value in note.items() if key not in ("shown", "last_shown")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def compatible_view(artifacts):
    """What a baseline reader needs, under the caller's locks: the notes as a list, the review state's baseline keys,
    and one legacy digest listing what the store's committed reviews acknowledged at the version it holds now."""
    if Path(artifacts).resolve() != ARTIFACTS.resolve():
        raise Refused("run the compatible export from the checkout whose artifacts/ it exports")
    reviews = Path(artifacts) / "reviews"
    envelope = site_notes.read_envelope(Path(artifacts) / "site-notes.json")
    notes = envelope["notes"] if envelope else []
    try:
        acknowledged = review_records.acknowledged(reviews)
    except review_records.RecordError as error:
        raise Refused(f"a committed review cannot be read: {error}") from None
    queue = review_runs.build_queue(notes=notes)  # what is still waiting, at today's versions
    runs = sorted(set(acknowledged["runs"]) - set(queue["runs"]))
    reviewed_notes = {note["id"]: baseline_note_hash(note) for note in notes
                      if review_records.note_hash(note) in acknowledged["notes"].get(note["id"], set())}
    state = site_notes.read_review_state(reviews / "state.json")
    baseline_state = {"last_start": state.get("last_start"), "next_due": state.get("next_due", 0), "running": None,
                      "failures": state.get("failures", 0), "off": state.get("off", False)}
    digest = {"queue": {"runs": runs, "notes": reviewed_notes}, "sent": "", "decisions": [], "flags": [],
              "proposals": [], "summary": "Compatibility export: what committed reviews acknowledged; no review ran.",
              "cost": 0}
    return notes, baseline_state, digest


def export(destination, artifacts=ARTIFACTS, *, compatible=False):
    """Copy the quiescent store with a manifest. compatible: a folder the baseline code (3efae4f) reads in place of
    artifacts/: the notes as a list, the review state's baseline keys, and a legacy digest of the acknowledgments, so a
    rollback neither drops a note nor reviews again what committed reviews acknowledged. Every current record is kept
    beside them, for a later reactivation."""
    artifacts = Path(artifacts)
    report = require_quiet(artifacts, intact=compatible)
    destination = outside(artifacts, destination)
    if compatible and report["notes"].get("pending_receipt"):
        raise Refused(f"a review receipt is pending; recover it first ({review_runs.RECOVER_COMMAND})")
    with writers_stopped(artifacts):
        if not compatible:
            return copy_store(artifacts, destination, "export-manifest.json")
        notes, state, digest = compatible_view(artifacts)
        record = copy_store(artifacts, destination, "export-manifest.json")
        moment = datetime.now().replace(microsecond=0)
        while (destination / "reviews" / f"{moment:%Y%m%d-%H%M%S}.json").exists():
            moment += timedelta(seconds=1)  # never on an existing legacy digest's name
        name = f"{moment:%Y%m%d-%H%M%S}"
        written = {"site-notes.json": notes, "reviews/state.json": state, f"reviews/{name}.json": digest}
        for relative, value in written.items():
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2) + "\n")
            record["files"][relative] = sha256(path)
        record["compatible"] = {"baseline": "3efae4f", "digest": f"reviews/{name}.json",
                                "acknowledged_runs": len(digest["queue"]["runs"]),
                                "acknowledged_notes": len(digest["queue"]["notes"])}
        (destination / "export-manifest.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        return record


def export_storage(artifacts, destination):
    """The current-format export (export() with compatible=False), kept for callers of the earlier name."""
    return export(destination, artifacts)["files"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory", help="what the store holds and what would refuse a change; writes nothing")
    copy = commands.add_parser("backup", help="a verified copy of the quiescent store")
    copy.add_argument("--to", required=True, type=Path)
    change = commands.add_parser("migrate", help="migrate in place, after a backup of exactly this state")
    change.add_argument("--backup", required=True, type=Path)
    out = commands.add_parser("export", help="a copy for a rollback; --compatible: one the baseline code reads")
    out.add_argument("--to", required=True, type=Path)
    out.add_argument("--compatible", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            result = inventory()
        elif args.command == "backup":
            result = {"backup": str(args.to), "files": len(backup(args.to)["files"])}
        elif args.command == "migrate":
            result = migrate(args.backup)
        else:
            record = export(args.to, compatible=args.compatible)
            result = {"export": str(args.to), "files": len(record["files"]), **record.get("compatible", {})}
    except Refused as error:
        print(f"refused, nothing changed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if args.command == "inventory" and (result["blocking"] or result.get("damaged")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
