# threads-cli

**Search Threads. Filter precisely. Keep the evidence.**

[English](README.md) · [简体中文](README.zh-CN.md) · [MIT license](LICENSE)

![Conversation cards flowing through a terminal into an organized evidence stack](docs/assets/launch.png)

An unofficial Threads CLI for turning fuzzy social search into a useful local
collection. Search posts, inspect replies and profiles, apply strict filters,
and export source-linked evidence as JSON. Account notifications and explicit
text publishing are also available through the browser bridge.

**Current setup:** authenticated commands require an existing **Dia browser
connection in Codex Desktop** and its trusted Node runtime. Installing the CLI
alone does not provide that connection. Offline commands and a limited anonymous
public-page mode work from a terminal. Other browser environments are unverified.

## Why use it?

Threads search is fuzzy. A query containing two words does not guarantee both
appear in every result. `threads-cli` adds a deterministic second pass:

- **Precise filters:** required terms, exclusions, dates, and reply-count limits.
- **Traceable results:** original text, author, URL, timestamps, and collection status.
- **Reusable local data:** SQLite checkpoints, JSON export, and offline inspection.
- **Bounded collection:** explicit page limits, partial-result reporting, and shared pacing.
- **Explicit publishing:** local previews, account checks, and a persistent outbox
  that prevents blindly repeating an uncertain send.

A built-in CS2 teammate preset demonstrates multi-query collection, source-backed
assessment, and one candidate per person. General search works with any topic.

## Install

