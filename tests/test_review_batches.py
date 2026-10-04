"""Disposable, offline contract tests for immutable review batches and publication."""

import json

from jev_ultrafast import site_notes
from scripts import review_runs


def test_overlap_redaction_preserves_no_canary_fragment():
    values = {'jane smith', 'smith bo lee'}
    for text in ('jane smith bo lee', 'JANE SMITH BO LEE', 'jane  smith bo  lee'):
        rules = review_runs.scrubber(values, {'jane smith'})
        assert review_runs.scrub(text, rules) == '<value>'
    assert review_runs.scrub('jane smith', rules) == 'jane smith'
    assert review_runs.scrub('plain text', review_runs.scrubber(set(), set())) == 'plain text'


def test_all_output_surfaces_share_privacy_rules(capsys):
    canaries = {'Selectedcanary', 'Deferredcanary', 'Excludedcanary'}
    queue = {'values': canaries, 'names': {'example.com-1'}, 'run_ids': set()}
    quote = review_runs.privacy_quote(queue)
    for surface in ('batch', 'receipt', 'digest', 'attempt', 'state'):
        source = {'surface': surface, 'error': ' '.join(canaries), 'identity': 'example.com-1'}
        sanitized = review_runs.without_values(source, site_notes.task_value_pattern(canaries),
                                              review_runs.kept_names(queue['names']), set())
        encoded = json.dumps(sanitized)
        assert not any(value in encoded for value in canaries)
        assert 'example.com-1' in encoded
        print(encoded)
    boundary = 'x ' * (review_runs.LABEL_CHARACTERS // 2 - 2) + 'Selectedcanary'
    message = review_runs.result_failure({'subtype': 'failed', 'result': boundary}, quote)
    assert 'Selected' not in message
    assert not any(value in capsys.readouterr().out for value in canaries)
    unknown = review_runs.schema_errors({'outcome': 'Selectedcanary'}, review_runs.REVIEW_SCHEMA, quote=quote)
    assert 'reply has an unknown key outcome' in unknown


def test_same_start_separator_variants_redact_the_longest_union():
    values = {'Jane----------------Smith', 'Jane Smith Bo Lee'}
    text = 'Jane Smith Bo Lee'
    kept = review_runs.kept_names({'Jane Smith'})
    pattern = site_notes.task_value_pattern(values)
    assert review_runs.scrub(text, review_runs.scrubber(values, {'Jane Smith'})) == '<value>'
    assert review_runs.without_values(text, pattern, kept, set()) == '<value>'
    assert review_runs.holds_value(text, pattern, kept, set())


from copy import deepcopy  # noqa: E402

import pytest  # noqa: E402

from jev_ultrafast import review_records  # noqa: E402
from scripts import report_runs  # noqa: E402

REAL_LAUNCH = review_runs.launch

RUN_A = '20261003-100000-0001'
RUN_B = '20261003-100100-0002'
RUN_C = '20261003-100200-0003'


def sample_run(**changes):
    return {'goal': 'Search', 'page': {'url': 'https://example.com/', 'title': 'Search'},
            'history': [], 'text_calls': [], 'decisions': [], 'previous_run': None,
            'result': {'status': 'blocked', 'notes': ['Jev answered BLOCKED']},
            'outcome': [{'passed': False, 'by': 'claude', 'evidence': 'No results', 'at': '2026-10-03T10:00:00'}],
            **changes}


def write_run(run_id=RUN_A, **changes):
    review_runs.RUNS.mkdir(parents=True, exist_ok=True)
    path = review_runs.RUNS / f'{run_id}.json'
    path.write_text(json.dumps(sample_run(**changes)))
    return path


def notes_bytes():
    return site_notes.NOTES_PATH.read_bytes() if site_notes.NOTES_PATH.exists() else None


@pytest.mark.parametrize('kind', ['batch', 'digest', 'attempt'])
def test_unknown_record_versions_fail_closed(kind, fake_paid, monkeypatch, capsys):
    with pytest.raises(review_records.RecordError):
        review_records.validate({'schema_version': 999}, kind)
    # A real record of each kind, then the same record from a later version, through the readers that use it.
    write_run()
    batch = review_runs.prepare_batch()
    if kind == 'batch':
        path = review_runs.REVIEWS / 'batches' / f"{batch['batch_id']}.json"
    elif kind == 'digest':
        path, _ = apply_batch(batch)
    else:
        claim = review_runs.claim_attempt(review_runs.read_state(), 'once', batch, time.time())
        path = review_runs.attempt_path(claim['attempt_id'])
    record = json.loads(path.read_text())
    path.write_text(json.dumps({**record, 'schema_version': 999}))
    notes_before = notes_bytes()
    capsys.readouterr()
    if kind == 'batch':
        with pytest.raises(review_records.RecordError):
            review_runs.load_batch(batch['batch_id'])
        monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(EMPTY_REPLY)))
        assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
        assert not review_runs.committed_path(batch['batch_id']).exists()
    elif kind == 'digest':
        with pytest.raises(review_records.RecordError):
            review_records.acknowledged(review_runs.REVIEWS)  # never a partial set of acknowledgments
        assert review_runs.main(['queue']) == 1 and capsys.readouterr().out == ''
    else:
        assert review_runs.once_command(None) == 1 and fake_paid == []  # unreadable ownership: no paid launch
    assert notes_bytes() == notes_before
    report = '\n'.join(report_runs.review_lines(review_runs.REVIEWS, [], set(), set()))
    if kind != 'batch':
        assert f'skipped {path}: invalid review record' in capsys.readouterr().err and str(path) not in report


def test_correction_changes_review_version():
    run = sample_run()
    before = review_records.base_version(run)
    run['outcome'].append({'passed': True, 'by': 'user', 'evidence': 'Correction', 'at': '2026-10-03T11:00:00'})
    assert review_records.base_version(run) != before
    after = review_records.base_version(run)
    run['outcome'][-1]['at'] = '2026-10-03T11:00:01'
    assert review_records.base_version(run) != after


def test_changed_predecessor_invalidates_recovery():
    runs = {RUN_A: sample_run(), RUN_B: sample_run(previous_run=RUN_A)}
    before = review_records.run_versions(runs, {RUN_B: ['recovered']}, {RUN_B: runs})[RUN_B]
    runs[RUN_A]['goal'] = 'Changed earlier goal'
    assert review_records.run_versions(runs, {RUN_B: ['recovered']}, {RUN_B: runs})[RUN_B] != before


def test_new_successor_changes_absence_dependency():
    runs = {RUN_A: sample_run(previous_run=RUN_C)}
    before = review_records.relations(runs, {RUN_A})
    assert before[RUN_A]['parent'] == {'state': 'missing', 'id': RUN_C}
    runs[RUN_B] = sample_run(previous_run=RUN_A)
    assert review_records.relations(runs, {RUN_A}) != before
    runs[RUN_C] = sample_run()
    assert review_records.relations(runs, {RUN_A})[RUN_A]['parent']['state'] == 'present'


def test_execution_clocks_do_not_change_review_version():
    run = sample_run()
    before = review_records.base_version(run)
    changed = deepcopy(run)
    changed.update(elapsed_ms=1000, setup_ms=100, nonce='random', total_ms=1001)
    changed['page'].update(screenshot='image', token='new')
    assert review_records.base_version(changed) == before
    runs = {RUN_A: run}
    version = review_records.run_versions(runs, {RUN_A: ['failed']}, {})[RUN_A]
    runs[RUN_B] = sample_run()
    assert review_records.run_versions(runs, {RUN_A: ['failed']}, {})[RUN_A] == version


def test_attempt_records_never_acknowledge_items(fake_paid, monkeypatch):
    attempts = review_runs.REVIEWS / 'attempts'
    attempts.mkdir(parents=True)
    (attempts / ('a' * 32 + '.json')).write_text(json.dumps({'queue': {'runs': [RUN_A]}}))
    assert review_records.acknowledged(review_runs.REVIEWS) == {'runs': {}, 'notes': {}}
    (attempts / ('a' * 32 + '.json')).unlink()
    # A real paid attempt that failed after sending RUN_A: membership is recorded, acknowledgment is not.
    write_run()

    def over_budget(text, budget, quote=str, *, before_spawn=None, on_spawn=None, on_exit=None):
        fake_paid.append((text, budget))
        process = SimpleNamespace(pid=12345)
        before_spawn()
        on_spawn(process)
        on_exit(process)
        return {}, {'subtype': 'error_max_budget_usd', 'is_error': True, 'result': 'over', 'total_cost_usd': 0.5}, None

    monkeypatch.setattr(review_runs, 'launch', over_budget)
    assert review_runs.once_command(None) == 1
    [failed] = [review_records.read(path, 'attempt') for path in attempts.glob('*.json')]
    assert failed['status'] == 'failed'
    assert [item['id'] for item in failed['input_items'] if item['kind'] == 'runs'] == [RUN_A]
    assert review_records.acknowledged(review_runs.REVIEWS) == {'runs': {}, 'notes': {}}
    assert RUN_A in review_runs.build_queue()['runs']
    # Even a forged success acknowledges nothing without a committed digest.
    review_runs.save_attempt({**failed, 'status': 'succeeded', 'error': None})
    assert review_records.acknowledged(review_runs.REVIEWS) == {'runs': {}, 'notes': {}}
    assert RUN_A in review_runs.build_queue()['runs']


EMPTY_REPLY = {'decisions': [], 'flags': [], 'proposals': [], 'summary': 'Reviewed'}


def apply_batch(batch, reply=None):
    return review_runs.record_review(reply or EMPTY_REPLY, batch)


def add_decision(run_id=RUN_B, **changes):
    return {'action': 'add', 'note': '', 'runs': [run_id], 'hint': 'scroll_first', 'detail': 'Scroll for filters.',
            'reason': 'Recovered after scrolling', **changes}


def recovery():
    write_run(RUN_A)
    write_run(RUN_B, previous_run=RUN_A, result={'status': 'done', 'notes': []},
              outcome=[{'passed': True, 'by': 'user', 'evidence': 'Verified', 'at': '2026-10-03T11:00:00'}])


def batch_id_of(err):
    [line] = [line for line in err.splitlines() if line.startswith('batch: ')]
    return line.removeprefix('batch: ')


def test_queue_prints_exact_saved_bytes(capsys):
    write_run()
    assert review_runs.main(['queue']) == 0
    output = capsys.readouterr()
    batch = review_runs.load_batch(batch_id_of(output.err))
    assert output.out.encode('utf-8') == batch['sent_text'].encode('utf-8')
    assert batch['sent_sha256'] == __import__('hashlib').sha256(output.out.encode()).hexdigest()


def test_deferred_and_excluded_contributors_still_redact(monkeypatch):
    write_run(RUN_A, goal='Deferredcanary Excludedcanary Selectedcanary')
    write_run(RUN_B, history=[{'text': 'Deferredcanary'}])
    write_run(RUN_C, previous_run=RUN_A, history=[{'text': 'Excludedcanary'}])
    site_notes.EXCLUDE_PATH.write_text(RUN_C)
    monkeypatch.setattr(review_runs, 'MAX_BATCH_RUNS', 1)
    batch = review_runs.prepare_batch()
    assert list(batch['runs']) == [RUN_A]
    assert set(batch['dependencies']['runs']) == {RUN_A, RUN_B, RUN_C}
    assert all(value not in batch['sent_text'] for value in ('Deferredcanary', 'Excludedcanary'))
    assert 'Deferredcanary' not in json.dumps(batch)
    assert batch['deferred'][0]['id'] == RUN_B


def test_batch_caps_defer_whole_items(monkeypatch):
    for number in range(28):
        write_run(f'20261003-100000-{number:04x}', goal='東京 ' * 100)
    batch = review_runs.prepare_batch()
    assert len(batch['runs']) == 25 and len(batch['notes']) <= 5
    assert len(batch['sent_text'].encode('utf-8')) <= 65_536
    assert sum(item['kind'] == 'runs' for item in batch['deferred']) == 3
    monkeypatch.setattr(review_runs, 'MAX_BATCH_BYTES', 1800)
    smaller = review_runs.prepare_batch()
    assert len(smaller['sent_text'].encode('utf-8')) <= 1800
    assert smaller['sent_text'].count('<untrusted page content ') == len(smaller['runs']) + len(smaller['notes'])


def test_oversized_item_does_not_starve_following_items(monkeypatch):
    write_run(RUN_A, history=[{'step': number, 'action': '巨大' * 100, 'operation': 'CLICK'} for number in range(100)])
    write_run(RUN_B)
    monkeypatch.setattr(review_runs, 'MAX_BATCH_BYTES', 1500)
    batch = review_runs.prepare_batch()
    assert RUN_A not in batch['runs'] and RUN_B in batch['runs']
    assert {'kind': 'runs', 'id': RUN_A, 'reason': 'byte_cap'} in batch['deferred']


