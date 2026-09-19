# Browser contract decisions

The API wire contract is unchanged. `lossless-json` parses raw response and
bootstrap text before conversion to JavaScript numbers. Safe integral values
remain numbers; unsafe integral tokens become bigint. Change-feed cursors are
converted directly to decimal strings. They are never rounded through Number.
Item versions currently use PostgreSQL int4 and quoted positive int32 If-Match
preconditions. The client validates safe integral versions; weak GET ETags never
become edit versions. Generated fields remain owned by gen-fields; the browser
type overrides change_seq to reflect lossless decoding. Tests cover values
above 2^53 and the maximum signed int64.

Caches and drafts live only in memory. Query keys include workspace, projection
and query. Writes never automatically replay. Any failed optimistic write rolls
back, then invalidates the workspace scope; this includes lists, ancestors and
moved subtrees. A 409 current representation is reconciled without replacing the
draft. A deliberate retry uses its new item version. Change-feed events are
invalidation hints, not replacement items. Cursor traversal is not a snapshot.

First-route budget uses decimal KB and Brotli quality 11. Count every distinct
entry/static-import JS asset plus all associated CSS. Lazy chunks are checked
individually. The generated route source has one eager list route, lazy login
and item routes. Markdown belongs exclusively to the detail graph.

Theme choice is injected as an HTML attribute; CSS media rules implement system
color/contrast before script execution. Preferences use PATCH /me. No browser
storage is used. Reduced motion follows the OS when the account value is null.

The document reads the workspace sequence before its data queries. Polling starts
from that exact lossless position, so it neither replays the entire old feed nor
misses a write between bootstrap reads. Polling pauses while hidden/unfocused and
backs off failures; full 200-event pages drain before returning to the 10s cadence.
