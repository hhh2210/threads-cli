"""Batch hidden-word input and the private browser-settings boundary."""

import re
import unicodedata

from .bridge import BrowserBridge
from .errors import ThreadsError
from .rate import RateGate

MAX_INPUT_BYTES = 1_000_000
MAX_WORDS = 1000


def word_key(word):
    return unicodedata.normalize("NFC", word).lower()


def parse_words(text):
    """Preserve phrases and spelling; split only commas and line endings."""
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ThreadsError("invalid_words", "Input exceeds the CLI's 1 MB limit.", 2)
    words, duplicates, seen = [], [], set()
    for item in re.split(r"[,，\r\n]+", text.lstrip("\ufeff")):
        word = unicodedata.normalize("NFC", item.strip())
        if not word:
            continue
        if any(unicodedata.category(char) == "Cc" for char in word):
            raise ThreadsError("invalid_words", "Words cannot contain control characters.", 2)
        key = word_key(word)
        if key in seen:
            duplicates.append(word)
        else:
            seen.add(key)
            words.append(word)
    if not words or len(words) > MAX_WORDS:
        raise ThreadsError("invalid_words", "Supply 1–1000 unique words or phrases.", 2)
    return words, duplicates


def manage_hidden_words(
    store,
    viewer,
    mode,
    *,
    operation="list",
    filter_name=None,
    text="",
    create=False,
    apply=False,
    check=False,
):
    if operation not in {"list", "add"}:
        raise ThreadsError("invalid_options", "Unknown hidden-words operation.", 2)
    if filter_name is not None:
        filter_name = filter_name.strip()
        if not filter_name or any(unicodedata.category(c) == "Cc" for c in filter_name):
            raise ThreadsError("invalid_options", "Supply a nonempty, single-line filter name.", 2)
    if apply and check:
        raise ThreadsError("invalid_options", "Choose --apply or --check, not both.", 2)
    words, duplicates = parse_words(text) if operation == "add" else ([], [])
    if operation == "add" and not filter_name:
        raise ThreadsError("invalid_options", "Choose a filter with --filter.", 2)
    if operation == "add" and not apply and not check:
        return {
            "ok": True,
            "status": "local_preview",
            "filter_name": filter_name,
            "words": words,
            "input_duplicates": duplicates,
            "create_if_missing": create,
            "remote_checked": False,
        }
    if not viewer:
        raise ThreadsError("viewer_required", "Configure --viewer for account settings.", 2)
    if mode != "browser":
        raise ThreadsError("browser_connection_required", "Settings need the browser bridge.", 4)
    with RateGate(store.directory) as gate:
        gate.wait()
        result = BrowserBridge().exchange(
            "hidden_words",
            operation=operation,
            viewer=viewer,
            filter_name=filter_name,
            words=words,
            create=create,
            apply=apply,
        )["result"]
    if result.get("username") != viewer:
        raise ThreadsError("account_mismatch", "Settings account did not match.", 4)
    if operation == "add":
        if result.get("filter_name") != filter_name:
            raise ThreadsError("verification_failed", "Wrong filter in settings result.", 5)
        expected_status = {"verified", "unchanged"} if apply else {"preview"}
        if result.get("status") not in expected_status:
            raise ThreadsError("verification_failed", "Settings operation was not verified.", 5)
        if apply:
            saved = result.get("words")
            if not isinstance(saved, list) or not all(isinstance(w, str) for w in saved):
                raise ThreadsError("verification_failed", "No saved word list returned.", 5)
            if not {word_key(w) for w in words} <= {word_key(w) for w in saved}:
                raise ThreadsError("verification_failed", "Requested words missing after save.", 5)
    # Preferences are returned to the caller, never archived as public post evidence.
    return {"ok": True, **result, "input_duplicates": duplicates}