def test_new_unrelated_run_is_not_added_at_apply():
    write_run(RUN_A)
    batch = review_runs.prepare_batch()
    write_run(RUN_B)
    path, problems = apply_batch(batch)
    assert not problems
    assert set(json.loads(path.read_text())['acknowledged']['runs']) == {RUN_A}
    assert RUN_B in review_runs.build_queue()['runs']


def test_legacy_notes_migrate_without_losing_fields():
    legacy = deepcopy(site_notes.SEEDS)
    legacy[0]['extension'] = {'untouched': True}
    site_notes.NOTES_PATH.parent.mkdir(parents=True)
    site_notes.NOTES_PATH.write_text(json.dumps(legacy))
    site_notes.update(lambda notes: notes[0].update(shown=4))
    envelope = json.loads(site_notes.NOTES_PATH.read_text())
    assert envelope['schema_version'] == 2 and envelope['pending_review'] is None
    assert envelope['notes'][0]['extension'] == {'untouched': True}
    assert site_notes.load()[0][0]['shown'] == 4


def test_transaction_callback_does_not_reenter_lock(monkeypatch):
    recovery()
    batch = review_runs.prepare_batch()
    original = site_notes.transaction
    depth = []

    def checked(*args, **kwargs):
        assert not depth, 'transaction reentered notes lock'
        depth.append(True)
        try:
            return original(*args, **kwargs)
        finally:
            depth.pop()
    monkeypatch.setattr(site_notes, 'transaction', checked)
    path, problems = apply_batch(batch, {**EMPTY_REPLY, 'decisions': [add_decision()]})
    assert not problems and json.loads(path.read_text())['decisions'][0]['applied']


def test_two_decisions_cannot_duplicate_one_recovery():
    recovery()
    batch = review_runs.prepare_batch()
    path, problems = apply_batch(batch, {**EMPTY_REPLY, 'decisions': [add_decision(), add_decision()]})
    assert not problems
    assert [item['applied'] for item in json.loads(path.read_text())['decisions']] == [True, False]
    assert sum(note['runs'].get('recovered') == RUN_B for note in site_notes.load()[0]) == 1


def test_unknown_notes_schema_stops_publication():
    site_notes.NOTES_PATH.parent.mkdir(parents=True)
    raw = '{"schema_version":999,"notes":[],"pending_review":null}'
    site_notes.NOTES_PATH.write_text(raw)
    with pytest.raises(site_notes.NotesStoreError):
        site_notes.update(lambda notes: notes.clear())
    assert site_notes.NOTES_PATH.read_text() == raw


@pytest.mark.parametrize('change', ['outcome', 'predecessor', 'new_successor', 'missing_parent'])
def test_changed_dependency_supersedes_before_mutation(change):
    write_run(RUN_A, previous_run=RUN_C if change == 'missing_parent' else None)
    batch = review_runs.prepare_batch()
    if change == 'outcome':
        write_run(RUN_A, outcome=[{'passed': False, 'by': 'user', 'evidence': 'Correction', 'at': 'later'}])
    elif change == 'predecessor':
        write_run(RUN_A, previous_run=RUN_B)
    else:
        write_run(RUN_B if change == 'new_successor' else RUN_C, previous_run=RUN_A)
    with pytest.raises(review_runs.Superseded):
        apply_batch(batch)
    assert not review_records.committed(review_runs.REVIEWS)
    assert not site_notes.NOTES_PATH.exists()


@pytest.mark.parametrize('change', ['value', 'new_successor', 'missing_parent'])
def test_changed_privacy_contributor_supersedes_batch(monkeypatch, change):
    write_run(RUN_A)
    write_run(RUN_B, previous_run=RUN_C if change == 'missing_parent' else None,
              history=[{'text': 'Deferredcanary'}])
    monkeypatch.setattr(review_runs, 'MAX_BATCH_RUNS', 1)
    batch = review_runs.prepare_batch()
    assert RUN_B not in batch['runs']
    if change == 'value':
        write_run(RUN_B, history=[{'text': 'Changedcanary'}])
    else:
        write_run(RUN_C, previous_run=RUN_B)
    with pytest.raises(review_runs.Superseded):
        apply_batch(batch)


def test_semantic_refusal_preserves_valid_neighbor():
    recovery()
    batch = review_runs.prepare_batch()
    reply = {**EMPTY_REPLY, 'decisions': [add_decision(detail='https://bad.test/'), add_decision()]}
    path, _ = apply_batch(batch, reply)
    digest = json.loads(path.read_text())
    assert [item['applied'] for item in digest['decisions']] == [False, True]
    assert digest['acknowledged']['runs'] == batch['runs']


def test_same_reply_replay_ignores_its_own_note_changes():
    recovery()
    batch, reply = review_runs.prepare_batch(), {**EMPTY_REPLY, 'decisions': [add_decision()]}
    path, _ = apply_batch(batch, reply)
    before = path.read_bytes(), site_notes.NOTES_PATH.read_bytes()
    assert apply_batch(batch, reply)[0] == path
    assert before == (path.read_bytes(), site_notes.NOTES_PATH.read_bytes())


def test_different_reply_after_commit_conflicts():
    write_run()
    batch = review_runs.prepare_batch()
    apply_batch(batch)
    with pytest.raises(ValueError, match='different reply'):
        apply_batch(batch, {**EMPTY_REPLY, 'summary': 'Different'})


def test_inventory_work_is_shared_across_long_chains(monkeypatch):
    runs = {f'20261003-100000-{number:04x}': sample_run(
        previous_run=f'20261003-100000-{number - 1:04x}' if number else None) for number in range(100)}
    calls = []
    original = review_records.Inventory
    class Counted(original):
        def __init__(self, values):
            calls.append(len(values))
            super().__init__(values)
    monkeypatch.setattr(review_records, 'Inventory', Counted)
    versions = review_records.run_versions(runs, {key: ['failed'] for key in runs}, {})
    assert len(versions) == 100 and calls == [100]


from jev_ultrafast import store_io  # noqa: E402


def test_storage_failure_acknowledges_nothing(monkeypatch):
    recovery()
    batch = review_runs.prepare_batch()
    original = store_io.publish

    def fail_notes(path, value, **options):
        if path.name == site_notes.NOTES_PATH.name:
            raise OSError('disk full before publication')
        return original(path, value, **options)

    monkeypatch.setattr(store_io, 'publish', fail_notes)
    with pytest.raises(OSError):
        apply_batch(batch, {**EMPTY_REPLY, 'decisions': [add_decision()]})
    assert not review_records.committed(review_runs.REVIEWS)
    assert review_records.acknowledged(review_runs.REVIEWS) == {'runs': {}, 'notes': {}}
    monkeypatch.setattr(store_io, 'publish', original)
    assert RUN_B in review_runs.build_queue()['runs']


@pytest.mark.parametrize('boundary', ['before_notes', 'after_notes', 'notes_fsync', 'before_digest',
                                      'after_digest', 'before_cleanup', 'after_cleanup'])
def test_crash_at_each_publication_boundary(monkeypatch, boundary, fake_paid):
    recovery()
    batch, reply = review_runs.prepare_batch(), {**EMPTY_REPLY, 'decisions': [add_decision()]}
    original, replace, fsync = store_io.publish, store_io.os.replace, store_io.fsync_directory
    fired = []

    def publish(path, value, **options):
        if path.name == site_notes.NOTES_PATH.name:
            phase = 'notes' if value.get('pending_review') else 'cleanup'
        else:
            phase = 'digest'
        if not fired and boundary == 'before_' + phase:
            fired.append(boundary)
            raise OSError('injected before publication')
        result = original(path, value, **options)
        if not fired and boundary == 'after_' + phase:
            fired.append(boundary)
            raise store_io.PublicationUncertain('injected after publication')
        return result

    def sync(directory):
        if not fired and boundary == 'notes_fsync' and directory.name == 'artifacts':
            fired.append(boundary)
            raise OSError('injected directory fsync')
        return fsync(directory)

    monkeypatch.setattr(store_io, 'publish', publish)
    monkeypatch.setattr(store_io, 'fsync_directory', sync)
    with pytest.raises(OSError):
        apply_batch(batch, reply)
    assert fired == [boundary]
    digest_path = review_runs.committed_path(batch['batch_id'])
    if boundary == 'before_notes':
        assert not site_notes.NOTES_PATH.exists() and not digest_path.exists()
    else:
        assert sum(note['runs'].get('recovered') == RUN_B for note in site_notes.load()[0]) == 1
        # Past the commit point some authoritative evidence always survives the fault: the receipt, the digest,
        # or both; a receipt is only ever cleared after its digest exists.
        receipt = site_notes.read_envelope(site_notes.NOTES_PATH)['pending_review']
        expected = {'after_notes': (True, False), 'notes_fsync': (True, False), 'before_digest': (True, False),
                    'after_digest': (True, True), 'before_cleanup': (True, True), 'after_cleanup': (False, True)}
        assert (receipt is not None, digest_path.exists()) == expected[boundary]
        # A paid dispatch recovers it first, then reviews only what is new: the note the decision added, never the
        # acknowledged runs again, and never the committed decisions a second time.
        assert review_runs.once_command(None) == 0
        assert all(f'run {key} · queued' not in text for text, _ in fake_paid for key in (RUN_A, RUN_B))
        assert digest_path.exists() and site_notes.read_envelope(site_notes.NOTES_PATH)['pending_review'] is None
        assert sum(note['runs'].get('recovered') == RUN_B for note in site_notes.load()[0]) == 1
    monkeypatch.setattr(store_io, 'publish', original)
    monkeypatch.setattr(store_io, 'fsync_directory', fsync)
    monkeypatch.setattr(store_io.os, 'replace', replace)
    path, problems = apply_batch(batch, reply)
    assert not problems
    digest = json.loads(path.read_text())
    assert digest['acknowledged'] == {'runs': batch['runs'], 'notes': batch['notes']}
    assert sum(note['runs'].get('recovered') == RUN_B for note in site_notes.load()[0]) == 1
    assert site_notes.read_envelope(site_notes.NOTES_PATH)['pending_review'] is None


def test_directory_fsync_failure_after_replace_never_replays(monkeypatch, fake_paid):
    test_crash_at_each_publication_boundary(monkeypatch, 'notes_fsync', fake_paid)


