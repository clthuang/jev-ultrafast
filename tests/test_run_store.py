"""Actual concurrent publishers, disposable paths, and field ownership."""

import fcntl
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from jev_ultrafast import mcp_server, run_store


def label(number=0, by='user'):
    return {'passed': number % 2 == 0, 'evidence': str(number), 'by': by, 'at': '2026-10-03T12:00:00',
            'custom': {'preserve': number}}


def test_save_preserves_sequential_user_correction(tmp_path):
    path = tmp_path / 'run.json'
    run_store.save_execution(path, {'status': 'running', 'stop_code': None})
    run_store.append_outcome(path, label(0, 'claude'))
    run_store.append_outcome(path, label(1))
    run_store.save_execution(path, {'status': 'done', 'stale_recoveries': 4})
    saved = json.loads(path.read_text())
    assert saved == {'status': 'done', 'stale_recoveries': 4, 'outcome': [label(0, 'claude'), label(1)]}


def test_save_and_reporters_preserve_all_writes(tmp_path):
    path = tmp_path / 'run.json'
    run_store.save_execution(path, {'status': 'running'})
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run_store.append_outcome, path, label(number)) for number in range(25)]
        futures += [pool.submit(run_store.save_execution, path, {'status': 'done', 'observer': number})
                    for number in range(25)]
        for future in futures:
            future.result()
    saved = json.loads(path.read_text())
    assert saved['status'] == 'done' and 'observer' in saved
    assert sorted(int(item['evidence']) for item in saved['outcome']) == list(range(25))
    assert all(item['custom']['preserve'] == int(item['evidence']) for item in saved['outcome'])


@pytest.mark.parametrize('raw', ['not json', '[]', '{"outcome":null}', '{"outcome":[null]}',
                                 '{"outcome":[{}]}', '{"outcome":[{"passed":"true"}]}',
                                 '{"outcome":[{"passed":true,"evidence":"ok","by":[]}]}',
                                 '{"outcome":[{"passed":true,"evidence":"ok","by":{}}]}'])
def test_malformed_existing_run_is_not_overwritten(tmp_path, raw):
    path = tmp_path / 'run.json'
    path.write_text(raw)
    for call in (lambda: run_store.save_execution(path, {}), lambda: run_store.append_outcome(path, label())):
        with pytest.raises(ValueError):
            call()
        assert path.read_text() == raw


def test_custom_trace_directory_uses_one_lock(tmp_path):
    real, alias = tmp_path / 'real', tmp_path / 'alias'
    real.mkdir()
    alias.symlink_to(real, target_is_directory=True)
    assert run_store.resolved_path(real / 'run.json') == run_store.resolved_path(alias / 'run.json')
    with run_store.metadata_lock(real):
        with (alias / '.metadata.lock').open('a') as second:
            with pytest.raises(BlockingIOError):
                fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_metadata_lock_is_released_before_lesson_and_review(tmp_path, monkeypatch):
    run_id = '20261003-120000-abcd'
    monkeypatch.setattr(mcp_server, 'RUNS', tmp_path)
    run_store.save_execution(tmp_path / f'{run_id}.json', {'status': 'done', 'observer': 42})
    callbacks = []

    def unlocked(name):
        with (tmp_path / '.metadata.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        callbacks.append(name)
        return ''

    monkeypatch.setattr(mcp_server, 'store_lesson', lambda *_: unlocked('lesson'))
    monkeypatch.setattr(mcp_server, 'review_trigger', lambda: unlocked('review'))
    assert 'Recorded passed' in mcp_server.report_outcome(run_id, True, 'Verified', lesson='scroll_first')
    assert callbacks == ['lesson', 'review']
    assert json.loads((tmp_path / f'{run_id}.json').read_text())['observer'] == 42


def test_post_rename_failure_never_claims_label_was_not_recorded(tmp_path, monkeypatch):
    from jev_ultrafast import store_io

    run_id = '20261003-120000-abcd'
    path = tmp_path / f'{run_id}.json'
    run_store.save_execution(path, {'status': 'done'})
    monkeypatch.setattr(mcp_server, 'RUNS', tmp_path)
    monkeypatch.setattr(mcp_server, 'review_trigger', lambda: pytest.fail('uncertain publication triggers no review'))

    def fail_directory_sync(directory):
        raise OSError('injected after visible replacement')

    monkeypatch.setattr(store_io, 'fsync_directory', fail_directory_sync)
    reply = mcp_server.report_outcome(run_id, True, 'Verified')
    assert 'may already be recorded' in reply and 'Inspect the run before retrying' in reply
    assert 'nothing recorded' not in reply
    assert len(json.loads(path.read_text())['outcome']) == 1


def test_page_surrogates_roundtrip_without_losing_execution(tmp_path):
    path = tmp_path / 'run.json'
    execution = {'page': {'text': 'surrogate \ud800', 'title': '東京'}, 'history': [{'operation': 'CLICK'}]}
    run_store.save_execution(path, execution)
    assert json.loads(path.read_text()) == {**execution, 'outcome': []}


def test_uncertain_lesson_does_not_claim_note_was_not_stored(tmp_path, monkeypatch):
    from jev_ultrafast import site_notes, store_io

    run_id = '20261003-120000-abcd'
    runs = tmp_path / 'runs'
    runs.mkdir()
    path = runs / f'{run_id}.json'
    run_store.save_execution(path, {'goal': 'Search', 'page': {'url': 'https://example.com/'},
                                    'result': {'status': 'blocked'}, 'history': [], 'previous_run': None})
    monkeypatch.setattr(mcp_server, 'RUNS', runs)
    monkeypatch.setattr(mcp_server, 'review_trigger', lambda: None)
    sync = store_io.fsync_directory
    def fail_notes(directory):
        if directory.name == 'artifacts':
            raise OSError('notes directory fsync failed')
        return sync(directory)
    monkeypatch.setattr(store_io, 'fsync_directory', fail_notes)
    reply = mcp_server.report_outcome(run_id, False, 'Verified', lesson='use_claude_in_chrome')
    assert 'may already be stored' in reply and 'Note not stored' not in reply
    assert len(json.loads(path.read_text())['outcome']) == 1
    assert sum(note['site'] == 'example.com' for note in site_notes.load()[0]) == 1
