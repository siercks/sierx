# Phase 2 release assurance

Sierx supports connected deployment and is being prepared for optional air-gapped
deployment. Offline CI does not establish offline installation/recovery support.
ADR-026 records the owner-approved direction.

## Promotion

The release workflow runs the source gate, builds native amd64/arm64 candidates
with the single `deploy/Containerfile.release` recipe, and stages their images.
Native runners then pull and test those exact digests. Only successful evidence
for both architectures and the current revision permits index promotion and
creation of `release.json`. Index children are verified before and after upload.
Candidate tags are not accepted deployment channels.

The artifact test checks runtime identity, bootstrap, partition maintenance,
authenticated writes, embedded initial documents, graceful stop and restart
persistence. It creates its own temporary PostgreSQL/pod with random loopback
ports and never reads an operator database configuration. HTTP and manual cookie
handling are test-only: separate HTTPS/Caddy, browser and recovery acceptance are
still required. Temporary pods are removed on exit.

On a native Linux host with the pinned Go/Node versions, make, Python, Podman and
curl, use the following sequence at one exact revision:

```sh
make release-binaries release-image ARCH=amd64 TAG=<full-revision>
# Authenticate privately to SIERX_RELEASE_REPOSITORY before publishing candidates.
make release-stage ARCH=amd64 TAG=<full-revision>
make release-test ARCH=amd64
```

Repeat on native arm64. Gather `dist/image-ARCH.txt` and
`dist/acceptance-ARCH.json` for both architectures into the same revision's `dist/`,
then run `make release-manifest TAG=<full-revision>`. These are the same targets
used by CI. Native tests acquire the pinned goose tool and PostgreSQL image while
connected. Cached exact-digest images are reused; an absent image is pulled.
A subsequent offline delivery branch will package these prerequisites.

The former `scripts/release-image.sh` alternative now delegates native candidate
construction to the canonical recipe. Its old `SIERX_RELEASE_IMAGE` shortcut
fails with migration guidance. Use `SIERX_RELEASE_REPOSITORY` and `TAG`; neither
that wrapper nor candidate construction can issue an untested release manifest.

Source/build jobs have read-only repository access. Staging needs package write;
tests need package read; promotion needs release/package write. OIDC permission
is absent until signing actually uses it. Acceptance JSON is workflow evidence,
not a cryptographic attestation. CA hashes record runner input, but do not yet
make that input reproducibly pinned.

## Unit and operator acceptance

`make gate-units` validates every rendered unit using Quadlet and systemd.
`make prove-units` requires a passing baseline before rejecting a deliberately
invalid WorkingDirectory. Missing tools fail the gate. The initial host profile
is Podman 4.9.3/systemd 255; other host profiles need measured acceptance.

Every shipped unit is inventoried in `scripts/deploy.py`:

| Unit | Installer |
|---|---|
| PostgreSQL | `make db-up` with reviewed host configuration |
| Application/Caddy | `make deploy-apply` |
| Connected polling | `make deploy-timer` |
| Partitions | `make deploy-maintenance-timer` |
| Backups | `python3 scripts/deploy.py install-backup-timer` |
| Restore test | `make deploy-restore-timer` |

Install timers after manual host acceptance. Connected polling remains optional.
Restore orchestration runs on the operator host because it needs backup scripts,
bash and PostgreSQL tools. Set `SIERX_OPERATOR_BIN` to the absolute executable
path of the accepted native release's CLI; match its revision with the operator
checkout and drivers. Create a protected 0600 `~/.config/sierx/restore.env` with
the driver and dedicated scratch inputs. The timer never compiles source or
downloads tools. Reinstall it when changing the accepted binary/checkout path.

The existing restore CLI rotates configured drivers and recreates its scratch
database. Its name must start with `sierx_restore_` and differ from the source;
administrative or arbitrary database names are rejected before any SQL runs.
Use only a dedicated disposable restore database. Physical conformance,
cipher checks and restored-application access remain separate acceptance; timer
installation is not recovery evidence.

## Remaining work

PR gates verify source behavior; artifact gates verify shipped images; host tests
verify deployment/reboot/rollback/recovery; scheduled tests monitor drift; human
acceptance covers real use, accessibility and design. These are distinct claims.

The next branch packages offline runtime/operator dependencies, exact migrations,
archive/internal-registry input, internal/supplied TLS and trusted offline
verification. Its exit test installs on a fresh host with external egress blocked,
then proves operation, update, rollback and recovery. UI work follows the existing
browser contracts and must introduce no mandatory public asset dependencies.

## Local validation - 2026-09-23

The uplift working source passed the full prepared, network-disabled Linux
`make ci-local` gate, including Chromium/Firefox workflow and 10,000-item scale
checks, Markdown mutation proof and unit-generation proof. Final focused checks
covered the subsequently tightened restore-target guard, Python evidence/runner
tests, workflow lint and shell lint. This is local evidence, not a hosted run at
the final branch revision.

On native amd64 WSL Ubuntu (Podman 4.9.3/systemd 255), the canonical image built
from `9fbdbee6ae5ca938c920ecf6416104959cb7b661` passed the packaged-image checks.
Its local image digest was
`sha256:47bef955e17d837ccff1ed7701113d50cbd13f8de246ae0d64f64b90ae888187`.
A derived image with a deliberately missing entrypoint failed specifically at
application startup and removed the prior acceptance file. Promotion-validator
tests also reject missing/failed/stale architecture evidence and changed index
children. No candidate was published during these local tests.

Native arm64 execution, hosted registry staging/promotion and operator-host
deployment/recovery remain unverified for this branch. These results do not
establish Phase 2 completion or air-gap deployment support.
