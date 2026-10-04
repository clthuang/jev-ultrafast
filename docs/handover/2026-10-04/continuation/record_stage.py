"""Capture immutable candidate hashes and root preservation evidence for one stage."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('stage')
args = parser.parse_args()
evidence = Path(__file__).resolve().parent
isolation = json.loads((evidence / 'isolation.json').read_text())
production, candidate = Path(isolation['production']), Path(isolation['candidate'])
baseline = isolation['source_baseline']
sha256 = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
changed_production = [name for name, digest in baseline.items()
                      if not (production / name).is_file() or sha256(production / name) != digest]
if changed_production:
    raise SystemExit('Production source changed; inspect before continuing: ' + repr(changed_production))
if (candidate / '.env').exists():
    raise SystemExit('Candidate must not contain .env')
paths = set(baseline)
paths.update(path.name for path in candidate.iterdir() if path.is_file())
for directory in ('jev_ultrafast', 'tests', 'scripts', 'examples', 'docs'):
    for path in (candidate / directory).rglob('*'):
        if path.is_file() and not {'__pycache__', '.pytest_cache'} & set(path.parts):
            paths.add(path.relative_to(candidate).as_posix())
hashes = {name: sha256(candidate / name) for name in sorted(paths) if (candidate / name).is_file()}
changed = [name for name, digest in hashes.items() if baseline.get(name) != digest]
removed = sorted(set(baseline) - set(hashes))
result = {'stage': args.stage, 'production_changed': changed_production,
          'baseline': baseline, 'candidate': hashes, 'changed_paths': changed, 'removed_paths': removed}
output = evidence / (args.stage + '-hashes.json')
with output.open('x') as stream:
    json.dump(result, stream, indent=2)
    stream.write('\n')
print(f'{output.name}: {len(changed)} changed candidate paths; production preserved')