def test_all_note_writers_preserve_pending_receipt(monkeypatch):
    recovery()
    batch = review_runs.prepare_batch()
    original = review_runs.ensure_digest
    monkeypatch.setattr(review_runs, 'ensure_digest', lambda receipt: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        apply_batch(batch, {**EMPTY_REPLY, 'decisions': [add_decision()]})
    receipt = site_notes.read_envelope(site_notes.NOTES_PATH)['pending_review']
    note_id = next(note['id'] for note in site_notes.load()[0] if note['runs'].get('recovered') == RUN_B)
    site_notes.record_shown([note_id])
    site_notes.record_failure('example.com', 'covered_target', shown={note_id})
    site_notes.set_state(note_id, 'approve')
    site_notes.set_state(note_id, 'retire')
    site_notes.set_state(note_id, 'restore')
    site_notes.add_note({'site': 'other.example', 'hint': 'scroll_first', 'detail': None, 'url': None,
                         'failure': None, 'runs': {'failed': [], 'recovered': None}})
    assert site_notes.read_envelope(site_notes.NOTES_PATH)['pending_review'] == receipt
    before = deepcopy(site_notes.load()[0])
    monkeypatch.setattr(review_runs, 'ensure_digest', original)
    with review_runs.review_lock():
        review_runs.recover_pending()
    assert site_notes.load()[0] == before


def test_deferred_recovery_cannot_be_used_by_a_reply(monkeypatch):
    recovery()
    monkeypatch.setattr(review_runs, 'MAX_BATCH_RUNS', 1)
    batch = review_runs.prepare_batch()
    assert RUN_B not in batch['runs']
    path, problems = apply_batch(batch, {**EMPTY_REPLY, 'decisions': [add_decision()]})
    assert not problems and not json.loads(path.read_text())['decisions'][0]['applied']
    assert not any(note['runs'].get('recovered') == RUN_B for note in site_notes.load()[0])


def test_same_second_batches_remain_distinct():
    write_run()
    first, second = review_runs.prepare_batch(), review_runs.prepare_batch()
    assert first['batch_id'] != second['batch_id']
    assert review_runs.load_batch(first['batch_id']) == first
    assert review_runs.load_batch(second['batch_id']) == second


def test_failed_attempt_does_not_occupy_committed_digest_path():
    write_run()
    batch = review_runs.prepare_batch()
    folder = review_runs.REVIEWS / 'attempts'
    folder.mkdir()
    attempt_id = 'a' * 32
    (folder / f'{attempt_id}.json').write_text(json.dumps({
        'schema_version': 1, 'attempt_id': attempt_id, 'batch_id': batch['batch_id'], 'kind': 'once',
        'status': 'failed', 'created_at': '2026-10-03T10:00:00', 'started_at': 0, 'deadline': 1, 'cost': None,
        'finished_at': '2026-10-03T10:00:01', 'child': {'exited': True}, 'input_items': batch['items'],
        'sent_text': batch['sent_text'], 'sent_sha256': batch['sent_sha256'], 'budget_usd': 0.5}))
    assert not review_runs.committed_path(batch['batch_id']).exists()
    assert RUN_A in review_runs.build_queue()['runs']


def test_legacy_requeue_happens_once():
    write_run()
    review_runs.REVIEWS.mkdir(parents=True)
    (review_runs.REVIEWS / '20261003-100000.json').write_text(json.dumps({'queue': {'runs': [RUN_A], 'notes': {}}}))
    assert RUN_A in review_runs.build_queue()['runs']
    batch = review_runs.prepare_batch()
    apply_batch(batch)
    assert RUN_A not in review_runs.build_queue()['runs']
    write_run(RUN_A, outcome=[{'passed': False, 'by': 'user', 'evidence': 'corrected', 'at': 'later'}])
    assert RUN_A in review_runs.build_queue()['runs']


import threading  # noqa: E402
import time  # noqa: E402
from types import SimpleNamespace  # noqa: E402


@pytest.fixture
def fake_paid(monkeypatch):
    monkeypatch.setenv("JEV_AUTO_REVIEW", "1")
    monkeypatch.setenv("JEV_LEARNING", "1")
    calls = []
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {
        'state': 'present', 'pid': pid, 'birth': '100:123', 'uid': review_runs.os.getuid(), 'pgid': pid})
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: False)

    def launch(text, budget, quote=str, *, before_spawn=None, on_spawn=None, on_exit=None):
        calls.append((text, budget))
        process = SimpleNamespace(pid=12345)
        before_spawn()
        on_spawn(process)
        on_exit(process)
        return {}, {'subtype': 'success', 'structured_output': EMPTY_REPLY, 'total_cost_usd': 0.0123}, None
    monkeypatch.setattr(review_runs, 'launch', launch)
    return calls


def attempts():
    return [review_records.read(path, 'attempt') for path in (review_runs.REVIEWS / 'attempts').glob('*.json')]


def test_auto_and_once_cannot_dispatch_together(fake_paid):
    write_run()
    lock = review_runs.take_dispatch_lock()
    with lock:
        assert review_runs.once_command(None) == 1
        assert review_runs.auto_command() == 0
        assert review_runs.preflight_command() == 1
    assert fake_paid == [] and attempts() == []


def test_manual_apply_finishes_while_model_waits(fake_paid, monkeypatch):
    write_run()
    manual = review_runs.prepare_batch()
    entered, release = threading.Event(), threading.Event()
    fake = review_runs.launch

    def wait(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return fake(*args, **kwargs)
    monkeypatch.setattr(review_runs, 'launch', wait)
    result = []
    worker = threading.Thread(target=lambda: result.append(review_runs.once_command(None)))
    worker.start()
    assert entered.wait(5)
    path, problems = apply_batch(manual)
    assert path.exists() and not problems
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    # The waiting batch was independently acknowledged; paid result is superseded.
    assert attempts()[0]['status'] == 'superseded'
    assert site_notes.read_review_state().get('failures', 0) == 0


def test_crash_after_claim_does_not_redispatch(fake_paid):
    write_run()
    batch = review_runs.prepare_batch()
    with review_runs.review_lock():
        state = review_runs.read_state()
        claim = review_runs.claim_attempt(state, 'auto', batch, time.time())
    assert review_runs.auto_command() == 0
    assert fake_paid == []
    state = review_runs.read_state()
    assert state['failures'] == 1 and state['accounted_attempt_ids'] == [claim['attempt_id']]
    assert state['next_due'] > time.time()
    assert review_runs.auto_command() == 0 and review_runs.read_state() == state


def test_superseded_consumes_slot_not_failure_streak(fake_paid, monkeypatch):
    write_run()
    fake = review_runs.launch
    def changed(*args, **kwargs):
        result = fake(*args, **kwargs)
        write_run(goal='Corrected while model waited')
        return result
    monkeypatch.setattr(review_runs, 'launch', changed)
    assert review_runs.once_command(None) == 1
    assert attempts()[0]['status'] == 'superseded'
    state = review_runs.read_state()
    assert state['next_due'] > time.time() and state.get('failures', 0) == 0
    assert review_runs.auto_command() == 0 and len(fake_paid) == 1


def test_recovery_settles_attempt_once(fake_paid, monkeypatch):
    write_run()
    original = review_runs.settle_attempt
    monkeypatch.setattr(review_runs, 'settle_attempt', lambda *args: (_ for _ in ()).throw(OSError('state disk full')))
    assert review_runs.once_command(None) == 1
    assert len(review_records.committed(review_runs.REVIEWS)) == 1
    monkeypatch.setattr(review_runs, 'settle_attempt', original)
    with review_runs.review_lock():
        state = review_runs.read_state()
        review_runs.recover_attempts(state)
        review_runs.recover_attempts(state)
    assert len(state['accounted_attempt_ids']) == 1 and state['failures'] == 0
    assert len(fake_paid) == 1


def test_unreadable_exclusions_change_no_state_or_dispatch(fake_paid):
    site_notes.EXCLUDE_PATH.parent.mkdir(parents=True)
    site_notes.EXCLUDE_PATH.mkdir()
    assert review_runs.auto_command() == 0
    assert review_runs.once_command(None) == 1
    assert review_runs.preflight_command() == 1
    assert not site_notes.REVIEW_STATE.exists() and fake_paid == []


def test_abandoned_claim_settles_uncertain_once(fake_paid):
    write_run()
    batch = review_runs.prepare_batch()
    with review_runs.review_lock():
        state = review_runs.read_state()
        claim = review_runs.claim_attempt(state, 'auto', batch, time.time())
        claim.update(status='running', child={'pid': 12345, 'identity': {'state': 'absent'}, 'exited': True})
        review_runs.save_attempt(claim)
        review_runs.recover_attempts(state)
        review_runs.recover_attempts(state)
    assert state['failures'] == 1 and len(state['accounted_attempt_ids']) == 1
    assert attempts()[0]['status'] == 'abandoned'
    assert fake_paid == []


REUSED_CHILD = {'pid': 12345, 'exited': False, 'identity': {
    'state': 'present', 'pid': 12345, 'birth': '100:122', 'uid': review_runs.os.getuid(), 'pgid': 12345}}


@pytest.mark.parametrize('status,child', [('spawning', None), ('running', REUSED_CHILD)])
def test_unknown_or_reused_child_blocks_paid_launch_without_signalling(fake_paid, monkeypatch, status, child):
    write_run()
    batch = review_runs.prepare_batch()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', batch, time.time() - 10000)
    claim.update(status=status, child=child)
    review_runs.save_attempt(claim)
    monkeypatch.setattr(review_runs.os, 'killpg', lambda *args: pytest.fail('must not signal unknown/reused child'))
    assert review_runs.once_command(None) == 1 and fake_paid == []


def test_preflight_never_stamps_or_changes_failure_streak(fake_paid):
    site_notes.write_review_state({'failures': 2, 'off': True, 'next_due': 123})
    assert review_runs.preflight_command() == 0
    state = review_runs.read_state()
    assert (state['failures'], state['off'], state['next_due']) == (2, True, 123)
    assert 'last_start' not in state
    assert len(state['accounted_attempt_ids']) == 1
    assert fake_paid == [(review_runs.PREFLIGHT_PROMPT, 0.05)]
    assert not review_records.committed(review_runs.REVIEWS)


def test_corrupt_state_cannot_reset_dispatch_limits(fake_paid):
    site_notes.REVIEW_STATE.parent.mkdir(parents=True)
    raw = 'not valid json'
    site_notes.REVIEW_STATE.write_text(raw)
    assert review_runs.once_command(None) == 1
    assert site_notes.REVIEW_STATE.read_text() == raw and fake_paid == []


def test_next_due_allows_new_batch_after_uncertain_dispatch(fake_paid):
    for number in range(review_runs.REVIEW_QUEUE):
        write_run(f'20261003-100000-{number:04x}')
    batch = review_runs.prepare_batch()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'auto', batch, time.time() - 90000)
    assert review_runs.auto_command() == 0
    assert len(fake_paid) == 1
    all_attempts = attempts()
    assert len(all_attempts) == 2
    assert next(item for item in all_attempts if item['attempt_id'] == claim['attempt_id'])['status'] == 'abandoned'
    assert len(review_records.committed(review_runs.REVIEWS)) == 1


@pytest.mark.parametrize('ownership', ['live', 'unknown'])
def test_live_or_unknown_child_blocks_new_dispatch(fake_paid, monkeypatch, ownership):
    write_run()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', review_runs.prepare_batch(), time.time())
    identity = {'state': 'present', 'pid': 12345, 'birth': '100:123', 'uid': review_runs.os.getuid(), 'pgid': 12345}
    claim.update(status='running', child={'pid': 12345, 'identity': identity, 'exited': False})
    review_runs.save_attempt(claim)
    if ownership == 'unknown':
        monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {'state': 'unknown'})
    monkeypatch.setattr(review_runs.os, 'killpg', lambda *args: pytest.fail('child is not authorized for termination'))
    assert review_runs.once_command(None) == 1 and fake_paid == []


def hold_review_lock(seconds):
    """Hold the reviews' lock from another thread, as a manual queue, apply or enable does; returns once it is held."""
    held, release = threading.Event(), threading.Event()

    def hold():
        lock = review_runs.take_lock()
        assert lock is not None
        with lock:
            held.set()
            release.wait(seconds)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert held.wait(5)
    return release, thread


@pytest.mark.parametrize('phase', ['before_spawn', 'on_spawn', 'on_exit', 'returned'])
def test_manual_lock_holder_delays_but_never_fails_a_paid_review(fake_paid, monkeypatch, phase):
    write_run()
    fake, holders = review_runs.launch, []

    def contended(text, budget, quote=str, *, before_spawn=None, on_spawn=None, on_exit=None):
        def at(name, callback):
            def wrapped(*args):
                if name == phase:
                    holders.append(hold_review_lock(0.3))
                return callback(*args)
            return wrapped
        result = fake(text, budget, quote, before_spawn=at('before_spawn', before_spawn),
                      on_spawn=at('on_spawn', on_spawn), on_exit=at('on_exit', on_exit))
        if phase == 'returned':
            holders.append(hold_review_lock(0.3))
        return result

    monkeypatch.setattr(review_runs, 'launch', contended)
    assert review_runs.once_command(None) == 0
    for _, thread in holders:
        thread.join(5)
    [attempt] = attempts()
    assert attempt['status'] == 'succeeded' and attempt['cost'] == 0.0123 and attempt['child']['exited'] is True
    assert len(fake_paid) == 1 and len(review_records.committed(review_runs.REVIEWS)) == 1
    state = review_runs.read_state()
    assert state.get('failures', 0) == 0 and state['accounted_attempt_ids'] == [attempt['attempt_id']]
    write_run(RUN_B)
    assert review_runs.once_command(None) == 0 and len(fake_paid) == 2  # nothing blocks the next dispatch


def test_paid_review_waits_for_the_review_lock_only_up_to_its_bound(fake_paid, monkeypatch, capsys):
    """Past SHORT_LOCK_SECONDS a paid review reports BUSY. Its attempt file still holds the reaped child and the known
    cost, so the next dispatch settles it once instead of being blocked or losing the cost."""
    write_run()
    monkeypatch.setattr(review_runs, 'SHORT_LOCK_SECONDS', 0.2)
    release, thread = hold_review_lock(10)
    assert review_runs.once_command(None) == 1  # BUSY before any claim: nothing launched or recorded
    assert review_runs.BUSY in capsys.readouterr().out and fake_paid == [] and attempts() == []
    release.set()
    thread.join(5)
    fake, holders = review_runs.launch, []

    def returns_into_contention(*args, **kwargs):
        result = fake(*args, **kwargs)
        holders.append(hold_review_lock(10))
        return result

    monkeypatch.setattr(review_runs, 'launch', returns_into_contention)
    assert review_runs.once_command(None) == 1
    assert review_runs.BUSY in capsys.readouterr().out
    [returned] = attempts()
    assert returned['status'] == 'returned' and returned['cost'] == 0.0123 and returned['child']['exited'] is True
    assert review_records.committed(review_runs.REVIEWS) == []
    release, thread = holders[0]
    release.set()
    thread.join(5)
    monkeypatch.setattr(review_runs, 'launch', fake)
    assert review_runs.once_command(None) == 0 and len(fake_paid) == 2
    settled = next(item for item in attempts() if item['attempt_id'] == returned['attempt_id'])
    assert settled['status'] == 'abandoned' and settled['cost'] == 0.0123  # known cost kept, never invented
    state = review_runs.read_state()
    assert returned['attempt_id'] in state['accounted_attempt_ids'] and len(state['accounted_attempt_ids']) == 2


