# Native offline host acceptance

This is release engineering tooling, separate from the application and its
operator prerequisites. The supported test matrix is Ubuntu 24.04 on native
amd64 and arm64, plus Rocky 10 on native amd64. A passing source browser suite
or the older rootful import/API fixture does not substitute for these reports.

The isolated workload boots its own kernel and real systemd managers in a
disposable QEMU VM. It has no network device, forwarded port, host home, host
container store, ordinary host user bus, or CI credential. All actual installer
operations run as the synthetic UID 1001. Guest root only prepares fault copies,
checks namespace/identity evidence and observes processes. Connected OS/browser
preparation happens before isolation, in the preparer's Podman store.

## Reproducer

Use a clean committed Linux checkout matching the native architecture. Install
Podman, QEMU for that architecture, e2fsprogs, Python, GitHub CLI, and the pinned
Go/Node build toolchains. Root namespace privileges are needed for the temporary
guest disk and VM launcher; the Make target invokes sudo for that launcher.

```sh
make release-binaries release-image
make sbom SBOM_OUT=dist/sbom-amd64.cdx.json
make offline-candidate-prepare
make offline-previous-prepare
make offline-host-prepare PROFILE=ubuntu24
make gate-offline-host PROFILE=ubuntu24
```

Use `arm64` in the SBOM filename on that native host. `PROFILE=rocky10` is the
additional amd64 profile. Local candidates are saved/imported without registry
publication. Release CI instead downloads and verifies the exact staged native
offline artifact, using `make offline-current-unpack`.

`deploy/ci/previous-offline-release.json` explicitly identifies the retained
approved predecessor, its Actions run, native child image references, archive
checksums and bundle lock checksums. Acquisition verifies its matching approval
evidence. There is no fallback to an arbitrary latest run. Keep the approved
artifacts available; an expired/missing artifact blocks the gate. Changing this
fixture requires a reviewed approval update.

## What the fixture exercises

- Actual verified import, Quadlet database startup, migrations/bootstrap,
  supplied HTTPS trust and rootless plan/apply with real user services.
- Delivered browser login, project/item creation and editing, transitions,
  comments, links, query/reload, cold bootstrap and canonical permanent URLs.
- No-op repeated apply and database/app/gateway restart persistence.
- Missing/corrupted media, wrong architecture/digest, missing certificate and
  an empty alternative image store, without fallback acquisition.
- A distinct approved predecessor and current candidate, compatible application
  rollback on the current schema, and unchanged tested data. No database-down
  migration is performed. Reports include the schema versions actually tested.
- A deliberately wrong-port candidate that starts and serves health directly,
  fails the gateway health check, and restores the prior accepted configuration
  and application. This fault copy never counts as the approved predecessor.
- A bounded 120-second change-feed observation, actual accelerated local
  maintenance timer, enabled-unit inventory and rejection of implicit offline
  acquisition schedules. This is not a longevity or reboot claim.
- Explicit acquisition from a synthetic, trusted HTTPS registry on loopback,
  in an empty separate store. The isolated fixture never contacts live CI/CD.

Root observers follow the real user manager and installer from startup,
including subordinate-UID containers and renamed browser threads. The decoder
tracks accepted/inherited/transferred sockets and PID namespaces. Failed TCP,
UDP/DNS and IPv6 attempts count. Unknown socket destinations, escaped children,
tracer errors and successful undecodable asynchronous I/O fail closed. DNS is
unnecessary in this literal-host fixture; even a failed loopback DNS lookup is
rejected outside its explicit control.

The Node/browser test service has an explicit seccomp policy denying io_uring
with ENOSYS, so all its network operations use observable socket calls. A real
syscall probe verifies the policy, and a separate Node fetch proves observation.
The shipped app, gateway and database keep their ordinary profiles. libuv's
`UV_USE_IO_URING` setting alone does not disable its epoll batching rings; see
the [pinned libuv implementation](https://github.com/libuv/libuv/blob/v1.52.1/src/unix/linux.c).
Browser context guards separately prove navigation, subresource, dedicated
worker and websocket interception; service workers are blocked explicitly.

## Evidence and limits

Versioned `host-input-<profile>-<arch>.json` receipts bind the candidate, exact
delivery archive, bundle, prepared OS and acceptance-suite inputs before execution.
The guest receives a fresh extraction of that archive. Promotion requires the
same archive bytes, including its directory/executable metadata. Sanitized
`host-acceptance-<profile>-<arch>.json` reports record browser/driver versions,
isolation, actual controls, kernel/systemd/Podman/SELinux versions, runtime
inventory and all required scenarios.
The stable **Offline delivery** CI check validates all applicable reports.
Documentation-only PRs can skip host work; missing, cancelled or failed relevant
coverage cannot pass the aggregate. Promotion additionally requires both native
staged images, every required host profile and every archived file to match the
tested inventory.

Private traces and diagnostics contain synthetic credentials/content and are
never uploaded. Only the explicitly named sanitized reports/receipts are public.
The launcher waits for a synced completion marker, stops its owned VM and
replays only that disposable disk's journal before reading evidence.

`--development` permits work on the fixture against an older approved bundle.
It records limited development coverage and cannot satisfy promotion. Keep
actual exact-candidate/native-profile results distinct from such probes.

Actual testbed reboot, SELinux/operator-profile acceptance, off-machine physical
recovery, independent journal/checkpoint custody, chosen-hardware performance,
phone/screen-reader review and owner real-use/sign-off remain separate records.
Automated guest evidence must not fill them in.
