"""Explicit, idempotent public replies through the existing browser session."""

import hashlib
import json

from .bridge import BrowserBridge
from .errors import ThreadsError
from .models import now_iso
from .rate import RateGate
from .urls import post_url, profile_url


def deliver_text(
    store, viewer, target, text, mode, send=False, *, action="reply", check_composer=False
):
    url, code = post_url(target) if action == "reply" else (profile_url(viewer or ""), None)
    if not viewer:
        raise ThreadsError("viewer_required", "Configure --viewer before replying.", 2)
    if not text.strip() or len(text) > 500:
        raise ThreadsError("invalid_text", "Reply must contain 1–500 characters.", 2)
    if "/@" not in url:
        raise ThreadsError("recipient_required", "Use the full author/post URL.", 2)
    recipient = url.split("/@", 1)[1].split("/", 1)[0]
    if action == "reply" and recipient.casefold() == viewer.casefold():
        raise ThreadsError("self_reply", "This command expects another author's post.", 2)
    key = hashlib.sha256(json.dumps([viewer, url, text]).encode()).hexdigest()
    preview = {"viewer": viewer, "recipient": recipient, "target": url, "text": text}
    if send and check_composer:
        raise ThreadsError("invalid_options", "Choose --send or --check-composer, not both.", 2)
    if not send and not check_composer:
        return {"ok": True, "status": "preview", "request_id": key, **preview}
    if mode != "browser":
        raise ThreadsError("browser_connection_required", "Sending requires the browser bridge.", 4)
    with RateGate(store.directory) as gate:
        bridge = BrowserBridge()
        if check_composer:
            if action != "post":
                raise ThreadsError(
                    "invalid_options", "Composer checks apply to standalone posts.", 2
                )
            gate.wait()
            result = bridge.exchange(
                action, url=url, kind="profile", viewer=viewer, text=text, check_composer=True
            )["result"]
            if (
                result.get("status") != "composer_verified"
                or result.get("published") is not False
                or result.get("username") != viewer
                or result.get("text") != text
            ):
                raise ThreadsError("browser_error", "Composer check result did not match.", 5)
            return {"ok": True, **result}
        store.db.execute("""CREATE TABLE IF NOT EXISTS reply_outbox (
            request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT
        )""")
        prior = store.db.execute(
            "SELECT status,result FROM reply_outbox WHERE request_id=?", (key,)
        ).fetchone()
        if prior and prior["status"] != "not_submitted":
            if prior["status"] == "verified":
                return {**json.loads(prior["result"]), "reused": True}
            raise ThreadsError(
                "send_unconfirmed", "Prior attempt needs read-only reconciliation; not resent.", 5
            )
        store.db.execute(
            "INSERT INTO reply_outbox VALUES(?,?,?,?,NULL) ON CONFLICT(request_id) "
            "DO UPDATE SET status=excluded.status,result=NULL",
            (key, now_iso(), "started", json.dumps(preview, ensure_ascii=False)),
        )
        store.db.commit()
        gate.wait()
        try:
            response = bridge.exchange(
                action,
                url=url,
                root_code=code,
                kind="post",
                viewer=viewer,
                recipient=recipient,
                text=text,
            )["result"]
            if (
                response.get("status") not in {"sent", "already_present"}
                or response.get("username") != viewer
                or response.get("text") != text
                or response.get("in_reply_to") != (url if action == "reply" else None)
            ):
                raise ThreadsError("send_unconfirmed", "Reply verification did not match.", 5)
            own_url, _ = post_url(response["url"])
            if not own_url.startswith(f"https://www.threads.com/@{viewer}/post/"):
                raise ThreadsError("send_unconfirmed", "Reply author URL did not match.", 5)
            result = {"ok": True, "request_id": key, **response}
            store.db.execute(
                "UPDATE reply_outbox SET status='verified',result=? WHERE request_id=?",
                (json.dumps(result, ensure_ascii=False), key),
            )
            store.db.commit()
            if action == "reply":
                store.annotate(recipient, contacted_at=now_iso(), contact_evidence_url=own_url)
            return result
        except BaseException as error:
            state = "not_submitted" if getattr(error, "code", "") == "not_submitted" else "unknown"
            store.db.execute("UPDATE reply_outbox SET status=? WHERE request_id=?", (state, key))
            store.db.commit()
            raise


def send_reply(store, viewer, target, text, mode, send=False):
    return deliver_text(store, viewer, target, text, mode, send)


def send_post(store, viewer, text, mode, send=False, check_composer=False):
    return deliver_text(
        store, viewer, None, text, mode, send, action="post", check_composer=check_composer
    )
