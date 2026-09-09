import pytest

from threads_cli.dm import request_dm
from threads_cli.errors import ThreadsError
from threads_cli.store import Store

THREAD = "1234567890123456"


def test_dm_send_verifies_recipient_and_only_unsends_its_recorded_message(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    monkeypatch.setattr("threads_cli.dm.RateGate.wait", lambda self: None)
    calls = []

    def exchange(self, action, **kw):
        calls.append(action)
        if action == "dm_send":
            return {
                "result": dict(
                    status="sent",
                    username="larryhaoai",
                    recipient="test_recipient",
                    text="test",
                    thread_id=THREAD,
                    message_id="mid.ours",
                )
            }
        assert action == "dm_unsend"
        assert kw["text"] == "test" and kw["recipient"] == "test_recipient"
        return {"result": dict(status="unsent", message_id="mid.ours", thread_id=THREAD)}

    monkeypatch.setattr("threads_cli.dm.BrowserBridge.exchange", exchange)
    s = Store(tmp_path)
    with pytest.raises(ThreadsError) as exc:
        request_dm(s, "larryhaoai", THREAD, message_id="mid.unrelated")
    assert exc.value.code == "untracked_message"
    request_dm(s, "larryhaoai", THREAD, "test_recipient", "test", True)
    assert request_dm(s, "larryhaoai", THREAD, "test_recipient", "test", True)["reused"]
    r = request_dm(s, "larryhaoai", THREAD, message_id="mid.ours")
    assert r["status"] == "unsent"
    assert calls == ["dm_send", "dm_unsend"]
    assert s.db.execute("SELECT status FROM dm_outbox").fetchone()[0] == "unsent"
    s.close()


def test_dm_wrong_recipient_never_marks_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    monkeypatch.setattr("threads_cli.dm.RateGate.wait", lambda self: None)
    monkeypatch.setattr(
        "threads_cli.dm.BrowserBridge.exchange",
        lambda *a, **kw: {
            "result": dict(
                status="sent",
                username="larryhaoai",
                recipient="wrong",
                text="test",
                thread_id=THREAD,
                message_id="mid.wrong",
            )
        },
    )
    s = Store(tmp_path)
    with pytest.raises(ThreadsError):
        request_dm(s, "larryhaoai", THREAD, "test_recipient", "test", True)
    assert s.db.execute("SELECT status FROM dm_outbox").fetchone()[0] == "unknown"
    s.close()
