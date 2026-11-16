"""Operation IDs are runtime-owned; uncertain outcomes require real evidence."""
import json
import sqlite3

import pytest

from cardinal_agent.agent.checkpoint import RecoveryRequired
from cardinal_agent.agent.registry import ToolRegistry
from cardinal_agent.examples.durable_reports import ReportStore
from cardinal_agent.harness import create_session
from cardinal_agent.types import AgentConfig, ToolSpec

ARGS = {'title': 'Weekly', 'body': 'Done'}
CALL = '<tool_call>' + json.dumps({'name': 'create_report', 'args': ARGS}) + '</tool_call>'


def test_report_deduplication_and_id_conflict(tmp_path):
    reports = ReportStore(tmp_path / 'reports.db')
    first = reports.execute(ARGS, 'same-operation')
    assert reports.execute(ARGS, 'same-operation') == first
    assert reports.lookup(ARGS, 'same-operation').content == first
    with pytest.raises(ValueError, match='different arguments'):
        reports.execute(dict(ARGS, body='Changed'), 'same-operation')
    with sqlite3.connect(reports.path) as db:
        assert db.execute('SELECT count(*) FROM reports').fetchone()[0] == 1


def test_lookup_recovers_committed_effect_without_execution(tmp_path):
    reports = ReportStore(tmp_path / 'reports.db')
    spec = reports.spec()
    execute = spec.execute_with_id
    def crash(args, operation_id):
        execute(args, operation_id)
        raise KeyboardInterrupt()
    spec.execute_with_id = crash
    config = AgentConfig(checkpoint_path=tmp_path / 'checkpoint.json')
    with pytest.raises(KeyboardInterrupt):
        create_session(lambda m: CALL, [spec], config).send('Save report')
    fresh = reports.spec()
    fresh.execute_with_id = lambda *args: pytest.fail('A completed report was executed again')
    result = create_session(lambda m: 'Saved', [fresh], config).resume()
    event = next(e for e in result.transcript if e['type'] == 'reconciliation_completed')
    assert event['source'] == 'lookup'
    assert len([e for e in result.transcript if e['type'] == 'tool_result']) == 1


def test_missing_or_failed_lookup_never_retries(tmp_path):
    reports = ReportStore(tmp_path / 'reports.db')
    spec = reports.spec()
    def crash(*args): raise KeyboardInterrupt()
    spec.execute_with_id = crash
    config = AgentConfig(checkpoint_path=tmp_path / 'checkpoint.json')
    with pytest.raises(KeyboardInterrupt):
        create_session(lambda m: CALL, [spec], config).send('Save')
    for lookup in (lambda *a: None, lambda *a: 'unverified'):
        spec.lookup_result = lookup
        with pytest.raises(RecoveryRequired):
            create_session(lambda m: 'Done', [spec], config).resume()
    with sqlite3.connect(reports.path) as db:
        assert db.execute('SELECT count(*) FROM reports').fetchone()[0] == 0


def test_recovery_contract_is_checked(tmp_path):
    reports = ReportStore(tmp_path / 'reports.db')
    spec = reports.spec()
    spec.lookup_result = None
    with pytest.raises(ValueError, match='together'):
        ToolRegistry([spec])
    plain = ToolSpec('x', 'X', {'type': 'object'}, lambda: 'ok')
    with pytest.raises(ValueError, match='Duplicate'):
        ToolRegistry([plain, plain])
