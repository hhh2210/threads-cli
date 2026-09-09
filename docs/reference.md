# Command reference and verification notes

[English overview](../README.md) · [中文概览](../README.zh-CN.md)

## Browser helper

`runBrowserCli(tab, args, options)` accepts `status`, `doctor`, `search`, `read`,
`user`, `scan`, `reply`, `post`, `notifications`, `inbox`, and `dm`. CLI options
are parsed identically through the helper. Optional helper settings include
`executable`, `viewer`, and `dataDir`.

Live commands require the existing browser driver; preview and cache commands
work directly in the terminal. Run `<command> --help` for the complete flags.

## Text posts and existing-conversation DMs

The following examples show command syntax. Pass live operations as an argument
array to `runBrowserCli`; they cannot authenticate themselves from a terminal.

```sh
threads post --text-file /absolute/path/post.txt
threads post --text-file /absolute/path/post.txt --check-composer
threads post --text-file /absolute/path/post.txt --send
threads dm read 1234567890123456
threads dm send 1234567890123456 --to recipient_handle --text-file /absolute/path/dm.txt --send
threads dm unsend 1234567890123456 --message-id MESSAGE_ID
```

Configure the expected `viewer` first. Post/reply/DM send defaults to a local
preview; `--send` opts into publishing. **`dm unsend` is itself a mutation** and
accepts only a verified CLI-authored message from its local outgoing ledger.
The numeric conversation above is a placeholder.

DM commands verify both participants of an existing one-to-one conversation.
They do not create conversations or support attachments. Private conversation
reads are not copied to the public evidence database; outgoing messages have a
private local ledger for duplicate protection and ownership checks.

Do not repeat an uncertain send automatically. Inspect the conversation or
published permalink first; preserve the outbox ledger across failures.

## CS2 preset

```js
await runBrowserCli(tab, ["scan", "--preset", "cs2", "--pages", "2", "--enrich", "3"]);
```

This opinionated example targets mainland Perfect World players around gold C+,
accepting C/B tiers below B+ and excluding B+/A/S, with a 14-day freshness
preference. It runs queries sequentially, deduplicates posts, and enriches the
strongest leads using the original threads.

```sh
threads candidates --json
threads candidates --include-review --json
threads candidates --include-excluded --include-review --json
```

- `match`: the configured conditions have supporting evidence.
- `review`: criteria are unknown, the post is old, or the person was already contacted.
- `exclude`: a concrete mismatch has been recorded.

Scores rank leads; they are not probabilities of identity or suitability.
Simplified Chinese is a writing-system signal, not proof of mainland residence.
Quoted posts and other commenters' statements cannot become claims by the author.
The author's newer replies can update their platform/rank assessment.

Optional `[cs2] gender = "female"` in the local config enables source-backed
female-only matching. `annotate --gender female --gender-evidence-url URL`
requires genuine self-identification evidence. Names, avatars, writing style,
and how someone addresses another person do not establish gender. Unknown
criteria remain `review`; mainland location needs separate evidence.

`annotate` stores source-backed annotations. `mark-contacted` records an existing
contact locally and sends nothing. `viewer` helps recognize already-sent replies
and must agree with the account used for live operations.

## Coverage, persistence, and errors

- `page_limit_reached`, `limit_reached`, `partial`, and `complete` are distinct.
  `complete` means the returned web connection ended, not a census of Threads.
- `read` captures reply threads included on the page. Collapsed/nested replies
  may be absent; missing payloads and further pages are reported.
- Notification/inbox output includes `has_more`/`completion` for the page's
  bounded window. It does not claim all-history coverage.
- `collection_actions` counts initiated collection actions, not background HTTP
  requests. Processes share a lock and pacing state; do not run parallel collectors.
- Each fetched page is checkpointed before the next request. Failed and unfinished
  runs remain visible through `runs`.
- Normalized evidence is kept in a private directory. Browser credentials, raw
  bootstrap HTML, request headers, and raw GraphQL bodies are not persisted.
- Anonymous mode is a limited crawler-visible window. The CS2 scan requires the
  browser driver because anonymous search may omit relevant Chinese results.

| Exit status | Meaning |
| --- | --- |
| `0` | Success or bounded results |
| `2` | Invalid input |
| `3` | Unavailable content |
| `4` | Browser/login/account mismatch |
| `5` | Collection or bridge failure |
| `6` | Some parser/schema failures |
| `7` | Busy/cooldown |
| `130` | Interrupted |

Inspect structured `error.code` or `errors[]` rather than parsing English error
messages. Keep login/challenge/rate-limit failures distinct from empty results.

## Live verification record — 2026-09-08/09

These are historical checks in the author's Dia/Codex environment:

- Account status, search pagination, post replies, and profiles worked; collapsed
  replies remain outside guaranteed coverage.
- Notifications returned 49 records; the incoming-reply inbox returned 24 reply
  records, with separate categories.
- A standalone post composer was filled, exact text checked, and the test draft
  discarded. No standalone post was published; final publication remains unverified.
- One authorized public reply was published and read back by permalink.
- One authorized DM test was sent and read back with a server message ID. The test
  was withdrawn through the page, and reload confirmed its ID and text absent.
  The CLI unsend path encountered rendering/control failures and is experimental.

## Launch artwork

The README/banner image was generated with the built-in `image_gen` tool.
The exact prompt is saved in [assets/launch-prompt.txt](assets/launch-prompt.txt).
It is a conceptual illustration, not a screenshot of CLI output.
