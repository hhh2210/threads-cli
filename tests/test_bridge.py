import io
import json

import pytest

from threads_cli.bridge import BrowserBridge
from threads_cli.errors import ThreadsError


def test_bridge_requires_explicit_local_driver(monkeypatch):
    monkeypatch.delenv("THREADS_BROWSER_BRIDGE", raising=False)
    with pytest.raises(ThreadsError) as e:
        BrowserBridge()
    assert e.value.code == "browser_connection_required"


def test_bridge_roundtrip_carries_only_content(monkeypatch):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    output = io.StringIO()

    class Input:
        def readline(self, limit):
            req = json.loads(output.getvalue().splitlines()[-1])["bridge_request"]
            return (
                json.dumps(
                    {
                        "id": req["id"],
                        "page": {
                            "data_roots": [
                                {
                                    "searchResults": {
                                        "edges": [],
                                        "page_info": {"has_next_page": False, "end_cursor": None},
                                    }
                                }
                            ],
                            "viewer": "larryhaoai",
                            "authenticated": True,
                        },
                    }
                )
                + "\n"
            )

    monkeypatch.setattr("sys.stdout", output)
    monkeypatch.setattr("sys.stdin", Input())
    page = BrowserBridge().request(
        "page", kind="search", url="https://www.threads.com/search?q=cs2"
    )
    assert page.posts == []
    assert page.authenticated
    assert "cookie" not in output.getvalue()


def test_missing_browser_reply_fails_explicitly(monkeypatch):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    monkeypatch.setattr("sys.stdout", io.StringIO())
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(ThreadsError) as e:
        BrowserBridge().request("page", kind="status", url="https://www.threads.com/")
    assert e.value.code == "browser_error"
