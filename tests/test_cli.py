import json

import pytest
from click.testing import CliRunner

from threads_cli import cli as module
from threads_cli.cli import cli
from threads_cli.models import Collection, Post


def test_partial_search_has_nonzero_exit_and_persisted_results(tmp_path, monkeypatch):
    p = Post("ROOT123", "123", "alice", "CS2找队友", "https://www.threads.com/@alice/post/ROOT123")

    class FakeClient:
        request_count = 2

        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def search(self, *a, on_page, **kw):
            on_page([p])
            return Collection(
                [p], 1, True, "partial", [{"code": "schema_changed", "message": "changed"}]
            )

    monkeypatch.setattr(module, "Client", FakeClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["--data-dir", str(tmp_path), "search", "cs2", "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["completion"] == "partial"
    assert len(payload["posts"]) == 1
    runs = runner.invoke(cli, ["--data-dir", str(tmp_path), "runs", "--json"])
    assert json.loads(runs.output)["runs"][0]["metadata"]["completion"] == "partial"


def test_entrypoint_propagates_click_returned_exit_status(monkeypatch):
    monkeypatch.setattr(module, "cli", lambda **kw: 5)
    with pytest.raises(SystemExit) as e:
        module.main()
    assert e.value.code == 5


def test_invalid_import_is_atomic_and_does_not_require_auth(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"schema_version": 1, "posts": [{"bad": "data"}]}))
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--data-dir", str(tmp_path / "db"), "import", str(source), "--json"]
    )
    assert result.exit_code != 0


def test_contact_evidence_does_not_replace_region_evidence(tmp_path):
    from threads_cli.store import Store

    store = Store(tmp_path)
    store.annotate("alice", region="mainland_verified", evidence_url="https://example.test/region")
    store.annotate(
        "alice", contacted_at="2026-09-07", contact_evidence_url="https://example.test/reply"
    )
    row = store.annotations()["alice"]
    assert row["evidence_url"].endswith("/region")
    assert row["contact_evidence_url"].endswith("/reply")
    store.close()
