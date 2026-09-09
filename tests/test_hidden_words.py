import json

import pytest
from click.testing import CliRunner

from threads_cli.cli import cli
from threads_cli.errors import ThreadsError
from threads_cli.hidden_words import manage_hidden_words, parse_words
from threads_cli.store import Store


def test_word_input_keeps_phrases_and_first_spelling():
    words, duplicates = parse_words("\ufeffClub,约会\r\nclub，multi word phrase\nCafe\u0301,Café\n")
    assert words == ["Club", "约会", "multi word phrase", "Café"]
    assert duplicates == ["club", "Café"]


@pytest.mark.parametrize(
    "text",
    ["", " ,，\r\n", "bad\x00word", "a" * 1_000_001, "\n".join(f"word{i}" for i in range(1001))],
)
def test_invalid_word_input_is_rejected(text):
    with pytest.raises(ThreadsError) as exc:
        parse_words(text)
    assert exc.value.code == "invalid_words"


def test_cli_preview_reads_utf8_file_without_auth_and_does_not_archive(tmp_path, monkeypatch):
    source = tmp_path / "words.txt"
    source.write_text("\ufeffclub，约会\nclub\nmulti word phrase", encoding="utf-8")
    monkeypatch.setattr(
        "threads_cli.hidden_words.BrowserBridge",
        lambda: pytest.fail("Local preview must not connect"),
    )
    result = CliRunner().invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "hidden-words",
            "add",
            "--filter",
            "Filter",
            "--file",
            str(source),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["status"] == "local_preview" and value["remote_checked"] is False
    assert value["words"] == ["club", "约会", "multi word phrase"]
    with Store(tmp_path / "data").db as db:
        assert db.execute("SELECT count(*) FROM posts").fetchone()[0] == 0


def test_cli_rejects_non_utf8_and_conflicting_save_flags(tmp_path):
    source = tmp_path / "words.txt"
    source.write_bytes(b"\xff")
    args = ["--data-dir", str(tmp_path / "data"), "hidden-words", "add", "--filter", "Filter"]
    runner = CliRunner()
    assert runner.invoke(cli, [*args, "--file", str(source)]).exit_code == 2
    assert runner.invoke(cli, [*args, "--word", "club", "--apply", "--check"]).exit_code != 0


def test_live_check_and_apply_require_browser_and_expected_account(tmp_path):
    store = Store(tmp_path)
    for viewer, mode, expected in [
        (None, "browser", "viewer_required"),
        ("alice", "public", "browser_connection_required"),
    ]:
        with pytest.raises(ThreadsError) as exc:
            manage_hidden_words(
                store, viewer, mode, operation="add", filter_name="Filter", text="club", check=True
            )
        assert exc.value.code == expected
    store.close()


@pytest.mark.parametrize(
    "bad_field,value",
    [
        ("username", "bob"),
        ("filter_name", "Other filter"),
        ("words", []),
        ("status", "preview"),
    ],
)
def test_apply_rejects_unverified_browser_results(tmp_path, monkeypatch, bad_field, value):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    monkeypatch.setattr("threads_cli.hidden_words.RateGate.wait", lambda self: None)
    result = {"username": "alice", "filter_name": "Filter", "status": "verified", "words": ["club"]}
    result[bad_field] = value
    monkeypatch.setattr(
        "threads_cli.hidden_words.BrowserBridge.exchange", lambda *a, **kw: {"result": result}
    )
    store = Store(tmp_path)
    with pytest.raises(ThreadsError):
        manage_hidden_words(
            store,
            "alice",
            "browser",
            operation="add",
            filter_name="Filter",
            text="club",
            apply=True,
        )
    store.close()


def test_check_never_requests_save_and_returns_remote_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADS_BROWSER_BRIDGE", "1")
    monkeypatch.setattr("threads_cli.hidden_words.RateGate.wait", lambda self: None)

    def exchange(self, action, **kw):
        assert action == "hidden_words" and kw["apply"] is False
        assert kw["words"] == ["club", "new phrase"]
        return {
            "result": {
                "username": "alice",
                "filter_name": "Filter",
                "status": "preview",
                "added": ["new phrase"],
                "skipped": ["club"],
            }
        }

    monkeypatch.setattr("threads_cli.hidden_words.BrowserBridge.exchange", exchange)
    store = Store(tmp_path)
    result = manage_hidden_words(
        store,
        "alice",
        "browser",
        operation="add",
        filter_name="Filter",
        text="club,Club,new phrase",
        check=True,
    )
    assert result["added"] == ["new phrase"] and result["input_duplicates"] == ["Club"]
    assert store.db.execute("SELECT count(*) FROM posts").fetchone()[0] == 0
    store.close()
