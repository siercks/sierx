# Phase 2 operator walkthrough

This is the candidate-code walkthrough, not a declaration of Phase 2 acceptance.
The owner runs Spark commands and chooses all real host values privately. Brave
is the primary manual browser; Firefox is the second browser. Automated Chromium
coverage does not prove Brave-specific behavior.

## 1. Verify the candidate in a disposable environment

Use a new checkout, not an existing working tree or your persistent database:

```bash
git clone --branch build/phase-2-frontend https://github.com/siercks/sierx.git sierx-phase2
cd sierx-phase2
git status --short
git rev-parse HEAD
sudo apt-get update
sudo apt-get install -y shellcheck
make ci-local-prepare
make ci-local
make check-workflows
make check-vulnerabilities
make check-web-supply-chain
```

Record the full revision before running commands. The package commands install
the host prerequisite for workflow lint on Debian/Ubuntu systems; use the host's
equivalent package manager elsewhere. `ci-local-prepare` downloads
native toolchains, npm packages and pinned browsers. `ci-local` runs the complete
`gate-2` in a disposable network-disabled container with its own database. It does
not mount the host database, host environment file, production ports or sockets.
The online vulnerability checks need the host toolchains and a prepared local
frontend (`npm --prefix web ci` and `make web-build`). These online scans are
separate from offline acceptance. ShellCheck is required for workflow lint.

Do not run the destructive migration/seed composite gates against a real backlog.
The normal browser fixture and the 10,000-item fixture are separate temporary
databases. Playwright traces can contain fixture credentials; keep reports private
and publish only scrubbed summaries/screenshots. Record browser versions from the
installed browser, not from the name of a compatibility project.

## 2. Build a release without building on the deployment device

The release workflow builds both native Linux architectures, embeds the frontend,
packages a scratch runtime, publishes the architecture images and a digest-pinned
manifest. Dispatch it for the **same accepted revision**, or release a reviewed tag.
The resulting `deployment-manifest` artifact contains `release.json`. Do not move
that manifest to the deployment channel until the revision's required checks pass.
The existing manual multistage `scripts/release-image.sh` path is for a builder
with both platform capabilities; native hosted builds are preferred.

With an authenticated GitHub CLI, dispatch and inspect the branch build as
follows. Set `RUN_ID` to the numeric ID printed by `gh run list`, and confirm
that `headSha` is the revision accepted in step 1:

```bash
gh auth status
gh workflow run release.yml --ref build/phase-2-frontend
gh run list --workflow release.yml --branch build/phase-2-frontend --limit 5
RUN_ID=replace-with-run-id
gh run view "$RUN_ID" --json headSha,status,conclusion,url
gh run watch "$RUN_ID" --exit-status
install -d -m 700 "$HOME/.local/share/sierx/release-review"
gh run download "$RUN_ID" --name deployment-manifest \
  --dir "$HOME/.local/share/sierx/release-review"
python3 -m json.tool "$HOME/.local/share/sierx/release-review/release.json"
```

The GitHub web interface is an equivalent route when `gh` is unavailable.
Review the full revision and image digest before publishing the manifest.

Publish the reviewed `release.json` to an owner-controlled HTTPS URL. The target
pulls this manifest; there is no inbound deployment webhook or self-hosted runner.
Use immutable app and Caddy image digests. Registry authentication, if necessary,
is configured privately on the deployment host.

## 3. Prepare a trial deployment

Keep trial, benchmark and real databases separate. Start with a fresh **trial**
database and standard migrations, then bootstrap an empty SRX workspace using
`SIERX_BOOTSTRAP_*` variables from `.env.example`. Never seed the real database.
The PostgreSQL runtime remains the existing pinned rootless Quadlet setup.

Provision DNS/certificates for an HTTPS origin, inbound TCP 443 and UDP 443 for
HTTP/3, and certificate issuance as required by your Caddy configuration. The
rootless host must permit its gateway to bind the chosen HTTPS port (an operator
host setting); do not expose the application's loopback port. Enable user lingering
for the service owner so its units survive logout. Verify these host prerequisites
before applying the deployment. The supplied gateway is local-login mode. Identity
proxy deployments require a reviewed gateway that strips untrusted identity
headers and supplies the configured trusted-proxy CIDRs; do not simply toggle the
app to proxy mode behind the unauthenticated template.

Create `~/.config/sierx/app.env` with permissions **0600**. Supply DATABASE_URL,
SIERX_SESSION_KEY, SIERX_AUTH_MODE=local, SIERX_BASE_URL and
SIERX_LISTEN_ADDR=127.0.0.1:<chosen app port>. Protect and back up the session key:
it also protects second-factor state. Keep all host files outside Git.
The repository default publishes the rootless PostgreSQL container on loopback
port 55432 and keeps 5432 inside the container. Keep that explicit port in
DATABASE_URL, or choose another free unprivileged host port.

