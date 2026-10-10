# Data lifecycle workflow design

Status: proposed engineering design for owner/operator review. This document is not a retention promise or legal determination. No destructive lifecycle behavior is enabled by this proposal.

## Existing data boundaries

Sierx has globally identified accounts and workspace memberships. An account may be referenced by project ownership, comments, and change-event actor fields. Item rows do not consistently record a creator. Change-event values retain prior item content; comment soft deletion keeps the comment row and removes its body from normal API output. Backups can contain earlier database states. These properties mean an account export or erasure cannot be defined as a single-row operation.

The database runtime role is tenant-scoped and intentionally cannot read authentication secrets. Any administrative lifecycle tooling must use a separate, audited, operator-authorized path. It must never run through ordinary API requests or ask an operator to edit production rows manually.

## Proposed sequence

### 1. Intake and decision record

Use a restricted operator case system outside the Sierx database. Record a case identifier, receipt date, instance identifier, request category, minimum verification result, affected account/content identifiers, hold status, decision owner, and completion/deferral evidence. Do not copy request documents, credentials, or full content into the case record unless the operator has a documented need. The requester receives a clear statement of what Sierx supports and what remains unavailable.

This intake record is not itself a data-access, correction, hold, or erasure capability.

### 2. Access and export

The first product workflow should be read-only and generate a bounded export from a consistent database snapshot. It must exclude password hashes, MFA secrets, session token hashes, and unrelated workspace content. Because items have no author field and history payloads may contain other people’s text, an export must not claim to be a complete personal-data export until its scope and review behavior are specified. Export creation and download should be audited, time-limited, and visible only to the verified requester or an authorized operator.

### 3. Correction

Correct current profile or work content through the existing authenticated edit paths where available. Keep the resulting change event. The event log is historical evidence, so a correction does not imply rewriting prior event values. Until the redaction policy below is approved, disclose this limit for requests concerning historical copies.

### 4. Account deactivation and session revocation

Implemented as `sierxctl accounts suspend|reactivate --user UUID --case UUID`. Treat suspension as reversible access control, not erasure. In one transaction, mark the global account inactive and revoke all its sessions. Session issuance uses the same account-row lock, so a login racing with suspension cannot leave a token that becomes usable after reactivation. Preserve membership, project ownership references, stable item keys, comments, and history. Reactivation requires the maintenance role and does not recreate revoked sessions. The action audit stores the maintenance login role, case UUID, account UUID, state change, timestamp, and number of sessions revoked; the runtime role cannot read or change it.

This command implements the code path only. The instance operator must authorize the target and case in a restricted case system before running it. It does not remove workspace membership, reassign project owners, notify the affected person, or erase any content. Define those operations separately before offering the workflow to users.

### 5. Holds and redaction

An approved hold must identify its authority, scope, start time, review date, and release decision. A hold blocks irreversible redaction and any retention job affecting the held records. Hold creation/release and blocked actions need an append-only operator audit trail.

Before redaction or retention code is enabled, the owner must decide whether to preserve event metadata while replacing old/new content values with a redaction marker; which current content, comments, search/bootstrap copies, and account fields can be redacted; how links and stable identifiers behave; and how conflicts between holds and a request are resolved. No policy is selected here.

### 6. Backups and restore

Backups follow the operator’s configured expiry schedule. If a restore predates a completed redaction, access to the restored database must remain blocked until the current redaction decisions have been replayed and verified. The durable decision record must survive loss of the database backup it governs, be access-controlled and tamper-evident, and be included in recovery drills. If that record is unavailable or cannot be applied, fail the restore acceptance rather than serving stale content.

## Owner decisions required before destructive implementation

1. **Export scope:** self-only account/profile and authored records; operator-reviewed broader workspace export; or both with distinct authorization paths.
2. **History treatment:** retain immutable old/new values; or permit value redaction while preserving event metadata and a redaction marker.
3. **Content scope:** treatment of items without a recorded creator, comments, links, shared views, account identifiers, and derived/search/bootstrap copies.
4. **Deactivation scope:** global account suspension (recommended for the current global account model) versus per-workspace membership removal. Define how project ownership references are reassigned.
5. **Hold rules:** who can issue/release a hold, required review cadence, and which actions it blocks.
6. **Restore authority:** who maintains the off-database redaction decision record, how it is authenticated, and who signs off after replay.
7. **Retention:** the operator supplies actual durations for sessions, logs, backups, and any content/history retention; do not encode generic periods as a default legal requirement.

Until these choices are recorded, safe implementation is limited to intake documentation, a non-destructive export design/prototype with an explicitly narrow scope, and reversible account suspension/session revocation that preserves all content. Redaction, pruning, purge, hard deletion, and automatic retention jobs remain disabled.

## Acceptance evidence

- Access-denied and cross-workspace export controls, with tests proving auth secrets and unrelated workspace rows are absent.
- Consistent export snapshot, bounded size, audit record, short-lived delivery, and no sensitive export contents in logs.
- Deactivation atomically blocks login and revokes existing sessions; reactivation does not revive old sessions.
- Held records cannot be redacted or expired; release is auditable.
- Restore from before and after redaction replays current decisions before application access; missing/corrupt decision records fail closed.
- Operator runbook documents case handling, authorization, backup expiry, escalation and user communication without promising unsupported actions.

See `docs/PRIVACY-OPERATIONS.md` and `docs/LEGAL-DESIGN-REGISTER.md` for the current disclosure and unresolved lifecycle status.
