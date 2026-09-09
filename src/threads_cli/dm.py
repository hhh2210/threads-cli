"""Explicit existing-conversation DMs and ownership-checked unsending."""

import hashlib
import json
import re

from .bridge import BrowserBridge
from .errors import ThreadsError
from .models import now_iso
from .rate import RateGate
from .urls import profile_url


def request_dm(store, viewer, thread_id, recipient=None, text=None, send=False, message_id=None):
    if not viewer:
        raise ThreadsError("viewer_required", "DM commands require --viewer.", 2)
    if not re.fullmatch(r"[0-9]{5,30}", thread_id):
        raise ThreadsError("invalid_thread", "Use the numeric thread ID from /messages/t/ID/.", 2)
    url = f"https://www.threads.com/messages/t/{thread_id}/"
    if recipient:
        profile_url(recipient)
    if text is not None and (not text.strip() or len(text) > 1000):
        raise ThreadsError("invalid_text", "DM text must contain 1–1000 characters.", 2)
    if text is not None and not send:
        return {"ok": True, "status": "preview", "recipient": recipient, "text": text, "url": url}
    with RateGate(store.directory) as gate:
        bridge = BrowserBridge()
        gate.wait()
        if text is None and message_id is None:
            return {
                "ok": True,
                **bridge.exchange(
                    "dm_read", url=url, thread_id=thread_id, viewer=viewer, recipient=recipient
                )["result"],
            }
        store.db.execute("""CREATE TABLE IF NOT EXISTS dm_outbox (
            request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
            payload TEXT NOT NULL, result TEXT)""")
        if message_id:
            matches = []
            for row in store.db.execute("SELECT * FROM dm_outbox WHERE status='verified'"):
                result = json.loads(row["result"])
                if result.get("message_id") == message_id and result.get("thread_id") == thread_id:
                    matches.append((row["request_id"], json.loads(row["payload"])))
            if len(matches) != 1:
                raise ThreadsError(
                    "untracked_message", "Unsend only verified CLI-authored messages.", 2
                )
            key, original = matches[0]
            if original["viewer"] != viewer:
                raise ThreadsError("account_mismatch", "The original DM sender did not match.", 4)
            result = bridge.exchange("dm_unsend", message_id=message_id, **original)["result"]
            if result.get("status") != "unsent" or result.get("message_id") != message_id:
                raise ThreadsError("send_unconfirmed", "Unsend was not verified.", 5)
            store.db.execute(
                "UPDATE dm_outbox SET status='unsent',result=? WHERE request_id=?",
                (json.dumps(result, ensure_ascii=False), key),
            )
            store.db.commit()
            return {"ok": True, **result}
        if not recipient or recipient == viewer:
            raise ThreadsError(
                "recipient_required", "Specify the exact other account with --to.", 2
            )
        payload = dict(url=url, thread_id=thread_id, viewer=viewer, recipient=recipient, text=text)
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        prior = store.db.execute("SELECT * FROM dm_outbox WHERE request_id=?", (key,)).fetchone()
        if prior:
            if prior["status"] in {"verified", "unsent"}:
                return {"ok": True, **json.loads(prior["result"]), "reused": True}
            raise ThreadsError("send_unconfirmed", "Existing DM attempt needs reconciliation.", 5)
        store.db.execute(
            "INSERT INTO dm_outbox VALUES(?,?,?,?,NULL)",
            (key, now_iso(), "started", json.dumps(payload, ensure_ascii=False)),
        )
        store.db.commit()
        try:
            result = bridge.exchange("dm_send", **payload)["result"]
            if (
                result.get("status") not in {"sent", "already_present"}
                or result.get("username") != viewer
                or result.get("recipient") != recipient
                or result.get("text") != text
                or result.get("thread_id") != thread_id
                or not result.get("message_id")
            ):
                raise ThreadsError("send_unconfirmed", "DM read-back failed verification.", 5)
            store.db.execute(
                "UPDATE dm_outbox SET status='verified',result=? WHERE request_id=?",
                (json.dumps(result, ensure_ascii=False), key),
            )
            store.db.commit()
            return {"ok": True, **result}
        except BaseException:
            store.db.execute("UPDATE dm_outbox SET status='unknown' WHERE request_id=?", (key,))
            store.db.commit()
            raise