Requires Python **3.12+** and [uv](https://docs.astral.sh/uv/). Browser-backed
commands also need the connected browser's trusted Node runtime.

```sh
uv tool install 'git+https://github.com/hhh2210/threads-cli.git'
threads doctor --json
threads --help
```

The distribution is named `larry-threads-cli`; the command is `threads`.
`doctor` reports local setup and helper paths; it does not prove a live login.

For a source checkout:

```sh
git clone https://github.com/hhh2210/threads-cli.git
cd threads-cli
uv sync --locked
uv tool install --editable .
```

## First authenticated search

1. Log in to Threads normally in Dia and connect the existing browser to Codex Desktop.
2. In the trusted Node REPL, use the connection's documented API to obtain a
   **task-owned Threads tab**. Read the runtime's browser, confirmation, and CDP
   documentation. The helper navigates this tab, so use one without an active draft.
3. Import `helper_path` from `threads doctor --json`, then run:

```js
// tab: a task-owned tab from the existing Dia connection.
const { runBrowserCli } = await import("<helper_path from threads doctor>");
const result = await runBrowserCli(tab, [
  "search", "open source", "--sort", "recent", "--pages", "2", "--limit", "50",
  "--all", "open", "--all", "source", "--exclude", "giveaway", "--since", "14d"
]);
nodeRepl.write(result);
```

The helper defaults to `~/.local/bin/threads`. If `uv` installed it elsewhere,
pass `{ executable: "/absolute/path/to/threads" }` as the third argument.
See the [browser workflow](skills/threads-search/SKILL.md) for runtime discovery.
The runtime is supplied by the host; this repository does not ship a standalone
browser driver or create a browser, extension, background service, or public port.

`browser_connection_required` means the command needs this driver. It is not a
request for a token to paste into your terminal. Authentication stays in the
browser: no cookie export, keychain access, password collection, or credential replay.

### Search filters

| Option | Meaning |
| --- | --- |
| `--all TEXT` (repeatable) | Require every term locally, with script normalization |
| `--exclude TEXT` (repeatable) | Reject results containing any excluded term |
| `--since 14d` / `--since YYYY-MM-DD` | Require a known timestamp after the cutoff |
| `--max-replies N` | Require a known reply count at or below the limit |
| `--sort top\|recent` | Select the upstream search surface |
| `--pages N` / `--limit N` | Bound collection pages / returned unique results |

A whole page may be cached before the output limit is applied. These filters
refine observed results; they cannot recover posts the platform did not return.

## Read, inspect, and export

```js
await runBrowserCli(tab, ["read", "https://www.threads.com/@user/post/shortcode"]);
await runBrowserCli(tab, ["user", "username"]);
```

Local commands need no browser:

```sh
threads runs --json
threads candidates --include-review --json
threads export evidence.json
threads import evidence.json
```

Data lives in `~/.local/share/threads-cli`. Use `--data-dir PATH` or
`THREADS_CLI_HOME` for a separate dataset. Imports accept normalized schema-v1
post evidence, not arbitrary HTML. Raw bootstrap pages, request headers, and
raw GraphQL bodies are not saved to the evidence database.

For a **limited anonymous public window**:

```sh
threads --auth public search 'open source' --pages 1 --json
```

Anonymous results can omit posts available when logged in. An empty response
is not proof that no matching posts exist.

## Notifications and publishing

Set your expected public handle in `~/.local/share/threads-cli/config.toml`:

```toml
viewer = "your_handle"
```

This is an account check and tracking preference, not authentication. You can
also pass `{ viewer: "your_handle" }` as the helper's third argument.

```js
await runBrowserCli(tab, ["notifications", "--kind", "all", "--limit", "50"]);
await runBrowserCli(tab, ["inbox", "--limit", "50"]); // incoming public replies
```

Preview a text post or reply locally:

```sh
threads --viewer your_handle post --text-file /absolute/path/post.txt
threads --viewer your_handle reply https://www.threads.com/@author/post/code \
  --text-file /absolute/path/reply.txt
```

Publish only when intended, through the connected browser:

```js
await runBrowserCli(tab, ["reply", "https://www.threads.com/@author/post/code",
  "--text-file", "/absolute/path/reply.txt", "--send"]);
await runBrowserCli(tab, ["post", "--text-file", "/absolute/path/post.txt", "--send"]);
```

The outbox tracks sender, target, and exact text. An uncertain send requires
read-only reconciliation before another attempt. Never automatically retry it.
`inbox` reports incoming public replies; private messages use the separate `dm`
commands for **existing one-to-one conversations**. See [command reference and
verification limits](docs/reference.md) before using experimental writing features.

## What is verified?

Live checks were performed on **2026-09-08/09** in the author's Dia/Codex setup.
They describe that tested environment, not a compatibility guarantee.

| Capability | Status |
| --- | --- |
| Account status, paginated search, post replies, profiles | Live verified; collapsed replies may be missing |
| Notifications and incoming public replies | Live verified; bounded notification window |
| Public text reply | Published and read back with author, exact text, and permalink |
| Standalone text post | Composer checked; final publication not yet live verified |
| DM send to an existing conversation | One authorized test sent and read back |
| CLI DM unsend | Experimental; not end-to-end verified |
| New DM conversations, attachments, likes, follows | Not implemented |

`complete` means the returned web connection ended, **not** that all of Threads
was searched. Page limits, partial results, login failures, rate limits, and
schema changes remain distinct outcomes.

## Development

```sh
uv sync --locked
uv run pytest
uv run ruff check .
node --test tests/*.test.mjs
```

The latest local validation passed 42 Python tests, 14 Node tests, and Ruff.
Bug reports are most useful with the command, structured error code, environment,
and a minimal redacted example. Browser compatibility, collection coverage,
and reproducible publishing checks are useful areas for contributions.

## License and credits

[MIT](LICENSE). Unofficial; not affiliated with Meta.

Built with [Click](https://github.com/pallets/click),
[Rich](https://github.com/Textualize/rich),
[curl_cffi](https://github.com/lexiforest/curl_cffi), Beautiful Soup, and
[OpenCC Python](https://github.com/yichen0831/opencc-python).
The anonymous public-page approach was informed by
[tamnd/threads-cli](https://github.com/tamnd/threads-cli).
