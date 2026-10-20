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

KVM runs have a 1,900-second workload limit. A host without nested virtualization
uses native-architecture TCG with a bounded 10,800-second workload limit and
1,800-second command limits (5,400 seconds for the complete browser command).
A measured emulated run spent 21 minutes importing,
27 minutes setting up the database and eight minutes migrating/bootstraping,
then exceeded the former 600-second plan/apply command limit. The longer
software-emulation budget leaves time for browser, rollback and runtime checks;
their assertions and scenario durations are unchanged. KVM commands retain
their 600-second limit in every phase. The workflow is capped at 210 minutes,
including connected preparation and evidence collection. TCG uses QEMU's `max` CPU
model rather than limiting Arm execution to Cortex-A72; see the
[QEMU CPU model documentation](https://www.qemu.org/docs/master/system/arm/virt.html).
These functional checks make no native-speed/performance claim.
TCG guests use four virtual CPUs so the browser, database and ordinary syscall
observer can use the [four cores on GitHub's public ARM runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
[Multi-threaded TCG](https://www.qemu.org/docs/master/devel/multi-thread-tcg.html)
runs each virtual CPU on a host thread. KVM guests retain two virtual CPUs.
Reports record the guest's actual `virtual_cpus` count; promotion rejects a
count that differs from its acceleration profile. Memory remains 4 GiB and
HTTP read/write deadlines are unchanged.
Native host tests explicitly retain the default one-second lifecycle check.
TCG sets `SIERX_LIFECYCLE_CHECK_TIMEOUT=10s` after measured ordinary-ptrace
emulation rejected recovery GETs at the former one-second deadline even with
four CPUs. This is a bounded server configuration on the emulated fixture:
the same checkpoint/database comparison still runs before every handler, and
timeouts, cancellation and mismatches still reject access. The fixture verifies
the actual container setting, records `lifecycle_check_timeout_seconds`, and
rejects reports that differ from the native/emulated profile. Delivered native
image acceptance and both KVM profiles exercise the default one-second setting.

Runtime observation still requires 120–180 seconds of successful health/change
polling and at least three polls. Inventory time is measured separately, so a
slow metadata query cannot substitute for observation. The maintenance timer
must have triggered and its oneshot must have completed successfully. The
emulated enabled-unit inventory uses a bounded 180-second
[`SYSTEMD_BUS_TIMEOUT`](https://github.com/systemd/systemd/blob/v255/docs/ENVIRONMENT.md)
for that single read-only query after ARM probes failed there after about 28
seconds. Native queries retain the system default. Reports record this selected
deadline, the enabled-unit query time and the total inventory time; promotion
requires the mode-correct deadline and bounds inventory to 60 seconds on KVM or
360 on TCG. The full workload, observation interval and required inventories
are unchanged. This setting does not alter shipped services or production.

The GitHub ARM preparer runs on `ubuntu-26.04-arm` for its newer host QEMU;
the isolated accepted guest remains Ubuntu 24.04 with its own recorded kernel
and rootfs hashes. Preparation attempts to load KVM, and the launcher still
requires a successful VM-creation probe before selecting it. Public progress
contains fixed phase/operation names only; command output and journals remain
private. A timeout is a failed acceptance, never a passing report.

Software-emulated browser fixtures allow 180 seconds to launch Chromium,
120 seconds for its actions/navigation, and 60 seconds for its assertions.
Firefox allows 600 seconds for startup/initial page and actions/navigation,
with 180-second assertions. Worker guards remain capped at 60 seconds. These
functional waits accommodate measured slow emulated startup and rendering.
Firefox reuses its initial blank page; startup and login steps have separate
safe failure labels. The complete emulated browser command has a 90-minute cap
within the three-hour workload cap. Standard runs retain Playwright's normal
30-second action/launch and five-second assertion limits. Reports identify the
timing mode. Required actions, TLS verification and connection controls remain
mandatory. Only software-emulated positive navigations may repeat a same-origin
GET after the server's exact plain-text recovery-gate 503 response, with at most
five retries per engine and a ten-minute navigation recovery bound. The report
records the total `recovery_read_retries` (zero for native runs). Unrelated
503s, write requests and negative controls are not retried. The server's
recovery comparison is unchanged. Native control windows remain bounded at 20
seconds; TCG allows 120 seconds including emulated process startup, with
60-second control command limits. The observer selects this budget from the
root launcher's actual acceleration mode and records it in the report; input
control records cannot choose a larger allowance. Exact role/address/port and
unique-window matching, all 11 required controls, and rejection of other
attempts still apply. Invalid-delivery commands allow up to 30 minutes on TCG
and retain their 180-second native limit; a timeout never counts as rejection.
Failures publish only allowlisted browser stage/exception labels extracted from
private diagnostics; network-control failures publish fixed reason codes only.
Credentials, work content and exception messages stay private.
Failure diagnostics distinguish fixed HTTP method/recovery-body/problem-body
categories without publishing response contents. Item creation separately
requires its first POST response to be 201 before checking the resulting view.
For recovery rejections present in the private service journal, `recovery-late`
counts unmatched 503 requests lasting at least 1,000 milliseconds;
`recovery-early` counts shorter requests. These counts help identify deadline
pressure without publishing journals.
`recovery-timeouts` counts fixed `deadline-exceeded` verification warnings.

The main guest store uses native rootless overlay on its private ext4 disk.
This avoids the repeated full-layer copying of vfs, particularly under arm64
software virtualization. The guest verifies the actual selected driver. The
empty-store and acquisition controls additionally check their actual separate
graph/runtime paths and zero-image inventory; a configuration file alone is
not proof that Podman selected it.

The disposable OS supplies setuid UID/GID mapping helpers so their required
privileges survive OCI export and ext4 population. Its database explicitly uses
slirp4netns for local port mapping without a physical network device; the guest
checks the running container's selected backend. These are test-OS prerequisites,
separate from the operator's real host/SELinux acceptance.

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

The installer observer uses strace's kernel syscall selection (`--seccomp-bpf`)
to avoid stopping on unselected archive reads/writes. The service manager
retains ordinary ptrace observation, including the browser service's seccomp
denials: seccomp-denied calls are not visible through `RET_TRACE` filtering.
The traced socket/process/descriptor calls and required external controls are
unchanged. Neither observer detaches for import, and no phase skips observation.
See the [strace option and precedence rules](https://man7.org/linux/man-pages/man1/strace.1.html).

The Node/browser test service has an explicit seccomp policy denying io_uring
with ENOSYS, so all its network operations use observable socket calls. A real
syscall probe verifies the policy, and a separate Node fetch proves observation.
The shipped app, gateway and database keep their ordinary profiles. libuv's
`UV_USE_IO_URING` setting alone does not disable its epoll batching rings; see
the [pinned libuv implementation](https://github.com/libuv/libuv/blob/v1.52.1/src/unix/linux.c).
Browser context guards separately prove navigation, subresource, dedicated
worker and websocket interception; service workers are blocked explicitly.
Both Firefox test profiles explicitly disable application update checks using
[Mozilla's desktop testing preferences](https://firefox-source-docs.mozilla.org/python/marionette_driver.html).
This prevents delayed `aus5.mozilla.org` DNS traffic in slower runs. Such traffic
is not exempted by the observer; any remaining unauthorized DNS still fails.

The browser test service allows IPv4, Unix and netlink sockets. This is an
IPv4 loopback browser fixture, not IPv6 browser-host acceptance. Chromium's
[built-in IPv6 route check](https://github.com/chromium/chromium/blob/153.0.8010.12/net/dns/host_resolver_manager.cc)
otherwise probes a public address even for local pages. A real syscall control
verifies this address-family restriction; denied socket setup is counted
separately. The request guard also proves interception of an off-origin IPv6
URL. The installer remains unrestricted and must produce the separately
observed failed IPv6 connection. App, database and gateway profiles are unchanged.
The database's intentional external control must be observed at both the
database and its canonical slirp4netns proxy, in the same bounded interval.

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

For a runtime/timer failure, manually dispatch `offline-delivery` with
`runtime_probe=true`, or use `make probe-offline-runtime` after preparation.
This performs the same real installation, restart, runtime observation and
timer checks while omitting browsers and release-switching scenarios. It
requires `--development --runtime-probe`, writes a separately named
`runtime-probe-<profile>-<arch>.json`, and has no **Offline delivery** aggregate.
Its distinct schema/coverage is rejected by promotion even if renamed.
The skipped diagnostic aggregate also uses a separate check name because
[GitHub treats skipped checks as successful](https://docs.github.com/en/pull-requests/reference/status-checks).
PR checks and reusable release calls always run the complete closeout suite.
Fixed runtime substage names and numeric command exit codes aid diagnosis;
arguments, output, credentials and journals remain private.

Actual testbed reboot, SELinux/operator-profile acceptance, off-machine physical
recovery, independent journal/checkpoint custody, chosen-hardware performance,
phone/screen-reader review and owner real-use/sign-off remain separate records.
Automated guest evidence must not fill them in.
