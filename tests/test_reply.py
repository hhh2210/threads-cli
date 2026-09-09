import pytest

from threads_cli.errors import ThreadsError
from threads_cli.reply import send_reply
from threads_cli.store import Store

TARGET = "https://www.threads.com/@alice/post/ROOT123"
OWN = "https://www.threads.com/@larryhaoai/post/OWN1234"


def test_preview_does_not_open_browser(tmp_path, monkeypatch):
    monkeypatch.delenv("THREADS_BROWSER_BRIDGE", raising=False)
    store = Store(tmp_path)
    result = send_reply(store, "larryhaoai", TARGET, "一起玩？", "browser")
    assert result["status"] == "preview"
    assert result["recipient"] == "alice"
    store.close()


def test_verified_reply_is_recorded_and_repeated_request_is_not_resent(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    calls = []

    def exchange(self, action, **args):
        calls.append((action, args))
        return {
            "result": {
                "status": "sent",
                "username": "larryhaoai",
                "text": "一起玩？",
                "url": OWN,
                "in_reply_to": TARGET,
            }
        }

    monkeypatch.setattr("threads_cli.reply.BrowserBridge.exchange", exchange)
    store = Store(tmp_path)
    first = send_reply(store, "larryhaoai", TARGET, "一起玩？", "browser", True)
    again = send_reply(store, "larryhaoai", TARGET, "一起玩？", "browser", True)
    assert first["url"] == OWN
    assert again["reused"] is True
    assert len(calls) == 1
    assert store.annotations()["alice"]["contact_evidence_url"] == OWN
    store.close()


def test_uncertain_attempt_cannot_be_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    calls = []

    def exchange(self, action, **args):
        calls.append(action)
        raise ThreadsError("send_unconfirmed", "Network lost after Post", 5)

    monkeypatch.setattr("threads_cli.reply.BrowserBridge.exchange", exchange)
    store = Store(tmp_path)
    for _ in range(2):
        with pytest.raises(ThreadsError, match=".*") as error:
            send_reply(store, "larryhaoai", TARGET, "一起玩？", "browser", True)
        assert error.value.code == "send_unconfirmed"
    assert len(calls) == 1
    assert not store.annotations()
    store.close()


def test_wrong_reply_author_is_not_marked_contacted(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    monkeypatch.setattr(
        "threads_cli.reply.BrowserBridge.exchange",
        lambda *a, **kw: {
            "result": {
                "status": "sent",
                "username": "someone_else",
                "text": "一起玩？",
                "url": OWN,
                "in_reply_to": TARGET,
            }
        },
    )
    store = Store(tmp_path)
    with pytest.raises(ThreadsError) as error:
        send_reply(store, "larryhaoai", TARGET, "一起玩？", "browser", True)
    assert error.value.code == "send_unconfirmed"
    assert not store.annotations()
    store.close()


def test_standalone_post_does_not_annotate_self(tmp_path, monkeypatch):
    from threads_cli.reply import send_post

    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    monkeypatch.setattr(
        "threads_cli.reply.BrowserBridge.exchange",
        lambda *a, **kw: {
            "result": {
                "status": "sent",
                "username": "larryhaoai",
                "text": "公开文字",
                "url": OWN,
                "in_reply_to": None,
            }
        },
    )
    store = Store(tmp_path)
    result = send_post(store, "larryhaoai", "公开文字", "browser", True)
    assert result["status"] == "sent"
    assert not store.annotations()
    assert send_post(store, "larryhaoai", "公开文字", "browser", True)["reused"]
    store.close()


def test_draft_check_cannot_claim_publish_and_does_not_use_outbox(tmp_path, monkeypatch):
    from threads_cli.reply import send_post

    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    monkeypatch.setattr(
        "threads_cli.reply.BrowserBridge.exchange",
        lambda *a, **kw: {
            "result": {
                "status": "composer_verified",
                "username": "larryhaoai",
                "text": "草稿",
                "published": False,
            }
        },
    )
    store = Store(tmp_path)
    result = send_post(store, "larryhaoai", "草稿", "browser", check_composer=True)
    assert result["published"] is False
    assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='reply_outbox'").fetchall()
    with pytest.raises(ThreadsError):
        send_post(store, "larryhaoai", "草稿", "browser", send=True, check_composer=True)
    store.close()
