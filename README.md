# Threads CLI

Threads collection, account inboxes, and explicit browser-backed publishing. Built for Larry's
existing Dia browser connection, with a limited anonymous mode for public pages.

The useful part is the second pass: strict local AND/exclusions, timestamps,
reply counts, author updates, one candidate per person, and an SQLite ledger of
what was read. Threads' upstream search itself is still fuzzy and incomplete.

Live verification on 2026-09-08: account status, search pagination, post replies,
and profiles work through the existing Dia connection. Collapsed replies remain
outside the guaranteed coverage.

## Install

```sh
uv tool install --editable .
threads doctor --json
```

Source and locked development dependencies:

```sh
uv sync --locked
uv run pytest
uv run ruff check .
node --test tests/browser_bridge.test.mjs
```

## Live search through Dia

Authenticated collection runs inside the existing browser. The CLI does **not**
read/export cookies, access the keychain, ask for a password, or replay browser
credentials in a separate HTTP client. A short-lived local stdin/stdout bridge
passes only whitelisted public content between the browser helper and CLI.

In Codex Desktop's trusted Node REPL, use the connected browser's documented
API to select Dia and obtain a **task-owned Threads tab**. Read its CDP and
confirmation documentation before first use. `threads doctor --json` reports the
installed helper path and available browser runtime entrypoints.

```js
// tab is an existing task-owned Threads tab in the authorized Dia connection.
const { runBrowserCli } = await import("<helper_path from threads doctor>");
const result = await runBrowserCli(tab, [
  "search", "cs2 完美", "--pages", "2", "--limit", "50",
  "--all", "完美", "--exclude", "faceit"
]);
nodeRepl.write(result);
```

The helper accepts `status`, `doctor`, `search`, `read`, `user`, `scan`, `reply`,
`post`, `notifications`, `inbox`, and `dm`.
It navigates the supplied task tab and observes normal browser pagination.
It creates no browser, extension, background service, public port, or scheduler.
Never pass a tab containing a draft, login form, or unrelated user work.

When the browser requests login, complete it normally in Dia. No password is
ever supplied to the CLI or assistant. `browser_connection_required` means that
a live command was invoked without this browser driver; it is not a missing token
to paste into a shell command.

## CS2 teammate workflow

The built-in `cs2` preset targets mainland Perfect World, **gold C+**, accepting C/B tiers below B+ and excluding B+/A/S, with a
14-day freshness preference. It reads multiple queries sequentially, deduplicates
posts, and can enrich the strongest leads with their original threads.

```js
await runBrowserCli(tab, ["scan", "--preset", "cs2", "--pages", "2", "--enrich", "3"]);
await runBrowserCli(tab, ["read", "https://www.threads.com/@user/post/shortcode"]);
```

Terminal commands that need no browser or account access:

```sh
threads candidates --json
threads candidates --include-review --json
threads candidates --include-excluded --include-review --json
threads runs --json
threads export evidence.json
```

`match` means the stated conditions have evidence. `review` preserves unknown
region/rank, old posts, and already-contacted people without claiming they match.
`exclude` records a concrete mismatch. Scores only rank leads; they are not
probabilities of identity or suitability.

Simplified Chinese is a writing-system preference, **not proof of mainland
residence**. No gender is inferred from pictures, names, or writing. Latest
author replies can change platform/rank assessment; another person's reply or
a quoted post cannot silently become the author's claim.

Set your public handle for detecting already-sent replies in
`~/.local/share/threads-cli/config.toml`:

```toml
viewer = "larryhaoai"
```

This is only a tracking preference, not authentication. The live browser account
must agree with it. Source-backed annotations and existing contacts can be stored
locally with `annotate` and `mark-contacted`; those commands send nothing.

## General search filters

CLI options are parsed by the CLI, including when invoked through the helper:

- `--sort top|recent`: choose the upstream search surface.
- `--pages N`: bound requested result pages; repeated cursors fail explicitly.
- `--limit N`: stop after this many observed unique results; a whole page may be
  cached and locally filtered before output is capped.
- repeated `--all TEXT`: every term must occur locally (script-normalized).
- repeated `--exclude TEXT`: reject any matching term locally.
- `--since 14d` or `--since YYYY-MM-DD`: strict local date filter; unknown dates fail it.
- `--max-replies N`: strict count filter; unknown counts fail it.

## Limits and provenance

- `page_limit_reached`, `limit_reached`, `partial`, and `complete` are distinct.
  `complete` means the returned web connection ended, never a census of Threads.
