# Sierx legal and security audit — Phase 2

Audit date: October 9, 2026. Source baseline: `a10425611a4492cc2469366231049b76a0838cec`. Findings are source/design evidence, not a certification of the deployed service or a determination that a law has been violated. File/line references below identify this baseline; absent controls are anchored to the code that would implement them.

## Operating context and scope

The owner operates the current instance in the United States, with access limited to the owner. Sierx is intended for independent self-hosted deployments, including isolated networks. Future public signup should be optional and disabled by default. Children must be considered before public admission is enabled. Optional future email is for Sierx notifications; paid subscriptions are not planned.

This review covers application source, migrations, frontend manifests/assets, authentication, deployment templates, security CI and acceptance tests. It includes targeted client secret-pattern scanning and isolated negative controls against the asset checker. It does not inspect the live host, upstream proxy settings, actual database grants, complete Git history, all transitive dependency code, a full rendered-bundle secret scan, or a DMCA agent registration. Legal applicability depends on each operator's location, audience, activities and data practices. US federal guidance is cited where relevant; a future operator must evaluate applicable state and other jurisdictional requirements before public service.

Software license notices identify the software and its dependencies. They are not an instance privacy policy, a substitute for the operator's notices, or proof that the software publisher operates every self-hosted instance.

## Requested checklist, with file and line evidence

| # | Assessment | File and line | Action |
|---|---|---|---|
| 1 | **Gap: no RLS declarations.** 21 logical application tables and three initial event partitions have no ENABLE/FORCE RLS or policies in the migrations. Existing workspace API filters/tests are present. **No embedded client credential found** in the targeted production-source scan. | `migrations/0002_identity.sql:4`; every table listed in the appendix; `internal/api/authorization_test.go:12`; `web/src/api/client.ts:76` | Add effective database policies and separate runtime/maintenance roles; add secret scanning rather than treating this bounded search as exhaustive. |
| 2 | **Gap: no privacy page or policy links.** Current routes are list/login/item; login footnote and app shell contain no legal links. No signup exists, so signup placement is a future requirement. | `web/src/routes/table.ts:3`; `web/src/routes/Login.tsx:90`; `web/src/components/Shell.tsx:182` | Add a public, locally served instance-specific privacy notice, footer and login/app links; make it available before any future signup collection. |
| 3 | **Conditional gap: no age admission or under-13 handling.** Current entry is login/admin bootstrap, not public signup. There is no age or parent-consent data model. | `internal/api/auth.go:40`; `internal/bootstrap/bootstrap.go:86`; `migrations/0002_identity.sql:12` | Keep public admission off; define a neutral pre-collection admission screen and an actual-knowledge/parent request path before applicable child access. |
| 4 | **No analytics/replay/pixel feature found.** Same-origin API calls and a necessary session cookie exist. Prevention has gaps: external images are permitted by CSP, and the asset checker accepts remote HTML resources. | `web/src/api/client.ts:76`; `internal/api/auth.go:178`; `internal/api/documents.go:177`; `web/scripts/offline-assets.mjs:41` | Preserve zero tracking; block unapproved resource loads, test browser/server requests, and prohibit recording sensitive fields even if future analytics is consented to. |
| 5 | **Not applicable to current code: no email sender or marketing campaign subsystem found.** Future notifications require classification by their actual purpose; calling a promotional message a notification does not exempt it. | `internal/api/auth.go:40`; `web/package.json:22`; `.github/workflows/security.yml:1` (absence anchors, not an email implementation) | Keep email optional/offline-compatible. Before commercial email, require sender/address/opt-out controls and suppression enforcement. |
| 6 | **Not applicable: no billing, checkout, pay button or subscription sender found; owner explicitly excludes paid subscriptions.** | `web/src/routes/table.ts:3`; `internal/api/auth.go:40`; `web/package.json:22` | Do not add billing infrastructure. Reassess terms, consent, receipt and cancellation if the product scope changes. |
| 7 | **N/A as requested.** | No code requirement supplied. | No work inferred. |
| 8 | **Partial coverage.** Labels, accessible names, alt checks, keyboard workflows and token contrast tests exist. A generic document title and incomplete reflow/screen-reader evidence remain. This is not full WCAG 2.1 AA conformance evidence. | `web/test/browser/accessibility.ts:4`; `web/test/browser/workflow.spec.ts:228`; `web/test/browser/workflow.spec.ts:443`; `web/src/themes/tokens.test.ts:23`; `web/index.html:3` | Meaningful titles, complete-page reflow/focus/dialog/status checks and manual assistive-technology review on current and new surfaces. |
| 9 | **Conditional gap: user content is hosted even without attachments.** Item bodies, comments and history store authored content; there is no copyright notice/takedown page in the routes. Agent registration is **unverified**, not inferred absent. | `migrations/0005_item.sql:8`; `migrations/0007_sprints_comments_views.sql:28`; `migrations/0006_rollup_links_events.sql:40`; `web/src/routes/table.ts:3`; `web/src/markdown/render.ts:15` | Provide operator-specific copyright handling; evaluate section 512 safe-harbor eligibility/registration when operating a relevant hosted service. |
| 10 | **Good inventory groundwork, enforcement gap.** Runtime npm dependencies are listed/licensed; no third-party font families are declared. Built Sierx fonts are local. There is no operator-facing runtime asset register, and remote HTML URLs are skipped by the checker. | `web/package.json:22`; `web/licenses.json:1`; `web/design/fonts/fonts.json:4`; `web/design/fonts/fonts.json:7`; `web/scripts/offline-assets.mjs:28`; `web/scripts/offline-assets.mjs:41` | Generate a runtime asset/service inventory; fix the checker and bind it to build/runtime request evidence and deployment-specific services. |