def test_note_cap_selects_oldest_despite_store_order():
    notes = []
    for number in reversed(range(7)):
        notes.append({**deepcopy(site_notes.SEEDS[0]), 'id': f'example{number}.com-1', 'site': f'example{number}.com',
                      'created': f'2026-10-{number + 1:02d}', 'approved': '2026-10-01'})
    site_notes.update(lambda existing: existing.__setitem__(slice(None), notes))
    batch = review_runs.prepare_batch()
    assert list(batch['notes']) == [f'example{number}.com-1' for number in range(5)]


def test_identity_exemptions_rerender_previous_items_before_byte_cap(monkeypatch):
    identity = 'longdomainexample.com'
    site_notes.update(lambda notes: notes.clear())
    write_run(RUN_A, goal=('See ' + identity + ' ') * 40, history=[{'text': identity}])
    write_run(RUN_B, page={'url': f'https://{identity}/', 'title': 'Search'})
    queue = review_runs.build_queue()
    queue['nonces'] = {RUN_A: '12345678', RUN_B: '12345678'}
    separate = sum(len(review_runs.summaries(review_runs.selected_queue(queue, [key], [])).encode())
                   for key in (RUN_A, RUN_B)) + 1
    together = len(review_runs.summaries(review_runs.selected_queue(queue, [RUN_A, RUN_B], [])).encode())
    assert separate < together
    monkeypatch.setattr(review_runs, 'MAX_BATCH_BYTES', separate)
    batch = review_runs.prepare_batch()
    assert list(batch['runs']) == [RUN_A] and identity not in batch['sent_text']
    assert len(batch['sent_text'].encode()) <= separate


def test_note_referencing_domain_excluded_run_is_not_sent():
    write_run(RUN_A, decisions=[{'observed_url': 'https://private.example/'}])
    site_notes.add_note({
        'site': 'example.com', 'hint': 'scroll_first', 'detail': 'Public detail.', 'url': None,
        'failure': None, 'runs': {'failed': [RUN_A], 'recovered': None}})
    site_notes.EXCLUDE_PATH.write_text('private.example')
    batch = review_runs.prepare_batch()
    assert RUN_A not in batch['sent_text'] and 'example.com-1' not in batch['notes']


@pytest.mark.parametrize('mutation', ['empty_dependencies', 'missing_source', 'missing_items', 'missing_sent',
                                      'unknown_summary', 'mismatched_items', 'bad_window'])
def test_batch_corruption_is_rejected_before_application(mutation):
    write_run()
    batch = review_runs.prepare_batch()
    broken = deepcopy(batch)
    if mutation == 'empty_dependencies':
        broken['dependencies'] = {}
    elif mutation.startswith('missing_'):
        missing = {'missing_source': 'source_revision', 'missing_items': 'items', 'missing_sent': 'sent_text'}
        broken.pop(missing[mutation])
    elif mutation == 'unknown_summary':
        broken['summary_version'] = 2
    elif mutation == 'bad_window':
        broken['since'] = '2026-09-29'  # run IDs start 20260929; a malformed window would raise TypeError later
    else:
        broken['items'][0]['version'] = 'f' * 64
    with pytest.raises(review_records.RecordError):
        review_records.validate(broken, 'batch')


@pytest.mark.parametrize('mutation', ['missing_items', 'missing_finished', 'bad_ack', 'extra_ack', 'wrong_filename'])
def test_digest_corruption_never_acknowledges_or_replays(mutation):
    write_run()
    batch = review_runs.prepare_batch()
    path, _ = apply_batch(batch)
    value = json.loads(path.read_text())
    if mutation == 'missing_items':
        value.pop('input_items')
    elif mutation == 'missing_finished':
        value.pop('finished_at')
    elif mutation == 'bad_ack':
        value['acknowledged'] = []
    elif mutation == 'extra_ack':
        value['acknowledged']['runs'][RUN_B] = 'f' * 64
    else:
        value['batch_id'] = 'f' * 32
    path.write_text(json.dumps(value))
    with pytest.raises(review_records.RecordError):
        review_records.acknowledged(review_runs.REVIEWS)
    with pytest.raises(review_records.RecordError):
        apply_batch(batch)


def test_auto_cutoff_and_exclusions_survive_migration(fake_paid):
    from scripts.migrate_review_storage import migrate_storage

    before_build = '20260926-100000-0001'  # before AUTO_FROM: automatic reviews never send it
    write_run(before_build)
    private = '20261003-090000-0001'
    write_run(private, page={'url': 'https://private.example/', 'title': 'Private'})
    eligible = [f'20261003-100000-{number:04x}' for number in range(review_runs.REVIEW_QUEUE)]
    for run_id in eligible:
        write_run(run_id)
    # A legacy store: list-format notes and the earlier state file, with one failure counted.
    site_notes.NOTES_PATH.write_text(json.dumps(site_notes.SEEDS))
    site_notes.EXCLUDE_PATH.write_text('private.example\n')
    site_notes.write_review_state({'last_start': '2026-09-29T09:00:00', 'next_due': 0, 'running': None,
                                   'failures': 1, 'off': False})
    migrate_storage(site_notes.NOTES_PATH.parent)
    assert site_notes.read_envelope(site_notes.NOTES_PATH)['schema_version'] == 2
    review_runs.auto_command()
    [(sent, budget)] = fake_paid
    assert budget == review_runs.REVIEW_BUDGET_USD
    assert all(f'run {run_id} · queued' in sent for run_id in eligible)
    assert before_build not in sent and private not in sent and 'private.example' not in sent
    state = review_runs.read_state()
    assert state['failures'] == 0 and state['next_due'] > time.time()  # success clears the carried count
    assert site_notes.EXCLUDE_PATH.read_text() == 'private.example\n'


