import fcntl
import json
import time
from pathlib import Path

from .errors import ThreadsError
from .store import private_dir


class RateGate:
    """One network collector at a time, with pacing shared across CLI processes."""

    def __init__(self, directory: Path, interval: float = 2.5):
        self.directory = private_dir(directory)
        self.path = directory / "rate.json"
        self.interval = interval
        self.lock = None

    def __enter__(self):
        self.lock = (self.directory / "collector.lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            raise ThreadsError(
                "collector_busy", "Another Threads collector is running.", 7
            ) from None
        return self

    def __exit__(self, *_):
        if self.lock:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (ValueError, OSError):
            raise ThreadsError(
                "rate_state_invalid", "Cannot read shared pacing state.", 7
            ) from None

    def _write(self, state):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(state))
        temp.chmod(0o600)
        temp.replace(self.path)

    def wait(self):
        state = self._read()
        now = time.time()
        blocked = state.get("blocked_until", 0) - now
        if blocked > 0:
            raise ThreadsError(
                "rate_limited", f"Threads cooldown active for {int(blocked) + 1}s.", 7
            )
        delay = state.get("next_request_at", 0) - now
        if delay > 0:
            time.sleep(min(delay, self.interval))
        state["next_request_at"] = time.time() + self.interval
        self._write(state)

    def block(self, seconds=900):
        state = self._read()
        state["blocked_until"] = time.time() + max(60, min(seconds, 3600))
        self._write(state)
