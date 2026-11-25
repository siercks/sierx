"""Bounded uninjected comparison; diagnostic only, no release acceptance."""
import hashlib,importlib.util,json,os,re,shlex,signal,subprocess,sys,tempfile,time,uuid
from pathlib import Path
from tracer_diagnostic import state_directory, FIXTURES, target_user, clean_environment
root=state_directory()
workspace=root
scripts=Path(__file__).resolve().parent
sys.path.insert(0,str(scripts))
import offline_host_diagnostics as diagnostics
spec=importlib.util.spec_from_file_location('host',scripts/'offline-host.py')
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
build=json.loads((root/'build.json').read_text())
user=target_user(build)
assert os.getuid()==0
assert {row['ifname'] for row in json.loads(subprocess.check_output(['ip','-j','link','show']))}=={'lo'}
os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:4]))
rows=[]
reproduced=False
with tempfile.TemporaryDirectory(prefix='sierx-natural-race-') as temporary:
    scratch=Path(temporary);scratch.chmod(0o755)
    worker=scratch/'worker'
    subprocess.run(['cc','-O2','-Wall','-Wextra','-pthread',str(FIXTURES/'natural-worker.c'),'-o',str(worker)],check=True)
    launcher=scratch/'installer'
    launcher.write_text('#!/usr/bin/python3\nimport os,sys\n'
        +'sys.path.insert(0,'+repr(str(scripts))+')\n'
        +'from offline_host_diagnostics import mark_installer\n'
        +'os.set_inheritable(4,False)\n'
        +'mark_installer("sierx-installer-start")\n'
        +'mark_installer("sierx-phase two-release-stress-1")\n'
        +'mark_installer("sierx-operation start apply")\n'
        +'os.execv('+repr(str(worker))+',['+repr(str(worker))+'])\n')
    launcher.chmod(0o755)
    for mode in ('old','fixed'):
        binary=root/('strace-'+mode)
        assert hashlib.sha256(binary.read_bytes()).hexdigest()==build['builds'][mode]['sha256']
        protected=scratch/mode;protected.mkdir(mode=0o700)
        instance=Path('/sys/kernel/tracing/instances')/('sierx-natural-'+uuid.uuid4().hex[:12])
        start=('import sys;from pathlib import Path;sys.path.insert(0,'+repr(str(scripts))+');'
               +'import offline_host_diagnostics as d;d.start_installer_exit_trace(Path('+repr(str(instance))+'))')
        enable=start.replace('start_installer_exit_trace','enable_tracer_error_events')
        wrapper=host.tracer_wrapper('installer','socket,execve,clone,clone3',protected,
            report_exits=True,ordinary_installer_trace=True)
        wrapper=wrapper.replace('/usr/bin/python3 /opt/acceptance/tests/offline_host_diagnostics.py --start-installer-exit-trace',
            '/usr/bin/python3 -B -c '+shlex.quote(start)).replace(
            '/usr/bin/python3 /opt/acceptance/tests/offline_host_diagnostics.py --enable-tracer-error-events',
            '/usr/bin/python3 -B -c '+shlex.quote(enable)).replace(str(diagnostics.INSTALLER_EXIT_TRACE),str(instance)).replace(
            'exec /usr/bin/strace','exec '+shlex.quote(str(binary))).replace(
            '-u acceptance /usr/sbin/sierx-observed-installer','-u '+shlex.quote(user)+' '+shlex.quote(str(launcher)))
        process=None;timed_out=False
        environment=clean_environment(scratch)
        environment['LC_ALL']='C'
        try:
            began=time.monotonic()
            with (protected/'setup.stderr').open('wb') as stderr:
                process=subprocess.Popen(['/bin/sh','-c',wrapper],env=environment,
                    stdout=subprocess.PIPE,stderr=stderr,start_new_session=True)
                try:output=process.communicate(timeout=90)[0]
                except subprocess.TimeoutExpired:
                    timed_out=True;os.killpg(process.pid,signal.SIGKILL)
                    output=process.communicate(timeout=5)[0]
            record=diagnostics.read_installer_exit_trace(instance)
            private=diagnostics.private_tail(protected/'installer.stderr')
            listen_eio='PTRACE_LISTEN' in private and 'Input/output error' in private
            normal=process.returncode==0 and output==b'completed=4096\n'
            reproduced=(mode=='old' and not timed_out and process.returncode==1 and listen_eio
                and record.get('kernel_exit_capture')=='observed'
                and record.get('kernel_exit')=={'installer':{'task_exited':True},
                    'tracer':{'task_exited':True,'requested_exit_code':1}})
            row={'mode':mode,'tracer_return':process.returncode,'deadline_reached':timed_out,
                'seconds':round(time.monotonic()-began,3),'completed_4096':normal,
                'listen_eio':listen_eio,'kernel':record,'fault_injection':False}
            rows.append(row);print(json.dumps(row,sort_keys=True),flush=True)
            if mode=='old' and not reproduced:break
            if mode=='fixed':assert normal and not listen_eio and not timed_out
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
            if instance.exists():instance.rmdir()
proof={'scope':'bounded-uninjected-terminating-thread-workload','build':build,'cases':rows,
    'fault_injection':False,'natural_failure_reproduced':bool(rows and rows[0]['listen_eio'] and rows[0]['tracer_return']==1),
    'narrow_fix_verified_on_natural_workload':len(rows)==2 and rows[1]['completed_4096'],
    'historical_cause_proven':False,'arm64_verified':False,'release_acceptance':False,
    'private_traces_retained':False,'system_binary_replaced':False}
(workspace/'phase3-getsiginfo-natural.json').write_text(json.dumps(proof,indent=2)+'\n')