def test_export_preserves_new_notes_outcomes_receipts_and_ack_history(tmp_path, monkeypatch):
    from jev_ultrafast import run_store
    from scripts.migrate_review_storage import export_storage, migrate_storage

    recovery()
    # A legacy store: list notes with a retired note, a timestamp-named digest and the earlier state file.
    retired = {**deepcopy(site_notes.SEEDS[0]), 'id': 'old.example-1', 'site': 'old.example', 'approved': None,
               'retired': '2026-09-28'}
    site_notes.NOTES_PATH.write_text(json.dumps([*site_notes.SEEDS, retired]))
    legacy_digest = review_runs.REVIEWS / '20260927-100000.json'
    legacy_digest.parent.mkdir(parents=True, exist_ok=True)
    legacy_digest.write_text(json.dumps({'queue': {'runs': [RUN_A]}, 'decisions': [], 'flags': [], 'proposals': [],
                                         'summary': 'Old review.', 'cost': 0.07}))
    site_notes.write_review_state({'last_start': '2026-09-28T09:00:00', 'next_due': 0, 'running': None,
                                   'failures': 2, 'off': False})
    legacy_state = site_notes.REVIEW_STATE.read_bytes()
    migrate_storage(site_notes.NOTES_PATH.parent)
    first = review_runs.prepare_batch()
    apply_batch(first)
    run_store.append_outcome(review_runs.RUNS / f'{RUN_B}.json',
                             {'passed': True, 'by': 'user', 'evidence': 'New label', 'at': 'later'})
    new_note = {'site': 'new.example', 'hint': 'scroll_first', 'detail': 'New note', 'url': None,
                'failure': None, 'runs': {'failed': [], 'recovered': None}}
    site_notes.add_note(new_note)
    batch = review_runs.prepare_batch()
    ensure = review_runs.ensure_digest
    monkeypatch.setattr(review_runs, 'ensure_digest', lambda receipt: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        apply_batch(batch)
    pending_copy = tmp_path / 'pending-export'
    manifest = export_storage('artifacts', pending_copy)
    assert 'site-notes.json' in manifest
    assert site_notes.read_envelope(pending_copy / 'site-notes.json')['pending_review']['batch_id'] == batch['batch_id']
    monkeypatch.setattr(review_runs, 'ensure_digest', ensure)
    with review_runs.review_lock():
        review_runs.recover_pending()
    exported = tmp_path / 'recovered-export'
    manifest = export_storage('artifacts', exported)
    for name, expected in manifest.items():
        source = Path('artifacts') / name
        assert source.read_bytes() == (exported / name).read_bytes()
        assert __import__('hashlib').sha256((exported / name).read_bytes()).hexdigest() == expected
    assert len(review_records.committed(exported / 'reviews')) == 2
    notes = {note['id']: note for note in site_notes.load(exported / 'site-notes.json')[0]}
    assert any(note['site'] == 'new.example' for note in notes.values())
    assert notes['old.example-1']['retired'] == '2026-09-28'  # migration kept the retirement
    assert len(json.loads((exported / 'runs' / f'{RUN_B}.json').read_text())['outcome']) == 2
    assert (exported / 'reviews' / legacy_digest.name).read_bytes() == legacy_digest.read_bytes()
    assert (exported / 'reviews' / 'state.json').read_bytes() == site_notes.REVIEW_STATE.read_bytes()
    assert json.loads(legacy_state)['failures'] == 2 == json.loads(site_notes.REVIEW_STATE.read_text())['failures']
    acknowledged = review_records.acknowledged(exported / 'reviews')
    assert set(acknowledged['runs']) == set(first['runs']) | set(batch['runs'])  # every exact version kept


PRIVATE_PREDECESSOR, FIRST_TRY, RECOVERED, UNRELATED = (
    '20261003-090000-0001', '20261003-090100-0002', '20261003-090200-0003', '20261003-100000-0004')
OTHER_FAILED, OTHER_RECOVERED = '20261003-090300-0005', '20261003-090400-0006'


def test_real_pipeline_redacts_every_publication_surface(monkeypatch, capsys, fake_paid):
    """Canaries typed by a selected run, a deferred run and an excluded predecessor never reach any output or file:
    the queue and apply CLI with their membership lines, a deferred note whose ID holds one, a start_at_url URL a
    recovery started at, refusals beside a valid decision, a receipt, recovery, every paid failure message (provider
    error, tools, MCP servers, did not start, crash), the automatic path with nothing eligible, attempts, state and the
    report."""
    from scripts.migrate_review_storage import migrate_storage

    selected, deferred, excluded = 'Selectedcanary', 'Deferredcanary', 'Excludedcanary'
    canaries = (selected, deferred, excluded)
    seeded_site = f'{deferred.lower()}.example'  # a stored note keyed by a site someone typed
    site_notes.NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    site_notes.NOTES_PATH.write_text(json.dumps(site_notes.SEEDS))  # a legacy store, migrated first
    migrate_storage(site_notes.NOTES_PATH.parent)
    site_notes.add_note({'site': seeded_site, 'hint': 'scroll_first', 'detail': None, 'url': None, 'failure': None,
                         'runs': {'failed': [], 'recovered': None}})
    write_run(PRIVATE_PREDECESSOR, goal=f'{excluded} search', history=[{'text': excluded}])
    write_run(FIRST_TRY, previous_run=PRIVATE_PREDECESSOR, goal=f'{selected} {deferred} {excluded}',
              history=[{'text': selected}])
    # The recovery started at a URL holding what only the excluded predecessor typed.
    write_run(RECOVERED, previous_run=FIRST_TRY, goal=f'{selected} again', history=[{'text': selected}],
              call={'url': f'https://example.com/u/{excluded}'}, result={'status': 'done', 'notes': []},
              outcome=[{'passed': True, 'by': 'user', 'evidence': 'Verified', 'at': '2026-10-03T11:00:00'}])
    other = {'url': 'https://example.org/', 'title': 'Other'}
    write_run(OTHER_FAILED, page=other, history=[{'text': selected}])
    write_run(OTHER_RECOVERED, page=other, previous_run=OTHER_FAILED, result={'status': 'done', 'notes': []},
              outcome=[{'passed': True, 'by': 'user', 'evidence': 'Verified', 'at': '2026-10-03T11:00:00'}])
    write_run(UNRELATED, history=[{'text': deferred}])
    site_notes.EXCLUDE_PATH.write_text(PRIVATE_PREDECESSOR)
    monkeypatch.setattr(review_runs, 'MAX_BATCH_RUNS', 4)
    monkeypatch.setattr(review_runs, 'MAX_BATCH_NOTES', 0)  # every note waits, the seeded one included
    outputs = []

    def drain():
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)
        return outputs[-1]

    assert review_runs.main(['queue']) == 0
    queued = drain()
    batch = review_runs.load_batch(batch_id_of(queued))
    assert set(batch['runs']) == {FIRST_TRY, RECOVERED, OTHER_FAILED, OTHER_RECOVERED}
    assert {'kind': 'runs', 'id': UNRELATED, 'reason': 'item_cap'} in batch['deferred']
    assert f'deferred: note <value>.example-1 ({review_runs.DEFERRED_REASONS["item_cap"]})' in queued
    # A schema refusal whose key is a canary is refused without quoting it.
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({**EMPTY_REPLY, deferred: 'unexpected'})))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    assert 'unknown key <value>' in drain()
    # Two refusals beside a valid decision; the digest then fails once, so the receipt keeps all three.
    reply = {**EMPTY_REPLY, 'summary': ' '.join(canaries), 'decisions': [
        add_decision(RECOVERED, hint='start_at_url', detail=''),
        add_decision(OTHER_RECOVERED, detail=f'Type {selected} first.'), add_decision(OTHER_RECOVERED)]}
    real_publish, fired = review_runs.store_io.publish, []

    def fail_digest_once(target, value, **options):
        if options.get('immutable') and Path(target).parent == review_runs.REVIEWS and not fired:
            fired.append(target)
            raise OSError(f'{excluded} disk full')
        return real_publish(target, value, **options)

    monkeypatch.setattr(review_runs.store_io, 'publish', fail_digest_once)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(reply)))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    assert 'decisions are committed' in drain()
    receipt_text = site_notes.NOTES_PATH.read_text()
    assert 'its detail holds a value from a task' in receipt_text
    assert review_runs.main(['recover']) == 0
    drain()
    digest = review_records.read(review_runs.committed_path(batch['batch_id']), 'digest')
    assert [decision['applied'] for decision in digest['decisions']] == [False, False, True]
    assert site_notes.VALUE_REFUSAL in digest['decisions'][0]['outcome']
    assert not [note for note in site_notes.load()[0] if note['runs'].get('recovered') == RECOVERED]
    # Each paid failure path, its message built from canaries; a correction requeues the first try each time.
    fake = review_runs.launch

    def provider_error(text, budget, quote=str, **callbacks):
        init, result, _ = fake(text, budget, quote, **callbacks)
        result.update(subtype=selected, result=f'{deferred} {excluded}')
        return init, result, None

    def start_failure_with(tools, servers):
        def start_failure(text, budget, quote=str, *, before_spawn=None, on_spawn=None, on_exit=None):
            fake_paid.append((text, budget))
            process = SimpleNamespace(pid=12345)
            before_spawn()
            on_spawn(process)
            on_exit(process)
            init = {'type': 'system', 'subtype': 'init', 'tools': tools, 'mcp_servers': servers}
            return init, None, review_runs.start_failure(init, quote)
        return start_failure

    def crash(*args, **kwargs):
        raise RuntimeError(f'{excluded} crashed the review')

    paths = [('provider', provider_error), ('tools', start_failure_with([selected], [])),
             ('servers', start_failure_with([review_runs.STRUCTURED_OUTPUT_TOOL], [{'name': deferred}])),
             ('crash', crash)]
    for number, (name, launcher) in enumerate(paths, 1):
        path = review_runs.RUNS / f'{FIRST_TRY}.json'
        value = json.loads(path.read_text())
        value['outcome'][0]['at'] = f'2026-10-03T12:00:0{number}'
        path.write_text(json.dumps(value))
        monkeypatch.setattr(review_runs, 'launch', launcher)
        assert review_runs.once_command(None) == 1
        drain()
    # The real launch, whose Popen fails with a message naming a canary.
    monkeypatch.setattr(review_runs, 'launch', REAL_LAUNCH)
    monkeypatch.setattr(review_runs.shutil, 'which', lambda name: '/usr/local/bin/claude')
    monkeypatch.setattr(review_runs.subprocess, 'Popen', lambda *args, **kwargs: (_ for _ in ()).throw(
        OSError(f'{deferred} is not executable')))
    path = review_runs.RUNS / f'{FIRST_TRY}.json'
    value = json.loads(path.read_text())
    value['outcome'][0]['at'] = '2026-10-03T12:00:09'
    path.write_text(json.dumps(value))
    assert review_runs.once_command(None) == 1
    drain()
    # The automatic path, turned on again a day later: too little waits, so it lists the batch it would send and
    # what it defers.
    assert review_runs.main(['enable']) == 0
    site_notes.write_review_state({**review_runs.read_state(), 'next_due': 0})
    assert review_runs.auto_command() == 0
    automatic = drain()
    assert 'nothing eligible for a paid review' in automatic and 'deferred: note <value>.example-1' in automatic
    report_runs.main(['--runs', str(review_runs.RUNS), '--artifacts', str(review_runs.RUNS.parent)])
    report = capsys.readouterr()
    assert 'deferred to a later batch:' in report.out
    assert f'1 run {review_runs.DEFERRED_REASONS["item_cap"]}' in report.out
    # The seeded note is the test's own input: the notes store and the batch records hold its ID by design, and the
    # report lists stored notes. Every other surface is checked unmasked: the reviewer-text block that holds each
    # batch's members, every digest, attempt and state file, and every CLI and paid-path output.
    listing = [line for line in report.out.splitlines() if line.lstrip().startswith(f'{seeded_site}-1')]
    assert listing  # the report lists the stored note; every other report line is checked unmasked
    rest = '\n'.join(line for line in report.out.splitlines() if line not in listing)
    batches = list((review_runs.REVIEWS / 'batches').glob('*.json'))
    by_design = receipt_text + ''.join(path.read_text() for path in [site_notes.NOTES_PATH, *batches]) + '\n'.join(
        listing)
    others = [site_notes.REVIEW_STATE, *(path for path in review_runs.REVIEWS.rglob('*.json') if path not in batches)]
    unmasked = ''.join(outputs) + rest + report.err + ''.join(path.read_text() for path in others if path.exists())
    everything = unmasked + re.sub(re.escape(seeded_site), '<site>', by_design, flags=re.I)
    assert seeded_site not in unmasked.lower()
    assert not any(canary.lower() in everything.lower() for canary in canaries)
    for wording in ('the review ended with <value>: <value> <value>', 'the session has tools beyond StructuredOutput',
                    "the session has MCP servers: [{'name': '<value>'}]", 'the review crashed: <value>',
                    'claude did not start: <value>', 'its detail holds a value from'):
        assert wording in everything, wording


import io  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

LEGACY_START = '2026-09-27T09:00:00'


def test_legacy_running_settles_once_and_only_under_the_review_lock(fake_paid, monkeypatch, capsys):
    for number in range(review_runs.REVIEW_QUEUE):
        write_run(f'20261003-100000-{number:04x}')
    site_notes.write_review_state({'last_start': LEGACY_START, 'next_due': 0, 'running': LEGACY_START,
                                   'failures': 0, 'off': False})
    monkeypatch.setattr(review_runs, 'SHORT_LOCK_SECONDS', 0.1)
    release, thread = hold_review_lock(10)  # that version held this lock for its whole review: maybe alive
    assert review_runs.auto_command() == 0
    assert review_runs.BUSY in capsys.readouterr().out and fake_paid == []
    assert site_notes.read_review_state()['running'] == LEGACY_START
    release.set()
    thread.join(5)
    assert review_runs.auto_command() == 0
    assert capsys.readouterr().out.count('never recorded its end: it counts as a failure') == 1
    assert len(fake_paid) == 1
    state = review_runs.read_state()
    assert state['running'] is None and len(state['accounted_attempt_ids']) == 1


def unverifiable_attempt():
    write_run()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', review_runs.prepare_batch(), time.time())
    claim['status'] = 'spawning'  # spawning may have succeeded before its child was recorded
    review_runs.save_attempt(claim)
    return claim


def test_resolve_settles_an_unverifiable_attempt_only_after_terminal_confirmation(fake_paid, monkeypatch, capsys):
    claim = unverifiable_attempt()
    assert review_runs.once_command(None) == 1 and fake_paid == []
    assert f"{review_runs.RESOLVE_COMMAND} {claim['attempt_id']}" in capsys.readouterr().out
    monkeypatch.setattr(review_runs, 'open_terminal', lambda: io.StringIO('no\n'))
    assert review_runs.main(['resolve', claim['attempt_id']]) == 1
    assert attempts() == [claim] and review_runs.read_state()['accounted_attempt_ids'] == []
    monkeypatch.setattr(review_runs, 'open_terminal', lambda: io.StringIO('yes\n'))
    assert review_runs.main(['resolve', claim['attempt_id']]) == 0
    [settled] = attempts()
    assert settled['status'] == 'abandoned' and settled['child'] == {'exited': True}
    state = review_runs.read_state()
    assert (state['failures'], state['running'], state['accounted_attempt_ids']) == (1, None, [claim['attempt_id']])
    assert review_runs.main(['resolve', claim['attempt_id']]) == 0  # already settled: counted once
    assert review_runs.read_state()['failures'] == 1
    assert review_runs.once_command(None) == 0 and len(fake_paid) == 1  # the next dispatch is no longer blocked


@pytest.mark.parametrize('liveness', ['leader alive', 'leader gone, group alive', 'group unknown'])
@pytest.mark.parametrize('deadline', ['ahead', 'passed'])
def test_resolve_never_settles_a_verifiably_live_reviewer(fake_paid, monkeypatch, capsys, liveness, deadline):
    """A reviewer or its group verifiably alive is refused without a question; when ps cannot list process groups,
    only the user can say, and resolve asks. It never signals, expired or not."""
    claim = unverifiable_attempt()
    identity = review_runs.process_identity(12345)  # the fake reports this child alive with this identity
    claim.update(status='running', child={'pid': 12345, 'identity': identity, 'exited': False})
    if deadline == 'passed':  # even an expired reviewer is only stopped by the next review, never by resolve
        claim['deadline'] = time.time() - 60
    review_runs.save_attempt(claim)
    if liveness != 'leader alive':
        monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {'state': 'absent'})
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: None if liveness == 'group unknown' else True)
    asked = []
    monkeypatch.setattr(review_runs, 'open_terminal', lambda: asked.append(True) or io.StringIO('no\n'))
    monkeypatch.setattr(review_runs.os, 'killpg', lambda *args: pytest.fail('resolve never signals'))
    assert review_runs.main(['resolve', claim['attempt_id']]) == 1
    out = capsys.readouterr().out
    if liveness == 'group unknown':
        assert asked and 'ps could not list process groups' in out and 'Not resolved.' in out
    else:
        assert not asked and out.startswith('Nothing resolved: its reviewer')
        assert ('process group 12345' in out) is (liveness == 'leader gone, group alive')
    assert attempts() == [claim] and review_runs.read_state()['accounted_attempt_ids'] == []


def test_resolve_checks_everything_again_after_its_confirmation(fake_paid, monkeypatch, capsys):
    """A group that reappears while the user answers is refused on the confirmed pass, never settled."""
    claim = unverifiable_attempt()
    claim.update(status='running', child={'pid': 12345, 'identity': review_runs.process_identity(12345),
                                          'exited': False})
    review_runs.save_attempt(claim)
    group = {'alive': None}
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {'state': 'absent'})
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: group['alive'])

    def answer():
        group['alive'] = True  # meanwhile a process of the review shows up in its group
        return io.StringIO('yes\n')

    monkeypatch.setattr(review_runs, 'open_terminal', answer)
    assert review_runs.main(['resolve', claim['attempt_id']]) == 1
    assert 'Nothing resolved: its reviewer exited, but processes remain' in capsys.readouterr().out
    assert attempts() == [claim] and review_runs.read_state()['accounted_attempt_ids'] == []


