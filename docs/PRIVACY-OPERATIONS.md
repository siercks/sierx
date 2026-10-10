# Privacy operations

## Instance setup

Before providing an instance to anyone beyond its operator, configure `SIERX_OPERATOR_NAME`, `SIERX_PRIVACY_CONTACT`, `SIERX_PRIVACY_RETENTION`, `SIERX_PRIVACY_BACKUPS`, `SIERX_PRIVACY_SERVICES`, `SIERX_PRIVACY_VERSION`, and `SIERX_PRIVACY_EFFECTIVE_DATE` in the protected server environment. The values appear as text on the public `/privacy` and `/third-party` pages. They are optional at startup so a private owner-only testbed can continue to run; the pages explicitly indicate when required operator facts are missing. Never put credentials or private keys in these values.

The operator must verify the descriptions against the actual proxy/gateway, certificate, logs, database, backup repositories, and expiry settings. The public pages do not infer those settings from application configuration.

## Current lifecycle behavior

- Session records have an expiration timestamp. Verify and document the deployed cleanup schedule.
- Item soft deletion is reversible application state, not erasure. It does not by itself remove events, comments, links, copies in search/bootstrap responses, or backups.
- Change events retain old and new JSON values. The existing schema specifies no history pruning.
- Backup expiry, off-machine copies, restore behavior, and log retention depend on the instance operator.
- Login rate-limit addresses are kept temporarily in server memory; operational request logs identify actor and workspace.

## Requests and holds

The application does not yet provide a complete supported workflow for data access/export, correction, redaction, account deactivation with session revocation, legal holds, or erasure-aware restore. Do not promise that these operations are available, and do not hand-edit production database rows as a substitute. Record a verified request with restricted access, preserve only what is necessary under the operator's obligations, and escalate to the instance operator for a case-specific decision.

Before implementing irreversible redaction or retention migrations, decide and document: which content/history may be removed, how stable keys and audit integrity are preserved, how comments/links/search/bootstrap copies are handled, what legal holds block, how backup expiry works, and how restored backups receive the current erasure decisions. This design decision remains open; this repository does not claim that the lifecycle workflow is complete.

## Review record

Use `docs/LEGAL-DESIGN-REGISTER.md` to record operator-specific legal and lifecycle choices. Review the public notice after material changes to authentication, content, logging, backup, proxy, or service configuration.
