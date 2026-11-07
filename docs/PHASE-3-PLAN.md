> Implementation entry: November 6, 2026. Base: `4b73427ab63ea1076556fd0b20f9bd2433acd65b`
> (main, merged PR #24). Branch: `codex/phase-3-foundation`.
> This is the accepted implementation scope, not a completion or release claim.
> ADR-031 freezes the engineering contracts; task IDs below remain the work inventory.
> P3-01/P3-02 and the P3-03 schema foundation are this first increment.

# sierx Phase 3 — coding guide

Revision 1.0 · November 6, 2026 · Ready for implementation planning and task execution

Deliver one responsive Kanban board per project and a complete personal Settings area. Include first day of week and display density. Preserve sierx's shared item model, workflow validation, permissions, appearances, query language, and offline delivery.

This guide consolidates the October 20 plan and the decisions made in “Plan sierx phase 3.” It supersedes their unexecuted task breakdowns for this work. It is a coding specification, not a claim that the features, tests, or production release already exist.

## 1. Scope and starting point

### Confirmed product behavior

| Area | Phase 3 requirement |
| --- | --- |
| Boards | One board per project; use the same item population and query semantics as the backlog. |
| Configuration | Administrators rename/reorder columns, group workflow statuses, and set WIP warning limits. Seed columns from the project workflow. |
| Cards | Key, title, type, assignee, priority, blocked state, due date, and compact parent context where applicable. |
| Movement | Pointer/touch dragging, keyboard movement, and a visible Move to action all use the same mutation. |
| Mobile | Swipeable horizontal columns, a column selector, readable cards, and a bottom-sheet move action. |
| WIP | Warn only. Exceeding a limit never blocks an otherwise valid move. |
| Username | Initial self-service claim once; subsequent changes require workspace-admin approval. |
| Display name | Users can change it without a lifetime edit-count limit. |
| Identity labels | Each viewer chooses username or display name for everyone across the interface; display-name fallback when a username is absent. |
| Sign-in | Accept current username or email for local authentication. |
| Avatar | Upload, preview/crop, replace, remove; initially display in personal Settings and the current user's bar. |
| Appearance | Retain all existing appearances and reduced-motion behavior; add Comfortable/Compact density. |
| Regional settings | Follow device timezone by default, with an explicit user override; date format; 12/24-hour clock; first day of week. |
| View preference | Remember each user's List/Board choice for a project. |
| Password | Authenticated local password change; revoke every existing session, including the current one, and require sign-in again. |
| 2FA | Expose existing local enrollment, verification, disable, and activation recovery-code flows accurately. |
| Personal work | Assigned items, created items, and projects the user owns. |
| Personal activity | Authored changes/comments, with current authorization and redaction applied. |
| SSO | Optional provider-neutral preparation around existing local/proxy modes; no mandatory provider or live provider integration. |

Email remains read-only. Custom landing pages and an active-session management screen remain deferred. Also excluded: password-reset email, notification infrastructure, multiple/cross-project boards, sprints, roadmaps, viewed-item tracking, browser-offline mutation queues, and YAML/Git project configuration.

### Inspected baseline and entry work

The reference checkout inspected for this guide was:

the historical Phase 2 reference checkout

Its HEAD was `bd9c4b59167c0ce3ad5d1ac63663f4653601f43e` on `codex/usability-followup`. It is a reference snapshot, not a declaration of the latest main or deployed revision.

The latest inspected Phase 2 chat reported that PR #24 had merged, the subsequent release failed an ARM64 host check, and deployment had not advanced. AMD64-only support was subsequently proposed, with no implementation reported in that inspected turn. Do not silently remove ARM64 or declare Phase 2 complete from this guide.

Task P3-01 must identify the actual implementation base, reconcile existing Gate 2 and seven-day use evidence, and record any current release limitation. The owner's readiness to begin Phase 3 and acceptance of the mobile concept are already recorded; do not repeat settled product questions. Use an isolated checkout/branch if the Phase 2 checkout is still active.

### Prototype reference

The approved interaction concept is available at:

the owner-approved private mobile board prototype (kept outside the public repository)

It contains five sample items. Selection, horizontal swiping, menu moves, WIP warnings, undo, and reset were exercised in Chromium with touch emulation. The owner approved its appearance. This does not establish actual iPhone/Safari testing, production performance, real persistence, workflow enforcement, or dragging.

Reimplement the interaction using sierx's components and tokens. Do not import the prototype's standalone wrapper, sample records, hardcoded colors, ChatGPT state bridge, or preview reset control into the application. Production undo is not confirmed scope: if added later, it must be a new authorized, version-checked workflow operation, never restoration of an old client snapshot.

This external planning copy includes a local checkout path and private preview URL for reference. When producing repository documentation, omit machine-specific paths and deployment hostnames in accordance with the existing topology gate; retain portable behavior/contracts and the verified base/evidence.

## 2. Repository rules and reuse map

Read `AGENTS.md`, `docs/BUILD.md`, `docs/SPEC.md`, `docs/DECISIONS.md`, `docs/UI-DESIGN-SYSTEM.md`, and current acceptance/release records before changing code. Current user instructions supersede older planning recommendations.

Preserve the configured human Git author and committer. Before every commit, verify both identities and the intended message. Do not change `user.name` or `user.email`, and do not add AI attribution or trailers.

| Existing location | Reuse or extend |
| --- | --- |
| `internal/store/mutate.go` | Governed item writes, event sequence allocation, item versions, rank handling, rollups, transactional commit. |
| `internal/store/rank.go` | Project-scoped rank generation and rebalance behavior. |
| `internal/api/transition.go` | Workflow transition, required-field patch, version and error conventions. |
| `internal/api/workflow.go` | Admin-only, versioned project configuration; preserve immutable historical status definitions. |
| `internal/api/projection/registry.go` | Authoritative projected fields and generated frontend types. |
| `internal/api/validation.go` | Existing ISO date, custom-field, membership, and item validation. |
| `internal/api/me.go` | Existing display-name/theme/motion updates. Keep credential writes outside this endpoint. |
| `internal/api/auth/local.go`, `password.go`, `totp.go` | Credential lookup, password policy/hashing, sessions, local TOTP. |
| `internal/api/auth.go`, `internal/api/totp.go` | Authenticated HTTP routes and security response handling. |
| `web/src/api/client.ts`, `feed.ts` | Request handling, exact sequence decoding, query cache, optimistic updates, change polling. |
| `web/src/components/Shell.tsx` | Bootstrap identity, appearance, session expiry, header, polling. |
| `web/src/routes/List.tsx`, `Settings.tsx` | Project selection, backlog query behavior, current admin settings. |
| `web/src/components/DetailEditor.tsx`, `Fields.tsx` | Due/start-date and custom-field editors; replace calendar behavior through shared controls. |
| `web/src/routes/table.ts` | Canonical browser routes; update through route generation. |
| `web/design/`, `web/src/themes/catalog.ts` | Semantic component styles, tokens, 23 appearances. |
| `Makefile`, `test/`, `web/scripts/` | Real gates, fixtures, generated-code checks, budget checks, browser tests. |

Important inspection findings:

- `item.due_date` is a PostgreSQL `date`. It is not a timestamp.
- There is no standalone built-in priority field in the inspected item projection. Custom fields are configured through `field_def`.
- “Blocked” exists as a workflow status suggestion; blocker links also exist. A card's blocked indicator needs a defined semantic rule.
- Project owners are metadata. The current permission model has `member` and workspace `admin`; it has no separate project-admin role.
- `PATCH /me` currently accepts only display name, theme, and reduced motion. New preferences require storage, validation, projections, and bootstrap work.
- The current native date inputs cannot be relied on to honor an application-specific first day of week.
- There is no Account or Board browser route in the inspected route table, and no dnd-kit dependency in the inspected package manifest.
- `store.Mutate` invokes its accumulation callback before opening its database transaction. Do not put race-sensitive board validation in that callback and assume it runs under transaction locks.

## 3. Kanban implementation contract

### 3.1 Configuration and authority

“Project administrator” means a user already authorized to edit that project's configuration under the current workspace-admin rule. Members can move/edit items within existing permissions; ownership alone grants no new configuration power.

Use a versioned board definition carried with the project configuration. Proposed normalized structures are `board_column` and `board_column_status`, keyed by project and configuration version. This is one logical board with historical configurations, not multiple saved boards.

Each column needs a stable identity, name, position, mapped statuses, nullable positive WIP limit, and optional default destination status. Use project-scoped foreign keys/constraints so a status cannot belong to another project or to two columns in the same snapshot.

Engineering defaults:

- Initial layout: one column per workflow status, in configured order; no WIP limit by default.
- Every configured status must have a mapping when a configuration is saved.
- Adding a workflow status automatically appends its initial column in the same configuration change. An administrator can group it afterward.
- Existing items must never disappear because of a mapping error. A defensive read may expose an “Unmapped” recovery column and an admin notice, but invalid configuration saves are rejected.
- A grouped column's default status must belong to that column. If it is not a legal destination for the selected item, offer the legal mapped alternatives. Never choose a status by array order.
- Renaming a column changes its label, not the underlying status identity or historical item records.
- Removing a column requires remapping its statuses in that same save; it does not delete items.
- Configuration edits use stale-write protection. Preserve a rejected draft and show the latest configuration.
- Workflow edits carry board configuration forward, and board edits carry the rest of the project configuration forward. Cover both directions in tests.

### 3.2 Card data and semantics

Use projected reads. Cards must not fetch Markdown bodies, whole activity histories, avatars, or entire arbitrary custom-field dictionaries just to display a few labels. Return enough identity/version/rank information for safe actions. Avoid per-card API calls.

Display the key, title, type, assignee, priority, due date, and relevant parent context. Display the actual status when grouping statuses makes it otherwise ambiguous. Use explicit “Unassigned,” “No priority,” and “No due date” states rather than invented values. Parent key is sufficient initially; add a title only through a bounded authorized projection.

**Priority — engineering default:** use a project `select` custom field as the canonical source, with the board configuration identifying its field key. Reuse a compatible existing `priority` definition. Where absent, the initial configuration can provision an optional `priority` select with Low, Normal, High, and Urgent; existing item values remain null. Never replace an incompatible field definition or migrate arbitrary values by guessing. Surface a configuration issue and allow an admin to choose a compatible field. Add the narrow editor needed to set it through the existing validated item `fields` patch.

**Blocked — engineering default:** an active/nonterminal item is blocked when its status is explicitly configured as blocked, or an incoming `blocks` link comes from a live, unfinished item. Done/cancelled blockers do not keep a target blocked. Do not infer this from a display-name substring. A seeded status whose stable key is `blocked` may be selected during initial configuration; later behavior uses explicit configuration. Apply existing link authorization and lifecycle rules; do not reveal inaccessible or redacted blocker details.

Keep these derivations server-authoritative and bounded. Add the necessary projection/type/index work rather than manufacturing different rules in Board, List, and Item.

**Due dates:** render the stored calendar date using the user's display format. “Today” and “Overdue” compare that date with the current calendar date in the user's effective timezone. The stored date does not change. Done/cancelled items do not receive an active-overdue warning. Pair warnings with text, not color alone.

### 3.3 Reading, filtering, counts, and order

The project and `sxq` filter define the same matching items as List. Preserve the query when switching views. All item types can appear. Archived/deleted/redacted items follow existing visibility rules.

Separate these counts in the response:

- Total live items in a column under the authorized project scope, independent of the viewer's search filter.
- Items matching the current filter.
- Items currently loaded/rendered.

WIP uses the first count. Pagination and virtualization must never make a column look below its limit when unloaded or filtered-out items exist.

Page columns independently or use a documented bounded multi-column first page. Bind cursors to project, filter, sort, column, and configuration version; reject incompatible reuse. Fetch additional cards on demand. Do not make “500-item support” mean rendering or loading every full item at once.

Reuse the existing project-wide rank model. Rank is not comparable across projects. The board is a filtered presentation of that order, and reordering can affect the corresponding List order.

Define placement by stable item anchors, not visible row indices. A proposed placement shape is `before/after` plus `anchor_key`, or `start/end` of the destination column. Resolve actual adjacent ranks server-side in the full project order, excluding the moving item. A column-end move finds the actual last item, including unloaded items. Validate stale/missing/wrong-project/wrong-column anchors and return an explicit conflict instead of guessing a new location.

### 3.4 One atomic move

Add one governed store operation for a board move. A status transition and its rank change must commit together, with any required-field patch, item version, history events, and rollups.

Required inputs:

- Item identity and expected item version, using the existing `If-Match` convention.
- Expected project/board configuration version.
- Destination column and explicit target status when needed.
- Stable placement anchor or start/end intent.
- Optional patch completing workflow-required fields.

An API preflight may improve messages, but the store transaction must recheck all race-sensitive conditions. Validate membership/visibility, configuration, source/destination status, allowed transition, required fields, and rank anchors before writing. Extend the store's transaction stage or add an explicit internal operation; do not use two independent client requests or direct API-layer item writes.

Preserve the existing lock order. Specify project/configuration and item locks in the implementation decision record, including their relationship to workspace sequence allocation and concurrent configuration edits. Test the interleavings rather than relying solely on preflight validation.

Within-column reorder preserves status. Moving to a different column respects the workflow even when drag looks physically possible. An over-limit result is a successful move with warning metadata; invalid workflow or missing fields remain real validation failures.

A missing required field opens a focused form. Retain entered values on error. Begin optimistic movement only after the user has supplied the intended transition and required values.

### 3.5 Client state and interaction

Use the existing query cache and change feed. Keep a pending operation associated with the item/version. Reconcile returned canonical items, counts, ranks, and configuration versions on success.

- Failure restores only the failed operation's effect; it must not overwrite newer server changes.
- A network timeout is an uncertain result. Refetch/reconcile before offering a retry; do not replay a mutation blindly.
- A conflict retains the user's intent and form draft while showing the latest item/configuration.
- If a successful transition causes the item to stop matching the filter, announce that it moved and no longer matches. Do not reinsert it incorrectly.
- Preserve column scroll, meaningful keyboard focus, and open drafts during background refresh.
- Retain focused polling at the existing 10-second interval, pause when hidden, and back off on failures. Do not introduce WebSockets.

Desktop shows a horizontal board within the available application shell. On narrow screens, show one readable column with a small next-column preview, horizontal swipe, and a native column selector. Avoid horizontal overflow of the whole page.

Build keyboard/menu movement first, then pointer and touch drag using the same command. Touch must distinguish scrolling from dragging through a deliberate activation gesture. Support Escape/cancel, visible targets, safe edge scrolling, focus restoration, and reduced motion. A visible Move to action remains available regardless of drag capability.

Keep the mobile move sheet within the visible viewport and safe areas, even when the column is longer than the screen. Use the existing dialog primitives for focus and dismissal. Support text zoom and screen-reader announcements. Comfortable/Compact modes must preserve roughly 44 CSS-pixel effective touch targets.

## 4. Personal Settings and preferences

### 4.1 Navigation

Use the visible name **Personal settings** in the account menu. Keep the existing admin `/settings` surface recognizable as workspace/project administration.

Proposed route family:

| Route | Contents |
| --- | --- |
| `/account` | Profile, username/request state, display name, read-only email, avatar, person-label preference. |
| `/account/appearance` | Appearance, reduced motion, display density. |
| `/account/preferences` | Timezone, date format, clock format, first day of week, and view-memory behavior. |
| `/account/security` | Password, local 2FA, provider-managed security information. |
| `/account/work` | Assigned to me, Created by me, Projects I own. |
| `/account/activity` | Authored changes/comments. |
| `/board?project=…&q=…` | Project board. |
| Existing admin settings | Board configuration and username-change review. |

These paths are implementation proposals. Add canonical routes, generated server routes, bootstrap handlers, lazy imports, tests, and reserved-prefix handling together. Check existing project-prefix collisions before reserving ACCOUNT or BOARD; do not silently rename projects.

### 4.2 Preference values and defaults

Defaults below are engineering choices, distinct from user-mandated features.

| Preference | Stored contract | Initial behavior |
| --- | --- | --- |
| Timezone mode | `device\|override` | `device` |
| Timezone override | Nullable validated IANA identifier | Ignored while following device; retain the last chosen override for convenience. |
| Date format | `system\|iso\|dmy\|mdy` | `system`; show examples for every choice. |
| Clock | `system\|12h\|24h` | `system` |
| First day of week | Integer 0–6, Sunday = 0 | Monday = 1; allow all seven choices. |
| Display density | `comfortable\|compact` | `comfortable` |
| Person labels | `display_name\|username` | `display_name` |
| Project view memory | `list\|board`, keyed by user/workspace/project | List until explicitly changed. |

Persist these choices server-side so they follow the user across sessions/devices. A device-following timezone mode travels with the user; the resolved device zone does not become a fixed account override.

Prefer one versioned preferences record per user and a separate per-user/project view record. Keep existing theme/motion storage authoritative unless there is a documented migration; do not maintain two competing sources for the same value. Return safe preferences in self/bootstrap data. Keep them out of member rosters and item actor payloads.

Use a versioned, partial-update endpoint for the new settings. Reject unknown enum values, invalid timezone names, and out-of-range week starts. Missing fields remain unchanged. A stale save returns current preferences and preserves the user's draft. Save sections independently and give visible success/error feedback.

### 4.3 Time and date behavior

Add shared formatting helpers for timestamps, date-only values, relative due-state labels, and week-grid layout.

- Timestamps remain absolute instants; display them in the effective timezone and selected clock format.
- Date-only values remain `YYYY-MM-DD` on the wire and in storage. Do not pass them through a local/UTC timestamp conversion that changes their day.
- Following device: determine the browser's current zone on startup and recheck on page resume/focus. Account override: use the validated stored zone.
- If zone detection fails, use a documented UTC fallback with a visible indication in Settings.
- Zone validation, timezone choices, and date formatting must work with locally available runtime/bundled data. Do not introduce an Internet-dependent timezone service or calendar asset.
- Apply timezone rules across item activity, comments, audit/activity timestamps, and personal views; do not localize machine-facing API/export values.
- Refresh Today/Overdue labels when the effective local day changes and when the page resumes.
- Cover DST changes, zones on either side of UTC, midnight, leap dates, and month/year boundaries.
- Do not silently reinterpret existing shared `sxq` date semantics based on each viewer. Display preferences alone must not change what a saved query means.

### 4.4 First day of week must work

This is a working preference, not a placeholder for future sprint screens. Apply it to the date-selection calendars used for due/start dates and configured date custom fields.

Native `input type=date` can follow browser/OS behavior instead of the chosen app preference. Introduce a shared, lazy calendar/date-field control where necessary, using the existing accessible interaction primitives.

The calendar must rotate weekday headings and cell placement together. Preserve the selected date when the week start changes. Support keyboard day/week/month movement, clear/cancel, visible focus, accessible full-date names, and a typed-entry path.

Keep typed entry unambiguous: initially use an explicitly labeled `YYYY-MM-DD` input alongside the calendar, while display labels follow the chosen date format. Do not guess whether an ambiguous numeric input is month-first or day-first. A future localized input parser can be specified separately.

This work does not add a calendar page, sprints, week-number rules, or new scheduling features.

### 4.5 Density and remembered view

Density changes shared spacing and row/card padding through sierx's semantic tokens/classes. Apply it consistently to lists, board cards, navigation, settings controls, and data tables where appropriate. Preserve text legibility, Markdown reading layout, focus rings, and touch targets; Compact is not permission to shrink everything.

Recalculate measured virtualized rows/columns when density changes. Preserve the anchor item and scroll position. Include density in initial bootstrap styling so pages do not visibly switch spacing after loading.

Remember view choices per user and project. Project navigation opens the remembered view and retains the common filter. An explicit List or Board URL takes precedence; never redirect a shared link just because a different view was remembered. Do not remember arbitrary query strings as a hidden default filter. List-only contexts, such as workspace-wide results, remain List.

## 5. Identity, avatars, security, and personal views

### 5.1 Username and labels

Retain stable account UUIDs everywhere. Proposed username grammar: 3–32 lowercase ASCII letters/digits/underscore/hyphen, beginning with a letter, with case-insensitive uniqueness and reserved system handles. Exclude `@` so login identifiers are unambiguous.

Existing accounts migrate with no invented username; email sign-in continues. Record the initial claim explicitly so clearing a value cannot reopen self-service claims. Use database uniqueness and transactional checks for simultaneous claims.

Later edits create a pending request. An authorized workspace admin approves/rejects against the current account version, current membership, current username, and available new handle. Keep the old handle until approval. Record requester, reviewer, outcome, timestamps, and optional reason. Prefer one pending request per account; replace/cancel explicitly rather than silently accumulating conflicting requests.

Reserve retired handles against reassignment to a different account. They are not automatic login aliases. Document any policy allowing the original account to reclaim one.

The current model is single-workspace operation with instance-wide login identifiers. Do not generalize rename authority across multiple workspaces without revisiting that authorization contract.

Use one shared person-label helper across assignments, comments, activity, history, owners, and menus. Display-name changes do not alter historical ownership. Do not expose email, password data, or authentication metadata in roster/actor projections.

### 5.2 Avatar

Keep the agreed 128 × 128 thumbnail and 32–40 CSS-pixel user-bar display. The stored-image target is at most 20 KB; prove the chosen encoder's behavior before treating it as a release guarantee.

Bound upload bytes, decoded pixel count, format, processing time, and output size. Decode/re-encode accepted raster formats and strip unnecessary metadata. Do not serve uploaded originals, SVG, or animation in this first increment. Choose and document exact limits and allowed input formats before implementing the endpoint.

Use existing account authorization with self-only mutations. Small normalized-image storage in PostgreSQL is the initial engineering direction. Include it in backup/restore, replacement, removal, lifecycle, and export policies.

The header reserves space and renders initials immediately. Avatar loading never gates page content. Use authenticated, versioned image delivery with a private cache policy and correct account-switch/deactivation behavior. Keep editing/processing dependencies out of the first-route bundle. Failed replacement preserves the existing image.

### 5.3 Password and 2FA

Keep credential operations in the auth service and its narrowly scoped database privileges. The application runtime must not gain password-hash or TOTP-secret access.

Password change requires an authenticated local account, current password, new password validation using the existing policy, and a fresh factor when 2FA is enabled. Preserve current hash parameters and abuse controls.

Commit the new hash and revoke all sessions atomically. Clear the current cookie and show a deliberate “Password changed; sign in again” outcome. Concurrent login/session creation must not create a fresh session from an old-password check after revocation. Serialize or revalidate against the locked current credential state; add a race test for this case.

For a lost response, reconcile by attempting normal sign-in; do not automatically resubmit a password change with a stale current password. Do not log credential bodies or put secrets in browser-persistent state.

Reuse local TOTP enrollment/verify/disable. Provide a safe status response, never existing secrets or historical recovery codes. Activation recovery codes appear once and remain visible until acknowledged; background session-expiry handling must not discard them before the user can save them. Respect existing replay and recovery-code consumption rules.

Provider-only accounts see accurate provider-managed security guidance. A new session-list/revoke-other-devices screen is deferred.

### 5.4 My work, activity, and SSO preparation

Derive “Created by me” from authenticated creation events, not current assignment or the first surviving edit. Any materialized creator index must preserve true provenance and lifecycle/redaction behavior. Missing provenance is displayed honestly.

Build personalized item views using the shared query machinery. Add a creator predicate and project-owner filter only through their normal grammar/validation/golden contracts. Paginate authored events/comments with stable cursors and no duplicate activity entries.

Apply current membership, deletion, holds, and redaction policies when reading activity. A new activity endpoint must not reveal values hidden by existing views.

For SSO preparation, separate stable internal identity from local credentials and provider claims. Define capability metadata around the working local/proxy modes. Future external links use provider identity, with verified issuer/subject for OIDC, and explicit linking after suitable authentication/provisioning. Never auto-link solely because an email matches.

No inactive sign-in buttons or unimplemented callback routes. Disabled SSO makes no provider requests. Keep trusted-proxy peer checks intact. Native provider integration and simultaneous local-plus-native-SSO sign-in are separate future deliverables.

## 6. API and schema task contract

Exact route names below are proposed. Finalize them in P3-01, then generate types/fixtures from the chosen contract. Do not claim these endpoints already exist.

Preserve the client's exact handling of large sequence numbers when adding Board and Activity DTOs. Do not coerce change-feed cursors or history sequences into unsafe JavaScript numbers.

| Surface | Proposed API | Key protections |
| --- | --- | --- |
| Board read | `GET /api/v1/projects/{key}/board` | Project scope, sxq parity, projections, independent totals, bound cursors. |
| Board configuration | `GET/PUT /api/v1/projects/{key}/board-config` | Admin only on write; shared project-config version and snapshot carry-forward. |
| Move | `POST /api/v1/items/{key}/board-move` | Item `If-Match`, config version, atomic status/fields/rank. |
| Preferences | `GET/PATCH /api/v1/me/preferences` | Self only; partial update; ETag/version conflict; strict values. |
| View memory | `PUT /api/v1/me/project-views/{key}` | Self and authorized project; idempotent view value. |
| Initial username | `POST /api/v1/me/username` | Claim-once transaction and uniqueness. |
| Rename request | `GET/POST /api/v1/me/username-requests` | Self scope; pending request lifecycle. |
| Rename review | `GET /api/v1/admin/username-requests`; explicit approve/reject actions | Workspace-admin authority and atomic decision. |
| Security status | `GET /api/v1/me/security` | Safe capability/status metadata only. |
| Password | `POST /api/v1/auth/password` | Reauthentication, factor, auth-only writes, all-session revocation. |
| Avatar | `GET/PUT/DELETE /api/v1/me/avatar` | Self mutation, bounded data, authenticated versioned delivery. |
| Activity | `GET /api/v1/me/activity` | Authored/currently authorized records; stable cursor. |

Existing `GET/PATCH /me`, local login, and `/auth/totp/enroll|verify|disable` need compatible extensions rather than duplicate security implementations.

Retain current problem-response conventions: malformed input, forbidden scope, absent/inaccessible resources, missing preconditions, conflicts, and invalid transitions remain distinguishable. Do not return raw SQL or credential details. Each new HTTP route needs golden coverage and each browser route needs direct-navigation/bootstrap coverage.

Migration families:

1. Versioned board columns/mappings, card metadata configuration, and necessary indexes.
2. New user preferences and per-project view memory with scoped policies.
3. Nullable username, claim marker, reservation/request/audit records.
4. Bounded avatar storage and lifecycle/export integration.
5. Narrow auth-service grants/functions for password changes and race-safe session creation.

Choose migration numbers from the accepted base. Follow existing up/down and schema-snapshot conventions in scratch databases. Never run destructive migration proofs against production. Preserve existing email login and profile values. New account-owned records must participate in deactivation, deletion/anonymization, backup, restoration, and export behavior; new user/workspace foreign keys need tenant-boundary tests.

## 7. Ordered implementation tasks

Each row is a bounded work unit. Keep schema, backend, and UI changes reviewable; do not treat a whole phase as one commit. Proposed files may be renamed to fit the accepted base.

| ID | Work and likely location | Completion evidence |
| --- | --- | --- |
| P3-01 | Reconcile base/entry record; add repository Phase 3 plan and decision records; freeze route, priority/blocked, and preference contracts. | Exact base recorded; supported release matrix identified; product decisions preserved; no unresolved contract hidden in code. |
| P3-02 | Wire Phase 3 gate scaffolding, budgets, route checks, and dependency review. | New checks/proofs fail for planted violations; existing Gate 2 remains meaningful. |
| P3-03 | Board/configuration schema and policies in migrations/schema/tests. | Scoped constraints, historical snapshots, migration round trip, no duplicate mappings. |
| P3-04 | Board config persistence and workflow carry-forward. | Seeded defaults; new statuses remain visible; stale edits rejected; both edit directions preserve data. |
| P3-05 | Board-config API and admin editor. | Member write denied; admin saves/groups/reorders columns; drafts survive conflict. |
| P3-06 | Card metadata definitions, bounded projections, priority editor, blocker derivation. | Null/legacy/custom-field collisions handled; blocker lifecycle correct; no per-card requests. |
| P3-07 | Project board query/cursors/counts. | List/Board query parity; full-scope WIP; bounded pages; unauthorized scopes rejected. |
| P3-08 | Atomic store move, transaction validation, rank anchors and event behavior. | Status/rank/fields commit together; races, rollback, rebalance, rollups and versions tested. |
| P3-09 | Move HTTP API and fixtures. | Legal/illegal transitions, required fields, conflicts, anchor checks, warning success. |
| P3-10 | Lazy Board route, shell integration, loading/error/empty states. | Direct URLs, filters, item detail/back navigation, bounded rendering, all appearances. |
| P3-11 | Menu/keyboard move and required-field completion form. | Separate keyboard-only and menu-only tests, retained drafts, visible restored focus. |
| P3-12 | Pointer/touch drag and mobile swipe/selector. | Shared mutation; scroll/drag distinction; cancel/edge scrolling; actual iPhone walkthrough. |
| P3-13 | Preferences/view-memory schema, policies, safe DTO/bootstrap integration. | Defaults, cross-account boundaries, migrations, lifecycle/export inventory. |
| P3-14 | Versioned preferences API and project view-memory API. | Enum/timezone validation, stale saves, unrelated field preservation, explicit-URL precedence. |
| P3-15 | Shared timestamp/date-only/effective-timezone formatting. | DST, midnight, leap/date boundaries; due dates never shift; consistent surfaces. |
| P3-16 | Shared date/calendar control honoring first day of week. | All seven week starts, typed ISO entry, keyboard/screen-reader navigation, start/due/custom-date integration. |
| P3-17 | Density tokens, bootstrap, virtualized measurement, view-memory navigation. | Both densities across 23 appearances; stable scroll/focus; touch targets; no initial spacing flash. |
| P3-18 | Username/claim/request/reservation schema and privileges. | Nullable migration; unique claims; no credential privilege widening. |
| P3-19 | Claim/request/admin-decision transactions and API. | Simultaneous claims; stale/duplicate decisions; active membership; retirement reservations; audit. |
| P3-20 | Username-or-email sign-in through local auth. | Both identifiers resolve the same UUID, password, factor and rate-limit rules; old handle rejected. |
| P3-21 | Shared person-label helper and member/actor projections. | Viewer preference works everywhere; no roster email/security leakage. |
| P3-22 | Personal Profile/Preferences/Appearance routes and forms. | Real saved controls including week start and density; sign-in/device persistence; errors retain drafts. |
| P3-23 | Admin username-request queue. | Correct role visibility; approve/reject/pending/stale outcomes; no email dependency. |
| P3-24 | Security status/password-change service, route, session-race protection. | Wrong password/factor rejected; every session revoked; old-password concurrent login cannot survive. |
| P3-25 | Personal Security UI and existing TOTP flows. | Activation/recovery acknowledgement/sign-in, disable, password success, provider-managed state. |
| P3-26 | Creator/activity queries, indexes, sxq predicate and project-owner filtering. | True provenance, authorization/redaction, stable cursors, populated query timing. |
| P3-27 | My work and My activity routes. | Assignment/creation/ownership remain distinct; preferred names/timestamps and empty states. |
| P3-28 | Avatar schema/storage and account lifecycle/recovery contracts. | Self scope, output-size bounds, replacement/removal, restored image/export handling. |
| P3-29 | Avatar processing, API, private versioned delivery. | Malformed/oversized/decoded-limit cases, thumbnail output, cache/account switching. |
| P3-30 | Avatar editor and nonblocking header fallback. | Crop/preview/replace/remove; reserved size; failed replacement preserves current image. |
| P3-31 | Provider-neutral auth capability seam around local/proxy modes. | Both existing modes pass; disabled SSO has no external traffic; no auto-link or trust regression. |
| P3-32 | Final account menu and shell integration. | Personal/admin settings distinct; keyboard/mobile navigation; appearance, drafts and expiry behavior preserved. |
| P3-33 | Full acceptance, reference-hardware performance, migration/recovery/release evidence. | Gate 3 and applicable existing delivery checks green; owner review and actual-phone findings recorded. |

Dependencies: P3-03–09 precede full Board interactions. Preferences P3-13–17 and identity P3-18–21 precede their complete Settings screens. Security and avatar service work precedes their UI. P3-33 follows all included features. This ordering does not authorize extra agents or new chats.

## 8. Verification and release acceptance

### Existing commands

The inspected repository provides the following commands. Run from the implementation checkout in its supported development environment with the pinned tools and disposable test database prepared:

```sh
make test-store
make test-api
make test-sxq
make test-golden
make gate-gen
make gate-rls
make web-test
make web-build
make gate-routes
make gate-bundle
make gate-browser
make gate-2
```

Use focused tests while developing and the required full gates at integration. `make check` is a fast loop, not proof of phase acceptance. Create `make gate-3` and its required proof wiring; it is specified by the build guide but not implemented in the inspected Makefile. Do not invent claims that proposed commands have passed.

### Performance targets

- Preserve first-route JavaScript ≤250 KB Brotli, first-route CSS ≤20 KB Brotli, and each lazy chunk ≤60 KB Brotli.
- Keep Board, Account, avatar editor, date picker, and drag dependencies lazy where appropriate. Measure the actual pinned drag package; old size estimates are not evidence.
- Meet the existing Board server-time p95 target below 150 ms with a 500-item projected fixture on explicitly identified reference hardware.
- Define the fixture distribution, columns, filter, page sizes, warmup/sample method, and exact request scope. Include totals/metadata costs. Record first-load and additional-column/page behavior separately.
- Do not substitute browser end-to-end latency for the server-time requirement. Record browser responsiveness as additional evidence, including a midrange phone and a delayed network.
- Verify immediate move feedback and usable scrolling/selection with populated columns, both densities, long titles, and pending/background updates. No blanket render of all cards or activity rows.

### Required acceptance scenarios

1. **Board parity:** filtered List and Board identify the same authorized items; deleted/archived/redacted cases match existing policy.
2. **WIP:** exceed, lower, and remove a limit; filtered and unloaded items still count; concurrent moves reconcile correctly; warnings never become extra confirmation gates.
3. **Workflow:** legal, illegal, grouped-status, and required-field moves; same-column reorder; concurrent configuration edit; atomic rollback.
4. **Ranks:** filtered anchors, empty columns, top/end moves, deleted or moved anchors, unloaded neighbors, project boundary and rebalance.
5. **Recovery:** failed save, uncertain timeout, stale item/configuration, lost permissions, expired session, and delayed polling without lost focus/drafts.
6. **Accessibility:** independent keyboard-only and menu-only moves; scrolled focus not obscured; screen-reader announcements; no color-only meaning; reduced motion; zoom.
7. **Mobile:** actual iPhone/Safari swipe, selector, menu, drag activation, long-board move sheet, safe areas, both orientations/densities, and back navigation. Record device/OS/browser.
8. **Preferences:** reload/new-session/second-device persistence; device zone changes versus override; valid/invalid IANA identifiers; all date/clock/week-start options.
9. **Dates:** due date unchanged across timezone switches; local midnight updates; DST gaps/overlaps; leap day/year rollover; all date pickers honor week start.
10. **Density:** every appearance remains usable; virtual row measurement updates; no clipping or smaller effective touch targets.
11. **Identity:** simultaneous initial claims, admin approval races, retired handles, viewer-wide name labels, username/email login and unchanged UUID references.
12. **Security:** current-password/factor enforcement, session invalidation including races, provider-managed cases, TOTP recovery acknowledgement, no secret persistence/logging.
13. **Avatar:** malformed images, excessive input/decoded size, normalized output, private caching/account switch, initials fallback, failed replacement, backup/restore/lifecycle.
14. **Personal views:** true creator evidence, authored activity pagination, missing/redacted provenance, current permissions, correct timezone/name presentation.
15. **SSO preparation:** working local/proxy behavior unchanged, no automatic account linking, no disabled-provider network traffic.
16. **Delivery:** required existing architecture/host checks for the accepted release matrix; no fabricated pass for a failed or deferred architecture.

### Completion record

Record the candidate commit, migration list, supported architectures, gate outputs, bundle sizes, benchmark environment/results, real-phone findings, known limitations, and owner review in the repository's normal progress/acceptance records.

Preserve the current release/backup procedure. Exercise migrations and restore against disposable copies before a production update. Do not represent reverting application code as sufficient recovery after an incompatible schema migration.

Phase 3 is complete when the included features work against real APIs, the required automated evidence passes, the owner can use Board and Personal settings on desktop and phone, and remaining limitations are explicitly accepted. A green prototype or a successful source build alone is insufficient.

## 9. First coding session

1. Read the repository rules and this guide; identify the actual accepted base and current support matrix.
2. Create an isolated `codex/` branch or checkout without disturbing active Phase 2 work.
3. Add the consolidated scope and engineering decisions to the repository documentation; record the base and entry evidence.
4. Freeze the proposed route/schema contracts, especially transactional board validation, priority/blocked derivation, preference storage, and shared date-picker behavior.
5. Implement P3-02, then begin P3-03. Keep each step's evidence attached to the change that produced it.

No further product question is currently required. Escalate only a newly discovered conflict that materially changes the agreed behavior, permissions, compatibility, or scope.
