"""Serialize execution saves and labels without losing either writer's fields."""

import contextlib
import fcntl
import json
from pathlib import Path

from .store_io import publish


class InvalidRun(ValueError):
    """Valid JSON whose run/outcome shape cannot be published safely."""


def resolved_path(path):
    path = Path(path)
    return path.parent.resolve() / path.name


@contextlib.contextmanager
def metadata_lock(directory, *, create=False):
    directory = Path(directory).resolve()
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.metadata.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield directory


def validate_run(run):
    if not isinstance(run, dict):
        raise InvalidRun('Existing run is not an object')
    outcomes = run.get('outcome', [])
    if not isinstance(outcomes, list) or any(
        not isinstance(label, dict) or type(label.get('passed')) is not bool
        or not isinstance(label.get('evidence'), str) or not isinstance(label.get('by'), str)
        or label['by'] not in {'claude', 'user'}
        or ('at' in label and not isinstance(label['at'], str))
        for label in outcomes
    ):
        raise InvalidRun('Existing run has malformed outcomes')
    return run


def read(path, *, missing=False):
    try:
        return validate_run(json.loads(Path(path).read_text()))
    except FileNotFoundError:
        if missing:
            return {}
        raise


def save_execution(path, execution):
    path = resolved_path(path)
    with metadata_lock(path.parent):
        current = read(path, missing=True)
        merged = {**execution, 'outcome': current.get('outcome', [])}
        validate_run(merged)
        publish(path, merged)
        return merged


def append_outcome(path, label):
    path = resolved_path(path)
    with metadata_lock(path.parent):
        run = read(path)
        run['outcome'] = [*run.get('outcome', []), label]
        validate_run(run)
        publish(path, run)
        return run
