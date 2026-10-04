"""Release-only pytest evidence plugin; records full collection and selected outcomes on fixed source."""
import hashlib
import json
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption('--validation-evidence', required=True, help='New result JSON path outside candidate source')
    parser.addoption('--validation-source', required=True, help='Immutable record_stage.py source manifest')


def source_matches(config):
    manifest_path = Path(config.getoption('--validation-source')).resolve()
    manifest = json.loads(manifest_path.read_text())
    root = Path(__file__).resolve().parent / 'candidate'
    if (root / '.env').exists():
        return ['.env: forbidden in candidate']
    actual = {name for name in manifest['baseline'] if (root / name).is_file()}
    actual.update(path.name for path in root.iterdir() if path.is_file())
    for directory in ('jev_ultrafast', 'tests', 'scripts', 'examples', 'docs'):
        actual.update(path.relative_to(root).as_posix() for path in (root / directory).rglob('*')
                      if path.is_file() and not {'__pycache__', '.pytest_cache'} & set(path.parts))
    expected_files = set(manifest['candidate'])
    changed = [name for name, expected in manifest['candidate'].items()
               if not (root / name).is_file() or hashlib.sha256((root / name).read_bytes()).hexdigest() != expected]
    return sorted(set(changed) | (actual ^ expected_files))


def pytest_configure(config):
    target = Path(config.getoption('--validation-evidence')).resolve()
    evidence = Path(__file__).resolve().parent
    if target.exists() or evidence not in target.parents or (evidence / 'candidate') in target.parents:
        raise pytest.UsageError('Release evidence must be a new file under evidence, outside candidate')
    root = evidence / 'candidate'
    selection = [(Path(config.invocation_params.dir) / name).resolve() for name in config.args]
    restricted = ('ignore', 'ignore_glob', 'deselect', 'pyargs', 'keyword', 'collectonly',
                  'lf', 'failedfirst', 'newfirst', 'stepwise')
    if (Path(config.rootpath).resolve() != root or selection != [root / 'tests']
            or any(config.getoption(name, default=False) for name in restricted)
            or config.getoption('markexpr') not in ('', 'native')):
        raise pytest.UsageError('Release evidence requires full tests-root collection with no selection except -m native')
    mismatches = source_matches(config)
    if mismatches:
        raise pytest.UsageError('Source differs from release manifest: ' + ', '.join(mismatches))
    manifest = Path(config.getoption('--validation-source')).resolve()
    config._release_evidence = {
        'schema_version': 1, 'source_manifest': str(manifest),
        'source_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'source_mismatches_before': mismatches, 'all_collected': [], 'selected': [], 'reports': [],
        'collection_errors': [], 'xfail_strict': config.getini('xfail_strict'),
        'junit': str(Path(config.option.xmlpath).resolve()) if config.option.xmlpath else None,
    }


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(config, items):
    config._release_evidence['all_collected'] = [item.nodeid for item in items]
    yield
    config._release_evidence['selected'] = [item.nodeid for item in items]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    report = result.get_result()
    item.config._release_evidence['reports'].append({
        'nodeid': report.nodeid, 'when': report.when, 'outcome': report.outcome,
        'wasxfail': getattr(report, 'wasxfail', None),
    })


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    result = yield
    report = result.get_result()
    if report.failed:
        collector.config._release_evidence['collection_errors'].append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    evidence = config._release_evidence
    evidence.update(exit_code=int(exitstatus), source_mismatches_after=source_matches(config))
    with Path(config.getoption('--validation-evidence')).open('x') as stream:
        json.dump(evidence, stream, indent=2)
        stream.write('\n')
