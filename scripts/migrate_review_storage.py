"""Explicit offline migration/export primitives; callers stop old writers before activation."""

import argparse
import fcntl
import hashlib
import json
import shutil
from pathlib import Path

from jev_ultrafast import run_store, site_notes


def migrate_storage(artifacts):
    """Preserve every legacy note field; unknown versions fail closed."""
    site_notes.update(lambda notes: None, Path(artifacts) / 'site-notes.json')


def export_storage(artifacts, destination):
    """Copy current state under review→metadata→notes locks, never an old rollback snapshot."""
    artifacts, destination = Path(artifacts).resolve(), Path(destination).resolve()
    if destination == artifacts or destination in artifacts.parents or artifacts in destination.parents:
        raise ValueError('Export destination must be outside the active artifact tree')
    reviews = artifacts / 'reviews'
    reviews.mkdir(parents=True, exist_ok=True)
    with (reviews / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with run_store.metadata_lock(artifacts / 'runs', create=True):
            def copy(envelope):
                destination.mkdir(parents=True, exist_ok=False)
                paths = [*sorted((artifacts / 'runs').glob('*.json')), *sorted(reviews.rglob('*.json'))]
                paths += [artifacts / name for name in ('site-notes.json', 'review-exclude.txt')]
                hashes = {}
                for source in paths:
                    if not source.is_file():
                        continue
                    relative = source.relative_to(artifacts)
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    hashes[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
                (destination / 'export-manifest.json').write_text(json.dumps(hashes, indent=2) + '\n')
                return hashes
            return site_notes.transaction(copy, artifacts / 'site-notes.json', write=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--migrate', action='store_true')
    action.add_argument('--export', type=Path)
    args = parser.parse_args(argv)
    if args.migrate:
        migrate_storage(args.artifacts)
    else:
        export_storage(args.artifacts, args.export)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
