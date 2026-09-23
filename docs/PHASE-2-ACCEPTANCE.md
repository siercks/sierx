# Phase 2 acceptance record

Status: Phase 2 code merged; host, recovery and full owner acceptance remain pending.

September 23 reconciliation: the owner-supplied September 22 post-mortem reports
successful offline gate-2 at PR head `1c14c0246b0bb3ee1b2819f61caa841f90ac4527`,
hosted CI/security and native release, plus Brave/Firefox trial review. The merge
is `71976c771d9fea1567ad34063e82037f56f93376`. This historical evidence does not
accept later uplift changes. Browser versions and private log locations still
need owner entry. No full phase-exit approval is recorded.

| Evidence | Current state |
|---|---|
| React frontend, budgets, themes and routes | Implemented; local automated checks pass |
| API and browser item workflows | Implemented; local real PostgreSQL/HTTPS checks pass |
| License inventory | MIT-0 and PSF-2.0 approved; exact-package Python-2.0 and CC-BY-4.0 approvals; copyleft drift remains blocked |
| Offline gate-2 on exact candidate | Owner reports GREEN on the historical PR head above; preserve the private log |
| Hosted workflow/vulnerability checks | Post-mortem reports passes: runs 35815051016 and 35815051149; new revisions require new checks |
| Brave walkthrough | Trial review reported in Brave and Firefox; versions, enrolled-account checks and full sign-off remain pending |
| Native amd64/arm64 release | Post-mortem reports workflow 35814461993 succeeded; native runtime artifact gates are new uplift work |
| HTTPS/HTTP3, restart and rollback | Operator scripts implemented; Spark acceptance pending |
| Encrypted off-machine physical recovery and cipher | Driver implemented; Linux conformance not yet claimed |
| Restored application and authentication access | Hook implemented; operator acceptance pending |
| Representative small hardware | Not measured; Spark results must be labeled separately |
| Preact experiment (optional, task 2.17) | Measured: Preact 10.29.8 50,025 bytes initial JS vs React 100,876; 32 browser checks passed. Reverted because full Linux compatibility acceptance is still pending; React is comfortably within budget. |
| Real SRX-1 and primary backlog | Cutover command prepared; owner operation pending |
| Seven consecutive days, design and copy signoff | Must be real owner evidence |

## Run metadata

- Candidate revision:
- Host architecture and hardware class (no private topology):
- Brave version / Firefox version:
- Offline gate result and scrubbed log location:
- Hosted required check results:
- Image manifest digest:
- HTTPS/HTTP3/restart/rollback result:
- Backup driver/version, encryption/transport class (no destination):
- Recovery counts/checksum/counter/rollup and application-access result:
- Backup schedule, accountable owner, last successful restore:
- Design/copy/60-30-10 decisions:
- Remaining defects and their Sierx keys:

## Seven days of actual primary-backlog use

Do not fill dates in advance. A synthetic run or merely opening the app is not a
day of primary-backlog work. Record any fallback to another tracker honestly.

| Date | Revision | Actual work | Friction/defect key | Fallback used? | Corrective action |
|---|---|---|---|---|---|

## Exit decision

Owner approval, date and any explicitly accepted deferrals:

Retrospective: what worked, what failed, changes to the next phase's plan:
