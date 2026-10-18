# Lifecycle operator runbook

Use the accepted native `sierxctl` binary on the database host, with a verified restricted case. The commands are privileged operator workflows. Do not put personal details or passwords in case identifiers, public reports or shell history. Review `docs/DATA-LIFECYCLE-DESIGN.md` before any permanent action.

## Initialize before starting the new application

Migrate an existing database with its migration/operator login; do not reset or bootstrap over existing work. Confirm a tested backup first. Set these values in a private operator environment, using absolute paths outside the checkout and backup restore tree:

- `SIERX_MAINTENANCE_DATABASE_URL`: maintenance role connection.
- `SIERX_LIFECYCLE_JOURNAL`: encrypted decision journal path.
- `SIERX_LIFECYCLE_KEY_FILE`: separate master key path.
- `SIERX_LIFECYCLE_CHECKPOINT`: current trusted checkpoint path.

Create private 0700 parent directories; then run `sierxctl lifecycle init` once. Initialization creates new 0600 journal/master/checkpoint files and `verification.key` next to the checkpoint, refuses overwrite, and binds them to the migrated instance. Failed partial initialization requires operator inspection; never replace existing production state with a new empty journal. Keep the master key away from the app and backed up independently of the database. Protect the current checkpoint from restoration with an older database backup.

For the shipped container deployment, the checkpoint directory is `$HOME/.local/share/sierx/lifecycle/guard`, with 0700 directory and 0600 `checkpoint.json`/`verification.key`. The app environment contains only:

```text
SIERX_LIFECYCLE_CHECKPOINT=/var/lib/sierx/lifecycle/guard/checkpoint.json
SIERX_LIFECYCLE_GUARD_KEY_FILE=/var/lib/sierx/lifecycle/guard/verification.key
```

The container maps the rootless host owner to the unprivileged image user and mounts this directory read-only. For native execution, use the real protected file paths. Existing app environment must contain runtime and auth role URLs, never operator/maintenance credentials or the journal master key. A release without guard initialization intentionally fails startup. Make an encrypted, access-controlled off-machine copy of the current journal, key and checkpoint after decisions; keep ownership and trust records private.

## Plan and apply a reviewed action

Write a private 0600 JSON action file. UUIDs below are placeholders, not example production identities:

```json
{"kind":"redact-item","case_ref":"<case-uuid>","workspace_id":"<workspace-uuid>","target_id":"<item-uuid>"}
```

Run `sierxctl lifecycle plan --file <private-action.json>` and review its bounded target counts. Then run `sierxctl lifecycle apply --file <private-action.json>` and `sierxctl lifecycle verify`. Apply revalidates the plan; it does not trust edited counts or an earlier preview. The CLI adds the timestamp, instance/origin and exact IDs itself. Output contains metadata/counts, never correction text. Decisions are irreversible where noted:

| kind | Required fields beyond case/workspace | Behavior |
|---|---|---|
| `hold-create` | `authority_ref`, future `review_at`; optional new `target_id` | Preserve workspace; generated hold ID is reported |
| `hold-release` | hold `target_id` | Audited explicit release; review dates never release holds |
| `takedown` | item `target_id` | Reversible subtree access restriction; restricted descendants prevent ancestor hierarchy movement until resolved |
| `restore-content` | original takedown root `target_id` | Release only this reversible notice |
| `redact-item` | item `target_id` | Permanent bounded subtree/comment/event-value redaction |
| `redact-comment` / `redact-view` | content `target_id` | Permanent targeted content redaction |
| `redact-history` | item `target_id` | Replace its history values, preserving metadata |
| `correct-history` | item `target_id`, `event_seq`, bounded `correction` | Permanent historical value correction |
| `remove-member` | account `target_id`, active admin `replacement_id` | Reassign ownership, remove membership, revoke sessions |
| `anonymize-account` | account `target_id` | Permanent account/attributed-content anonymization after prerequisites |
| `retention` | explicit past `cutoff` | Bounded previously deleted content only |
| `cleanup` | case only; no workspace | Expired sessions/artifacts, respecting holds |

Holds prevent destructive actions and audit blocked attempts. Do not repeatedly retry an unauthorized action. Keep downloaded copies and external evidence under the restricted case process. `exports create --user <uuid> --workspace <uuid> --case <uuid>` creates the bounded workspace export; omit `--workspace` for the limited account export. Download with `exports download --id <uuid> --case <uuid> --out <new-private-file>`. Creation/retrieval require the maintenance role. Verify authority and communicate the scope/truncation limits to the requester.

## Optional scheduled maintenance

No timer is activated by default. A private `~/.config/sierx/retention.json` policy has the form:

```json
{"enabled":false,"case_ref":"<reviewed-case-uuid>","workspaces":[{"workspace_id":"<workspace-uuid>","deleted_content_days":30}]}
```

The number above is an illustration, not an instance policy or legal requirement. Supply reviewed durations (positive whole days), UUIDs and `enabled:true` only when ready. Test `sierxctl lifecycle maintain --policy <private-policy-file>` manually. Each run processes a bounded batch per workspace and cleanup. A held/refused workspace produces a failed run and restricted audit; other configured workspaces can still progress. Review repeated failures and remaining batches.

To install the optional daily 03:00 UTC timer, provide a 0600 `~/.config/sierx/lifecycle.env` with maintenance/journal/key/checkpoint paths, the enabled private policy above, and `SIERX_OPERATOR_BIN` pointing to the accepted executable. Run `make deploy-lifecycle-timer`. Installation validates prerequisites; offline hosts use separately reviewed manual schedules. Review actual timer status and private logs. Existing general maintenance/backup schedules still have their own jobs; configure host/proxy log retention and encrypted backup expiry separately.

## Restore and interrupted writes

1. Stop ordinary app access. Preserve the current external journal/master/checkpoint; never restore these from the old database backup.
2. Restore the database through the backup driver. Logical archives now preserve owners and ACLs; the original operator and restricted roles must exist on the restore cluster. Any missing-role/ACL failure rejects restore.
3. Set the maintenance URL to the restored database. Run `sierxctl lifecycle replay`, then `sierxctl lifecycle verify`. A valid older database must be an exact journal prefix; instance/origin mismatches and corrupt/truncated journals fail.
4. Run the restored application smoke and verify redacted/taken-down content, disabled accounts, session revocation, counters and rollups. Only then allow ordinary access.

`restore-test` and backup conformance integrate replay when their private operator environment has the lifecycle materials. The application-access hook uses the restored database's restricted role connections and mounts only the checkpoint/verification key. See `docs/OFFLINE-DELIVERY.md` for the larger recovery drill.

If a process crashes after a journal append but before checkpoint publication, verify the process is dead, preserve files and inspect the private lock. Remove only that stale empty `.lock` directory after confirming no process owns the operation. `sierxctl lifecycle reconcile-checkpoint` authenticates a tail extending the last trusted checkpoint; it refuses truncation. Then replay and verify before reopening access. Never repair by truncating the journal or resetting database receipts. Missing/corrupt master material requires trusted recovery; do not bypass the guard. Hold releases and redactions are historical replay decisions, not new authorization decisions during recovery.

## Acceptance

`make test-lifecycle` creates disposable named databases and tests real CLI/HTTP/SQL operations, holds, independent takedowns, content/correction handling, membership revocation, bounded exports, the running guard and old populated backup replay. Unit tests cover tampering and crash-tail recovery. These automated tests do not establish actual host backup durability, operator case authority, legal suitability or manual browser acceptance. Record those and the exact candidate in `docs/PHASE-2-ACCEPTANCE.md` before the seven-day collection window.
