# Privacy operations

## Instance setup

Before providing an instance to anyone beyond its operator, configure `SIERX_OPERATOR_NAME`, `SIERX_PRIVACY_CONTACT`, `SIERX_PRIVACY_RETENTION`, `SIERX_PRIVACY_BACKUPS`, `SIERX_PRIVACY_SERVICES`, `SIERX_PRIVACY_VERSION`, and `SIERX_PRIVACY_EFFECTIVE_DATE` in the protected server environment. The values appear as text on the public `/privacy` and `/third-party` pages. They are optional at startup so a private owner-only testbed can continue to run; the pages explicitly indicate when required operator facts are missing. Never put credentials or private keys in these values.

The operator must verify the descriptions against the actual proxy/gateway, certificate, logs, database, backup repositories, and expiry settings. The public pages do not infer those settings from application configuration.

Account admission is private and operator-provisioned. `SIERX_REGISTRATION_MODE` defaults to `private`; `invitation` and `public` are reserved values that fail startup until their routes and safeguards are implemented. Do not enable a deployment by changing this setting: the validation intentionally rejects those modes.

## Current lifecycle behavior

- Session records have an expiration timestamp. Verify and document the deployed cleanup schedule.
- Item soft deletion is reversible application state, not erasure. It does not by itself remove events, comments, links, copies in search/bootstrap responses, or backups.
- Change events retain old and new JSON values. The existing schema specifies no history pruning.
- Backup expiry, off-machine copies, restore behavior, and log retention depend on the instance operator.
- Login rate-limit addresses are kept temporarily in server memory; operational request logs identify actor and workspace.

Sierx has no public signup, invitation flow, notification email sender, analytics/replay SDK, or billing/subscription path. `SIERX_REGISTRATION_MODE` is private by default and rejects the reserved admission modes. No SMTP or payment provider is contacted by the application. Revisit this register before adding any such feature; do not treat a configured proxy, mail relay, or payment service as implicit consent to send data.

## Requests and holds

Sierx provides an operator-only, reversible account suspension/reactivation command. Suspension disables the global account and revokes all its sessions in one transaction; reactivation does not restore old sessions. It preserves memberships, project ownership, content, comments, and history, so it is not erasure. The command requires the maintenance database role and a restricted case UUID; its audit record contains the account UUID, case UUID, database login role, state change, time, and count of revoked sessions. Do not pass personal details as the case identifier.

After the operator has verified and authorized a restricted case, run `sierxctl accounts suspend --user <account-uuid> --case <case-uuid>` or `sierxctl accounts reactivate --user <account-uuid> --case <case-uuid>` with `SIERX_MAINTENANCE_DATABASE_URL` set to the maintenance login. Session creation is serialized with suspension, and reactivation never restores old sessions. The command reports only UUIDs, state, and revoked-session count; retain the case decision in the restricted case system.

The application still does not provide a complete supported workflow for data access/export, correction of historical copies, content redaction, legal holds, or erasure-aware restore. Do not promise that these operations are available, and do not hand-edit production database rows as a substitute. Record a verified request with restricted access, preserve only what is necessary under the operator's obligations, and escalate to the instance operator for a case-specific decision.

Until tested operator tooling exists, handle an incoming request as an operator case rather than a self-service product feature: record the request and receipt date in a restricted system; verify the requester's authority without collecting extra identity documents; identify the instance, affected account/content and any applicable hold; have the instance operator decide the response and any preservation duty; record actions and affected backups; and tell the requester which steps are complete or unavailable. Do not export or alter content through ad hoc SQL. This interim handling does not itself provide a complete access, correction, deletion, or hold process.

Before implementing irreversible redaction or retention migrations, decide and document the open questions in `docs/DATA-LIFECYCLE-DESIGN.md`: which content/history may be removed, how stable keys and audit integrity are preserved, how comments/links/search/bootstrap copies are handled, what legal holds block, how backup expiry works, and how restored backups receive the current erasure decisions. This design decision remains open; this repository does not claim that the lifecycle workflow is complete.

## Review record

Use `docs/LEGAL-DESIGN-REGISTER.md` to record operator-specific legal and lifecycle choices. Review the public notice after material changes to authentication, content, logging, backup, proxy, or service configuration.