- `read` captures reply threads included on the page. Collapsed/nested replies
  may be absent; missing reply payloads or further pages are reported.
- `collection_actions` counts initiated collection actions, not the browser's
  background HTTP requests. Collector processes share a lock and pacing state.
- Each fetched page is checkpointed before requesting the next one. Failed and
  unfinished runs remain visible through `runs`.
- Evidence is stored in a private directory as normalized JSON in SQLite. Raw
  bootstrap HTML, request headers and raw GraphQL bodies are not persisted.
- `--data-dir PATH` / `THREADS_CLI_HOME` isolates a different dataset.
- `threads import FILE` accepts normalized schema-v1 post evidence for offline
  replay. It does not import arbitrary HTML, secrets, or executable code.

Anonymous fallback is explicit:

```sh
threads --auth public search cs2 --pages 1 --json
```

It reads the public crawler window and can omit results available to logged-in
users, especially Chinese combinations. An empty anonymous response is not a
definitive no-match. The CS2 scan preset therefore requires the browser driver.

Exit statuses: `0` success/bounded results, `2` invalid input, `3` unavailable
content, `4` browser/login/account mismatch, `5` collection or bridge failure,
`6` some parser/schema failures, `7` busy/cooldown, `130` interrupted. Inspect the
structured `error.code` or `errors[]`; never parse English messages to branch.

## Credits

Uses [Click](https://github.com/pallets/click), [Rich](https://github.com/Textualize/rich),
[curl_cffi](https://github.com/lexiforest/curl_cffi), Beautiful Soup, and
[OpenCC Python](https://github.com/yichen0831/opencc-python).
The public-page approach was informed by [tamnd/threads-cli](https://github.com/tamnd/threads-cli).
These projects deserve support; consider starring the ones you find useful.

Unofficial; not affiliated with Meta. Text replies, standalone text posts, account notifications, and existing-conversation
DM commands are implemented. New DM conversations, following and liking are not implemented.

## Send a public reply

`threads reply TARGET --text-file message.txt` previews the exact recipient and
text locally. `--send` publishes through the same `runBrowserCli` helper used
for collection. Set the expected account with `--viewer` or the local config.

```js
await runBrowserCli(tab, ["reply", "https://www.threads.com/@author/post/code",
  "--text-file", "/absolute/path/message.txt", "--send"]);
```

The command checks sender and recipient, posts once, then reads the new permalink
back to verify the author and exact text. A persistent outbox deduplicates an
identical sender/target/text request. An uncertain attempt requires read-only
reconciliation; repeating the command will not blindly resend. Public replies
are visible to others and are not private messages.

## Account activity and standalone posts

```sh
threads post --text-file /absolute/path/post.txt             # local preview
threads post --text-file /absolute/path/post.txt --check-composer
threads post --text-file /absolute/path/post.txt --send
threads notifications --kind all --limit 50
threads inbox --limit 50                                    # incoming public replies
threads dm read 1234567890123456
threads dm send 1234567890123456 --to test_recipient --text-file /absolute/path/dm.txt --send
threads dm unsend 1234567890123456 --message-id MESSAGE_ID
```

Live commands above still require `runBrowserCli(tab, [...])`; these are not
standalone terminal commands without an attached driver. Preview and cache
commands work directly in the terminal. Inbox commands return the page's bounded
notification window with `has_more`/`completion`; they do not claim all-history
coverage. `inbox` means replies received, not replies authored by the user.

Private message commands currently address an existing numeric conversation ID
and verify its two participants. They do not create conversations or support
attachments. Private conversation reads are not copied into the public evidence
database. The outgoing-DM ledger is local and private.

### Verification on 2026-09-09

- Notifications: 49 records read, reply inbox: 24 reply records, with separate categories.
- Standalone text post: composer filled, exact text verified, test draft discarded.
  No standalone public test post was published; final publication still lacks live validation.
- Public reply: one real invitation was published and read back with its permalink.
- DM send: one explicitly authorized test to a designated recipient was sent and read back
  with a server message ID. The test was withdrawn via the page and a reload
  confirmed both its ID and text absent. CLI unsend encountered rendering/control
  failures and is experimental, not end-to-end verified.
- 42 Python tests and 14 Node tests pass, plus Ruff and diff whitespace checks.

### Updated CS2 preferences

`[cs2] gender = "female"` in the local config enables source-backed female-only
matching. B+ and above are excluded. `annotate --gender female
--gender-evidence-url URL` requires genuine self-identification evidence; a name,
avatar, or the word “brother” cannot supply it. Mainland location still needs
its own evidence. Unknown criteria stay in `review`.
