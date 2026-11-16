"""Atomic local checkpoints, guarded by a single-writer process lock."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile


class RecoveryRequired(RuntimeError):
    """A tool may have executed; an operator must reconcile its outcome."""


class CheckpointStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def locked(self):
        # The local runtime targets Linux/WSL; never silently omit locking.
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + '.lock').open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('This checkpoint is already in use.') from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def write(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.checkpoint-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(state, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
