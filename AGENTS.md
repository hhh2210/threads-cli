# Threads CLI

Use `uv sync --locked`, `uv run pytest`, and `uv run ruff check .`.

Search, account notifications, text posts/replies and existing-conversation DMs
use the already-connected Dia browser. Publishing commands require `--send`;
preview is the default. `dm unsend` accepts only verified CLI-authored messages.
Use ordinary website controls, verify account,
recipient, exact content and the published permalink. Never retry an uncertain
submission automatically. Preserve the outbox ledger across process failures.
Authenticated requests remain in the browser; no session credential export or
HTTP replay. The separate public mode only makes anonymous GET requests.

The browser helper passes only whitelisted post/profile fields over the local
stdin/stdout pipe. Do not read/export cookies or tokens, access the keychain,
or forward raw bootstrap HTML or raw GraphQL requests/responses. Persist only
normalized public evidence and collection provenance. Private conversation reads
are returned without an inbox archive; explicit outgoing DMs have a private
local outbox for idempotency and ownership-checked unsending.

An empty result, partial result, expired session, rate limit, and upstream schema
change are distinct outcomes. Preserve pagination and collection provenance.
Use shared process locking and stop on a login/challenge/rate-limit response.

Preserve original language. Simplified Chinese is a writing-system signal, not
evidence of mainland residence. Do not infer gender from names or pictures.
Keep facts attributed to their author; quoted posts and other commenters must
not silently change a candidate's profile or rank.

CS2 teammate selection requires sourced female identity, mainland location, and
C/B ranks below B+. Unknown identity is review, never a match. Do not infer
gender from names, avatars, or how someone addresses another person.