## Confirmed findings and mitigation priorities

### SEC-01 — Database isolation relies on application predicates; RLS is absent

Priority: high for additional users/public deployments; implement before declaring the requested database control complete. Every table location is in the appendix. API workspace filters and `TestWorkspaceIsolation` reduce current risk; absence of RLS is a defense-in-depth gap, not evidence that an existing endpoint leaks data.

Enable and force RLS on application-owned tables with explicit USING and WITH CHECK policies. Direct workspace tables use validated request workspace context; project/item-derived tables follow indexed ownership relationships. Saved views must retain their shared-or-owner visibility, and comment modification must retain its author/admin fence. Workspace membership does not mean every member may read password hashes or two-factor secrets.

Global identity/session tables need a distinct narrow authentication path and self/authorized-member policies; blindly adding `workspace_id` checks would break login or leak credentials. Privileged bootstrap, migrations, partition maintenance and complete backups need separate protected operations. Check newly created event partitions and the Goose migration metadata table as well as original tables; runtime must not directly read migration metadata or exploit child-table grants.

Use transaction-local context set only after authenticated identity resolution. Refactor direct pool reads/writes through a request-scoped transaction/executor; ensure store mutations use the same authenticated context. Tests must alternate concurrent tenants through a reused pool, fail closed with missing context, exercise direct SQL without endpoint filters, and prove reads and writes are isolated. Avoid recursive policies, unchecked security-definer search paths, unindexed ownership joins and global runtime bypass. RLS is not protection against a compromised superuser or an unrestricted arbitrary-SQL attacker with the runtime's own powers. [PostgreSQL 18 row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html).

### SEC-02 — Default database provisioning couples app credentials to the initialization superuser

Priority: high. `scripts/db.sh:98` renders `POSTGRES_USER` from the same DATABASE_URL credentials consumed by `cmd/sierx/main.go:25`; migrations also use DATABASE_URL at `scripts/migrate.sh:42`. No separate least-privilege runtime role provisioning was found. On a fresh official PostgreSQL image, POSTGRES_USER defines the initialization superuser. This proves a risky default path, not the current testbed's actual grant state. [Official PostgreSQL image](https://hub.docker.com/_/postgres).

