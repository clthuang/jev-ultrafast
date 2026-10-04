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


@pytest.mark.parametrize('kind', ['batch', 'digest', 'attempt'])
def test_unknown_record_versions_fail_closed(kind):
    with pytest.raises(review_records.RecordError):
        review_records.validate({'schema_version': 999}, kind)


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


def test_attempt_records_never_acknowledge_items():
    attempts = review_runs.REVIEWS / 'attempts'
    attempts.mkdir(parents=True)
    (attempts / ('a' * 32 + '.json')).write_text(json.dumps({'queue': {'runs': [RUN_A]}}))
    assert review_records.acknowledged(review_runs.REVIEWS) == {'runs': {}, 'notes': {}}


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
def test_crash_at_each_publication_boundary(monkeypatch, boundary):
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
    if boundary == 'before_notes':
        assert not site_notes.NOTES_PATH.exists()
    else:
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


def test_directory_fsync_failure_after_replace_never_replays(monkeypatch):
    test_crash_at_each_publication_boundary(monkeypatch, 'notes_fsync')


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
                                      'unknown_summary', 'mismatched_items'])
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


def test_auto_cutoff_and_exclusions_survive_migration():
    from scripts.migrate_review_storage import migrate_storage

    write_run('20260926-100000-0001')
    write_run(RUN_A)
    write_run(RUN_B, page={'url': 'https://private.example/', 'title': 'Private'})
    site_notes.NOTES_PATH.write_text(json.dumps(site_notes.SEEDS))
    site_notes.EXCLUDE_PATH.write_text('private.example\n')
    cutoff = review_runs.AUTO_FROM
    migrate_storage(site_notes.NOTES_PATH.parent)
    batch = review_runs.prepare_batch(review_runs.day(cutoff))
    assert list(batch['runs']) == [RUN_A]
    assert review_runs.AUTO_FROM == cutoff
    assert site_notes.EXCLUDE_PATH.read_text() == 'private.example\n'


def test_export_preserves_new_notes_outcomes_receipts_and_ack_history(tmp_path, monkeypatch):
    from jev_ultrafast import run_store
    from scripts.migrate_review_storage import export_storage, migrate_storage

    recovery()
    site_notes.NOTES_PATH.write_text(json.dumps(site_notes.SEEDS))
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
        source = __import__('pathlib').Path('artifacts') / name
        assert source.read_bytes() == (exported / name).read_bytes()
    assert len(review_records.committed(exported / 'reviews')) == 2
    assert any(note['site'] == 'new.example' for note in site_notes.load(exported / 'site-notes.json')[0])
    assert len(json.loads((exported / 'runs' / f'{RUN_B}.json').read_text())['outcome']) == 2


def test_real_pipeline_redacts_every_publication_surface(monkeypatch, capsys, fake_paid):
    from scripts import report_runs

    selected, deferred, excluded = 'Selectedcanary', 'Deferredcanary', 'Excludedcanary'
    write_run(RUN_A, goal=f'{selected} {deferred} {excluded}', history=[{'text': selected}])
    write_run(RUN_B, history=[{'text': deferred}])
    write_run(RUN_C, previous_run=RUN_A, history=[{'text': excluded}])
    site_notes.EXCLUDE_PATH.write_text(RUN_C)
    monkeypatch.setattr(review_runs, 'MAX_BATCH_RUNS', 1)
    batch = review_runs.prepare_batch()
    # Schema refusal cannot quote dynamic keys; semantic refusal keeps trusted wording.
    _, errors = apply_batch(batch, {**EMPTY_REPLY, deferred: 'unexpected'})
    print('; '.join(errors))
    reply = {**EMPTY_REPLY, 'summary': selected + ' ' + deferred + ' ' + excluded,
             'decisions': [add_decision(detail=selected)]}
    original = review_runs.ensure_digest
    monkeypatch.setattr(review_runs, 'ensure_digest', lambda receipt: (_ for _ in ()).throw(OSError('fixture')))
    with pytest.raises(OSError):
        apply_batch(batch, reply)
    receipt_bytes = site_notes.NOTES_PATH.read_text()
    assert 'its detail holds a value from a task' in receipt_bytes
    monkeypatch.setattr(review_runs, 'ensure_digest', original)
    with review_runs.review_lock():
        review_runs.recover_pending()
    # Change a contributor to requeue, retaining all canary values in the verified context.
    path = review_runs.RUNS / f'{RUN_A}.json'
    value = json.loads(path.read_text())
    value['outcome'][0]['at'] = 'later'
    path.write_text(json.dumps(value))
    fake = review_runs.launch
    def provider_error(*args, **kwargs):
        init, result, _ = fake(*args, **kwargs)
        result.update(subtype=selected, result=deferred + ' ' + excluded)
        return init, result, None
    monkeypatch.setattr(review_runs, 'launch', provider_error)
    assert review_runs.once_command(None) == 1
    report_runs.review_lines(review_runs.REVIEWS, site_notes.load()[0], {RUN_C}, {RUN_C})
    published = [site_notes.NOTES_PATH, *review_runs.REVIEWS.rglob('*.json')]
    all_output = receipt_bytes + capsys.readouterr().out + ''.join(path.read_text() for path in published)
    assert not any(canary in all_output for canary in (selected, deferred, excluded))
    assert 'the review ended with <value>: <value> <value>' in all_output


import io  # noqa: E402
import sys  # noqa: E402
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


def test_resolve_never_settles_a_verifiably_live_reviewer(fake_paid, monkeypatch, capsys):
    claim = unverifiable_attempt()
    identity = review_runs.process_identity(12345)  # the fake reports this child alive with this identity
    claim.update(status='running', child={'pid': 12345, 'identity': identity, 'exited': False})
    review_runs.save_attempt(claim)
    monkeypatch.setattr(review_runs, 'open_terminal', lambda: pytest.fail('a live reviewer needs no confirmation'))
    monkeypatch.setattr(review_runs.os, 'killpg', lambda *args: pytest.fail('resolve never signals'))
    monkeypatch.setattr(review_runs, 'group_alive', lambda pid: True)
    assert review_runs.main(['resolve', claim['attempt_id']]) == 1
    assert 'still running' in capsys.readouterr().out
    assert attempts() == [claim] and review_runs.read_state()['accounted_attempt_ids'] == []


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
    # Until recovery succeeds, neither another apply nor a paid review runs.
    monkeypatch.setattr(sys, 'stdin', io.StringIO(reply))
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
