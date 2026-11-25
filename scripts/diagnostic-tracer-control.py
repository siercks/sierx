"""Compare matched old/fixed tracers in a controlled, no-NIC child-death race."""
import fcntl
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from tracer_diagnostic import state_directory, FIXTURES, target_user, clean_environment
root = state_directory()
workspace = root
scripts = Path(__file__).resolve().parent
sys.path.insert(0, str(scripts))
import offline_host_diagnostics as diagnostics
spec = importlib.util.spec_from_file_location('host', scripts/'offline-host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
build = json.loads((root/'build.json').read_text())
user = target_user(build)
assert os.getuid() == 0
assert {row['ifname'] for row in json.loads(subprocess.check_output(['ip','-j','link','show']))} == {'lo'}
os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:4]))
rows = []

def requests(instance):
    tracer = None
    pending = None
    result = []
    if not (instance/'trace').is_file(): return result
    for line in (instance/'trace').read_text().splitlines():
        match = diagnostics.EXIT_TRACE_LINE.match(line)
        if not match: continue
        pid, _timestamp, event = match.groups()
        if event == 'tracing_mark_write: sierx-tracer-start': tracer = pid
        if pid != tracer: continue
        entry = re.match(r'sys_ptrace\(request: (?:0x)?([0-9a-f]+), pid: (?:0x)?([0-9a-f]+),', event)
        if entry: pending = (int(entry[1],16), int(entry[2],16))
        returned = diagnostics.TRACER_RETURN.fullmatch(event)
        if returned and returned[1]=='ptrace' and pending:
            number = int(returned[2],10 if returned[2].startswith('-') else 16)
            if number >= 2**63: number -= 2**64
            if -4095 <= number < 0: result.append((*pending,-number))
    return result

