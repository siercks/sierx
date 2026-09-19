# pgBackRest operations

This directory holds the config template and the runbooks. The driver is
`scripts/backup/driver-pgbackrest.sh`.

**Status: the pgBackRest driver has not passed `make backup-conformance`.**
ADR-017 is explicit that a driver which has not passed conformance is not a
driver, so `SIERX_BACKUP_DRIVERS` must not list `pgbackrest` until it has. The
`pgdump` driver is conformance-green and is what the restore test currently
rotates through. See `PROGRESS.md` task 0.11.

The config is never hand-edited. `scripts/backup/render-conf.sh` renders
`pgbackrest.conf.tmpl` from the environment; `render-conf.sh --check <path>`
fails if the installed file has drifted, and the driver runs that check before
every operation.

---

## Phase 2 implementation and first acceptance

The physical `restore-to` verb is implemented. It creates a fresh private restore
cluster, replays recovery there, then transports that recovered database into the
new scratch database required by the shared driver contract. Configure
PGBACKREST_RESTORE_PATH outside source PGDATA and a distinct unprivileged
PGBACKREST_RESTORE_PORT. PostgreSQL 18 server/client tools must be available to
the data-directory owner. No caller-supplied directory is removed or overwritten.

Use the transport-specific PGBACKREST_SFTP_* or PGBACKREST_S3_* variables in
`.env.example`, render the private config, then configure PostgreSQL continuous
WAL archiving with the selected stanza/config. Verify the repository is genuinely
off-machine. SFTP requires a verified known-hosts file and strict key checking.

Run shared conformance on nonempty quiescent trial data, then
`make backup-cipher-check BACKUP_DRIVER=pgbackrest`. The latter requires encrypted
repository metadata and rejects access with cipher=none or an incorrect key. It
never rewrites the repository or its protected config. Successful encrypted
backup alone is not enough: compare restored counts, all table checksums,
sequence state and rollups, and exercise login/deep links through the restored
application using the hook in [the walkthrough](../../docs/PHASE-2-WALKTHROUGH.md).

The scheduled backup runner chooses a full backup on Sunday and incremental
backups on other days. It verifies each backup and applies retention. Install its
timer only after conformance. Physical acceptance has not been run on this Windows
development host; this document does not claim a usable production backup.

## PostgreSQL major upgrade

The order matters, and getting it wrong is how a repository becomes unusable
at the moment it is needed.

1. **Take a backup and verify it on the old version, before touching anything.**
   ```bash
   bash scripts/backup/driver.sh pgbackrest backup
   bash scripts/backup/driver.sh pgbackrest verify
   ```
2. **Stop the old cluster.** Do not start the new one yet.
3. **Install the new PostgreSQL major version** and initialise or `pg_upgrade`
   the new data directory.
4. **Update `PGBACKREST_PG1_PATH`** in the host's `0600` env file to the new
   data directory, then re-render:
   ```bash
   bash scripts/backup/render-conf.sh /etc/pgbackrest/pgbackrest.conf
   ```
5. **Run `stanza-upgrade` BEFORE starting the new cluster** (ADR-010):
   ```bash
   bash scripts/backup/driver.sh pgbackrest init   # stanza-create, else stanza-upgrade
   ```
   Starting the new cluster first means WAL from an unknown version arrives in
   a stanza that still describes the old one.
6. **Start the new cluster.**
7. **Run the restore test immediately** (ADR-010). Not tonight, not after the
   change window closes:
   ```bash
   make restore-test
   ```
   A stanza upgrade that silently broke restores looks exactly like a stanza
   upgrade that worked until the first restore is attempted.

A physical repository is tied to the PostgreSQL major version. That is why the
`pgdump` driver exists (ADR-017): a `pg_dump -Fc` file from the old cluster is
restorable by the new one with no pgBackRest involved, which is the escape
hatch if the steps above go wrong. Keep the last pre-upgrade dump until the
restore test is green on the new version.

---

## Multiple repositories

The current renderer and cipher check support repository 1 only. Choose its
off-machine destination before acceptance. A second repository needs an explicit
template/driver extension and conformance for that destination; selecting
PGBACKREST_REPO=2 today is rejected. Existing restore-test rotation is across
drivers, not automatic repository selection. Do not claim a second destination
is protected until it is configured, tested and included in actual rotation.

**Encryption cannot be changed on an existing stanza.** `repo-cipher-type` and
`repo-cipher-pass` are fixed when the stanza is created; changing either means
creating a new stanza and taking a full backup. This has NOT been verified
against an installed pgBackRest in this build — BUILD task 0.11 step 5 asks
for that verification, and it is outstanding. If it turns out the cipher *can*
be changed in place, ADR-010's table is wrong and should be corrected.

---

## Swapping in a different tool (WAL-G, or anything else)

ADR-017 exists so this is three steps rather than a project:

1. Write `scripts/backup/driver-walg.sh` implementing the six verbs with the
   same contracts. `bash scripts/backup/driver.sh --contract walg` checks the
   shape.
2. Run `SIERX_BACKUP_DRIVERS=walg make backup-conformance`. Until that passes,
   it is not a driver.
3. Change `SIERX_BACKUP_DRIVERS` in the host env file. No `make` target and no
   Go code names a tool — `make gate-nobackupleak` enforces that — so nothing
   else changes.

Keep the old driver configured alongside the new one for at least one full
retention period. A new driver whose first real test is the first real
incident is not an improvement.
