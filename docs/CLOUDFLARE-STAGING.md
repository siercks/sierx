# Persistent staging through Cloudflare Tunnel

This is an optional connected deployment profile. It does not establish air-gap
support or direct-origin HTTP/3 acceptance. The application image is unchanged.
Use this guide with PHASE-2-WALKTHROUGH.md and RELEASE-ASSURANCE.md.

## 1. Accept one candidate

Publish the uplift branch and require both native CI jobs and security checks to
pass at its current revision. Manually dispatch the release workflow on that
branch. Both native image tests and promotion must pass. Download that run's
deployment-manifest artifact and verify the revision and architecture evidence.
Do not use an older green revision to accept new deployment changes.

Keep automatic deployment polling disabled while testing. Copy the reviewed
release.json to the staging account's ~/.local/share/sierx/release-review/.
Set SIERX_DEPLOY_MANIFEST_FILE to its absolute path. Leave
SIERX_DEPLOY_MANIFEST_URL unset. This avoids publishing a separate manifest URL;
it does not authenticate an arbitrary file or remove registry/tool downloads.

## 2. Prepare a separate host account

First inspect the intended Linux host (read-only):

```sh
uname -m
podman --version
systemctl --version | head -n 1
systemctl --user is-system-running
loginctl show-user "$USER" -p Linger
command -v cloudflared || true
```

Use a dedicated staging account, such as sierx-stage, to avoid the existing
user's fixed container/volume names and development database. An administrator
creates that account with rootless Podman support and enables lingering for it.
Lingering on the development account does not cover the staging account.
Do not delete or reuse the development database volume.

Example for Ubuntu, only after confirming the new account does not already exist:

```sh
sudo adduser --disabled-password --gecos '' sierx-stage
sudo loginctl enable-linger sierx-stage
sudo -iu sierx-stage
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
systemctl --user is-system-running
loginctl show-user "$USER" -p Linger
```

Verify rootless Podman prerequisites, available disk, and free host ports before
deployment. The examples below reserve application 18081, gateway 18080 and
database 55433. Existing listeners must not be replaced. Clone the branch as this
user and check out the exact accepted commit. Install the operator prerequisites
from BUILD.md; the application runtime is the accepted image, not a source build.

## 3. Locate Cloudflare and configure the connector

Sign in at https://dash.cloudflare.com/. Select the account containing your
domain. If it is absent, locate its owner/account before making DNS changes.
Current dashboard path: Networking > Tunnels > Create Tunnel. Older Cloudflare
One dashboards may group connectors under Networks. Use a named remotely-managed
tunnel, for example sierx-staging, and select Linux ARM64 for an arm64 host.

Follow the dashboard's package-install instructions on the host. Keep the tunnel
token private; do not paste it into a ticket, repository, screenshot or chat.
For the user service below, install the binary only, rather than also installing
a second system-wide connector service. Require cloudflared 2025.4.0 or newer
for token-file support and verify its actual executable path.

As the staging user, save only the token to a protected file through an editor:

```sh
install -d -m 700 "$HOME/.config/sierx" "$HOME/.config/systemd/user"
umask 077
touch "$HOME/.config/sierx/tunnel-token"
chmod 600 "$HOME/.config/sierx/tunnel-token"
${EDITOR:-nano} "$HOME/.config/sierx/tunnel-token"
```

Create ~/.config/systemd/user/sierx-cloudflared.service with the following content
(adjust /usr/bin/cloudflared if command -v reports another absolute path):

```ini
[Unit]
Description=Sierx staging tunnel
After=network-online.target

[Service]
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate run --token-file %h/.config/sierx/tunnel-token
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

Then run systemctl --user daemon-reload and
systemctl --user enable --now sierx-cloudflared.service. Record the connector
version; keep it fixed during candidate acceptance. Confirm the tunnel is healthy
in Cloudflare. A healthy connector alone does not mean Sierx is deployed.

Add a published application route, using your actual hostname:

| Setting | Example |
|---|---|
| Public hostname | tracker.example.test (replace with your real DNS name) |
| Service | HTTP |
| Origin URL | http://127.0.0.1:18080 |
| HTTP Host Header | The same public hostname, without scheme or port |

The connector must run on the same host network as Caddy. Here the connector is
a host binary, not a bridged container whose localhost points somewhere else.
Do not forward router ports or change the domain's nameservers for this profile.
Review any existing DNS record for the chosen hostname before replacing it.
Until the application is installed, the route may return an origin error.

Ensure no Cloudflare Cache Everything rule overrides the application's private
HTML/API cache headers. Keep app authentication in local mode. Cloudflare Access
is an optional additional layer; if enabled, automated health/smoke requests need
an explicit compatible access policy. Do not silently disable TLS verification
or Sierx login to make a probe pass.

## 4. Prepare database and application configuration

Follow walkthrough section 3 for a fresh staging database, migrations, protected
session key and accepted-image bootstrap. Use a unique staging database and
loopback port 55433. Never run reset/seed gates against persistent staging data.
The staging account's named database volume persists container restarts; it is
not itself a backup. Back up the session key as well as the database.

Protected app.env inputs include:

```ini
DATABASE_URL=postgres://REPLACE_USER:REPLACE_PASSWORD@127.0.0.1:55433/sierx_stage?sslmode=disable
SIERX_AUTH_MODE=local
SIERX_BASE_URL=https://tracker.example.test
SIERX_LISTEN_ADDR=127.0.0.1:18081
SIERX_SESSION_KEY=REPLACE_WITH_PRIVATE_GENERATED_KEY
```

Do not use these placeholder credentials. Protected deploy.env inputs include:

```ini
SIERX_DEPLOY_MANIFEST_FILE=/home/sierx-stage/.local/share/sierx/release-review/release.json
SIERX_IMAGE_REPOSITORY=ghcr.io/siercks/sierx
SIERX_CADDY_IMAGE=REPLACE_WITH_REVIEWED_CADDY_REPOSITORY_AT_SHA256_DIGEST
SIERX_BASE_URL=https://tracker.example.test
SIERX_APP_PORT=18081
SIERX_GATEWAY_MODE=tunnel
SIERX_GATEWAY_PORT=18080
```

Use the same real hostname in the route, app.env and deploy.env. Load deploy.env,
run make deploy-plan, inspect the selected revision, then run make deploy-apply.
The database must already be ready. Public HTTPS health is required: an unavailable
tunnel or failed origin causes rollback rather than accepting a broken deployment.
Bootstrap the empty workspace with the accepted CLI as described in the walkthrough.

Tunnel mode keeps Caddy HTTP and its upstream application on loopback. Caddy's
automatic HTTPS and admin listener are disabled for this profile. Direct mode
remains the default. Moving between gateway profiles at the same image revision
reapplies changed configuration and retains the usual rollback behavior.

## 5. Record acceptance

- Verify HTTPS login, cookies, writes, assets and permanent item links from a
  second device. Use the existing scripts/release-smoke.py with private fixtures.
- Disconnect SSH and the laptop. Confirm the site still works.
- Restart the laptop. Confirm no editor or port forward is required.
- Reboot the host during an agreed test window. Before reconnecting SSH, check
  the site from another device; the connector and user services must return.
- Compare item fingerprints before/after application and host restarts.
- Test an accepted update and rollback. Rollback must use schema-compatible
  candidates; switching an image does not reverse a database migration.
- Install and exercise maintenance/restore services against staging fixtures,
  verify a separate restore, and record backup ownership before real cutover.
- Record image/commit, host profile, Caddy/cloudflared versions, workflow links
  and results. Edge HTTP/3 is not evidence for direct Caddy HTTP/3. Connected
  staging is not evidence for offline installation or recovery.

## References

- https://developers.cloudflare.com/tunnel/get-started/
- https://developers.cloudflare.com/tunnel/reference/run-parameters/#token-file
- https://caddyserver.com/docs/caddyfile/directives/bind

Local preparation: deployment regression tests cover manifest input, tunnel
port/authentication controls, same-revision configuration updates and rollback.
A disposable Caddy 2.11.4 runtime check verified loopback binding, disabled admin,
HTTP API proxying without redirect, static asset serving and wrong-host isolation.
These local results do not substitute for a real Cloudflare route or arm64 host
acceptance.
