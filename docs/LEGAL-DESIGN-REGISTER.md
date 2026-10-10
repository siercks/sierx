# Legal and data-lifecycle design register

This register tracks engineering choices and operator facts without deciding whether a law applies to every Sierx deployment.

| Topic | Current state | Decision owner / evidence needed |
|---|---|---|
| Current audience | Public signup is absent; the current instance is described by its owner as private to the owner. | Instance operator verifies the deployed access policy. |
| Public admission and children | Public signup and child admission remain disabled. Age-screening, actual-knowledge response, parent access/deletion and verified consent are not implemented. | Product owner and applicable legal review before enabling any admission flow. |
| Email | No email sender or notification-delivery path is present. | Product owner defines purpose/preferences/transport before future implementation. |
| Billing | No paid subscription or billing feature is planned. | Revisit only if the product scope changes. |
| Privacy notice | Public route is backed by instance environment settings. It reports setup as incomplete when operator/contact/retention/backup/service/version/date facts are missing. | Each instance operator supplies and verifies the facts before serving others. |
| Copyright notice | Public route exists, but agent/contact/notice/counter-notice/repeat-infringer values are instance-specific and remain unconfigured until supplied. | Relevant instance operator determines applicability, registration, and process. |
| Content lifecycle | History currently retains old/new values; soft deletion is not erasure; schema says no pruning. | Explicit owner decision required before destructive/redaction migration or retention promise. |
| RLS and database roles | Authenticated API requests now establish transaction-local workspace, user, and role context, including nested mutation transactions. RLS policies, a restricted runtime role, the separate authentication path, and direct-SQL isolation evidence are still absent. | Engineering/security design and direct-SQL isolation evidence required before claiming the control complete. |
| Accessibility | Route titles and legal/footer surfaces are being added. Full WCAG 2.1 AA evidence still requires browser and assistive-technology review. | Product owner records manual review results and remaining defects. |
| Hosted release and recovery | Offline promotion, rootless installer, Rocky host, encrypted off-machine restore, and two-release rollback require runtime/operator evidence. | Operator and release maintainers provide exact-candidate and host evidence. |

Do not mark Phase 2 accepted from this register alone. See `docs/PHASE-2-ACCEPTANCE.md` for the release and human exit gates.