@pytest.mark.parametrize('path', ['dispatch', 'resolve', 'resolve, confirmed'])
def test_recording_a_settled_attempts_exit_keeps_its_settled_status(fake_paid, monkeypatch, capsys, path):
    write_run()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', review_runs.prepare_batch(), time.time())
    claim.update(status='uncertain', error='The reply was lost', child={
        'pid': 12345, 'identity': review_runs.process_identity(12345), 'exited': False})
    review_runs.save_attempt(claim)
    with review_runs.review_lock():
        review_runs.settle_attempt(review_runs.read_state(), claim)
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {'state': 'absent'})  # now verifiably ended
    if path == 'dispatch':
        with review_runs.review_lock():
            review_runs.recover_attempts(review_runs.read_state())
    elif path == 'resolve':
        assert review_runs.main(['resolve', claim['attempt_id']]) == 0
        assert 'Recorded the exit' in capsys.readouterr().out
    else:  # ps cannot list process groups: the user confirms, and only the exit is recorded
        monkeypatch.setattr(review_runs, 'group_alive', lambda pid: None)
        monkeypatch.setattr(review_runs, 'open_terminal', lambda: io.StringIO('yes\n'))
        assert review_runs.main(['resolve', claim['attempt_id']]) == 0
        assert 'counts nothing again' in capsys.readouterr().out
    [recorded] = attempts()
    assert recorded['child']['exited'] is True and recorded['status'] == 'uncertain'
    assert recorded['error'] == 'The reply was lost' and review_runs.read_state()['failures'] == 1


@pytest.mark.parametrize('attempt_id', ['not-an-id', 'a' * 32])
def test_resolve_refuses_unknown_attempts(fake_paid, attempt_id, capsys):
    assert review_runs.main(['resolve', attempt_id]) == 1
    assert 'nothing resolved' in capsys.readouterr().out


def pending_receipt():
    envelope = json.loads(site_notes.NOTES_PATH.read_text())
    return envelope['pending_review']


@pytest.mark.parametrize('fault', ['digest write', 'conflicting digest', 'malformed digest'])
def test_failure_after_commit_reports_recovery_pending_never_not_applied(fake_paid, monkeypatch, capsys, fault):
    recovery()
    batch = review_runs.prepare_batch()
    reply = json.dumps({**EMPTY_REPLY, 'decisions': [add_decision()]})
    path = review_runs.committed_path(batch['batch_id'])
    real = review_runs.store_io.publish

    def failing(target, value, **options):
        if options.get('immutable') and Path(target) == path:
            raise OSError('injected digest write failure')  # before publication: a plain OSError
        return real(target, value, **options)

    monkeypatch.setattr(review_runs.store_io, 'publish', failing)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(reply))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    out = capsys.readouterr().out
    assert "decisions are committed" in out and 'could not be applied' not in out
    receipt = pending_receipt()
    assert receipt and receipt['batch_id'] == batch['batch_id'] and not path.exists()
    added = [note for note in site_notes.load()[0] if note['runs'].get('recovered') == RUN_B]
    assert len(added) == 1  # committed exactly once
    if fault != 'digest write':
        monkeypatch.setattr(review_runs.store_io, 'publish', real)
        path.write_text('{"broken": ' if fault == 'malformed digest' else
                        json.dumps({**receipt['digest'], 'summary': 'A different reply'}))
    # Until recovery succeeds, neither another apply nor a paid review runs. The same reply is told it is committed;
    # any other reply, that nothing of it was applied.
    monkeypatch.setattr(sys, 'stdin', io.StringIO(reply))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    out = capsys.readouterr().out
    assert "The reply's decisions are committed" in out and 'nothing was applied' not in out
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(EMPTY_REPLY)))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    assert 'nothing was applied' in capsys.readouterr().out
    write_run(RUN_C)
    assert review_runs.once_command(None) == 1 and fake_paid == []
    assert 'pending recovery' in capsys.readouterr().out
    if fault == 'digest write':
        monkeypatch.setattr(review_runs.store_io, 'publish', real)
        assert review_runs.main(['recover']) == 0
        assert pending_receipt() is None and review_records.read(path, 'digest') == receipt['digest']
        monkeypatch.setattr(sys, 'stdin', io.StringIO(reply))
        assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 0  # same reply: its recorded result
        assert len([note for note in site_notes.load()[0] if note['runs'].get('recovered') == RUN_B]) == 1
    else:
        assert review_runs.main(['recover']) == 1
        assert 'receipt is retained' in capsys.readouterr().out and pending_receipt() == receipt


def test_queue_shows_input_membership_and_deferred_items(monkeypatch, capsys):
    write_run(RUN_A, history=[{'step': number, 'action': '巨大' * 100, 'operation': 'CLICK'} for number in range(100)])
    write_run(RUN_B)
    monkeypatch.setattr(review_runs, 'MAX_BATCH_BYTES', 1500)
    assert review_runs.main(['queue']) == 0
    err = capsys.readouterr().err
    batch = review_runs.load_batch(batch_id_of(err))
    assert f"input: run {RUN_B} @{batch['runs'][RUN_B][:8]}" in err.splitlines()
    assert f"deferred: run {RUN_A} (over the batch's byte limit)" in err.splitlines()
    assert 'Nothing' not in err


def test_queue_holding_only_oversized_items_says_so(monkeypatch, capsys):
    path, problems = apply_batch(review_runs.prepare_batch())  # the seed notes, reviewed before
    assert path.exists() and not problems
    write_run(RUN_A, history=[{'step': number, 'action': '巨大' * 100, 'operation': 'CLICK'} for number in range(100)])
    monkeypatch.setattr(review_runs, 'MAX_BATCH_BYTES', 1500)
    assert review_runs.main(['queue']) == 0
    output = capsys.readouterr()
    assert output.out == ''
    assert f"deferred: run {RUN_A} (over the batch's byte limit)" in output.err.splitlines()
    assert 'Nothing fits a batch; the deferred items need a manual look.' in output.err
    assert 'Nothing is queued.' not in output.err


def test_attempt_error_must_be_text(fake_paid):
    write_run()
    attempt = review_runs.claim_attempt(review_runs.read_state(), 'once', review_runs.prepare_batch(), time.time())
    with pytest.raises(review_records.RecordError):
        review_runs.save_attempt({**attempt, 'error': {'raw': 'provider object'}})
    path = review_runs.attempt_path(attempt['attempt_id'])
    path.write_text(json.dumps({**attempt, 'error': 123}))
    with pytest.raises(review_records.RecordError):
        review_records.read(path, 'attempt')


def test_pending_receipt_must_match_its_digest(monkeypatch, capsys):
    recovery()
    batch = review_runs.prepare_batch()
    real = review_runs.store_io.publish
    monkeypatch.setattr(review_runs.store_io, 'publish', lambda target, value, **options: (
        (_ for _ in ()).throw(OSError('injected')) if options.get('immutable') else real(target, value, **options)))
    with pytest.raises(review_runs.RecoveryPending):
        apply_batch(batch, {**EMPTY_REPLY, 'decisions': [add_decision()]})
    envelope = json.loads(site_notes.NOTES_PATH.read_text())
    envelope['pending_review']['batch_id'] = 'f' * 32  # no longer the batch its digest records
    site_notes.NOTES_PATH.write_text(json.dumps(envelope))
    with pytest.raises(site_notes.NotesStoreError):
        site_notes.read_envelope(site_notes.NOTES_PATH)
    monkeypatch.setattr(review_runs.store_io, 'publish', real)
    assert review_runs.main(['recover']) == 1 and 'receipt is retained' in capsys.readouterr().out
    assert json.loads(site_notes.NOTES_PATH.read_text()) == envelope  # nothing rewrote the evidence


def test_naive_stored_times_are_read_as_local_times(monkeypatch):
    """Stored times carry no zone and are written with datetime.now(): read them as local, not UTC."""
    monkeypatch.setenv('TZ', 'Asia/Taipei')
    time.tzset()
    try:
        moment = 1_790_000_000
        stored = datetime.fromtimestamp(moment).isoformat()
        assert review_records.timestamp(stored) == moment
        assert review_records.timestamp(datetime.fromtimestamp(moment, timezone.utc).isoformat()) == moment
    finally:
        monkeypatch.undo()
        time.tzset()


import os  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402

from jev_ultrafast import review_processes  # noqa: E402


def test_review_process_identity_is_precise_and_fails_closed():
    current = review_processes.process_identity(os.getpid())
    assert current == {'state': 'present', 'pid': os.getpid(), 'birth': current['birth'], 'uid': os.getuid(),
                       'pgid': os.getpgid(0)}
    assert current['birth'] and review_processes.process_identity(os.getpid()) == current
    for pid in (0, 1, -5, '123', True, None):
        assert review_processes.process_identity(pid) == {'state': 'unknown'}
    child = subprocess.Popen(['node', '-e', 'setTimeout(()=>{}, 2000)'])  # the test guard allows node only
    try:
        alive = review_processes.process_identity(child.pid)
        assert alive['state'] == 'present' and alive['pid'] == child.pid and alive['birth'] != current['birth']
    finally:
        child.kill()
        child.wait(5)
    assert review_processes.process_identity(child.pid) in ({'state': 'absent'}, {'state': 'unknown'}) or (
        review_processes.process_identity(child.pid)['birth'] != alive['birth'])  # gone, or a different process


def test_review_signals_are_guarded_by_reaping_and_birth_identity(monkeypatch):
    signals = []
    monkeypatch.setattr(review_runs.os, 'killpg', lambda pgid, sig: signals.append((pgid, sig)))
    identity = {'state': 'present', 'pid': 4321, 'birth': '100:123', 'uid': os.getuid(), 'pgid': 4321}
    process = SimpleNamespace(pid=4321, _review_identity=identity, _review_signal_lock=threading.RLock(),
                              _review_reaped=False)
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: dict(identity))
    assert review_runs.kill_group(process) is True and signals == [(4321, signal.SIGTERM)]
    process._review_reaped = True  # reaped: its PID may already belong to another process
    assert review_runs.kill_group(process, signal.SIGKILL) is False
    process._review_reaped = False
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {**identity, 'birth': '200:1'})  # reused PID
    assert review_runs.kill_group(process, signal.SIGKILL) is False
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: dict(identity))
    process._review_identity = {**identity, 'pgid': 99}  # not the leader of its own group
    assert review_runs.kill_group(process, signal.SIGKILL) is False
    assert signals == [(4321, signal.SIGTERM)]


@pytest.mark.parametrize('reused', [False, True])
def test_expired_child_is_signalled_only_after_identity_checks(fake_paid, monkeypatch, reused):
    write_run()
    started = time.time() - review_runs.REVIEW_TIMEOUT_MINUTES * 60 - 60  # its deadline has passed
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', review_runs.prepare_batch(), started)
    identity = {'state': 'present', 'pid': 12345, 'birth': '100:123', 'uid': os.getuid(), 'pgid': 12345}
    claim.update(status='running', child={'pid': 12345, 'identity': identity, 'exited': False})
    review_runs.save_attempt(claim)
    signals, alive = [], {'value': True}

    def identity_now(pid):
        if reused:
            return {**identity, 'birth': '999:1'}
        return dict(identity) if alive['value'] else {'state': 'absent'}

    def killpg(pgid, sig):
        signals.append((pgid, sig))
        alive['value'] = False

    monkeypatch.setattr(review_runs, 'process_identity', identity_now)
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: alive['value'])
    monkeypatch.setattr(review_runs.os, 'killpg', killpg)
    result = review_runs.once_command(None)
    if reused:
        assert (result, signals, fake_paid) == (1, [], [])  # a reused PID is never signalled; dispatch waits
    else:
        assert signals == [(12345, signal.SIGTERM)] and result == 0 and len(fake_paid) == 1
        old = next(item for item in attempts() if item['attempt_id'] == claim['attempt_id'])
        assert old['status'] == 'abandoned' and old['child']['exited'] is True


def test_auto_counts_runs_deferred_by_the_byte_cap(fake_paid, monkeypatch, capsys):
    big = [{'step': number, 'action': '巨大' * 100, 'operation': 'CLICK'} for number in range(100)]
    deferred = {f'20261003-100000-{number:04x}' for number in range(3)}
    for number in range(review_runs.REVIEW_QUEUE):
        write_run(f'20261003-100000-{number:04x}', history=big if number < 3 else [])
    monkeypatch.setattr(review_runs, 'MAX_BATCH_BYTES', 1500)
    review_runs.auto_command()
    assert len(fake_paid) == 1  # five runs wait, although only two fit the batch
    out = capsys.readouterr().out  # a launched review lists what it sent and what it deferred, as queue does
    for key in deferred:
        assert f'deferred: run {key} ({review_runs.DEFERRED_REASONS["byte_cap"]})' in out
    assert out.count('input: run ') == 2
    [attempt] = attempts()
    assert not deferred & {item['id'] for item in attempt['input_items']}
    assert deferred <= set(review_runs.build_queue()['runs'])  # deferred runs stay queued, unacknowledged


