"""A report tool whose effect and operation receipt share one SQLite transaction.

This demonstrates actual deduplication, not a generic promise that arbitrary
remote side effects can be made exactly-once by the harness.
"""
import json
from contextlib import closing
from pathlib import Path
import sqlite3

from cardinal_agent.types import ToolResult, ToolSpec


class ReportStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS reports '
                       '(operation_id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL)')

    def _result(self, row):
        return json.dumps(dict(zip(('operation_id', 'title', 'body'), row)), ensure_ascii=False)

    def execute(self, args, operation_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR IGNORE INTO reports VALUES (?, ?, ?)',
                       (operation_id, args['title'], args['body']))
            row = db.execute('SELECT * FROM reports WHERE operation_id = ?', (operation_id,)).fetchone()
            if row[1:] != (args['title'], args['body']):
                raise ValueError('Operation ID was already used with different arguments.')
            return self._result(row)

    def lookup(self, args, operation_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute('SELECT * FROM reports WHERE operation_id = ?', (operation_id,)).fetchone()
        if row is None:
            return None
        if row[1:] != (args['title'], args['body']):
            raise ValueError('Operation arguments do not match the saved report.')
        return ToolResult('ok', self._result(row))

    def spec(self):
        def without_id(**args):
            raise ValueError('This tool requires a runtime-generated operation ID.')
        return ToolSpec('create_report', 'Save a report in a local transactional store.',
                        {'type': 'object', 'properties': {'title': {'type': 'string'},
                         'body': {'type': 'string'}}, 'required': ['title', 'body'],
                         'additionalProperties': False}, without_id,
                        execute_with_id=self.execute, lookup_result=self.lookup)
