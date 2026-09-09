"""Threads collection and explicit browser-backed public replies."""

import json
import sys
import tomllib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__
from .bridge import BrowserBridge
from .client import Client
from .dm import request_dm
from .errors import ThreadsError
from .filters import classify_cs2, local_match, since_value
from .models import Post, now_iso
from .rate import RateGate
from .reply import send_post, send_reply
from .store import Store
from .urls import post_url, profile_url

DEFAULT_QUERIES = ("完美搭子", "cs搭子", "cs2 完美")


def make_client(obj):
    return Client(obj["store"].directory, mode=obj["auth_mode"], viewer=obj["viewer"])


def json_option(fn):
    return click.option("--json", "json_output", is_flag=True, help="Emit structured JSON.")(fn)


def output(value: dict, json_output=False):
    if json_output or not sys.stdout.isatty():
        click.echo(json.dumps({"schema_version": 1, **value}, ensure_ascii=False, indent=2))
        return
    console = Console()
    rows = value.get("posts") or value.get("candidates")
    if rows:
        table = Table("User", "Date", "Replies", "Text", "Assessment")
        for row in rows:
            assessment = row.get("assessment", {})
            table.add_row(
                escape(row["username"]),
                (row.get("created_at") or "?")[:10],
                str(row.get("replies") if row.get("replies") is not None else "?"),
                escape(row["text"][:160]),
                assessment.get("status", "") + ": " + ", ".join(assessment.get("reasons", []))
                if assessment
                else "",
            )
        console.print(table)
        for row in rows:
            console.print(row["url"], markup=False, highlight=False)
        console.print({k: v for k, v in value.items() if k not in {"posts", "candidates"}})
    else:
        console.print_json(data=value)


def error_exit(errors: list[dict]):
    if not errors:
        return
    code = errors[0]["code"]
    status = (
        7
        if code in {"rate_limited", "collector_busy"}
        else (
            4
            if code in {"auth_required", "verification_required", "browser_connection_required"}
            else 5
        )
    )
    raise click.exceptions.Exit(status)


def remember_contact(store: Store, result):
    if not result.viewer:
        return
    roots = {p.code: p for p in result.posts if not p.is_reply}
    for post in result.posts:
        if post.username == result.viewer and post.root_code in roots:
            root = roots[post.root_code]
            store.annotate(
                root.username,
                contacted_at=post.created_at or now_iso(),
                note="Detected own reply in fetched thread",
                contact_evidence_url=post.url,
            )


def collect_read(client: Client, store: Store, value: str):
    run_id = store.start_run("read", value)
    try:
        result = client.read(value)
        store.save(result.posts, run_id)
        remember_contact(store, result)
        metadata = {k: v for k, v in result.to_dict().items() if k != "posts"}
        metadata.update(
            {
                "auth_mode": client.mode,
                "transport": "browser_page" if client.mode == "browser" else "public_http",
            }
        )
        store.finish_run(run_id, metadata)
        return result, run_id
    except ThreadsError as exc:
        store.finish_run(run_id, {"completion": "failed", "error": exc.as_dict()})
        raise


def classify_all(
    store: Store, days: int, include_review=False, include_excluded=False, run_id=None, gender=None
) -> tuple[list[dict], dict]:
    posts = store.all_posts(run_id)
    context = store.all_posts()
    annotations = store.annotations()
    assessed = [
        classify_cs2(p, context, annotations.get(p["username"]), days=days, desired_gender=gender)
        for p in posts
    ]
    counts = dict(Counter(p["assessment"]["status"] for p in assessed))
    allowed = {"match"}
    if include_review:
        allowed.add("review")
    if include_excluded:
        allowed.add("exclude")
    assessed = [p for p in assessed if p["assessment"]["status"] in allowed]
    assessed.sort(key=lambda p: (p["assessment"]["score"], p.get("created_at") or ""), reverse=True)
    by_user = {}
    for post in assessed:
        by_user.setdefault(post["username"], post)
    return list(by_user.values()), counts