def test_three_failed_reviews_in_a_row_turn_automatic_reviews_off(fake_paid, monkeypatch, capsys):
    succeeding = review_runs.launch

    def no_result(text, budget, quote=str, *, before_spawn=None, on_spawn=None, on_exit=None):
        fake_paid.append((text, budget))
        process = SimpleNamespace(pid=12345)
        before_spawn()
        on_spawn(process)
        on_exit(process)
        return {}, None, 'the stream ended with no result'

    monkeypatch.setattr(review_runs, 'launch', no_result)
    for number in range(review_runs.REVIEW_QUEUE):
        write_run(f'20261003-100000-{number:04x}')
    for failures in range(1, review_runs.REVIEW_MAX_FAILURES + 1):
        state = review_runs.read_state()
        site_notes.write_review_state({**state, 'next_due': 0})  # a day later
        assert review_runs.auto_command() == 1
        state = review_runs.read_state()
        assert (state['failures'], state.get('off', False)) == (failures, failures == review_runs.REVIEW_MAX_FAILURES)
    site_notes.write_review_state({**review_runs.read_state(), 'next_due': 0})
    assert review_runs.auto_command() == 0 and len(fake_paid) == review_runs.REVIEW_MAX_FAILURES
    assert 'automatic reviews are off' in capsys.readouterr().out
    assert review_runs.main(['enable']) == 0
    state = review_runs.read_state()
    assert (state['failures'], state['off']) == (0, False) and len(state['accounted_attempt_ids']) == 3
    monkeypatch.setattr(review_runs, 'launch', succeeding)
    assert review_runs.auto_command() == 0
    assert len(fake_paid) == review_runs.REVIEW_MAX_FAILURES + 1  # automatic reviews run again after enable
    assert review_runs.read_state()['failures'] == 0


@pytest.mark.parametrize('boundary', ['after the replace', 'directory fsync'])
def test_uncertain_notes_publication_is_reported_through_the_cli(fake_paid, monkeypatch, capsys, boundary):
    """The notes replace happens, then publication fails: apply says the decisions may be committed, never that the
    reply could not be applied, and recovery then settles them once."""
    recovery()
    batch = review_runs.prepare_batch()
    original, fsync, fired = store_io.publish, store_io.fsync_directory, []

    def publish(path, value, **options):
        result = original(path, value, **options)
        if (boundary == 'after the replace' and not fired and Path(path).name == site_notes.NOTES_PATH.name
                and value.get('pending_review')):
            fired.append(path)
            raise store_io.PublicationUncertain('injected after the replace')
        return result

    def sync(directory):
        if boundary == 'directory fsync' and not fired and Path(directory).name == site_notes.NOTES_PATH.parent.name:
            fired.append(directory)
            raise OSError('injected directory fsync')
        return fsync(directory)

    monkeypatch.setattr(store_io, 'publish', publish)
    monkeypatch.setattr(store_io, 'fsync_directory', sync)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({**EMPTY_REPLY, 'decisions': [add_decision()]})))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    out = capsys.readouterr().out
    assert fired and 'Publication is uncertain' in out and 'Decisions may already be committed' in out
    assert 'could not be applied' not in out and pending_receipt()['batch_id'] == batch['batch_id']
    monkeypatch.setattr(store_io, 'publish', original)
    monkeypatch.setattr(store_io, 'fsync_directory', fsync)
    assert review_runs.main(['recover']) == 0
    assert sum(note['runs'].get('recovered') == RUN_B for note in site_notes.load()[0]) == 1


def test_an_unreadable_notes_file_after_the_commit_reports_recovery_pending(fake_paid, monkeypatch, capsys):
    """Notes and receipt are committed; reading the notes again then fails: committed, pending recovery."""
    recovery()
    batch = review_runs.prepare_batch()
    real_read, commits = site_notes.read_envelope, []
    real_publish = store_io.publish

    def publish(path, value, **options):
        if Path(path).name == site_notes.NOTES_PATH.name and value.get('pending_review'):
            commits.append(path)
        return real_publish(path, value, **options)

    def read_envelope(path, *args, **kwargs):
        if commits:
            raise site_notes.NotesStoreError('injected EIO reading the notes file')
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(store_io, 'publish', publish)
    monkeypatch.setattr(site_notes, 'read_envelope', read_envelope)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({**EMPTY_REPLY, 'decisions': [add_decision()]})))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    out = capsys.readouterr().out
    assert commits and "The reply's decisions are committed" in out and 'could not be applied' not in out
    monkeypatch.setattr(site_notes, 'read_envelope', real_read)
    assert pending_receipt()['batch_id'] == batch['batch_id']
    assert review_runs.main(['recover']) == 0


def test_apply_reports_a_held_lock_and_a_conflicting_reply_as_such(fake_paid, monkeypatch, capsys):
    recovery()
    batch = review_runs.prepare_batch()
    release, thread = hold_review_lock(10)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(EMPTY_REPLY)))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    assert review_runs.BUSY in capsys.readouterr().out
    release.set()
    thread.join(5)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(EMPTY_REPLY)))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 0
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({**EMPTY_REPLY, 'summary': 'Another reply'})))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    out = capsys.readouterr().out
    assert 'A different reply is already committed for this batch' in out and 'recover' not in out


@pytest.mark.parametrize('where', ['its own final section', 'a later recovery'])
def test_committed_evidence_makes_an_unfinished_paid_attempt_a_success(fake_paid, monkeypatch, where):
    write_run()
    if where == 'its own final section':
        real_apply = review_runs._apply_batch

        def commit_then_crash(batch, reply, cost=None, attempt_id=None):
            real_apply(batch, reply, cost, attempt_id)
            raise RuntimeError('crashed after the commit point')

        monkeypatch.setattr(review_runs, '_apply_batch', commit_then_crash)
        assert review_runs.once_command(None) == 0
    else:  # the process died after the commit, before its final section
        batch = review_runs.prepare_batch()
        claim = review_runs.claim_attempt(review_runs.read_state(), 'once', batch, time.time())
        claim.update(status='returned', cost=0.0123, child={
            'pid': 12345, 'identity': review_runs.process_identity(12345), 'exited': True})
        review_runs.save_attempt(claim)
        with review_runs.review_lock():
            review_runs._apply_batch(batch, EMPTY_REPLY, 0.0123, claim['attempt_id'])
            review_runs.recover_attempts(review_runs.read_state())
    [attempt] = attempts()
    state = review_runs.read_state()
    assert attempt['status'] == 'succeeded' and attempt['cost'] == 0.0123
    assert state.get('failures', 0) == 0 and state['accounted_attempt_ids'] == [attempt['attempt_id']]


def test_settling_an_attempt_again_counts_it_once(fake_paid):
    write_run()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', review_runs.prepare_batch(), time.time())
    claim['status'] = 'abandoned'
    with review_runs.review_lock():
        for state in (review_runs.read_state(), review_runs.read_state()):
            review_runs.settle_attempt(state, claim)
            review_runs.settle_attempt(state, claim)
    state = review_runs.read_state()
    assert state['failures'] == 1 and state['accounted_attempt_ids'] == [claim['attempt_id']]


def test_a_group_left_alive_by_its_leader_blocks_settlement_and_dispatch(fake_paid, monkeypatch, capsys):
    """The leader exits, a process stays in its group: no exit is recorded, nothing settles, no review starts;
    once the group is gone, the attempt settles once and its exit is recorded."""
    write_run()
    identity = review_runs.process_identity(12345)
    leader, group = {'present': True}, {'alive': True}
    monkeypatch.setattr(review_runs, 'process_identity',
                        lambda pid: dict(identity) if leader['present'] else {'state': 'absent'})
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: group['alive'])
    fake = review_runs.launch

    def leader_exits(*args, **kwargs):
        result = fake(*args, **kwargs)
        leader['present'] = False
        return result

    monkeypatch.setattr(review_runs, 'launch', leader_exits)
    assert review_runs.once_command(None) == 1
    assert 'exit is not verified' in capsys.readouterr().out
    [attempt] = attempts()
    assert attempt['child']['exited'] is False and review_runs.read_state()['accounted_attempt_ids'] == []
    write_run(RUN_B)
    assert review_runs.once_command(None) == 1 and len(fake_paid) == 1  # still blocked
    group['alive'] = False
    assert review_runs.once_command(None) == 0 and len(fake_paid) == 2
    settled = next(item for item in attempts() if item['attempt_id'] == attempt['attempt_id'])
    assert settled['child']['exited'] is True and settled['status'] == 'succeeded'
    state = review_runs.read_state()
    assert attempt['attempt_id'] in state['accounted_attempt_ids'] and state.get('failures', 0) == 0


def test_an_exit_verified_after_on_exit_is_recorded_so_it_never_blocks_later(fake_paid, monkeypatch):
    """on_exit still sees the group; the final section verifies its end: the attempt records the exit, so a reused
    PID or a failing ps later blocks nothing."""
    write_run()
    group = {'alive': True}
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: group['alive'])
    fake = review_runs.launch

    def group_ends_after_on_exit(*args, **kwargs):
        result = fake(*args, **kwargs)
        group['alive'] = False
        return result

    monkeypatch.setattr(review_runs, 'launch', group_ends_after_on_exit)
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {'state': 'absent'} if not group['alive'] else {
        'state': 'present', 'pid': pid, 'birth': '100:123', 'uid': os.getuid(), 'pgid': pid})
    assert review_runs.once_command(None) == 0
    [attempt] = attempts()
    assert attempt['child']['exited'] is True and attempt['status'] == 'succeeded'
    # Later its PID belongs to another process and ps fails: the recorded exit is enough, nothing blocks.
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {
        'state': 'present', 'pid': pid, 'birth': '999:1', 'uid': os.getuid(), 'pgid': pid})
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: None)
    with review_runs.review_lock():
        review_runs.recover_attempts(review_runs.read_state())


def test_resolve_records_the_exit_of_a_settled_attempt_without_counting_it_again(fake_paid, monkeypatch, capsys):
    write_run()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', review_runs.prepare_batch(), time.time())
    identity = review_runs.process_identity(12345)
    claim.update(status='failed', child={'pid': 12345, 'identity': identity, 'exited': False})
    review_runs.save_attempt(claim)
    with review_runs.review_lock():
        state = review_runs.read_state()
        review_runs.settle_attempt(state, claim)  # settled, its exit never recorded
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {**identity, 'birth': '999:1'})  # reused
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: None)  # and ps fails
    assert review_runs.once_command(None) == 1 and fake_paid == []
    assert f"{review_runs.RESOLVE_COMMAND} {claim['attempt_id']}" in capsys.readouterr().out
    monkeypatch.setattr(review_runs, 'open_terminal', lambda: io.StringIO('yes\n'))
    monkeypatch.setattr(review_runs.os, 'killpg', lambda *args: pytest.fail('resolve never signals'))
    assert review_runs.main(['resolve', claim['attempt_id']]) == 0
    [resolved] = attempts()
    assert resolved['status'] == 'failed' and resolved['child']['exited'] is True and resolved['child']['pid'] == 12345
    assert review_runs.read_state()['failures'] == 1
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {'state': 'absent'})  # the next child exits
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: False)
    assert review_runs.once_command(None) == 0 and len(fake_paid) == 1  # no longer blocked


def test_resolve_publishes_a_pending_receipt_first_so_committed_evidence_wins(fake_paid, monkeypatch, capsys):
    recovery()
    batch = review_runs.prepare_batch()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', batch, time.time())
    claim['status'] = 'spawning'  # its child was never recorded
    review_runs.save_attempt(claim)
    real_publish, fired = store_io.publish, []

    def fail_digest_once(target, value, **options):
        if options.get('immutable') and Path(target).parent == review_runs.REVIEWS and not fired:
            fired.append(target)
            raise OSError('injected digest write failure')
        return real_publish(target, value, **options)

    monkeypatch.setattr(store_io, 'publish', fail_digest_once)
    with review_runs.review_lock(), pytest.raises(review_runs.RecoveryPending):
        review_runs._apply_batch(batch, EMPTY_REPLY, 0.0123, claim['attempt_id'])
    assert pending_receipt()['batch_id'] == batch['batch_id']
    monkeypatch.setattr(review_runs, 'open_terminal', lambda: pytest.fail('committed evidence needs no confirmation'))
    claim['status'] = 'running'
    claim['child'] = {'pid': 12345, 'identity': review_runs.process_identity(12345), 'exited': True}
    review_runs.save_attempt(claim)
    assert review_runs.main(['resolve', claim['attempt_id']]) == 0
    assert pending_receipt() is None
    [resolved] = attempts()
    assert resolved['status'] == 'succeeded' and review_runs.read_state().get('failures', 0) == 0


