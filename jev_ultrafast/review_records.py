"""Pure review identities and strict readers shared by writers and reports."""

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from . import site_notes
from .store_io import canonical_bytes

BATCH_SCHEMA = 1
DIGEST_SCHEMA = 2
ATTEMPT_SCHEMA = 1
ID = re.compile(r'[0-9a-f]{32}')
HASH = re.compile(r'[0-9a-f]{64}')
RUN_ID = re.compile(r'\d{8}-\d{6}-[0-9a-f]{4}')
LEGACY_DIGEST = re.compile(r'\d{8}-\d{6}')
ATTEMPT_STATES = {'claimed', 'spawning', 'running', 'succeeded', 'failed', 'superseded', 'uncertain', 'abandoned'}


class RecordError(ValueError):
    """An unsupported or malformed authoritative record stops mutations."""


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def note_hash(note):
    return digest({key: value for key, value in note.items() if key not in ('shown', 'last_shown')})


def base_projection(run):
    """Only review evidence, privacy sources and linkage affect a run's version."""
    page, result = run.get('page') or {}, run.get('result')
    return {
        'goal': run.get('goal'), 'call': {key: (run.get('call') or {}).get(key)
                                       for key in ('goal', 'url', 'allowed_operations', 'allowed_sites', 'allow_commit')},
        'previous_run': run.get('previous_run'), 'has_previous_run': 'previous_run' in run, 'pid': run.get('pid'),
        'page': {key: page.get(key) for key in ('url', 'title')}, 'outcome': run.get('outcome', []),
        'result': None if result is None else {key: result.get(key) for key in ('status', 'notes')},
        'failure': run.get('failure'), 'has_failure': 'failure' in run, 'notes_shown': run.get('notes_shown', []),
        'history': [{key: step.get(key) for key in ('step', 'operation', 'action', 'kind', 'text', 'url',
                                                  'page_changed', 'probability')}
                    for step in run.get('history', [])],
        'text_values': [call.get('value') for call in run.get('text_calls', [])],
        'visited_urls': site_notes.visited_urls(run), 'allowed_operations': run.get('allowed_operations'),
    }


def base_version(run):
    return digest({'fingerprint_version': 1, 'run': base_projection(run)})


class Inventory:
    """Compute shared linkage, successor and privacy-chain evidence once per view."""

    def __init__(self, runs):
        self.runs = runs
        self.links = site_notes.links(runs)
        self.successors = {key: set() for key in runs}
        for child, run in runs.items():
            for parent in (self.links.get(child), run.get("previous_run")):
                if isinstance(parent, str) and parent in runs:
                    self.successors[parent].add(child)
        self.chains = site_notes.chains(runs)
        self.chain_of = {key: chain for chain in self.chains for key in chain}


def relations(runs, roots, inventory=None):
    """Explicit absent/self/invalid parents and successor queries survive normalization."""
    inventory = inventory or Inventory(runs)
    result = {}
    for run_id in sorted(roots):
        run = runs.get(run_id)
        if run is None:
            result[run_id] = {'state': 'missing'}
            continue
        raw = run.get('previous_run')
        parent = ({'state': 'legacy', 'resolved': inventory.links.get(run_id)} if 'previous_run' not in run else
                  {'state': 'none'} if raw is None else
                  {'state': 'self', 'id': raw} if raw == run_id else
                  {'state': 'present' if raw in runs else 'missing', 'id': raw}
                  if isinstance(raw, str) and RUN_ID.fullmatch(raw) else {'state': 'invalid', 'hash': digest(raw)})
        result[run_id] = {'parent': parent, 'successors': sorted(inventory.successors.get(run_id, ()))}
    return result


def closure(runs, roots, inventory=None):
    inventory = inventory or Inventory(runs)
    return set().union(*(set(inventory.chain_of.get(key, {key: None})) for key in roots))


def run_versions(runs, reasons, recoveries):
    inventory = Inventory(runs)
    bases = {key: base_version(run) for key, run in runs.items()}
    component_hashes = {}
    for chain in inventory.chains:
        related = set(chain)
        for key in chain:
            related.update(inventory.successors[key])
            if inventory.links[key] is not None:
                related.add(inventory.links[key])
        component = digest({'chain': list(chain), 'bases': {key: bases[key] for key in sorted(related)},
                            'relations': relations(runs, related, inventory)})
        component_hashes.update({key: component for key in chain})
    return {key: digest({'base': bases[key], 'reasons': why, 'component': component_hashes[key],
                         'recovery': list(recoveries.get(key, {}))}) for key, why in reasons.items()}


def valid_time(value):
    try:
        return isinstance(value, str) and bool(datetime.fromisoformat(value))
    except ValueError:
        return False


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def valid_cost(value):
    return value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0


def version_map(value):
    return isinstance(value, dict) and all(isinstance(key, str) and isinstance(item, str) and HASH.fullmatch(item)
                                          for key, item in value.items())


def string(value):
    return isinstance(value, str) and bool(value)


