"""Run the historical import on a disposable runner's native kernel."""
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile

import offline
import offline_host_diagnostics as diagnostics

SCRIPT = str(Path(__file__).resolve())
PYTHON = ('/usr/bin/python3', '-B', SCRIPT)
MARKER = diagnostics.INSTALLER_MARKER_FD
PATH = '/usr/sbin:/usr/bin:/sbin:/bin'


def start_trace(instance, directory, user, helper):
    diagnostics.start_installer_exit_trace(instance)
    with (instance / 'trace_marker').open('wb', buffering=0) as marker:
        os.dup2(marker.fileno(), MARKER)
        diagnostics.mark_installer('sierx-tracer-start')
        diagnostics.enable_tracer_error_events(instance)
        diagnostics.mark_installer('sierx-tracer-errors-ready')
        with (directory / 'installer-guest.stderr').open('wb') as stderr:
            os.dup2(stderr.fileno(), 3)
            os.execv('/usr/bin/strace', ('strace', '--kill-on-exit', '-q', '-f',
                '--decode-pids=comm,pidns', '-ttt', '-yy', '-s', '256', '-e',
                'trace=?socket,?socketpair,?connect,?accept,?accept4,?getpeername,'
                '?sendto,?sendmsg,?sendmmsg,?recvmsg,?close,?close_range,?unshare,'
                '?dup,?dup2,?dup3,?fcntl,?execve,?execveat,?clone,?clone3,?fork,?vfork,'
                '?io_uring_setup,?io_uring_enter,?io_uring_register',
                '-o', str(directory / 'installer.trace'), '-u', user,
                *PYTHON, '--installer', helper))


def installer(helper):
    os.dup2(3, 2)
    os.close(3)
    os.set_inheritable(MARKER, False)
    for marker in ('sierx-installer-start', 'sierx-phase import', 'sierx-operation start import'):
        diagnostics.mark_installer(marker)
    return subprocess.run((*PYTHON, '--helper', helper), pass_fds=(MARKER,)).returncode


def probe(bundle, expected, uid):
    if os.geteuid() != 0 or uid < 1000:
        raise ValueError('Native import requires root in a fresh loopback-only namespace and an unprivileged runner')
    # /sys can be mounted from the parent netns. Verify the namespace directly.
    links = subprocess.check_output(['ip', '-j', 'link', 'show'], timeout=15)
    if {entry['ifname'] for entry in json.loads(links)} != {'lo'}:
        raise ValueError('Native import requires a loopback-only namespace')
    data = offline.verify(bundle, expected)
    user = pwd.getpwuid(uid)
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='sierx-native-import-') as temporary:
        directory = Path(temporary)
        directory.chmod(0o711)
        home = directory / 'home'
        graph, runroot, runtime = (home / name for name in ('graph', 'runroot', 'runtime'))
        config = home / '.config'
        containers = config / 'containers'
        containers.mkdir(parents=True)
        runtime.mkdir()
        (containers / 'storage.conf').write_text(
            '[storage]\ndriver="overlay"\ngraphroot='+json.dumps(str(graph))+
            '\nrootless_storage_path='+json.dumps(str(graph))+'\nrunroot='+json.dumps(str(runroot))+'\n')
        for entry in (home, config, containers, containers/'storage.conf', runtime):
            os.chown(entry, user.pw_uid, user.pw_gid)
        env = {'PATH': PATH, 'HOME': str(home), 'USER': user.pw_name, 'LOGNAME': user.pw_name,
               'XDG_RUNTIME_DIR': str(runtime), 'XDG_CONFIG_HOME': str(config),
               'SIERX_OFFLINE_BUNDLE': str(bundle), 'SIERX_OFFLINE_SHA256': expected}
        podman = ('/usr/sbin/runuser', '-p', '-u', user.pw_name, '--', '/usr/bin/podman')
        with (directory / 'podman.stderr').open('wb') as private:
            info = json.loads(subprocess.check_output((*podman, 'info', '--format', 'json'),
                env=env, stderr=private, timeout=30))
            store = info['store']
            if (Path(store['graphRoot']) != graph or Path(store['runRoot']) != runroot
                    or store['graphDriverName'] != 'overlay' or store['imageStore']['number'] != 0
                    or info['host']['security']['rootless'] is not True):
                raise ValueError('Native import did not select its separate empty rootless overlay store')
            instance = Path('/sys/kernel/tracing/instances') / Path(temporary).name
            try:
                with (directory / 'installer.stderr').open('wb') as stderr:
                    args = (*PYTHON, '--trace', str(instance), temporary, user.pw_name,
                            str(bundle / 'scripts/offline.py'))
                    result = subprocess.run(args, env=env, cwd=bundle, stdout=private,
                                            stderr=stderr, timeout=180)
                capture = diagnostics.read_installer_exit_trace(instance)
            finally:
                if instance.exists():
                    instance.rmdir()
                subprocess.run((*podman, 'system', 'migrate'), env=env, stdout=private,
                               stderr=private, timeout=30, check=True)
        status = diagnostics.sanitize_failure({'result':'failed', 'phase':'import',
            'failure_source':'service-exit', **capture,
            'installer_tracer_stderr_bytes':(directory/'installer.stderr').stat().st_size,
            'observer_errors':{'installer':diagnostics.observer_errors(
                diagnostics.private_tail(directory/'installer.stderr'))}})
        tracee_stderr = directory / 'installer-guest.stderr'
        if tracee_stderr.is_file():
            status['tracee_stderr_bytes'] = tracee_stderr.stat().st_size
        observed_zero = {'task_exited': True, 'requested_exit_code': 0}
        passed = (result.returncode == 0 and status.get('import_stage') == 'import-complete'
                  and status.get('kernel_exit') == dict.fromkeys(
                      ('tracer', 'installer', 'import-helper'), observed_zero))
        observation = {key:value for key,value in status.items() if key not in
                       {'result','phase','failure_type','failure_source'}}
    kernel = os.uname().release
    if not re.fullmatch(r'[a-zA-Z0-9.+_-]{1,128}', kernel):
        raise ValueError('Invalid native kernel release')
    return {'suite':'offline-native-import-probe-v1', 'release_acceptance':False,
            'arch':data['arch'], 'release':data['release'], 'bundle_sha256':expected,
            'kernel_release':kernel, 'strace_sha256':offline.digest(Path('/usr/bin/strace')),
            'podman_sha256':offline.digest(Path('/usr/bin/podman')),
            'fresh_rootless_overlay':True, 'loopback_only':True, 'installer_trace_mode':'ordinary-ptrace',
            'result':'passed' if passed else 'failed', 'tracer_returncode':result.returncode,
            'observation':observation}


if __name__ == '__main__':
    mode, *args = sys.argv[1:]
    if mode == '--trace' and os.geteuid() == 0:
        start_trace(Path(args[0]), Path(args[1]), *args[2:])
    elif mode == '--installer' and os.geteuid() != 0:
        sys.exit(installer(*args))
    elif mode == '--helper' and os.geteuid() != 0:
        os.set_inheritable(MARKER, False)
        diagnostics.observe_import(*args)
    elif mode == '--probe':
        bundle, digest, uid, output = args
        try:
            report = probe(Path(bundle).resolve(), digest, int(uid))
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            sys.exit('offline-native-import: native setup or evidence collection failed')
        output = Path(output)
        with output.open('x') as stream:
            stream.write(json.dumps(report, indent=2)+'\n')
        output.chmod(0o644)
        sys.exit(report['result'] != 'passed')
    else:
        raise SystemExit('Unsupported native import operation')