Separate initialization/migration/maintenance credentials from runtime credentials. The app role must be NOSUPERUSER, NOBYPASSRLS, not own tables, and lack DDL/TRUNCATE/role-management powers. Add an operator role inventory and startup/gate assertions. Plan an explicit existing-volume transition after verified recovery; merely changing POSTGRES_USER on an initialized volume does not rewrite its roles. Superusers bypass RLS even with FORCE enabled. [PostgreSQL bypass behavior](https://www.postgresql.org/docs/18/ddl-rowsecurity.html).

### PRIV-01 — No instance-specific privacy notice or collection-point disclosure

Priority: current Phase 2 work. Evidence: `web/src/routes/table.ts:3`, `web/src/routes/Login.tsx:90`, `web/src/components/Shell.tsx:182`.

The actual data inventory includes email/display name, password hashes, encrypted two-factor/recovery state, session-token hashes and expiry, membership, preferences, authored item/comment content, assignees, links, saved queries and change history. App request logs contain actor/workspace IDs and timing at `internal/api/middleware.go:39`; transient login rate limiting uses RemoteAddr at `internal/api/auth.go:123`. Neither app path logs request bodies in the reviewed code. Host journald, database logs, proxies, backups and optional tunnel/DNS providers require operator verification; do not claim they collect nothing.

Ship public local privacy content with operator identity/contact, categories/purposes, access/recipients, actual retention, rights/contact process, essential cookies, security/backups and optional external services. Independent self-hosters supply their own operator facts. Do not publish invented contacts, retention promises, universal compliance claims or a generic statement that Sierx never processes personal data. Use applicability review for US state requirements; international deployments must evaluate their own obligations. [California privacy guidance](https://oag.ca.gov/privacy/privacy-laws); [privacy-information design checklist, where applicable](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/the-right-to-be-informed/what-privacy-information-should-we-provide/).

### PRIV-02 — Indefinite personal-content history conflicts with a future deletion/retention promise

Priority: Phase 2 policy/design reconciliation, before applicable public/child admission. `docs/SPEC.md:393` explicitly rejects event pruning; `migrations/0006_rollup_links_events.sql:40` stores old/new JSON. Soft deletion retains item bodies (`migrations/0005_item.sql:8` / `internal/store/query/item.sql:68`) and comment storage (`internal/store/comments.go:23`). The store's HardDeleteItem path (`internal/store/mutate.go:607`) does not constitute a complete account/history/backup privacy-erasure workflow. No such complete workflow was found.

Define purpose-based retention by data class and an authenticated request process. Keep necessary stable keys/tombstones while separately considering redaction of personal payloads, account identifiers and inaccessible history. Address copies in search indexes, comments, event payloads, logs and backups, and reapply erasure restrictions after restoration. Record narrowly justified legal holds. Do not call soft deletion erasure, promise immediate removal from immutable backups, or impose a blanket purge that destroys historical integrity.

### CHILD-01 — No public admission or actual-knowledge response design

Priority: precondition for a future public/child-enabled mode; not a reason to collect birth dates from the current private operator.

Evidence: `internal/api/auth.go:40`, `internal/bootstrap/bootstrap.go:86`, `migrations/0002_identity.sql:12`. COPPA is not triggered merely because a child could visit any general-audience site; relevant coverage includes covered child-directed services and actual knowledge of under-13 collection. A neutral screen does not exempt a primarily child-directed service. [FTC COPPA FAQ](https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions).

Before appropriate public admission, place a neutral age screen before account/profile/contact collection, with no adult default or coaching. Keep only the minimum admission result needed rather than retaining full birth dates without a purpose. An under-13 result stops ordinary signup; offer an operator contact/parent-managed process. Supporting covered child accounts requires verified parental consent, parent review/deletion, security and purpose-limited retention; until implemented and reviewed, child-account admission remains disabled. If an existing account is discovered to belong to a child, stop further ordinary collection/access as appropriate, route a verified parent request and review existing data; do not assume suspending login deletes data. [FTC six-step plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business).

### TRACK-01 — Tracking-free behavior exists, but the asset gate has reproducible false negatives

Priority: current Phase 2 fix. `web/scripts/offline-assets.mjs:28` scans CSS/HTML, not JavaScript behavior; line 41 skips remote `src`/`href` references. Isolated fixtures containing a remote script, remote stylesheet link and remote image each exited **0** and printed “no ... remote references.” All three should fail a resource gate. These fixtures were scratch files, not changes to Sierx's production code.

Existing CSP blocks cross-origin scripts/styles/connections, which limits the remote-script case; `internal/api/documents.go:177` nevertheless permits external HTTPS images. The Markdown renderer already replaces external images with deliberate links at `web/src/markdown/render.ts:14`. Tighten img-src to the actually needed local sources; keep that Markdown protection. Distinguish ordinary external hyperlinks from automatic resource loads rather than banning all external text/links.

Fix element-aware resource validation and prove rejection of scripts, stylesheet/preload links, frames, pixels, CSS resources and dynamic runtime loads. Add browser and server observation in the offline gate. Do not introduce analytics or a consent manager SDK now. Essential authentication is not optional analytics; a notice is still needed. If optional analytics is ever proposed, require prior valid consent where applicable, withdrawal, and a strict ban on capture of form/chat/payment/health fields and workspace text even after consent. Self-hosting a tracker does not remove those concerns.

### MAIL-01 — Future notification purpose and suppression rules are unspecified

Priority: future feature gate. No sender, SMTP integration, notification preference model or marketing templates were found in first-party source/manifests. There is no current message on which to report a missing unsubscribe/footer line; absence anchors are `internal/api/auth.go:40` and `web/package.json:22`.

Optional notifications must use a configured transport, minimum necessary content and user preferences; air-gapped deployments can keep transport disabled or use an explicitly configured internal server. No automatic delivery to a software publisher. Classify each template by actual primary purpose. US commercial mail requires truthful headers/subjects, a postal address, an easy opt-out and honoring opt-outs within 10 business days; the mechanism must remain operational for at least 30 days. Build immediate suppression and check it at enqueue and send time, including delayed jobs. Pure transactional messages are assessed separately; exclude marketing from them. [FTC CAN-SPAM guide](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business).

### PAY-01 — No current subscription requirement

No payment/subscription feature or paid-product intent exists. `web/src/routes/table.ts:3`, `internal/api/auth.go:40`, `web/package.json:22` are absence anchors. Do not add payment code or invented subscription terms.

Retain the owner's requested clear terms, confirmation and simple online cancellation as a future scope gate if billing is ever introduced. Do not cite the FTC's 2024 amended click-to-cancel rule as currently operative: the FTC's 2026 rulemaking notice records its 2025 vacatur. ROSCA and applicable state rules still require separate review for future recurring charges. [FTC 2026 rulemaking notice](https://www.ftc.gov/system/files/ftc_gov/pdf/p064202negativeoptionruleanprm.pdf); [FTC ROSCA guidance](https://www.ftc.gov/business-guidance/blog/2018/07/time-rosca-recap-ftc-says-risk-free-trial-was-risky-not-free).

### A11Y-01 — Document titles do not distinguish pages

Priority: Phase 2 UI fix. `web/index.html:3` has a fixed `<title>Sierx</title>`; `internal/api/documents.go:167` injects theme/bootstrap without a route-purpose title. Login, backlog and distinct item pages therefore do not have demonstrated meaningful topic-specific titles.

Render an escaped purpose-specific title in initial HTML and update it during client navigation. Avoid placing private item content in a public/legal page. Test login, workspace, selected project, item and legal pages, including errors and session-expired states. WCAG 2.1 includes page-title and name/role/value requirements. [WCAG 2.1](https://www.w3.org/TR/WCAG21/).

### A11Y-02 — Accessibility checks do not establish complete AA conformance

Priority: Phase 2 acceptance coverage. `web/test/browser/accessibility.ts:4` validates selected rules and names/targets; `web/test/browser/workflow.spec.ts:443` adds 200% text/spacing and checks form visibility. That test does not assert absence of clipped/overlapping content across complete pages. Existing keyboard, focus restoration and contrast tests are valuable; this is a coverage gap, not a claim that every untested criterion fails.

Add full-page 320-CSS-pixel reflow and 200% resize checks where applicable, text-spacing content retention, focus visibility/order/no traps, dialog Escape/return focus, error association, status announcements and non-color information. Manually assess keyboard and screen-reader behavior on complete processes in supported browsers. Distinguish the existing 24-pixel target requirement as an additional product/2.2-style control rather than a universal WCAG 2.1 AA target minimum. Record exceptions accurately, including two-dimensional data layouts. [WCAG 2.1 complete-process conformance](https://www.w3.org/TR/WCAG21/#conformance-reqs).

### COPYRIGHT-01 — Hosted text/history needs a copyright response design

Priority: design now; operator implementation before an applicable hosted public service. `migrations/0005_item.sql:8`, `migrations/0007_sprints_comments_views.sql:28`, `migrations/0006_rollup_links_events.sql:40` show that attachments are not the only user content. No copyright route appears in `web/src/routes/table.ts:3`. A registration cannot be confirmed or denied from this code.

If a relevant US operator seeks section 512 safe-harbor protection, agent designation/public contact is one condition, not an automatic immunity or a universal obligation for every private installation. Design valid notice/counter-notice processing, expeditious disabling of access, the statutory counter-notice/restoration process where applicable, repeat-infringer handling and scoped evidence retention. Soft-deleted item URLs remain readable under `docs/SPEC.md:517`, so ordinary soft delete is not sufficient to disable access to contested material; also assess history, comments, links and search/bootstrap payloads. Keep the software publisher's contact distinct from each instance operator. Registration/renewal is an operator action; the directory requires renewal within three years. [Copyright Office service-provider guidance](https://www.copyright.gov/onlinesp/); [section 512 conditions](https://www.copyright.gov/512/); [agent renewal](https://www.copyright.gov/dmca-directory/faq.html).

### ASSET-01 — Dependency inventory is not an operator-facing runtime service inventory

Priority: Phase 2 disclosure/build integration. `web/package.json:22` lists seven runtime npm dependencies: Base UI, TanStack Query, TanStack Virtual, lossless-json, markdown-it, React and React DOM. Their code is bundled locally, not fetched as seven remote scripts. `web/licenses.json:1` records license inventory. `web/design/fonts/fonts.json:4` declares no third-party families; built Sierx Mono/Sierx Symbols are local, with platform system-font fallbacks supplied by the user's device.

Generate a report distinguishing runtime code, development tools, bundled fonts, device fonts and optional deployment services. Include versions/licenses, delivery origin and purpose. Optional gateways, certificate providers, mail, backups or metrics destinations must be documented by each operator. Self-hosting removes an asset-fetch dependency but does not resolve licensing or data-sharing issues by itself. Bind published asset evidence to exact release builds and fix TRACK-01 rather than relying on the current success message.

### SEC-03 — Secret assurance lacks a dedicated checked-in workflow gate

Priority: Phase 2 assurance. The targeted scan covered 20 first-party production client source files, found no tested secret patterns and no client environment references. User-entered login credentials and a user's own MFA-enrollment secret are intentional authenticated flows, not build-time server-secret embedding. Server credentials must never enter general bootstrap/client bundles.

The current `.github/workflows/security.yml:1` contains workflow lint, Go advisories and npm supply-chain checks, not a dedicated secret scanner. The topology gate protects real local configuration values but is not a complete credential detector. Add prepared offline source/diff and rendered-bundle scans, plus an initial history assessment; use planted synthetic credentials to prove detection. Restrict exceptions to documented synthetic fixtures, with no blanket suppression. No real credential is reproduced in this audit.

## Controls already worth preserving

- HttpOnly/Secure/SameSite session cookie: `internal/api/auth.go:178`; stored session hashes: `internal/api/auth/local.go:70`.
- Argon2id password handling: `internal/api/auth/password.go:22`; encrypted/bound TOTP state: `internal/api/auth/totp.go:33`.
- Same-origin write checks and strict JSON decoding: `internal/api/auth.go:83`, `internal/api/auth.go:107`. No confirmed CSRF exploit was demonstrated here.
- Non-public bootstrap cache policy and HTML/script escaping: `internal/api/documents.go:152`, `internal/api/documents.go:173`.
- Existing CSP/frame restrictions and external referrer restriction: `internal/api/documents.go:175`.
- Request logs use route patterns rather than raw queries/bodies: `internal/api/middleware.go:29` and `:39`.
- Markdown active HTML disabled; unsafe schemes rejected; external images become links: `web/src/markdown/render.ts:2` and `:14`.
- Browser contrast/name/keyboard tests, local assets, dependency licenses and offline delivery groundwork remain applicable.

## RLS table-by-table inventory

All entries below lack migration-declared RLS/policies at the audited baseline. The logical tables number 21; the additional three are explicit partitions. A live catalog may contain more partitions and `goose_db_version`, so implementation must audit the actual application schema and newly created objects too.

| Table | File:line | Required policy scope |
|---|---|---|
| workspace | `migrations/0002_identity.sql:4` | Authenticated selected workspace/membership |
| user_account | `migrations/0002_identity.sql:12` | Self/authorized roster; credential columns via narrow auth path |
| membership | `migrations/0002_identity.sql:24` | Selected workspace; role-controlled writes |
| session | `migrations/0002_identity.sql:31` | Narrow authentication/session path; no roster access |
| project | `migrations/0003_project.sql:3` | Workspace; admin metadata writes |
| project_config | `migrations/0004_config.sql:6` | Project workspace; restricted versioned writes |
| status | `migrations/0004_config.sql:16` | Project workspace; retain immutable definitions |
| item_type | `migrations/0004_config.sql:26` | Project workspace; retain immutable definitions |
| config_status | `migrations/0004_config.sql:36` | Project workspace/version |
| config_type | `migrations/0004_config.sql:45` | Project workspace/version |
| config_transition | `migrations/0004_config.sql:54` | Project workspace/version |
| field_def | `migrations/0004_config.sql:64` | Project workspace/version |
| item | `migrations/0005_item.sql:8` | Workspace with owning-project integrity |
| item_rollup | `migrations/0006_rollup_links_events.sql:7` | Owning item's workspace; derived writes |
| item_link | `migrations/0006_rollup_links_events.sql:18` | Both endpoints in permitted workspace |
| change_event | `migrations/0006_rollup_links_events.sql:32` | Workspace; history visibility restrictions |
| change_event_2026_09 | `migrations/0006_rollup_links_events.sql:50` | Prevent direct-child bypass |
| change_event_2026_10 | `migrations/0006_rollup_links_events.sql:52` | Prevent direct-child bypass |
| change_event_2026_11 | `migrations/0006_rollup_links_events.sql:54` | Prevent direct-child bypass |
| seq_counter | `migrations/0006_rollup_links_events.sql:57` | Workspace; atomic authorized mutation allocation |
| sprint | `migrations/0007_sprints_comments_views.sql:5` | Project workspace |
| sprint_item | `migrations/0007_sprints_comments_views.sql:16` | Sprint and item workspace/project integrity |
| comment | `migrations/0007_sprints_comments_views.sql:24` | Item workspace plus author/admin write fence |
| saved_view | `migrations/0007_sprints_comments_views.sql:34` | Workspace and shared-or-owner visibility |

Future partitions are created at `migrations/0009_seq.sql:49`; policy/privilege setup and verification must cover that creation path, not only the three listed partitions. New project owner/version fields must be covered by the same rules.

## Mitigation integration and release boundaries

The revised Phase 2 closeout plan adds Workstream F for these controls. Implement database role/RLS foundations alongside project metadata; legal routes/footer and meaningful titles alongside navigation; resource/secret controls alongside offline CI; retention/recovery and manual accessibility alongside operator acceptance. Public signup and child admission remain disabled until their explicit release conditions are fulfilled. Notification sending remains optional future work; billing stays out of scope.

Publish operational facts only after the operator verifies them. Capture tests, reviews and actual deployment evidence by revision. The current private single-user instance is a different legal-risk context from a future public operator, but the reusable design must support truthful notices, effective controls and later feature reviews without introducing compulsory Internet connections.
