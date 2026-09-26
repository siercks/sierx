# Offline delivery

Sierx continues to support connected deployments. This profile moves registry
and migration-tool downloads into connected release assembly, then transfers
an architecture-specific directory to an isolated host. It uses the same promoted
application image, database migrations and deployment controller. It does not
provide browser offline editing.

## Supported boundary

The initial host profile is Ubuntu 24.04, native Linux amd64 or arm64, rootless
Podman 4.9.3 and systemd 255 with cgroup v2. The OS provisioning process must
supply Python 3.11+, Bash, coreutils, a working user systemd manager, subordinate
UID/GID ranges and lingering for the dedicated service account. Install these
before isolation, or provide your organization's separately verified OS package
repository/media. This bundle is not an OS installer. 32-bit x86 is unsupported.

Local authentication is the initial isolated-host profile. Internal DNS, time
synchronization, site certificate authority and backup destinations may be
reachable; public Internet access is unnecessary. No Cloudflare connector is
required. Supply a certificate from your internal PKI (or another already trusted
issuer); certificate issuance and renewal are the site's responsibility.

The bundle contains:

- Three native OCI archives: the promoted app, pinned PostgreSQL and pinned Caddy.
- The native `sierxctl` extracted from that exact app image and checksum-pinned Goose.
- The complete tracked source snapshot at the release revision, including exact
  migrations, deployment templates, backup drivers, documentation, project/vendor
  licenses and frontend dependency/license inventories. No Git metadata or caches.
- The release's application CycloneDX SBOM, Goose license/tool inventory, original
  image references, configuration digests and hashes/sizes of every delivered file.

The application SBOM does not claim to inventory every distribution package in
the PostgreSQL/Caddy images. Their exact image identities are recorded separately;
image vulnerability assessment and distribution license/source obligations remain
part of release review. Credentials, private certificates, live databases and
backups never belong in the bundle.

## Prepare while connected

Use a clean checkout **at the exact promoted release revision**, on the matching
native architecture. Download the release manifest and matching application SBOM
from its successful release workflow. The release workflow runs this assembly and
its isolated acceptance test separately on amd64 and arm64, publishing an
`offline-delivery-<arch>` artifact only after the test succeeds.

```bash
python3 -B scripts/offline.py prepare \
  --release /absolute/review/release.json \
  --sbom /absolute/review/sbom-amd64.cdx.json \
  --caddy-image docker.io/library/caddy@sha256:0c994536bddb66445885237f1a5dcc1916bccea922661c76b4e9fc24061f9b52 \
  --output /absolute/delivery/sierx-offline-amd64
```

For arm64, use its SBOM and output name. Preparation pulls the pinned images,
verifies architecture and application revision, exports by configuration ID,
and downloads/validates Goose. Exporting by ID avoids OCI archive name/digest
ambiguities when the original reference names a multiarch index. No image rebuild
or mutable deployment tag is introduced.

Record the printed `bundle.lock.json` SHA-256 in the release approval record.
Keep a protected copy of the trusted verifier (`scripts/offline.py`) and transfer
the bundle using approved media. To use tar for transport, preserve executable
permissions and verify the independently approved outer archive digest **before
extraction**. Extract as an unprivileged account into a new empty directory.

## Trust and verify

The trust anchor is the lock digest received through an independently authenticated
approval channel, plus the previously trusted verifier. A checksum file copied
beside untrusted media is not authentication. This format does not claim publisher
signatures, transparency-log checks or automatic trust bootstrapping.

Do not execute the verifier from unverified media first. From a trusted copy:

```bash
python3 -B /opt/trusted-sierx/offline.py verify \
  --bundle /opt/sierx/releases/REVIEWED_RELEASE \
  --expected-sha256 APPROVED_LOCK_SHA256
```

Verification rejects changed/missing/unlisted files, links, unsafe paths, a wrong
architecture and inconsistent release/image metadata. Keep the directory immutable
to other users throughout verification and execution. Do not place reports,
environment files, editor caches or backup data inside it. `-B` suppresses Python
bytecode caches. Save both the old and new approved bundles for rollback.

## Install and operate without downloads

As the dedicated lingering service account, establish the user service context
again after every new login:

```bash
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export SIERX_OFFLINE_BUNDLE=/opt/sierx/releases/REVIEWED_RELEASE
export SIERX_OFFLINE_SHA256=APPROVED_LOCK_SHA256
```

Create private mode-0600 `~/.config/sierx/app.env` and `deploy.env` using the
existing deployment documentation. In app.env, use the intended local database
URL, local authentication, a generated session key, HTTPS origin and loopback
application address. In deploy.env set:

```ini
SIERX_BASE_URL=https://tracker.example.test:8443
SIERX_APP_PORT=18081
SIERX_GATEWAY_MODE=direct
SIERX_TLS_MODE=provided
```

The explicit 8443 port works with an unprivileged account. If using 443, arrange
the host's privileged-port policy separately. Use the same origin in app.env.
Install the full certificate chain at `~/.config/sierx/tls/server.crt` and its
private mode-0600 key at `server.key` in that directory. Distribute the CA trust
to browsers and the operator host. Set `SSL_CERT_FILE` to an absolute approved
CA bundle if host trust has not been configured. Never disable TLS verification.
The provided-certificate profile disables automatic certificate issuance, port-80
redirects and the Caddy admin listener. Offline mode also disables OCSP stapling
fetches; use your site's certificate/revocation policy. Restart `sierx-caddy.service`
after replacing certificate files, then rerun the HTTPS smoke check.