with tempfile.TemporaryDirectory(prefix='sierx-query-race-') as temporary:
    scratch = Path(temporary)
    scratch.chmod(0o755)
    shim = scratch/'fault-query.so'
    fixture = scratch/'installer'
    subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-O2',str(FIXTURES/'fault-query.c'),
                    '-o',str(shim),'-ldl'], check=True)
    subprocess.run(['cc','-Wall','-Wextra','-O2',str(FIXTURES/'remaining-installer.c'),
                    '-o',str(fixture)], check=True)
    observed_installer=scratch/'observed-installer'
    observed_installer.write_text('#!/usr/bin/python3\nimport os,sys\n'
        +'sys.path.insert(0,'+repr(str(scripts))+')\n'
        +'from offline_host_diagnostics import mark_installer\n'
        +'os.set_inheritable(4,False)\n'
        +'mark_installer("sierx-installer-start")\n'
        +'mark_installer("sierx-phase two-release-stress-1")\n'
        +'mark_installer("sierx-operation start apply")\n'
        +'os.environ["SIERX_SKIP_MARKERS"]="1"\n'
        +'os.execv('+repr(str(fixture))+',['+repr(str(fixture))+'])\n')
    observed_installer.chmod(0o755)
    for mode in ('old','fixed'):
        binary = root/('strace-'+mode)
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == build['builds'][mode]['sha256']
        for ordinary in (True,False):
            case = mode+('-ordinary' if ordinary else '-seccomp')
            protected = scratch/case
            protected.mkdir(mode=0o700)
            instance = Path('/sys/kernel/tracing/instances')/('sierx-query-'+uuid.uuid4().hex[:12])
            read_fd, write_fd = os.pipe2(os.O_NONBLOCK)
            high_read = fcntl.fcntl(read_fd, fcntl.F_DUPFD_CLOEXEC, 10)
            high_write = fcntl.fcntl(write_fd, fcntl.F_DUPFD_CLOEXEC, 10)
            os.close(read_fd); os.close(write_fd)
            ready_read,ready_write=os.pipe2(os.O_NONBLOCK)
            high_ready_read=fcntl.fcntl(ready_read,fcntl.F_DUPFD_CLOEXEC,12)
            high_ready_write=fcntl.fcntl(ready_write,fcntl.F_DUPFD_CLOEXEC,12)
            os.close(ready_read);os.close(ready_write)
            environment = {**clean_environment(scratch), 'SIERX_PROBE_PID_READ_FD':str(high_read),
                           'SIERX_PROBE_PID_WRITE_FD':str(high_write),
                           'SIERX_PROBE_READY_FD':str(high_ready_write)}
            start = ('import sys;from pathlib import Path;'+
                     'sys.path.insert(0,'+repr(str(scripts))+');'+
                     'import offline_host_diagnostics as d;'+
                     'd.start_installer_exit_trace(Path('+repr(str(instance))+'))')
            enable = start.replace('start_installer_exit_trace','enable_tracer_error_events')
            enable += (';p=Path('+repr(str(instance))+');'
                '(p/"buffer_size_kb").write_text("1024");'
                'starts=[m[1] for line in (p/"trace").read_text().splitlines() '
                'if (m:=d.EXIT_TRACE_LINE.fullmatch(line)) and '
                'm[3]=="tracing_mark_write: sierx-tracer-start"];'
                'assert len(starts)==1;'
                'e=p/"events/syscalls/sys_enter_ptrace";'
                '(e/"filter").write_text("common_pid == "+starts[0]);'
                '(e/"enable").write_text("1")')
            wrapper = host.tracer_wrapper('installer','socket,execve,clone,clone3',protected,
                report_exits=True,ordinary_installer_trace=ordinary)
            wrapper = wrapper.replace(
                '/usr/bin/python3 /opt/acceptance/tests/offline_host_diagnostics.py --start-installer-exit-trace',
                '/usr/bin/python3 -B -c '+shlex.quote(start)).replace(
                '/usr/bin/python3 /opt/acceptance/tests/offline_host_diagnostics.py --enable-tracer-error-events',
                '/usr/bin/python3 -B -c '+shlex.quote(enable)).replace(
                str(diagnostics.INSTALLER_EXIT_TRACE),str(instance)).replace(
                'exec /usr/bin/strace','exec env LD_PRELOAD='+shlex.quote(str(shim))+' '+shlex.quote(str(binary))).replace(
                '-u acceptance /usr/sbin/sierx-observed-installer','-u '+shlex.quote(user)+' '+shlex.quote(str(observed_installer)))
            outer = protected/'outer.trace'
            process = None
            try:
                with (protected/'outer.stderr').open('wb') as stderr:
                    process = subprocess.Popen(['/bin/sh','-c',wrapper],
                        env=environment,stdout=subprocess.PIPE,stderr=stderr,
                        pass_fds=(high_read,high_write,high_ready_read,high_ready_write),start_new_session=True)
                    until = time.monotonic()+15
                    target = None
                    while time.monotonic()<until:
                        try:ready=os.read(high_ready_read,4)
                        except BlockingIOError:ready=b''
                        if ready:
                            assert len(ready)==4
                            target=int.from_bytes(ready,sys.byteorder,signed=True)
                            assert target>1
                            try: os.kill(target,signal.SIGKILL)
                            except ProcessLookupError: pass
                            break
                        if process.poll() is not None: break
                        time.sleep(0.005)
                    output = process.communicate(timeout=8)[0]
                observed = requests(instance)
                requested = target is not None and any(row[2]==3 for row in observed)
                listen_eio = any(row[0]==0x4208 and row[2]==5 for row in observed)
                if not requested:
                    private = diagnostics.private_tail(protected/'installer.stderr')
                    private_outer = diagnostics.private_tail(protected/'outer.stderr')
                    kernel_text=(instance/'trace').read_text()
                    failure = {'case':case,'return_code':process.returncode,
                        'query_records':len(observed),
                        'request_errno_pairs':[[row[0],row[2]] for row in observed],
                        'kernel_installer_markers':kernel_text.count('sierx-installer-start'),
                        'event_kinds':sorted(set(re.findall(r':\s+([a-z_]+)(?:\(|:| ->)',kernel_text))),
                        'errno_numbers':[number for number in errno.errorcode if os.strerror(number) in private],
                        'outer_bytes':len(private_outer),'inner_bytes':len(private),
                        'inner_categories':diagnostics.observer_errors(private.replace(str(binary),'/usr/bin/strace')),
                        'request_names':sorted(set(re.findall(r'\bPTRACE_[A-Z_]+\b',private))),
                        'error_labels':[label for text,label in (
                            ('Permission denied','access'),('Operation not permitted','permission'),
                            ('No such process','missing-task'),('Input/output error','io'),
                            ('Invalid argument','argument'),('Function not implemented','unsupported'),
                            ('Bad address','address'),('invalid option','option'),
                            ('invalid system call','syscall-selection')) if text in private],
                        'outer_categories':diagnostics.observer_errors(private_outer),
                        'outer_python':diagnostics.journal_failure(private_outer),
                        'loader_error': 'cannot be preloaded' in private,
                        'kernel':diagnostics.read_installer_exit_trace(instance)}
                    (workspace/'phase3-getsiginfo-control-failure.json').write_text(json.dumps(failure,indent=2)+'\n')
                    print(json.dumps(failure,sort_keys=True),flush=True)
                expected_code = 1 if mode=='old' else 0
                assert process.returncode==expected_code, (case,process.returncode)
                assert requested and target is not None, case
                assert listen_eio == (mode=='old'), case
                assert output == (b'' if mode=='old' else b'installer-survived\n'), case
                until = time.monotonic()+3
                while time.monotonic()<until:
                    record = diagnostics.installer_exit_events((instance/'trace').open())
                    if len(record.get('kernel_exit',{}))==2 and all(
                            row['task_exited'] for row in record['kernel_exit'].values()): break
                    time.sleep(0.01)
                record = diagnostics.read_installer_exit_trace(instance)
                expected = {'installer':{'task_exited':True},
                            'tracer':{'task_exited':True,'requested_exit_code':1}}
                if mode=='fixed':
                    expected = {role:{'task_exited':True,'requested_exit_code':0} for role in ('installer','tracer')}
                assert record['kernel_exit_capture']=='observed' and record['kernel_exit']==expected, (case,record)
                assert (protected/'installer.stderr').stat().st_mode & 0o777 == 0o600
                rows.append({'case':case,'forced_query_esrch_observed':True,
                    'subsequent_listen_eio_observed':listen_eio,'tracer_return':process.returncode,
                    'installer_survived':mode=='fixed','kernel_exit':record['kernel_exit'],
                    'kernel_exit_capture':record['kernel_exit_capture']})
                print(json.dumps(rows[-1],sort_keys=True),flush=True)
            finally:
                os.close(high_read); os.close(high_write)
                os.close(high_ready_read);os.close(high_ready_write)
                if process is not None and process.poll() is None:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait(timeout=5)
                if instance.exists(): instance.rmdir()
proof = {'scope':'synthetic-synchronized-getsiginfo-esrch-child-termination',
    'build':build,'cases':rows,'natural_race_reproduced':False,
    'historical_cause_proven':False,'release_acceptance':False,
    'private_traces_retained':False,'system_binary_replaced':False}
(workspace/'phase3-getsiginfo-control.json').write_text(json.dumps(proof,indent=2)+'\n')
print('matched tracer control complete; no release acceptance',flush=True)
