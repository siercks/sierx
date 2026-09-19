# Phase 2 acceptance record

Status: code candidate; host, recovery and owner acceptance are pending.

| Evidence | Current state |
|---|---|
| React frontend, budgets, themes and routes | Implemented; local automated checks pass |
| API and browser item workflows | Implemented; local real PostgreSQL/HTTPS checks pass |
| License inventory | MPL remains blocked; narrow additional permissive-license decision pending |
| Offline gate-2 on exact candidate | Run on Spark; not yet claimed |
| Hosted workflow/vulnerability checks | Candidate must pass before release |
| Brave walkthrough | Owner pending; Chromium is not identical to Brave |
| Native amd64/arm64 release | Workflow implemented; published artifact acceptance pending |
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