def item_maps(items):
    if not isinstance(items, list):
        raise RecordError("Missing input items")
    mappings = {"runs": {}, "notes": {}}
    for item in items:
        if (not isinstance(item, dict) or item.get("kind") not in mappings or not string(item.get("id"))
                or not isinstance(item.get("version"), str) or not HASH.fullmatch(item["version"])
                or not isinstance(item.get("reasons"), list) or not all(string(reason) for reason in item["reasons"])):
            raise RecordError("Malformed input item")
        kind, key = item["kind"], item["id"]
        if key in mappings[kind] or kind == "runs" and not RUN_ID.fullmatch(key):
            raise RecordError("Duplicate or invalid input item")
        mappings[kind][key] = item["version"]
    return mappings


def text_fields(value, names):
    return isinstance(value, dict) and all(isinstance(value.get(key), str) for key in names)


def string_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def valid_decision(value):
    return (text_fields(value, ('action', 'note', 'hint', 'detail', 'reason', 'outcome'))
            and value['action'] in {'add', 'flag', 'retire'} and type(value.get('applied')) is bool
            and string_list(value.get('runs')))


def valid_flag(value):
    return text_fields(value, ('run', 'reason'))


def valid_proposal(value):
    return (text_fields(value, ('hypothesis', 'mechanism', 'test', 'pass_bar'))
            and string_list(value.get('evidence_runs')))


def valid_child(value):
    if value is None:
        return True
    if not isinstance(value, dict) or type(value.get('exited')) is not bool:
        return False
    if value['exited'] and set(value) == {'exited'}:
        return True
    identity = value.get('identity')
    return (type(value.get('pid')) is int and value['pid'] > 1 and isinstance(identity, dict)
            and identity.get('state') in {'present', 'absent', 'unknown'}
            and (identity['state'] != 'present' or (
                identity.get('pid') == value['pid'] and type(identity.get('pgid')) is int
                and isinstance(identity.get('birth'), str) and type(identity.get('uid')) is int)))


def validate(record, kind):
    versions = {'batch': BATCH_SCHEMA, 'digest': DIGEST_SCHEMA, 'attempt': ATTEMPT_SCHEMA}
    if (not isinstance(record, dict) or type(record.get('schema_version')) is not int
            or record['schema_version'] != versions[kind]):
        raise RecordError(f'Unknown or missing {kind} schema version')
    identifier = record.get('batch_id' if kind == 'digest' else f'{kind}_id')
    if not isinstance(identifier, str) or not ID.fullmatch(identifier) or not valid_time(record.get('created_at')):
        raise RecordError(f'Malformed {kind} identity or creation time')
    if kind in {'batch', 'digest'}:
        if (not isinstance(record.get('sent_text'), str)
                or record.get('sent_sha256') != hashlib.sha256(record['sent_text'].encode('utf-8')).hexdigest()):
            raise RecordError('Malformed sent input or integrity hash')
    if kind == 'batch':
        if any(type(record.get(key)) is not int or record[key] != 1
               for key in ('summary_version', 'fingerprint_version', 'scrubber_version')):
            raise RecordError('Unsupported batch semantic version')
        if not string(record.get('source_revision')) or not all(version_map(record.get(key)) for key in ('runs', 'notes')):
            raise RecordError('Malformed batch evidence')
        if item_maps(record.get('items')) != {key: record[key] for key in ('runs', 'notes')}:
            raise RecordError('Batch input membership differs from item versions')
        deps = record.get('dependencies')
        if (not isinstance(deps, dict) or not version_map(deps.get('runs')) or not version_map(deps.get('notes'))
                or not isinstance(deps.get('relations'), dict) or not isinstance(deps.get('note_site_hashes'), list)
                or not all(isinstance(value, str) and HASH.fullmatch(value) for value in deps['note_site_hashes'])
                or not isinstance(record.get('exclusions_version'), str)
                or not HASH.fullmatch(record['exclusions_version'])
                or deps.get('exclusions_version') != record['exclusions_version']):
            raise RecordError('Malformed batch dependencies')
        for key, relation in deps['relations'].items():
            if not RUN_ID.fullmatch(key) or not isinstance(relation, dict):
                raise RecordError('Malformed dependency relation')
            if relation == {'state': 'missing'}:
                continue
            parent = relation.get('parent')
            if (not isinstance(parent, dict) or parent.get('state') not in
                    {'none', 'legacy', 'self', 'present', 'missing', 'invalid'}
                    or not isinstance(relation.get('successors'), list)
                    or not all(isinstance(value, str) and RUN_ID.fullmatch(value) for value in relation['successors'])):
                raise RecordError('Malformed dependency parent/successors')
        if (not isinstance(record.get('deferred'), list)
                or any(not isinstance(item, dict) or item.get('kind') not in {'runs', 'notes'}
                       or not string(item.get('id')) or item.get('reason') not in {'item_cap', 'byte_cap'}
                       for item in record['deferred'])):
            raise RecordError('Malformed deferred membership')
    elif kind == 'digest':
        ack = record.get('acknowledged')
        if (record.get('status') != 'committed' or not HASH.fullmatch(str(record.get('reply_sha256', '')))
                or not isinstance(ack, dict) or not all(version_map(ack.get(key)) for key in ('runs', 'notes'))
                or not valid_time(record.get('finished_at')) or not valid_cost(record.get('cost'))
                or not isinstance(record.get('summary'), str)
                or any(not isinstance(record.get(key), list) or not all(check(item) for item in record[key])
                       for key, check in (('decisions', valid_decision), ('flags', valid_flag),
                                          ('proposals', valid_proposal)))):
            raise RecordError('Malformed committed digest')
        items = item_maps(record.get('input_items'))
        if any(items[kind].get(key) != value for kind, mapping in ack.items() for key, value in mapping.items()
               if kind in items) or set(ack) != set(items):
            raise RecordError('Acknowledgment does not match reviewed input')
        if record.get('attempt_id') is not None and not ID.fullmatch(str(record['attempt_id'])):
            raise RecordError('Malformed paid attempt identity')
    else:
        if (not isinstance(record.get('kind'), str) or record['kind'] not in {'auto', 'once', 'preflight'}
                or not isinstance(record.get('status'), str) or record['status'] not in ATTEMPT_STATES
                or type(record.get('started_at')) not in (int, float) or not math.isfinite(record['started_at'])
                or type(record.get('deadline')) not in (int, float) or not math.isfinite(record['deadline'])
                or not valid_cost(record.get('cost')) or not valid_child(record.get('child'))
                or 'child' not in record or 'finished_at' not in record
                or record['finished_at'] is not None and not valid_time(record['finished_at'])
                or record.get('batch_id') is not None and not ID.fullmatch(str(record['batch_id']))
                or record.get('budget_usd') != (0.05 if record['kind'] == 'preflight' else 0.5)
                or not isinstance(record.get('sent_text'), str)
                or record.get('sent_sha256') != hashlib.sha256(record['sent_text'].encode('utf-8')).hexdigest()):
            raise RecordError('Malformed review attempt')
        item_maps(record.get('input_items'))
        if record['kind'] == 'preflight' and (record.get('batch_id') is not None or record['input_items']):
            raise RecordError('Preflight cannot carry reviewed items')
        if record['kind'] != 'preflight' and record.get('batch_id') is None:
            raise RecordError('Review attempt requires a batch')
    return record


def read(path, kind):
    try:
        record = validate(json.loads(Path(path).read_text()), kind)
        key = 'batch_id' if kind in {'batch', 'digest'} else 'attempt_id'
        if Path(path).stem != record[key]:
            raise RecordError('Record filename differs from its identity')
        return record
    except (OSError, ValueError, TypeError) as error:
        raise RecordError(f'Cannot read {kind} record {Path(path).name}') from error


def committed(reviews):
    found = []
    for path in Path(reviews).glob('*.json'):
        if ID.fullmatch(path.stem):
            found.append((path, read(path, 'digest')))
    return sorted(found, key=lambda pair: (timestamp(pair[1]['created_at']), pair[1]['batch_id']))


def acknowledged(reviews):
    result = {'runs': {}, 'notes': {}}
    for _, record in committed(reviews):
        for kind in result:
            for key, version in record['acknowledged'][kind].items():
                result[kind].setdefault(key, set()).add(version)
    return result


def report_records(reviews):
    """Chronological v2/legacy digests and unpaired attempts, without writing."""
    records, paired, errors, paid_attempts = [], set(), [], {}
    for path in Path(reviews).glob('*.json'):
        try:
            if ID.fullmatch(path.stem):
                record = read(path, 'digest')
                paired.add(record.get('attempt_id'))
            elif LEGACY_DIGEST.fullmatch(path.stem):
                record = json.loads(path.read_text())
                if (not isinstance(record, dict) or 'schema_version' in record or not valid_cost(record.get('cost'))
                        or any(not isinstance(record.get(key, []), list)
                               or any(not isinstance(item, dict) for item in record.get(key, []))
                               for key in ('decisions', 'flags', 'proposals'))
                        or 'failure' in record and not isinstance(record['failure'], str)):
                    raise RecordError('Unsupported historical digest')
                record = {**record, 'created_at': datetime.strptime(path.stem, '%Y%m%d-%H%M%S').isoformat(),
                          'status': 'failed' if 'failure' in record else 'committed', 'legacy': True}
            else:
                continue
            records.append((path, record))
        except (OSError, ValueError, TypeError) as error:
            errors.append((path, str(error)))
    for path in (Path(reviews) / 'attempts').glob('*.json'):
        try:
            attempt = read(path, 'attempt')
            paid_attempts[attempt['attempt_id']] = attempt
            if attempt['attempt_id'] not in paired:
                records.append((path, attempt))
        except RecordError as error:
            errors.append((path, str(error)))
    costs = {}
    for path, record in records:
        key = record.get('attempt_id') or str(path)
        cost = paid_attempts.get(key, {}).get('cost')
        if cost is None:
            cost = record.get('cost')
        if costs.get(key) is None:
            costs[key] = cost
        record['cost_key'] = key
    for _, record in records:
        record['reported_cost'] = costs[record['cost_key']]
    return sorted(records, key=lambda pair: (timestamp(pair[1]['created_at']), pair[0].name)), errors