Create the protected files and enable user services after logout:

```bash
sudo loginctl enable-linger "$USER"
loginctl show-user "$USER" -p Linger
install -d -m 700 "$HOME/.config/sierx"
umask 077
touch "$HOME/.config/sierx/app.env" "$HOME/.config/sierx/deploy.env"
chmod 600 "$HOME/.config/sierx/app.env" "$HOME/.config/sierx/deploy.env"
${EDITOR:-nano} "$HOME/.config/sierx/app.env"
${EDITOR:-nano} "$HOME/.config/sierx/deploy.env"
```

Create a private `~/.config/sierx/deploy.env` with these required inputs:

| Variable | Meaning |
|---|---|
| SIERX_DEPLOY_MANIFEST_URL | Reviewed release.json HTTPS URL |
| SIERX_IMAGE_REPOSITORY | Exact permitted application repository, without tag |
| SIERX_CADDY_IMAGE | Caddy image including @sha256 digest |
| SIERX_BASE_URL | Real HTTPS origin matching app.env |
| SIERX_APP_PORT | Unprivileged loopback application port |

After the fresh trial database exists, load `app.env` and apply migrations. This
does not reset or seed the database:

```bash
set -a
. "$HOME/.config/sierx/app.env"
set +a
make migrate-up
make migrate-status
```

Load the private deployment environment into the operator shell, then apply the
reviewed release:

```bash
set -a
. "$HOME/.config/sierx/deploy.env"
set +a
make deploy-plan
make deploy-apply
systemctl --user status sierx.service sierx-caddy.service
```

Bootstrap the empty trial workspace with the `sierxctl` binary from the accepted
release image. The password is read without echo and is inherited by the
temporary container rather than placed in its command line:

```bash
DEPLOYED_IMAGE=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".local/share/sierx/current.json").read_text())["image"])')
export SIERX_BOOTSTRAP_WORKSPACE_SLUG=trial
export SIERX_BOOTSTRAP_WORKSPACE_NAME='Sierx trial'
export SIERX_BOOTSTRAP_ADMIN_EMAIL='replace-with-private-admin-email'
export SIERX_BOOTSTRAP_ADMIN_NAME='Administrator'
export SIERX_BOOTSTRAP_PROJECT_PREFIX=SRX
export SIERX_BOOTSTRAP_PROJECT_NAME='Sierx backlog'
read -rsp 'Initial administrator password: ' SIERX_BOOTSTRAP_ADMIN_PASSWORD
export SIERX_BOOTSTRAP_ADMIN_PASSWORD
printf '\n'
podman run --rm --network host \
  --env-file "$HOME/.config/sierx/app.env" \
  -e SIERX_BOOTSTRAP_WORKSPACE_SLUG -e SIERX_BOOTSTRAP_WORKSPACE_NAME \
  -e SIERX_BOOTSTRAP_ADMIN_EMAIL -e SIERX_BOOTSTRAP_ADMIN_NAME \
  -e SIERX_BOOTSTRAP_ADMIN_PASSWORD -e SIERX_BOOTSTRAP_PROJECT_PREFIX \
  -e SIERX_BOOTSTRAP_PROJECT_NAME \
  --entrypoint /usr/local/bin/sierxctl "$DEPLOYED_IMAGE" bootstrap
unset SIERX_BOOTSTRAP_ADMIN_PASSWORD
```

The apply command checks image revision labels, keeps old hashed assets for open
sessions, writes user Quadlets and verifies HTTPS health. Failure restores previous
unit/config files; on a first-install failure it stops the candidate services.
It never migrates or resets a database. Automatic schema migrations are deliberately
absent; Phase 2 adds none. Test rollback privately before enabling `make deploy-timer`.
The pull timer checks every five minutes and does nothing for an already accepted
manifest. For host-only configuration changes, restart the affected unit manually;
the manifest timer is an application release mechanism.

## 4. Walk through the browser

1. Sign in with the bootstrap account. Try a wrong password first. For an enrolled
   account test its authenticator, then a recovery code; a consumed recovery code
   must fail. Account-security enrollment remains the existing API operator flow.
2. Switch through System, Light, Dark, Light high contrast and Dark high contrast.
   Reload each. Check system color/contrast and reduced-motion preferences.
3. Use only Tab, Shift+Tab, Enter, Escape and ordinary typing to create an epic and
   a story. Change the story to Doing, assign yourself, reparent and reorder it,
   add a comment, edit it and create/remove a link. Escape should return focus.
4. Edit an item in two independent sessions. Save one, then save the other. Read
   the current/submitted comparison. Cancel once and verify the draft remains;
   deliberately retry afterward. Failed writes must preserve entered text.
5. Search with `project = SRX`. Copy the resulting URL, reopen it, reload and use
   Back. Try an invalid field and inspect its error. Open an item directly and
   reload it; lowercase keys and a trailing slash should canonicalize.
