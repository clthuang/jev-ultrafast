"""Reconstruct the unaccepted WIP in a NEW ignored directory; never activate it."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    root = Path(subprocess.check_output(
        ['git', '-C', str(package), 'rev-parse', '--show-toplevel'], text=True
    ).strip()).resolve()
    destination = args.destination.resolve()
    if destination.exists() or not destination.is_relative_to(root / 'artifacts'):
        raise SystemExit('Destination must be new and inside this checkout/artifacts; existing paths are refused')
    manifest = json.loads((package / 'candidate-manifest.json').read_text())
    patch = package / 'candidate-wip.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['patch_sha256']:
        raise SystemExit('WIP patch checksum mismatch')
    archive = subprocess.check_output([
        'git', '-C', str(root), 'archive', '--format=tar', manifest['base_commit']
    ])
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(destination, filter='data')
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'}}
    environment['GIT_CEILING_DIRECTORIES'] = str(destination.parent)
    discovery = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=destination,
                               env=environment, capture_output=True)
    if discovery.returncode == 0:
        raise SystemExit('Refusing to apply: destination unexpectedly resolves to a Git checkout')
    for check in (True, False):
        command = ['git', 'apply'] + (['--check'] if check else []) + [str(patch)]
        subprocess.run(command, cwd=destination, env=environment, check=True)
    actual = {path.relative_to(destination).as_posix() for path in destination.rglob('*') if path.is_file()}
    expected = set(manifest['paths'])
    mismatches = sorted(actual ^ expected)
    for name, record in manifest['paths'].items():
        path = destination / name
        if not path.is_file():
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            mismatches.append(name + ': content')
        if bool(path.stat().st_mode & 0o111) != (record['mode'] == '100755'):
            mismatches.append(name + ': executable mode')
    if mismatches or (destination / '.env').exists():
        raise SystemExit('Reconstruction mismatch; preserve for inspection: ' + repr(mismatches))
    print(json.dumps({'destination': str(destination), 'verified_paths': len(expected),
                      'base_commit': manifest['base_commit'], 'status': 'unaccepted WIP restored'}, indent=2))


if __name__ == '__main__':
    main()
