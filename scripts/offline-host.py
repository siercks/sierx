"""Boot a no-NIC disposable VM; run the real installer as an unprivileged user.

Connected preparation is offline-host-prepare.sh. No host home, credential,
container store or user bus enters this guest. Requires native Linux root,
QEMU and ext4 image tools. Never uses the operator's systemd managers.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

import offline
import offline_host_evidence as evidence
import network_observer
import offline_archive

ROOT = Path(__file__).resolve().parent.parent
SUITE_FILES = ('offline-host.py', 'offline-host-guest.py', 'offline_host_evidence.py', 'offline-browser.mjs',
               'network_observer.py', 'offline-network-controls.py', 'offline-host-scenarios.py',
               'offline_host_inputs.py', 'offline-local-registry.py', 'offline.py','offline_archive.py')


def suite_digest(scripts=None, packages=None):
    digest = hashlib.sha256()
    scripts = scripts or ROOT / 'scripts'
    packages = packages or ROOT / 'web'
    for name in SUITE_FILES:
        digest.update(name.encode() + b'\0' + (scripts / name).read_bytes())
    for name in ('package.json','package-lock.json'):
        digest.update(('web/'+name).encode() + b'\0' + (packages / name).read_bytes())
    return digest.hexdigest()


def run(*args, **kwargs):
    return subprocess.check_output(list(map(str, args)), stderr=subprocess.PIPE, **kwargs)


def verify_rootfs(path, expected):
    path = Path(path)
    if not re.fullmatch(r'[a-f0-9]{64}', expected) or offline.digest(path) != expected:
        raise ValueError('Prepared test OS differs from the independently supplied checksum')
    # The checksum identifies the connected, trusted OS preparation output.
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        symlinks = {Path(entry.name) for entry in members if entry.issym()}
        for entry in members:
            parts = Path(entry.name).parts
            if (entry.name.startswith('/') or '..' in parts or entry.isdev() or entry.isfifo()
                    or not parts and not entry.isdir()):
                raise ValueError('Unexpected path or special file in prepared test OS')
            if any(parent in symlinks for parent in Path(entry.name).parents):
                raise ValueError('Prepared OS archive writes through a symbolic-link parent')
            if entry.islnk() and (entry.linkname.startswith('/') or '..' in Path(entry.linkname).parts):
                raise ValueError('Unsafe hard-link target in prepared test OS')
            if entry.islnk() and any(path in symlinks for path in (Path(entry.linkname),*Path(entry.linkname).parents)):
                raise ValueError('Prepared OS hard link resolves through a symbolic link')


def setup(root, args):
    for name in ('home', 'etc', 'var', 'opt', 'etc/passwd', 'etc/group', 'etc/shadow',
                 'etc/subuid', 'etc/subgid', 'etc/hosts', 'etc/machine-id', 'usr/sbin','boot',
                 'etc/systemd/system','var/log/sierx-network','opt/acceptance/tests'):
        if not (root / name).resolve().is_relative_to(root.resolve()):
            raise ValueError('Prepared OS configuration path escapes the guest')
    home = root / 'home/acceptance'
    home.mkdir(parents=True)
    os.chown(home, 1001, 1001)
    etc = root / 'etc'
    for name, value in (
        ('passwd', 'acceptance:x:1001:1001:Offline acceptance:/home/acceptance:/bin/bash\n'),
        ('group', 'acceptance:x:1001:\n'),
        ('shadow', 'acceptance:!:20000:0:99999:7:::\n'),
        ('subuid', 'acceptance:100000:65536\n'),
        ('subgid', 'acceptance:100000:65536\n'),
    ):
        path = etc / name
        if path.exists() and ('acceptance:' in path.read_text() or (name in {'passwd', 'group'} and ':1001:' in path.read_text())):
            raise ValueError('Prepared test OS already contains the reserved fixture account')
        with path.open('a') as stream:
            stream.write(value)
    (etc / 'shadow').chmod(0o600)
    # Literal local-only names; never inherit host DNS or resolver configuration.
    resolver = etc / 'resolv.conf'
    resolver.unlink(missing_ok=True)
    resolver.write_text('')
    resolver.chmod(0o644)
    hosts = etc / 'hosts'
    hosts.write_text('127.0.0.1 localhost\n::1 localhost\n')
    hosts.chmod(0o644)
    linger = root / 'var/lib/systemd/linger'
    linger.mkdir(parents=True, exist_ok=True)
    (linger / 'acceptance').touch()
    containers = home / '.config/containers'
    containers.mkdir(parents=True)
    (containers / 'storage.conf').write_text('[storage]\ndriver="overlay"\n')
    (containers / 'containers.conf').write_text('[engine]\ncgroup_manager="systemd"\nevents_logger="file"\n'
        '[containers]\nnetns="slirp4netns"\n')
    for path in (home / '.config', containers, *containers.iterdir()):
        os.chown(path, 1001, 1001)
    for name in ('machine-id',):
        (etc / name).write_text('')
    trace = root / 'var/log/sierx-network'
    trace.mkdir(mode=0o700)
    # Root observers can follow subordinate-UID container processes. -u drops
    # each tracee to the actual acceptance identity, retaining root only in the
    # observer. Nothing contacts the host's ordinary user bus or image store.
    trace_calls = 'socket,socketpair,connect,accept,accept4,getpeername,sendto,sendmsg,sendmmsg,close,dup,dup2,dup3,fcntl,execve,execveat,clone,clone3,fork,vfork,io_uring_setup,io_uring_enter,io_uring_register'
    trace_calls=','.join('?'+name for name in trace_calls.split(','))
    for name, command in (('manager','/usr/lib/systemd/systemd --user'),
                          ('installer','/usr/bin/python3 /opt/acceptance/tests/offline-host-guest.py')):
        wrapper = root / ('usr/sbin/sierx-trace-'+name)
        wrapper.write_text('#!/bin/sh\nexec 3>&2\nexec /usr/bin/strace -qq -f --decode-pids=comm,pidns -ttt -yy -s 256 -e trace='+trace_calls+
            ' -o /var/log/sierx-network/'+name+'.trace -u acceptance /usr/sbin/sierx-observed-'+name+
            ' 2>/var/log/sierx-network/'+name+'.stderr\n')
        tracee = root / ('usr/sbin/sierx-observed-'+name)
        tracee.write_text('#!/bin/sh\nexec '+command+' 2>&3 3>&-\n')
        wrapper.chmod(0o755)
        tracee.chmod(0o755)
    units = etc / 'systemd/system'
    units.mkdir(parents=True, exist_ok=True)
    manager_override = units / 'user@1001.service.d'
    manager_override.mkdir()
    (manager_override/'observe.conf').write_text('''[Service]
ExecStart=
ExecStart=+/usr/sbin/sierx-trace-manager
NotifyAccess=all
Environment=XDG_RUNTIME_DIR=/run/user/1001
Environment=HOME=/home/acceptance
Environment=USER=acceptance
Environment=LOGNAME=acceptance
''')
    for name in ('systemd-networkd.service', 'systemd-resolved.service', 'systemd-timesyncd.service',
                 'systemd-firstboot.service', 'nftables.service', 'keyboard-setup.service'):
        path = units / name
        path.unlink(missing_ok=True)
        path.symlink_to('/dev/null')
    (units / 'sierx-acceptance.service').write_text('''[Unit]
Requires=user@1001.service
After=user@1001.service
SuccessAction=poweroff-force
FailureAction=poweroff-force
[Service]
Type=oneshot
User=acceptance
Group=acceptance
Environment=HOME=/home/acceptance
Environment=XDG_RUNTIME_DIR=/run/user/1001
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus
Environment=PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
Environment=PATH=/usr/lib/postgresql/18/bin:/usr/pgsql-18/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStartPre=+/usr/bin/python3 /opt/acceptance/tests/offline-host-guest.py --manager-proof
ExecStart=+/usr/sbin/sierx-trace-installer
TimeoutStartSec=4400
StandardOutput=journal+console
StandardError=journal
''')
    (units / 'sierx-acceptance.target').write_text('''[Unit]
Requires=basic.target
Wants=sierx-acceptance.service dbus.service
After=basic.target
''')
    options = {'bundle_sha256': args.expected_sha256, 'previous_sha256': args.previous_sha256,
               'soak_seconds': args.soak_seconds, 'suite_sha256': args.suite_sha256,
               'closeout':not args.development,'virtual_cpu':args.virtual_cpu}
    (home / 'options.json').write_text(json.dumps(options))
    os.chown(home / 'options.json', 1001, 1001)


def acceleration(requested):
    available = False
    try:
        with open('/dev/kvm', 'rb', buffering=0) as device:
            vm = fcntl.ioctl(device, 0xAE01, 0)  # KVM_CREATE_VM: release this probe immediately.
            os.close(vm)
            available = True
    except OSError:
        pass
    if requested == 'kvm' and not available:
        raise ValueError('KVM was required but is unavailable')
    return 'kvm' if available and requested != 'tcg' else 'tcg'


def qemu_command(arch, mode, disk, kernel, initrd, serial):
    emulator = 'qemu-system-x86_64' if arch == 'amd64' else 'qemu-system-aarch64'
    cpu = 'host' if mode == 'kvm' else ('max' if arch == 'amd64' else 'cortex-a72')
    console = 'ttyS0' if arch == 'amd64' else 'ttyAMA0'
    board = 'q35' if arch == 'amd64' else 'virt'
    return [emulator, '-machine', board, '-accel', mode, '-cpu', cpu, '-m', '4096', '-smp', '2',
            '-nodefaults', '-nic', 'none', '-display', 'none', '-monitor', 'none',
            '-serial', 'file:' + str(serial), '-no-reboot',
            '-drive', 'file=' + str(disk) + ',format=raw,if=none,id=acceptance',
            '-device', 'virtio-blk-pci,drive=acceptance', '-kernel', str(kernel), '-initrd', str(initrd),
            '-append', 'root=/dev/vda rw console='+console+' systemd.unit=sierx-acceptance.target']


def disk_file(disk, name):
    # Only fixed guest paths are accepted, never operator-provided debugfs commands.
    paths = {'result.json':'/home/acceptance/result.json', 'diagnostics.log':'/home/acceptance/diagnostics.log',
             'manager.trace':'/var/log/sierx-network/manager.trace', 'manager.stderr':'/var/log/sierx-network/manager.stderr',
             'installer.trace':'/var/log/sierx-network/installer.trace', 'installer.stderr':'/var/log/sierx-network/installer.stderr',
             'network-controls.json':'/home/acceptance/network-controls.json'}
    if name not in paths:
        raise ValueError('Unsupported guest evidence path')
    return run('debugfs', '-R', 'cat ' + paths[name], disk)


def recover_disk(disk):
    # The owned guest disk is never mounted on the host. Replay only its journal
    # after QEMU stops, so debugfs sees metadata durably synced by the fixture.
    result=subprocess.run(['e2fsck','-p','-E','journal_only',str(disk)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.returncode not in {0,1}:
        raise ValueError('Disposable guest filesystem recovery failed; no passing evidence')


def main(args):
    args.suite_sha256 = suite_digest()
    report = Path(args.report).absolute()
    report.unlink(missing_ok=True)
    if os.geteuid() != 0:
        raise ValueError('Run on a disposable native Linux host with root namespace privileges')
    arch = offline.native_arch()
    for tool in ('qemu-system-x86_64' if arch == 'amd64' else 'qemu-system-aarch64',
                 'mkfs.ext4', 'debugfs', 'e2fsck', 'tar'):
        if not shutil.which(tool):
            raise ValueError('Missing host test prerequisite: ' + tool)
    bundle = Path(args.bundle).resolve()
    data = offline.verify(bundle, args.expected_sha256)
    if args.previous_bundle:
        old = offline.verify(Path(args.previous_bundle).resolve(), args.previous_sha256)
        if not args.previous_evidence:
            raise ValueError('The retained release requires independently supplied approved acceptance evidence')
        offline.verify_evidence(old,args.previous_sha256,json.loads(Path(args.previous_evidence).read_text()))
        if old['release']['revision'] == data['release']['revision']:
            raise ValueError('Two-release acceptance requires two distinct approved revisions')
    elif not args.development:
        raise ValueError('Closeout acceptance requires a distinct retained approved bundle and evidence')
    verify_rootfs(args.rootfs, args.rootfs_sha256)
    mode = acceleration(args.acceleration)
    args.virtual_cpu=mode
    report.parent.mkdir(parents=True, exist_ok=True)
    private = report.with_suffix('.private.log')
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='sierx-offline-host-') as temporary:
        root = Path(temporary) / 'root'
        root.mkdir()
        run('tar', '-xf', args.rootfs, '-C', root, '--no-same-owner')
        # Rootless OCI export can preserve a private storage root's 0700 mode.
        # The outer temporary directory stays private; the guest's / must be
        # traversable by its actual non-root system services and test account.
        root.chmod(0o755)
        setup(root, args)
        tests = root / 'opt/acceptance/tests'
        tests.mkdir(parents=True, exist_ok=True)
        tests.chmod(0o755)
        for name in SUITE_FILES:
            source = ROOT / 'scripts' / name
            if source.exists():
                shutil.copyfile(source, tests / name)
                (tests / name).chmod(0o644)
        for name in ('package.json','package-lock.json'):
            shutil.copyfile(ROOT/'web'/name,tests/name)
            (tests/name).chmod(0o644)
        if suite_digest(tests,tests) != args.suite_sha256:
            raise ValueError('Acceptance inputs changed while constructing the immutable guest snapshot')
        staged=root/'opt/.delivery-input'
        delivered=offline_archive.unpack(args.archive,staged,args.archive_sha256,args.expected_sha256,arch)
        destination=root/'opt/sierx-bundle'
        if destination.exists():raise ValueError('Prepared test OS already contains the candidate bundle')
        delivered.rename(destination)
        staged.rmdir()
        if args.previous_bundle:
            shutil.copytree(Path(args.previous_bundle).resolve(), root / 'opt/previous-bundle', symlinks=True)
        kernels = sorted((root / 'boot').glob('vmlinuz-*'))
        if len(kernels) != 1:
            raise ValueError('Prepared test OS must contain exactly one explicit boot kernel')
        kernel = kernels[0]
        version = kernel.name.removeprefix('vmlinuz-')
        initrds = [path for path in (root / 'boot' / ('initrd.img-' + version),
                                    root / 'boot' / ('initramfs-' + version + '.img')) if path.is_file()]
        if len(initrds) != 1:
            raise ValueError('Prepared test OS lacks the matching initramfs')
        disk = Path(temporary) / 'guest.ext4'
        with disk.open('wb') as stream:
            stream.truncate(24 * 1024**3)
        run('mkfs.ext4', '-q', '-F', '-i', '65536', '-d', root, disk)
        # Retain only the boot inputs after creating the guest disk. This avoids
        # keeping two populated OS trees during a native hosted-runner test.
        kernel_digest = offline.digest(kernel)
        boot_kernel,boot_initrd = Path(temporary)/'kernel',Path(temporary)/'initrd'
        shutil.copyfile(kernel,boot_kernel)
        shutil.copyfile(initrds[0],boot_initrd)
        if root.resolve().parent != Path(temporary).resolve():
            raise ValueError('Disposable OS cleanup path escaped its owned temporary directory')
        shutil.rmtree(root)
        serial = Path(temporary) / 'serial.log'
        command = qemu_command(arch, mode, disk, boot_kernel, boot_initrd, serial)
        process = None
        recovered = False
        try:
            with private.open('wb') as log:
                process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
                print('offline-host: boot ' + arch + '/' + mode + ' with native overlay storage',flush=True)
                deadline = time.monotonic() + (4500 if mode=='tcg' else 1900)
                startup_deadline = time.monotonic() + (180 if mode == 'kvm' else 600)
                last_phase = None
                finished = None
                while process.poll() is None and time.monotonic() < deadline:
                    if serial.exists():
                        console_text=serial.read_text(errors='replace')
                        phases = re.findall(r'SIERX_PHASE: ([a-z-]{1,80})', console_text)
                        if phases and phases[-1] != last_phase:
                            last_phase = phases[-1]
                            print('offline-host: ' + last_phase, flush=True)
                        matches=re.findall(r'SIERX_FINISHED: ([a-f0-9]{64}) (passed|failed)',console_text)
                        if matches:
                            finished=matches[-1]
                            if finished[0]!=args.suite_sha256:
                                raise ValueError('Guest completion belongs to a different acceptance snapshot')
                            # Root strace follows persistent Podman helpers.
                            # Stop the entire owned VM after the tracee synced
                            # its result, rather than waiting for those daemons.
                            process.terminate()
                            process.wait(timeout=30)
                            break
                    if last_phase is None and time.monotonic() > startup_deadline:
                        raise ValueError('Guest user manager or installer failed to start; inspect private diagnostics')
                    time.sleep(1)
                if process.poll() is None:
                    raise ValueError('Rootless acceptance exceeded its declared timeout')
            recover_disk(disk)
            recovered=True
            if finished is None:
                matches=re.findall(r'SIERX_FINISHED: ([a-f0-9]{64}) (passed|failed)',serial.read_text(errors='replace'))
                finished=matches[-1] if matches else None
            if finished is None or finished[0]!=args.suite_sha256:
                raise ValueError('Guest stopped before a complete synced acceptance result')
            raw_result = disk_file(disk, 'result.json')
            if not raw_result.strip():
                raise ValueError('Guest did not produce a complete acceptance result; inspect private diagnostics')
            result = json.loads(raw_result)
            if result.get('result')!=finished[1]:
                raise ValueError('Guest result does not match its completion marker')
            if result.get('result') == 'failed':
                failed_phase = str(result.get('phase', 'unknown'))
                if not re.fullmatch(r'[a-z-]{1,80}', failed_phase):
                    failed_phase = 'unknown'
                failure_type=result.get('failure_type','unknown')
                if failure_type not in {'TimeoutExpired','ValueError','RuntimeError','PermissionError','FileNotFoundError'}:
                    failure_type='unknown'
                raise ValueError('Real rootless acceptance failed at ' + failed_phase + ' ('+failure_type+'); inspect private diagnostics')
            evidence.validate(result, data, args.expected_sha256, args.suite_sha256)
            trace = (disk_file(disk,'manager.trace') + disk_file(disk,'installer.trace')).decode()
            observation = network_observer.summarize(trace.splitlines(),
                json.loads(disk_file(disk,'network-controls.json')), result.pop('internal_addresses'),
                (disk_file(disk,'manager.stderr')+disk_file(disk,'installer.stderr')).decode())
            result['network'] = observation
            result['rootfs_sha256'] = args.rootfs_sha256
            result['archive_sha256'] = args.archive_sha256
            result['virtual_cpu'] = mode
            result['kernel_sha256'] = kernel_digest
            evidence.validate_network(result['network'])
            if not args.development:
                evidence.validate_closeout(result,data,args.expected_sha256,args.suite_sha256)
            report.write_text(json.dumps(result, indent=2) + '\n')
            report.chmod(0o644)  # Sanitized evidence is readable by the artifact uploader.
            print('offline-host: real isolated rootless installer passed on ' + result['profile'], flush=True)
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=30)
            if not recovered:
                recover_disk(disk)
            # These are guest files from a synthetic VM, never the host journal.
            with private.open('ab') as stream:
                if serial.exists():
                    stream.write(serial.read_bytes()[-65536:])
                stream.write(disk_file(disk, 'diagnostics.log')[-65536:])
            for name in ('manager.trace','installer.trace','manager.stderr','installer.stderr','result.json','network-controls.json'):
                private.with_suffix('.'+name).write_bytes(disk_file(disk,name))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--archive',required=True)
    parser.add_argument('--archive-sha256',required=True)
    parser.add_argument('--rootfs', required=True)
    parser.add_argument('--rootfs-sha256', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--previous-bundle')
    parser.add_argument('--previous-sha256')
    parser.add_argument('--previous-evidence')
    parser.add_argument('--development',action='store_true',help='Limited fixture development; never valid for promotion')
    parser.add_argument('--soak-seconds', type=int, default=120)
    parser.add_argument('--acceleration', choices=('auto', 'kvm', 'tcg'), default='auto')
    try:
        main(parser.parse_args())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit('offline-host: ' + (str(error) if isinstance(error, ValueError) else 'operation failed; no passing report'))