6. Paste hostile HTML/Markdown into a description. It must display safely, without
   active HTML or remote images. Soft-delete an item: its link must show a dated
   banner and no editing controls. Check 200% text, spacing overrides and narrow
   windows. Inspect visible focus, labels, status accents and error copy.
7. Expire a session while a draft is open. Keep the tab, sign in in a second tab,
   use Continue this session and retry without losing the draft.
8. Repeat the important steps in Firefox. Record your actual Brave/Firefox versions,
   revision, issues and design/copy/60-30-10 review decisions.

For automated deployed smoke, privately set SIERX_SMOKE_URL, SIERX_SMOKE_EMAIL,
SIERX_SMOKE_PASSWORD, optional SIERX_SMOKE_CODE, and SIERX_SMOKE_ITEM, then run
`python3 scripts/release-smoke.py`. It validates certificate trust, HTTPS login,
secure cookies, private HTML and useful deep-link state. Run it before and after
`systemctl --user restart sierx.service`; the item fingerprint should stay equal.
Use a fresh valid second factor for each login. No password is printed.

Keep those values in another protected file and run the smoke check on both
sides of an application restart:

```bash
umask 077
touch "$HOME/.config/sierx/smoke.env"
chmod 600 "$HOME/.config/sierx/smoke.env"
${EDITOR:-nano} "$HOME/.config/sierx/smoke.env"
set -a
. "$HOME/.config/sierx/smoke.env"
set +a
python3 scripts/release-smoke.py
systemctl --user restart sierx.service
systemctl --user is-active sierx.service sierx-caddy.service
python3 scripts/release-smoke.py
journalctl --user -u sierx.service -u sierx-caddy.service --since '-10 minutes' --no-pager
```

Compare the two printed item fingerprints; they must match.

## 5. Prove recovery before cutover

See [the physical-backup runbook](../deploy/pgbackrest/README.md). Do not enable an
unverified driver in the normal backup list. Configure encrypted **off-machine**
SFTP or S3 storage (or an independently verified off-machine POSIX mount), protected
credentials and continuous WAL archiving. A local path alone is not off-machine.
Run conformance against representative **quiescent trial data**, never an empty
source. Writes during comparison invalidate the comparison.

A temporary conformance selection is allowed for testing:

```bash
SIERX_BACKUP_DRIVERS=pgbackrest make backup-conformance
make backup-cipher-check BACKUP_DRIVER=pgbackrest
```

Supply a separate restore root, port, scratch database and protected authentication
configuration. The physical driver restores to a fresh private cluster directory,
starts it on loopback, transfers recovered data to a newly created scratch database,
and compares all data tables, sequence counters/high-water marks and rollups. It
refuses existing scratch database names and never deletes a caller's directory.
Keep physical restore evidence private and prune it only after review.

For application-level recovery acceptance, configure a separate HTTPS restore-test
gateway and set SIERX_RESTORE_APP_CHECK=scripts/restore-app-check.sh. The hook requires
SIERX_RESTORE_IMAGE (accepted digest), SIERX_RESTORE_APP_ENV (0600 auth config with
original session key), SIERX_RESTORE_BASE_URL, SIERX_RESTORE_APP_PORT (different from
the live app) and the private smoke credentials/item above. It launches that exact
image against the restored scratch database and runs HTTPS login/deep-link checks.
Without the hook conformance explicitly reports application access as NOT CHECKED;
that is insufficient for cutover. Run both conformance and the immutable-cipher
check successfully before adding the physical driver to the normal configured list.

After acceptance, install the private `backup.env` for the PostgreSQL data-directory
owner and run `python3 scripts/deploy.py install-backup-timer`. The timer performs a
Sunday full backup and daily incremental backups at 02:00 UTC with verification and
retention. Ensure its service account can read the cluster and repository. Check
systemd failures daily; record the accountable person and last successful restore.
Keep the existing restore-test timer and schedule periodic isolated app restore checks.
Do not describe scheduling as proof that a backup succeeded.

## 6. Real backlog and phase exit

After durable trial deployment and recovery are accepted, provision a separate fresh
real database, migrate it and bootstrap the real workspace with SRX as its first
project. Point the reviewed deployment at that database. Confirm the real project
has no trial data. Set SIERX_CUTOVER_ACCEPTED=1 only after completing the checklist,
then run `python3 scripts/cutover.py` with the real private smoke login inputs.
It creates SRX-1 describing Phase 3 and refuses a nonempty active backlog. Inspect
any failure before repeating; no import or database reset is performed.

Move remaining actual work into Sierx. Begin the seven-day record only when Sierx
is the primary backlog. Use [the acceptance record](PHASE-2-ACCEPTANCE.md). Spark
numbers must be labeled Spark; no Raspberry Pi or small-host performance claim is
made here. Record representative-hardware acceptance separately under ADR-020.
Phase 3 implementation waits for actual Phase 2 exit approval.