@click.group()
@click.option("--data-dir", type=click.Path(path_type=Path), envvar="THREADS_CLI_HOME")
@click.option(
    "--auth",
    "auth_mode",
    type=click.Choice(["public", "browser"]),
    default="browser",
    show_default=True,
    help="Public crawler window, or an existing browser session supplied by the helper.",
)
@click.option("--viewer", help="Your public handle, solely to recognize already-sent replies.")
@click.version_option(__version__)
@click.pass_context
def cli(ctx, data_dir, auth_mode, viewer):
    """Search Threads, read account activity, and explicitly publish text posts/replies."""
    store = Store(data_dir)
    ctx.call_on_close(store.close)
    config = store.directory / "config.toml"
    settings = tomllib.loads(config.read_text()) if config.exists() else {}
    viewer = viewer or settings.get("viewer")
    if viewer:
        profile_url(viewer)
        viewer = viewer.removeprefix("@")
    ctx.obj = {
        "store": store,
        "auth_mode": auth_mode,
        "viewer": viewer,
        "cs2_gender": settings.get("cs2", {}).get("gender"),
    }


@cli.command()
@click.option(
    "--live", is_flag=True, help="Also verify the current Threads session over the network."
)
@json_option
@click.pass_obj
def doctor(obj, live, json_output):
    """Inspect local setup; --live verifies actual account access."""
    value = {
        "ok": True,
        "version": __version__,
        "auth_mode": obj["auth_mode"],
        "tracking_viewer": obj["viewer"],
        "data_dir": str(obj["store"].directory),
        "read_only": False,
        "write_commands": ["reply --send", "post --send", "dm send --send", "dm unsend"],
        "cs2_criteria": {"gender": obj["cs2_gender"], "max_rank": "B", "region": "mainland"},
        "browser_transport": "existing Dia page; no credential export",
        "helper_path": str(Path(__file__).with_name("browser_bridge.mjs")),
        "browser_runtime_candidates": [
            str(p)
            for p in sorted(
                (Path.home() / ".codex/plugins/cache/openai-bundled").glob(
                    "chrome/*/scripts/browser-client.mjs"
                ),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        ],
    }
    if live:
        with make_client(obj) as client:
            value["session"] = client.status()
    output(value, json_output)


@cli.command()
@json_option
@click.pass_obj
def status(obj, json_output):
    """Verify public access, or account access when --auth browser is selected."""
    with make_client(obj) as client:
        output({"ok": True, **client.status()}, json_output)


@cli.command()
@click.argument("query")
@click.option("--sort", type=click.Choice(["top", "recent"]), default="top")
@click.option("--pages", type=click.IntRange(1, 10), default=2, show_default=True)
@click.option("--limit", type=click.IntRange(1, 200), default=30, show_default=True)
@click.option("--all", "all_terms", multiple=True, help="Require every repeated term locally.")
@click.option("--exclude", "excluded", multiple=True, help="Exclude any repeated term locally.")
@click.option("--since", help="Local time filter: 14d or YYYY-MM-DD (UTC). Unknown dates excluded.")
@click.option("--max-replies", type=click.IntRange(0), help="Unknown reply counts excluded.")
@json_option
@click.pass_obj
def search(obj, query, sort, pages, limit, all_terms, excluded, since, max_replies, json_output):
    """Collect search results. --all is strict AND; Threads' own query is not."""
    try:
        cutoff = since_value(since)
    except ValueError:
        raise click.BadParameter("Use 14d or YYYY-MM-DD.", param_hint="--since") from None
    store = obj["store"]
    run_id = store.start_run("search", query)
    try:
        with make_client(obj) as client:
            result = client.search(
                query,
                sort == "recent",
                pages,
                limit,
                on_page=lambda posts: store.save(posts, run_id),
            )
            metadata = {k: v for k, v in result.to_dict().items() if k != "posts"}
            metadata.update(
                {
                    "sort": sort,
                    "collection_actions": client.request_count,
                    "transport": "browser_page" if obj["auth_mode"] == "browser" else "public_http",
                    "auth_mode": obj["auth_mode"],
                    "coverage": "returned_web_window",
                }
            )
            store.finish_run(run_id, metadata)
    except ThreadsError as exc:
        store.finish_run(run_id, {"completion": "failed", "error": exc.as_dict()})
        raise
    posts = [p.to_dict() for p in result.posts]
    selected = [p for p in posts if local_match(p, all_terms, excluded, cutoff, max_replies)][
        :limit
    ]
    output(
        {
            "ok": not result.errors,
            "run_id": run_id,
            "query": query,
            **metadata,
            "fetched": len(posts),
            "returned": len(selected),
            "posts": selected,
        },
        json_output,
    )
    error_exit(result.errors)


@cli.command()
@click.argument("url")
@json_option
@click.pass_obj
def read(obj, url, json_output):
    """Read a post and reply threads included in its web page; retain author evidence."""
    with make_client(obj) as client:
        result, run_id = collect_read(client, obj["store"], url)
    output(
        {
            "ok": not result.errors,
            "run_id": run_id,
            **result.to_dict(),
            "reply_scope": "web_page_threads; collapsed replies may be absent",
        },
        json_output,
    )
    error_exit(result.errors)


@cli.command()
@click.argument("handle")
@json_option
@click.pass_obj
def user(obj, handle, json_output):
    """Read a public profile. Do not infer identity from its avatar."""
    with make_client(obj) as client:
        output({"ok": True, "profile": client.user(handle)}, json_output)


@cli.command()
@click.option("--preset", type=click.Choice(["cs2"]), default="cs2")
@click.option("--query", "queries", multiple=True, help="Replace the preset's collection queries.")
@click.option("--pages", type=click.IntRange(1, 5), default=2)
@click.option(
    "--limit", type=click.IntRange(1, 100), default=30, help="Per-query collection limit."
)
@click.option("--days", type=click.IntRange(1, 365), default=14)
@click.option(
    "--enrich", type=click.IntRange(0, 10), default=3, help="Read up to N candidate threads."
)
@json_option
@click.pass_obj
def scan(obj, preset, queries, pages, limit, days, enrich, json_output):
    """Collect sequentially and rank CS2 teammates for mainland Perfect World, C+."""
    if obj["auth_mode"] != "browser":
        raise ThreadsError(
            "browser_connection_required",
            "The CS2 preset uses logged-in browser search; anonymous search has incomplete recall.",
            4,
        )
    store = obj["store"]
    query_results = []
    errors = []
    with make_client(obj) as client:
        for query in queries or DEFAULT_QUERIES:
            run_id = store.start_run("search", query)
            result = client.search(
                query, False, pages, limit, on_page=lambda posts, rid=run_id: store.save(posts, rid)
            )
            metadata = {k: v for k, v in result.to_dict().items() if k != "posts"}
            store.finish_run(run_id, metadata)
            query_results.append(
                {"query": query, "run_id": run_id, "fetched": len(result.posts), **metadata}
            )
            if result.errors:
                errors.extend(result.errors)
                break
        candidates, _ = classify_all(store, days, include_review=True, gender=obj["cs2_gender"])
        enriched = []
        if not errors:
            for candidate in candidates[:enrich]:
                try:
                    result, run_id = collect_read(client, store, candidate["url"])
                    enriched.append(
                        {
                            "url": candidate["url"],
                            "run_id": run_id,
                            "posts": len(result.posts),
                            "completion": result.completion,
                        }
                    )
                    if result.errors:
                        errors.extend(result.errors)
                        break
                except ThreadsError as exc:
                    errors.append(exc.as_dict())
                    break
        requests_count = client.request_count
    candidates, counts = classify_all(store, days, include_review=True, gender=obj["cs2_gender"])
    output(
        {
            "ok": not errors,
            "preset": preset,
            "my_rank": "金C+",
            "days": days,
            "queries": query_results,
            "enriched": enriched,
            "collection_actions": requests_count,
            "transport": "browser_page",
            "auth_mode": obj["auth_mode"],
            "coverage": "returned_web_window",
            "counts": counts,
            "errors": errors,
            "candidates": candidates,
        },
        json_output,
    )
    error_exit(errors)


@cli.command()
@click.option("--days", type=click.IntRange(1, 365), default=14)
@click.option("--include-review", is_flag=True, help="Include incomplete or older leads, labelled.")
@click.option("--include-excluded", is_flag=True)
@click.option("--run", "run_id", help="Restrict candidates to one collection run.")
@json_option
@click.pass_obj
def candidates(obj, days, include_review, include_excluded, run_id, json_output):
    """Rank cached evidence without network or account access. One result per person."""
    rows, counts = classify_all(
        obj["store"], days, include_review, include_excluded, run_id, gender=obj["cs2_gender"]
    )
    output(
        {
            "ok": True,
            "source": "local_cache",
            "evaluated_at": now_iso(),
            "my_rank": "金C+",
            "counts": counts,
            "candidates": rows,
        },
        json_output,
    )


@cli.command()
@click.argument("target")
@click.option("--text-file", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--send", is_flag=True, help="Publish once; omitted means preview only.")
@json_option
@click.pass_obj
def reply(obj, target, text_file, send, json_output):
    """Reply to a post and verify the published author, text and permalink."""
    text = text_file.read_text(encoding="utf-8").rstrip("\n")
    output(
        send_reply(obj["store"], obj["viewer"], target, text, obj["auth_mode"], send), json_output
    )


@cli.command()
@click.option("--text-file", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--send", is_flag=True, help="Publish once; default is a local preview.")
@click.option(
    "--check-composer", is_flag=True, help="Fill, verify and clear a browser draft; no post."
)
@json_option
@click.pass_obj
def post(obj, text_file, send, check_composer, json_output):
    """Create a standalone text post, with preview and browser draft verification."""
    text = text_file.read_text(encoding="utf-8").rstrip("\n")
    output(
        send_post(obj["store"], obj["viewer"], text, obj["auth_mode"], send, check_composer),
        json_output,
    )


def collect_notifications(obj, kind, limit):
    if obj["auth_mode"] != "browser" or not obj["viewer"]:
        raise ThreadsError("browser_connection_required", "Inbox needs a browser and --viewer.", 4)
    with RateGate(obj["store"].directory) as gate:
        gate.wait()
        result = BrowserBridge().exchange(
            "notifications", kind=kind, limit=limit, viewer=obj["viewer"]
        )["result"]
    if result.get("viewer") != obj["viewer"]:
        raise ThreadsError("account_mismatch", "Inbox account did not match.", 4)
    return result


@cli.command()
@click.option(
    "--kind",
    type=click.Choice(["all", "reply", "like", "follow", "repost", "quote", "mention"]),
    default="all",
)
@click.option("--limit", type=click.IntRange(1, 100), default=50)
@json_option
@click.pass_obj
def notifications(obj, kind, limit, json_output):
    """Read the account's returned notification window, optionally filtered by type."""
    output(collect_notifications(obj, kind, limit), json_output)


@cli.command()
@click.option("--limit", type=click.IntRange(1, 100), default=50)
@json_option
@click.pass_obj
def inbox(obj, limit, json_output):
    """Read incoming public reply notifications (not your authored replies or DMs)."""
    output(collect_notifications(obj, "reply", limit), json_output)


@cli.group()
@click.pass_obj
def dm(obj):
    """Read/send in an existing direct conversation, or unsend a verified CLI message."""
    if obj["auth_mode"] != "browser":
        raise ThreadsError("browser_connection_required", "DM requires the existing browser.", 4)


@dm.command("read")
@click.argument("thread_id")
@json_option
@click.pass_obj
def dm_read(obj, thread_id, json_output):
    output(request_dm(obj["store"], obj["viewer"], thread_id), json_output)


@dm.command("send")
@click.argument("thread_id")
@click.option("--to", "recipient", required=True)
@click.option("--text-file", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--send", "publish", is_flag=True, help="Submit once; otherwise preview only.")
@json_option
@click.pass_obj
def dm_send(obj, thread_id, recipient, text_file, publish, json_output):
    text = text_file.read_text(encoding="utf-8").rstrip("\n")
    output(
        request_dm(obj["store"], obj["viewer"], thread_id, recipient, text, publish), json_output
    )


@dm.command("unsend")
@click.argument("thread_id")
@click.option("--message-id", required=True)
@json_option
@click.pass_obj
def dm_unsend(obj, thread_id, message_id, json_output):
    output(request_dm(obj["store"], obj["viewer"], thread_id, message_id=message_id), json_output)


@cli.command("mark-contacted")
@click.argument("username")
@click.option("--at", "contacted_at", help="ISO timestamp or YYYY-MM-DD. Defaults to now.")
@click.option(
    "--evidence-url", required=True, help="URL of your already-sent reply/message evidence."
)
@json_option
@click.pass_obj
def mark_contacted(obj, username, contacted_at, evidence_url, json_output):
    """Record an existing contact locally. This sends no message."""
    profile_url(username)
    try:
        date = datetime.fromisoformat(contacted_at) if contacted_at else datetime.now(UTC)
    except ValueError:
        raise click.BadParameter("Expected an ISO date/time.", param_hint="--at") from None
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    obj["store"].annotate(
        username.removeprefix("@"), contacted_at=date.isoformat(), contact_evidence_url=evidence_url
    )
    output({"ok": True, "username": username, "local_only": True}, json_output)


@cli.command()
@click.argument("username")
@click.option(
    "--region",
    type=click.Choice(["mainland_verified", "outside_mainland_verified", "unknown"]),
    default=None,
)
@click.option("--evidence-url")
@click.option("--gender", type=click.Choice(["female", "male", "unknown"]))
@click.option("--gender-evidence-url")
@click.option("--note", default="")
@json_option
@click.pass_obj
def annotate(obj, username, region, evidence_url, gender, gender_evidence_url, note, json_output):
    """Save a source-backed geographic assessment locally; never infer it from script."""
    profile_url(username)
    fields = {"note": note}
    if region:
        if not evidence_url:
            raise click.UsageError("--region requires --evidence-url")
        fields.update(region=region, evidence_url=evidence_url)
    if gender:
        if not gender_evidence_url:
            raise click.UsageError("--gender requires --gender-evidence-url")
        fields.update(gender=gender, gender_evidence_url=gender_evidence_url)
    if not region and not gender:
        raise click.UsageError("Specify --region or --gender with a source URL")
    obj["store"].annotate(username.removeprefix("@"), **fields)
    output({"ok": True, "username": username, "local_only": True}, json_output)


@cli.command()
@click.option("--limit", type=click.IntRange(1, 100), default=10)
@json_option
@click.pass_obj
def runs(obj, limit, json_output):
    """Inspect collection provenance, including interrupted and partial runs."""
    output({"ok": True, "runs": obj["store"].runs(limit)}, json_output)


@cli.command()
@click.argument("destination", type=click.Path(path_type=Path))
@click.option("--run", "run_id")
@click.pass_obj
def export(obj, destination, run_id):
    """Export normalized evidence as JSON (no cookies or raw HTTP payloads)."""
    if destination.exists():
        raise click.ClickException("Destination exists; choose a new output path.")
    payload = {
        "schema_version": 1,
        "exported_at": now_iso(),
        "posts": obj["store"].all_posts(run_id),
        "annotations": obj["store"].annotations(),
    }
    with destination.open("x", encoding="utf-8") as stream:
        destination.chmod(0o600)
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    output({"ok": True, "file": str(destination.resolve()), "posts": len(payload["posts"])})


@cli.command("import")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@json_option
@click.pass_obj
def import_evidence(obj, source, json_output):
    """Import normalized public post evidence for offline replay. No account access."""
    if source.stat().st_size > 20_000_000:
        raise click.ClickException("Evidence file exceeds 20 MB.")
    try:
        payload = json.loads(source.read_text())
        if payload.get("schema_version") != 1 or not isinstance(payload.get("posts"), list):
            raise ValueError("unsupported schema")
        posts = []
        for row in payload["posts"]:
            post = Post(**row)
            canonical, code = post_url(post.url)
            if code != post.code or canonical != post.url:
                raise ValueError("non-canonical post")
            profile_url(post.username)
            if not isinstance(post.text, str):
                raise ValueError("invalid text")
            for field in (post.created_at, post.collected_at):
                if field and datetime.fromisoformat(field).tzinfo is None:
                    raise ValueError("timestamp requires timezone")
            posts.append(post)
    except (ValueError, TypeError, KeyError, AttributeError, ThreadsError):
        raise click.ClickException(
            "Invalid normalized evidence file; no records imported."
        ) from None
    store = obj["store"]
    run_id = store.start_run("import", source.name)
    store.save(posts, run_id)
    store.finish_run(run_id, {"completion": "imported", "count": len(posts)})
    output({"ok": True, "run_id": run_id, "imported": len(posts), "source": "file"}, json_output)


def main():
    try:
        exit_code = cli(standalone_mode=False)
        if isinstance(exit_code, int) and exit_code:
            raise SystemExit(exit_code)
    except ThreadsError as exc:
        output({"ok": False, "error": exc.as_dict()}, "--json" in sys.argv)
        raise SystemExit(exc.exit_code) from None
    except click.ClickException as exc:
        output(
            {"ok": False, "error": {"code": "usage_error", "message": exc.format_message()}},
            "--json" in sys.argv,
        )
        raise SystemExit(exc.exit_code) from None
    except click.exceptions.Exit as exc:
        raise SystemExit(exc.exit_code) from None
    except KeyboardInterrupt:
        output(
            {"ok": False, "error": {"code": "interrupted", "message": "Collection stopped."}},
            "--json" in sys.argv,
        )
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
