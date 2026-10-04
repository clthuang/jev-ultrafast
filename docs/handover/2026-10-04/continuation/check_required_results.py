"""Verify every collected required parameter variant passed under fixed-source release runs."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--required', type=Path, required=True)
parser.add_argument('--execution', type=Path, nargs='+', required=True, help='pytest_evidence.py final run records')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
evidence = Path(__file__).resolve().parent
requirements = json.loads(args.required.read_text())
required = {node for nodes in requirements['required'].values() for node in nodes}
required.update(json.loads((evidence / 'readiness-required-tests.json').read_text()))
expected_variants, passed_variants, source_hashes = set(), set(), set()
failures, reports = [], []
for path in args.execution:
    run = json.loads(path.read_text())
    source_hashes.add(run['source_manifest_sha256'])
    if hashlib.sha256(Path(run['source_manifest']).read_bytes()).hexdigest() != run['source_manifest_sha256']:
        failures.append(f'{path}: source manifest changed')
    if run['exit_code'] or run['collection_errors'] or run['source_mismatches_before'] or run['source_mismatches_after']:
        failures.append(f'{path}: unsuccessful session, collection, or source check')
    if not run['xfail_strict']:
        failures.append(f'{path}: xfail_strict was not enabled')
    expected_variants.update(node for node in run['all_collected'] if node.split('[', 1)[0] in required)
    phases = {}
    for report in run['reports']:
        phases.setdefault(report['nodeid'], {})[report['when']] = report
        if report['outcome'] == 'failed' or report['wasxfail']:
            failures.append(f'{path}: {report["nodeid"]} {report["when"]} {report["outcome"]}')
    for node in run['selected']:
        parts = phases.get(node, {})
        if set(parts) == {'setup', 'call', 'teardown'} and all(
                part['outcome'] == 'passed' and not part['wasxfail'] for part in parts.values()):
            passed_variants.add(node)
        elif node.split('[', 1)[0] in required:
            failures.append(f'{path}: required variant did not pass every phase: {node}')
    if not run['junit']:
        failures.append(f'{path}: no JUnit evidence')
    else:
        for case in ET.parse(run['junit']).iter('testcase'):
            if any(child.tag in {'failure', 'error'} for child in case):
                failures.append(f'{path}: JUnit failure/error {case.attrib.get("name")}')
        reports.append(run['junit'])
if len(source_hashes) != 1:
    failures.append('Final modes did not use one fixed source manifest')
missing_names = sorted(required - {node.split('[', 1)[0] for node in expected_variants})
missing_variants = sorted(expected_variants - passed_variants)
result = {'required_names': len(required), 'expected_variants': len(expected_variants),
          'passed_required_variants': len(expected_variants & passed_variants),
          'missing_collection': missing_names, 'missing_execution': missing_variants,
          'failures': failures, 'missing_source': requirements['missing'],
          'source_parse_errors': requirements['parse_errors'], 'junit_reports': reports,
          'source_manifest_hashes': sorted(source_hashes),
          'required_variant_ids': sorted(expected_variants)}
result['passed'] = not any((missing_names, missing_variants, failures,
                            result['missing_source'], result['source_parse_errors']))
with args.output.open('x') as stream:
    json.dump(result, stream, indent=2)
    stream.write('\n')
print(json.dumps({key: value for key, value in result.items() if key != 'required_variant_ids'}, indent=2))
raise SystemExit(0 if result['passed'] else 1)