```bash
set -a
. "$HOME/.config/sierx/app.env"
. "$HOME/.config/sierx/deploy.env"
set +a
cd "$SIERX_OFFLINE_BUNDLE"
python3 -B scripts/offline.py import
python3 -B scripts/offline.py db-up
python3 -B scripts/offline.py migrate-status
python3 -B scripts/offline.py migrate-up
```

`import` verifies all files before loading images and checks the loaded IDs,
architecture and app revision. It changes no services or database. Database setup
uses the verified local PostgreSQL ID and retains its volume. Migrations remain
an explicit operator action; inspect status and take a tested backup before an
update. Never run `db-reset` or migration up/down tests against this installation.

For a new empty workspace only, enter the `SIERX_BOOTSTRAP_*` inputs privately as
described in `.env.example`, then run `python3 -B scripts/offline.py bootstrap`.
Clear the bootstrap password afterward. Continue with:

```bash
python3 -B scripts/offline.py plan
python3 -B scripts/offline.py apply
systemctl --user is-active sierx-postgres.service sierx.service sierx-caddy.service
```

The wrapper supplies the locked manifest/tool/image inputs and overrides a stale
online manifest URL. The controller refuses public ACME or tunnel mode while
offline. Application, database and gateway units use `Pull=never`; a missing image
fails instead of contacting a registry. Provided TLS works in connected mode too.

After setting private `SIERX_SMOKE_*` inputs for an existing item, run
`python3 -B scripts/offline.py smoke`. Compare fingerprints after service restart
and host reboot. Keep credentials outside shell history and reports.

## Updates, rollback and recovery

Import a second approved bundle into the same user's image store, review migration
compatibility and backups, then repeat plan/apply from that bundle. Application
deployment retains the previous units and restores them on failed HTTPS health.
The retained images are required for rollback; do not prune them during acceptance.
Switching images never reverses migrations or restores old data. A successful
health probe does not establish schema compatibility with an older application.

The shipped backup drivers and native CLI run without Git or source builds.
Backup/restore hosts still need their selected tools provisioned ahead of isolation:
PostgreSQL 18 client tools for logical backups; the configured physical backup
driver, PostgreSQL binaries and repository transport for physical recovery.
Set an absolute `SIERX_DUMP_DIR` outside the bundle even when testing recovery.
Restore rotation state defaults to `~/.local/share/sierx/restore` through the
offline wrapper; `SIERX_RESTORE_STATE_DIR` may select another external directory.
Use `offline.py backup` and `offline.py restore-test` with the existing protected
driver and dedicated `sierx_restore_*` scratch settings. Keep the restored app,
database and ports separate from the live installation. The bundle supplies no
repository credentials, backup cipher passphrase or data.

Encrypted off-machine physical backup, same-architecture restore, restored-app
access and wrong-key rejection remain required before real cutover. Logical
cross-architecture migration is a separate procedure. Offline timer installation
is deliberately rejected until a site reviews a schedule using the verified
wrapper and protected trust inputs. This prevents the connected pull timer from
silently becoming the offline update mechanism.

Archive delivery is the implemented offline acquisition path. An internal registry
mirror is a later adapter: it must preserve approved image identity and have its
own CA/authentication configuration; changing tags is not a substitute for bundle
verification. There is no public-registry fallback in the offline profile.

## Evidence and acceptance limits

Python tests reject tampering, omitted dependencies, unlisted files, wrong native
architecture, release mismatch and online-only settings. The real acceptance harness
runs in a fresh Linux network namespace containing only loopback, with a separate
empty Podman image store. It imports all archives, applies migrations, bootstraps,
serves supplied-certificate HTTPS, performs authenticated writes/deep links, and
compares item fingerprints after database/app/gateway restart. It never uses the
operator's user services or database. Its report names the release and lock digest.

To repeat it on a prepared disposable validation host:

```bash
sudo env SIERX_OFFLINE_BUNDLE="$SIERX_OFFLINE_BUNDLE" \
  SIERX_OFFLINE_SHA256="$SIERX_OFFLINE_SHA256" \
  SIERX_OFFLINE_REPORT=/absolute/evidence/offline-acceptance.json \
  unshare --net -- python3 -B scripts/test-offline-bundle.py
```

This test additionally needs root namespace/container privileges, iproute2 and
OpenSSL. Failure produces no passing report; subprocess diagnostics are private
and must not be uploaded as public artifacts. Native amd64 and arm64 workflow
reports are required. A local fixture run is development evidence only.

Before claiming fresh-host airgap support, also record actual rootless systemd
installation, SSH disconnect, full reboot, two-release update/rollback and separate
encrypted backup recovery on the supported hosts with external egress blocked.
Those host/recovery checks are not replaced by the network-namespace test. The
initial branch must not be described as complete production airgap certification.

Implementation references: [Podman 4.9 Quadlet](https://docs.podman.io/en/v4.9.3/markdown/podman-systemd.unit.5.html)
and [Caddy supplied certificates](https://caddyserver.com/docs/caddyfile/directives/tls).