def test_an_expired_reviewer_is_stopped_without_the_reviews_lock_and_never_after_its_pid_is_reused(
        fake_paid, monkeypatch):
    write_run()
    started = time.time() - review_runs.REVIEW_TIMEOUT_MINUTES * 60 - 60
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', review_runs.prepare_batch(), started)
    identity = {'state': 'present', 'pid': 12345, 'birth': '100:123', 'uid': os.getuid(), 'pgid': 12345}
    claim.update(status='running', child={'pid': 12345, 'identity': identity, 'exited': False})
    review_runs.save_attempt(claim)
    monkeypatch.setattr(review_runs, 'EXIT_SECONDS', 0.1)
    signals, term = [], {}

    def identity_now(pid):  # it ignores SIGTERM; its PID is reused just before SIGKILL would be sent
        if 'at' in term and time.monotonic() - term['at'] >= review_runs.EXIT_SECONDS:
            return {**identity, 'birth': '999:1'}
        return dict(identity)

    def killpg(pgid, sig):
        signals.append(sig)
        term.setdefault('at', time.monotonic())
        assert review_runs.take_lock() is not None  # the reviews' lock is free while a child is stopped

    monkeypatch.setattr(review_runs, 'process_identity', identity_now)
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: True)
    monkeypatch.setattr(review_runs.os, 'killpg', killpg)
    assert review_runs.once_command(None) == 1 and fake_paid == []
    assert signals == [signal.SIGTERM]  # never a SIGKILL to the reused PID


def test_a_clip_that_ends_a_longer_word_right_after_a_value_is_quoted_again():
    """The value check runs before a cut too: x…x Selectedcanaryzz passes it, and its cut ends Selectedcanary…"""
    quote = review_runs.privacy_quote({'values': {'selectedcanary'}, 'names': set(), 'run_ids': set()})
    before = 'x' * (review_runs.LABEL_CHARACTERS - len('Selectedcanary') - 2) + ' '
    text = before + 'Selectedcanaryzz and more'
    assert quote(text) == text  # whole, the word is not the value
    messages = [
        review_runs.result_failure({'subtype': text, 'result': text}, quote),
        *review_runs.schema_errors({text: 'x'}, review_runs.REVIEW_SCHEMA, quote=quote),
        # Its servers print as a list, so ['x…x Selectedcanaryzz…'] is cut at TEXT_CHARACTERS.
        review_runs.start_failure({'type': 'system', 'subtype': 'init', 'tools': [], 'mcp_servers': [
            'x' * (review_runs.TEXT_CHARACTERS - len('Selectedcanary') - 4) + ' Selectedcanaryzz and more']}, quote),
    ]
    for message in messages:
        assert 'canary' not in message.lower(), message
    notes = [{'id': 'example.com-1', 'approved': None}]
    with pytest.raises(review_runs.DecisionRefused) as refused:
        review_runs.unapproved(notes, text)
    assert 'canary' not in str(refused.value).lower()
    with pytest.raises(review_runs.DecisionRefused, match='no note example.com-9$'):
        review_runs.unapproved(notes, 'example.com-9')


def test_a_stored_time_no_reader_can_convert_is_invalid(fake_paid, capsys):
    for value in ('0001-01-01T00:00:00', 'not a time', None, 5):
        assert not review_records.valid_time(value)
    assert review_records.valid_time('2026-10-03T10:00:00') and review_records.valid_time('0001-01-01T00:00:00+00:00')
    site_notes.write_review_state({'last_start': '0001-01-01T00:00:00', 'next_due': 0})
    with pytest.raises(review_records.RecordError):
        review_runs.read_state()
    assert review_runs.once_command(None) == 1 and fake_paid == []
    assert 'Traceback' not in capsys.readouterr().out


def test_a_failed_exit_record_keeps_the_reply_and_its_cost(monkeypatch):
    """The real launch() with a fake child: a failure to record its exit never replaces the result it returned."""
    class Child:
        pid = 4321

        def __init__(self, *args, **kwargs):
            init = {'type': 'system', 'subtype': 'init', 'tools': [review_runs.STRUCTURED_OUTPUT_TOOL],
                    'mcp_servers': []}
            result = {'type': 'result', 'subtype': 'success', 'structured_output': EMPTY_REPLY,
                      'total_cost_usd': 0.0456}
            self.stdout = io.StringIO(json.dumps(init) + '\n' + json.dumps(result) + '\n')

        def wait(self, timeout=None):
            return 0

    def on_exit(process):
        raise OSError('disk full while recording the exit')

    monkeypatch.setattr(review_runs.shutil, 'which', lambda name: '/usr/local/bin/claude')
    monkeypatch.setattr(review_runs.subprocess, 'Popen', Child)
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {
        'state': 'present', 'pid': pid, 'birth': '100:123', 'uid': os.getuid(), 'pgid': pid})
    init, result, failure = REAL_LAUNCH('text', 0.5, on_exit=on_exit)
    assert failure is None and result['total_cost_usd'] == 0.0456 and init['subtype'] == 'init'


@pytest.mark.parametrize('running', [5, ['x'], {'attempt': 'x'}])
def test_a_running_value_that_is_neither_an_attempt_nor_a_time_stops_dispatch_clearly(fake_paid, capsys, running):
    site_notes.write_review_state({'running': running, 'next_due': 0})
    with pytest.raises(review_records.RecordError):
        review_runs.read_state()
    assert review_runs.once_command(None) == 1 and fake_paid == []
    assert 'resolve' not in capsys.readouterr().out  # no attempt ID that resolve could never match


LINKED_FAILED, LINKED_RECOVERED, OTHER_SITE = '20261003-080100-0011', '20261003-080200-0012', '20261003-110000-0013'


@pytest.mark.parametrize('case', ['a value only another queued run typed', 'an excluded run in its chain'])
def test_a_review_lesson_is_checked_as_the_server_checks_one(monkeypatch, capsys, case):
    """Each half of the check alone: the URL against the batch's privacy closure, and the whole chain with its
    excluded runs."""
    canary = 'Linkedcanary'
    if case == 'an excluded run in its chain':
        write_run(PRIVATE_PREDECESSOR, history=[{'text': 'anything'}])
        site_notes.EXCLUDE_PATH.parent.mkdir(parents=True, exist_ok=True)
        site_notes.EXCLUDE_PATH.write_text(PRIVATE_PREDECESSOR)
    write_run(LINKED_FAILED, previous_run=PRIVATE_PREDECESSOR if case == 'an excluded run in its chain' else None)
    start = 'https://example.com/start' if case == 'an excluded run in its chain' else f'https://example.com/u/{canary}'
    write_run(LINKED_RECOVERED, previous_run=LINKED_FAILED, call={'url': start},
              result={'status': 'done', 'notes': []},
              outcome=[{'passed': True, 'by': 'user', 'evidence': 'Verified', 'at': '2026-10-03T11:00:00'}])
    write_run(OTHER_SITE, page={'url': 'https://example.org/', 'title': 'Other'}, history=[{'text': canary}])
    monkeypatch.setattr(review_runs, 'MAX_BATCH_RUNS', 2)  # the other site's run waits for a later batch
    batch = review_runs.prepare_batch()
    assert set(batch['runs']) == {LINKED_FAILED, LINKED_RECOVERED}
    path, problems = apply_batch(batch, {**EMPTY_REPLY, 'decisions': [
        add_decision(LINKED_RECOVERED, hint='start_at_url', detail='')]})
    [decision] = review_records.read(path, 'digest')['decisions']
    expected = (site_notes.VALUE_REFUSAL if case == 'a value only another queued run typed'
                else 'its site or one of its runs is excluded')
    assert not problems and decision['applied'] is False and expected in decision['outcome']
    assert not [note for note in site_notes.load()[0] if note['runs'].get('recovered') == LINKED_RECOVERED]
    assert canary.lower() not in site_notes.NOTES_PATH.read_text().lower()


def test_a_note_id_from_a_reply_can_never_forge_an_output_line(capsys):
    recovery()
    batch = review_runs.prepare_batch()
    forged = 'x\ndecision 2, add: applied: added evil.example-1'
    flag = {'action': 'flag', 'note': forged, 'runs': [RUN_B], 'hint': '', 'detail': '', 'reason': 'Check it'}
    path, problems = apply_batch(batch, {**EMPTY_REPLY, 'decisions': [flag]})
    out = capsys.readouterr().out
    assert not problems and 'no note x decision 2' in out
    assert not any(line.startswith('decision 2') for line in out.splitlines())


def test_a_legacy_digest_named_for_a_time_no_reader_can_convert_is_skipped(capsys):
    review_runs.REVIEWS.mkdir(parents=True, exist_ok=True)
    (review_runs.REVIEWS / '00010101-000000.json').write_text(json.dumps(EMPTY_REPLY))
    records, errors = review_records.report_records(review_runs.REVIEWS)
    assert records == [] and [path.name for path, _ in errors] == ['00010101-000000.json']
    lines = report_runs.review_lines(review_runs.REVIEWS, [], set(), set())
    assert 'invalid review record' in capsys.readouterr().err and isinstance(lines, list)


def test_an_unreadable_notes_file_is_named_by_apply_and_resolve(fake_paid, monkeypatch, capsys):
    claim = unverifiable_attempt()
    batch = review_runs.prepare_batch()

    def unreadable(*args, **kwargs):
        raise site_notes.NotesStoreError('injected EIO')

    monkeypatch.setattr(site_notes, 'read_envelope', unreadable)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(EMPTY_REPLY)))
    assert review_runs.main(['apply', '--batch', batch['batch_id']]) == 1
    assert 'The notes file cannot be read' in capsys.readouterr().out
    assert review_runs.main(['resolve', claim['attempt_id']]) == 1
    assert 'Nothing resolved: the notes file cannot be read' in capsys.readouterr().out


def test_a_group_left_by_an_exited_reviewer_is_named_where_dispatch_stops(fake_paid, monkeypatch, capsys):
    claim = unverifiable_attempt()
    claim.update(status='running', child={'pid': 12345, 'identity': review_runs.process_identity(12345),
                                          'exited': False})
    review_runs.save_attempt(claim)
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {'state': 'absent'})
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: True)
    monkeypatch.setattr(review_runs.os, 'killpg', lambda *args: pytest.fail('a leaderless group is never signalled'))
    assert review_runs.once_command(None) == 1 and fake_paid == []
    out = capsys.readouterr().out
    assert 'processes remain in its process group 12345' in out and 'ps -g 12345' in out


def test_reply_and_provider_text_cannot_drive_the_terminal(fake_paid, monkeypatch, capsys):
    recovery()
    batch = review_runs.prepare_batch()
    erase = 'x\x1b[2K\x1b[1Gdecision 1, add: applied: added evil.example-1'
    flag = {'action': 'flag', 'note': erase, 'runs': [RUN_B], 'hint': '', 'detail': '', 'reason': 'Check it'}
    apply_batch(batch, {**EMPTY_REPLY, 'decisions': [flag]})
    fake = review_runs.launch

    def provider_error(text, budget, quote=str, **callbacks):
        init, result, _ = fake(text, budget, quote, **callbacks)
        result.update(subtype='error\x1b[2K', result='\x1b]0;title\x07')
        return init, result, None

    write_run(RUN_C)
    monkeypatch.setattr(review_runs, 'launch', provider_error)
    review_runs.once_command(None)
    out = capsys.readouterr().out
    assert '\x1b' not in out and '\x07' not in out and 'no note x?[2K?[1Gdecision 1' in out


def test_resolve_names_what_settles_an_attempt_and_what_blocks_it(fake_paid, monkeypatch, capsys):
    """Its question says when committed evidence settles the attempt as succeeded; a process at the reviewer's PID
    whose identity was never read is named as such, never promised to the next review."""
    recovery()
    batch = review_runs.prepare_batch()
    claim = review_runs.claim_attempt(review_runs.read_state(), 'once', batch, time.time() - 10000)
    claim.update(status='running', child={'pid': 12345, 'identity': {'state': 'unknown'}, 'exited': False})
    review_runs.save_attempt(claim)
    assert review_runs.once_command(None) == 1 and fake_paid == []
    out = capsys.readouterr().out
    assert "the reviewer's identity was never read" in out and 'inspect process 12345' in out
    assert 'stops it at its deadline' not in out
    with review_runs.review_lock():
        review_runs._apply_batch(batch, EMPTY_REPLY, 0.0123, claim['attempt_id'])
    monkeypatch.setattr(review_runs, 'process_identity', lambda pid: {'state': 'absent'})
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: None)
    monkeypatch.setattr(review_runs, 'open_terminal', lambda: io.StringIO('no\n'))
    assert review_runs.main(['resolve', claim['attempt_id']]) == 1
    assert 'Its committed review settles it as succeeded.' in capsys.readouterr().out
