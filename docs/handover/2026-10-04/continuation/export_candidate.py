"""Build and dry-run a candidate patch without touching the running checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', help='Existing immutable stage name, normally release-final')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = Path(__file__).resolve().parent
    isolation = json.loads((evidence / 'isolation.json').read_text())
    production = Path(isolation['production'])
    candidate = Path(isolation['candidate'])
    stage = json.loads((evidence / f'{args.stage}-hashes.json').read_text())
    output = args.output.resolve()
    if evidence not in output.parents or output.exists():
        raise SystemExit('Output must be a new directory inside the evidence directory')
    baseline_hashes, candidate_hashes = stage['baseline'], stage['candidate']
    for name, expected in baseline_hashes.items():
        if digest(production / name) != expected or digest(evidence / 'baseline' / name) != expected:
            raise SystemExit(f'Baseline/production changed: {name}')
    for name, expected in candidate_hashes.items():
        if digest(candidate / name) != expected:
            raise SystemExit(f'Candidate changed after stage capture: {name}')
    changed = sorted(name for name in baseline_hashes.keys() | candidate_hashes.keys()
                     if baseline_hashes.get(name) != candidate_hashes.get(name))
    with tempfile.TemporaryDirectory(prefix='patch-check-', dir=evidence) as directory:
        scratch = Path(directory)
        before, after, rehearsal = (scratch / name for name in ('a', 'b', 'rehearsal'))
        for tree in (before, after, rehearsal):
            tree.mkdir()
        for name in changed:
            for tree, source, hashes in ((before, evidence / 'baseline', baseline_hashes),
                                         (after, candidate, candidate_hashes)):
                if name in hashes:
                    target = tree / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / name, target)
        for name in baseline_hashes:
            target = rehearsal / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(evidence / 'baseline' / name, target)
        diff = subprocess.run(['git', 'diff', '--no-index', '--binary', '--no-prefix', '--', 'a', 'b'],
                              cwd=scratch, capture_output=True, check=False)
        if diff.returncode not in (0, 1):
            raise SystemExit(diff.stderr.decode())
        patch = scratch / 'implementation.patch'
        patch.write_bytes(diff.stdout)
        commands = []
        isolated_git = {key: value for key, value in os.environ.items()
                        if key not in {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'}}
        isolated_git['GIT_CEILING_DIRECTORIES'] = str(evidence)
        for operation in (['--check'], []):
            command = ['git', 'apply', *operation, str(patch)]
            result = subprocess.run(command, cwd=rehearsal, env=isolated_git, capture_output=True, check=False)
            commands.append({'argv': command, 'exit_code': result.returncode,
                             'stdout': result.stdout.decode(), 'stderr': result.stderr.decode()})
            if result.returncode:
                raise SystemExit(result.stderr.decode())
        for name, expected in candidate_hashes.items():
            if digest(rehearsal / name) != expected:
                raise SystemExit(f'Patch reconstruction mismatch: {name}')
        for name in baseline_hashes.keys() - candidate_hashes.keys():
            if (rehearsal / name).exists():
                raise SystemExit(f'Patch did not remove: {name}')
        output.mkdir()
        shutil.copy2(patch, output / 'implementation.patch')
        manifest = {'stage': args.stage, 'baseline_commit': (evidence / 'HEAD.txt').read_text().strip(),
                    'production_preserved': True, 'changed_paths': changed,
                    'baseline_hashes': baseline_hashes, 'candidate_hashes': candidate_hashes,
                    'patch_sha256': digest(patch), 'reconstruction_matches': True,
                    'commands': commands, 'activation_performed': False}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(json.dumps({'output': str(output), 'changed_paths': len(changed),
                          'patch_sha256': digest(patch), 'reconstruction_matches': True}))


if __name__ == '__main__':
    main()
