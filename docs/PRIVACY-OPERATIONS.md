# Privacy operations

## Instance setup

Before providing an instance to anyone beyond its operator, configure `SIERX_OPERATOR_NAME`, `SIERX_PRIVACY_CONTACT`, `SIERX_PRIVACY_RETENTION`, `SIERX_PRIVACY_BACKUPS`, `SIERX_PRIVACY_SERVICES`, `SIERX_PRIVACY_VERSION`, and `SIERX_PRIVACY_EFFECTIVE_DATE` in the protected server environment. The values appear as text on the public `/privacy` and `/third-party` pages. They are optional at startup so a private owner-only testbed can continue to run; the pages explicitly indicate when required operator facts are missing. Never put credentials or private keys in these values.

The operator must verify the descriptions against the actual proxy/gateway, certificate, logs, database, backup repositories, and expiry settings. The public pages do not infer those settings from application configuration.

Account admission is private and operator-provisioned. `SIERX_REGISTRATION_MODE` defaults to `private`; `invitation` and `public` are reserved values that fail startup until their routes and safeguards are implemented. Do not enable a deployment by changing this setting: the validation intentionally rejects those modes.

## Current lifecycle behavior

- Session records have an expiration timestamp. Verify and document the deployed cleanup schedule.
- Item soft deletion is reversible application state, not erasure. It does not by itself remove events, comments, links, copies in search/bootstrap responses, or backups.
- Change events normally retain old/new JSON values. Reviewed lifecycle actions may replace values with markers or corrections while preserving event metadata and partitions. Ordinary soft deletion does not do this.
- Backup expiry, off-machine copies, restore behavior, and log retention depend on the instance operator.
- Login rate-limit addresses are kept temporarily in server memory; operational request logs identify actor and workspace.

Sierx has no public signup, invitation flow, notification email sender, analytics/replay SDK, or billing/subscription path. `SIERX_REGISTRATION_MODE` is private by default and rejects the reserved admission modes. No SMTP or payment provider is contacted by the application. Revisit this register before adding any such feature; do not treat a configured proxy, mail relay, or payment service as implicit consent to send data.

## Requests and holds

Sierx provides an operator-only, reversible account suspension/reactivation command. Suspension disables the global account and revokes all its sessions in one transaction; reactivation does not restore old sessions. It preserves memberships, project ownership, content, comments, and history, so it is not erasure. The command requires the maintenance database role and a restricted case UUID; its audit record contains the account UUID, case UUID, database login role, state change, time, and count of revoked sessions. Do not pass personal details as the case identifier.

After the operator has verified and authorized a restricted case, run `sierxctl accounts suspend --user <account-uuid> --case <case-uuid>` or `sierxctl accounts reactivate --user <account-uuid> --case <case-uuid>` with `SIERX_MAINTENANCE_DATABASE_URL` set to the maintenance login. Session creation is serialized with suspension, and reactivation never restores old sessions. The command reports only UUIDs, state, and revoked-session count; retain the case decision in the restricted case system.

Sierx provides an operator-mediated limited access export. After verifying and authorizing a restricted case, run `sierxctl exports create --user <account-uuid> --case <case-uuid>` with `SIERX_MAINTENANCE_DATABASE_URL` set to the maintenance login. This creates a one-hour server-side artifact and prints its UUID and expiry. Retrieve it with `sierxctl exports download --id <export-uuid> --case <case-uuid> --out <new-file-path>`. The case UUID must match the one used at creation. Creation and retrieval are audited; expired server-side payloads are cleared on the next export creation while audit metadata remains. The payload is capped at 20 MiB, 512 comments and 512 saved views; comment bodies and view queries are limited to 4,096 characters with truncation markers. The operator must protect and handle downloaded files in the restricted case process.

The export contains account profile fields, workspace memberships, comments directly authored by the account (without bodies for soft-deleted comments), and saved views owned by the account. It excludes credentials, item content (items have no author field), change-event old/new values, and unrelated workspace content. Its manifest says it is not a complete personal-data export. Add `--workspace <uuid>` for a bounded snapshot of visible content in that single workspace; the requester must have membership there. Both forms exclude credentials, sessions and event values. Content/access decisions revoke server artifacts; downloaded copies remain operator-controlled.

Holds, reversible takedowns, permanent bounded content/history redaction, explicit historical correction, membership removal with an active administrator replacement, account anonymization, and journal-aware recovery are implemented. There is no default destructive schedule. Follow `docs/LIFECYCLE-OPERATIONS.md` for protected environment setup, review/plan/apply, optional explicit retention and recovery. Do not offer complete person-wide erasure: author attribution is incomplete and external copies/backups require operator handling. Hold authority, durations, backup expiry and requester communication remain instance-specific facts.

Initialize and independently protect the encrypted decision journal and trusted checkpoint before adopting this release. App startup and requests fail closed when database receipts disagree with the checkpoint. An old restored backup must replay and verify current decisions before access. Review the current instance notice after enabling any policy or changing external backup/log handling.

## Review record

Use `docs/LEGAL-DESIGN-REGISTER.md` to record operator-specific legal and lifecycle choices. Review the public notice after material changes to authentication, content, logging, backup, proxy, or service configuration.
