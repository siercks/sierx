# CI portability

The build interface is `make`. Hosted CI runs `make gate-0`; the local runner
runs the same command against an isolated PostgreSQL cluster.

## Local offline CI

On a Linux host with rootless Podman, Git, Python 3 and tar:

```bash
make ci-local-prepare  # online: pull images, install tools, cache Go modules
make ci-local         # offline: full gate in a disposable container
```

Preparation uses the Go version in go.mod, the Node major in .nvmrc and the
PostgreSQL digest in the Quadlet unit. Go and Node tags are resolved to local
immutable image IDs before building. The prepared image retains the exact
installed versions until preparation runs again; this is an operator-built
CI environment, not a reproducible release artifact. OS package installation
happens only during preparation.

The run uses `--network=none` and `--pull=never`. It takes a snapshot of current
committable files, including uncommitted changes, and streams it into the
container. Ignored files, the host .git directory and host .env are not copied;
tracked environment files other than .env.example and symbolic links are
rejected. There are no host mounts, published ports or inherited database
credentials. A temporary UTF8/C cluster and its backups live inside the
container. The host checkout and existing databases are untouched.

A synthetic Git commit represents the tested snapshot, enabling the same
schema/generated-code/vendor checks as hosted CI. Its commit ID in the test
SBOM is deliberately not a release provenance claim. Release SBOMs must be
created from the actual release checkout.

If module, toolchain, image pin or CI setup inputs change, the run fails and
asks for `make ci-local-prepare` again. A prepared image is native to the host
architecture. The runner uses Podman installed in the image only for the
bootstrap version check; it does not start nested containers or expose a host
container socket. The runtime environment is for Phase 0; frontend tooling
must be added and verified when Phase 2 starts.

**Validation status:** the prepared image built and the complete offline gate
passed on the Spark on 2026-09-18 after the vendor exclusion fix. The acceptance
log is `docs/acceptance/phase0-offline-spark-2026-09-18.log`. Task 0.12 is accepted.

## Hosted providers

Reproduce the pinned toolchain, install Python 3 and PostgreSQL 18 clients,
provide a disposable UTF8/C database, then invoke `make gate-0`. The existing
GitHub job is the reference environment. A GitLab or Forgejo job can instead
use a Linux runner with Podman and invoke the two commands above. Provider
configuration supplies checkout, runner selection and artifact upload; no
additional test logic belongs in provider YAML.

The checked-in GitHub database service already has a digest pin. The ordinary
hosted gate currently runs on amd64; the Spark run supplies separate native
arm64 evidence. Cross-compilation is not equivalent to native testing.

The source checks, SQL tests, Go tests, SBOM validation, backup conformance,
benchmark smoke run and deliberate-violation proofs live in the gate. SBOM
validation covers the format emitted by sierx and compares every stable field
against freshly generated output; it is not a general CycloneDX validator.

## Release boundary

The release workflow still names release-binaries, release-image and
release-manifest, which have not been implemented. Do not publish a release
until their owning tasks land and the workflow is tested. This closeout does
not create a server or release container ahead of Phase 1/2.

Podman option reference: https://docs.podman.io/en/latest/markdown/podman-run.1.html
