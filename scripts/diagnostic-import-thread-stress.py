"""One natural thread-exit comparison during an original import; no acceptance."""
import hashlib,importlib.util,json,os,re,signal,subprocess,sys,tempfile
from pathlib import Path
import offline
from tracer_diagnostic import architecture,state_directory,target_user,FIXTURES
from native_tracer_diagnostic import validate_build,public_build,public_case,expected_old_failure,expected_fixed_completion

ROOT=Path(__file__).resolve().parent.parent
SCRIPT=Path(__file__).resolve()
NATURAL_SHA='4cce0574bc3cc7b4904c0905a70c34a3dbc11ee33ed7c97a79ef15ccc86ca737'
WORKER_FLAGS=['-O2','-pthread']
SUITE=('diagnostic-import-thread-stress.py','offline-native-import.py','native_tracer_diagnostic.py',
    'tracer_diagnostic.py','offline.py','offline_host_diagnostics.py','offline_apply_trace.py',
    'kernel_network_evidence.py','network_observer.py','offline_host_evidence.py','offline_guest_podman.py','offline_smoke_trace.py')


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def suite_digest():
    value=hashlib.sha256()
    for name in SUITE:value.update(name.encode()+b'\0'+(ROOT/'scripts'/name).read_bytes())
    value.update((FIXTURES/'natural-worker.c').read_bytes());return value.hexdigest()


def validate_worker(receipt,binary):
    if (not isinstance(receipt,dict) or set(receipt)!={'source_sha256','binary_sha256','flags','cycles','arch','owner_uid','release_acceptance'}
            or receipt['source_sha256']!=NATURAL_SHA or offline.digest(FIXTURES/'natural-worker.c')!=NATURAL_SHA
            or receipt['flags']!=WORKER_FLAGS or type(receipt['cycles']) is not int or receipt['cycles']!=4096
            or receipt['arch']!=architecture() or type(receipt['owner_uid']) is not int or receipt['owner_uid']<1000
            or receipt['release_acceptance'] is not False or binary.is_symlink() or not binary.is_file()
            or not isinstance(receipt['binary_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',receipt['binary_sha256'])
            or offline.digest(binary)!=receipt['binary_sha256']):
        raise ValueError('Natural worker must match its exact source, build and native account')
    return receipt


def prepare():
    state=state_directory();assert os.geteuid()!=0
    build=json.loads((state/'query-build.json').read_text());validate_build(build)
    if build.get('owner_uid')!=os.getuid() or build.get('arch')!=architecture():raise ValueError('Worker preparer differs from tracer preparer')
    worker=state/'import-natural-worker';receipt=state/'import-natural-worker.json'
    if worker.exists() or receipt.exists():raise ValueError('Natural worker preparation must be fresh')
    if offline.digest(FIXTURES/'natural-worker.c')!=NATURAL_SHA:raise ValueError('Natural source changed')
    os.umask(0o077)
    with (state/'import-natural-build.private.log').open('wb') as private:
        subprocess.run(['gcc',*WORKER_FLAGS,'-o',str(worker),str(FIXTURES/'natural-worker.c')],
            stdout=private,stderr=private,check=True,timeout=30)
    worker.chmod(0o755)
    value={'source_sha256':NATURAL_SHA,'binary_sha256':offline.digest(worker),'flags':WORKER_FLAGS,
        'cycles':4096,'arch':architecture(),'owner_uid':os.getuid(),'release_acceptance':False}
    validate_worker(value,worker);receipt.write_text(json.dumps(value)+'\n')


def stress_evidence(path):
    if path.is_symlink():raise ValueError('Private worker checkpoint cannot be a symlink')
    if not path.exists():return {'started':False,'completed':False}
    if path.is_symlink() or not path.is_file() or path.stat().st_size>1024:raise ValueError('Invalid private worker checkpoint')
    value=json.loads(path.read_text())
    if (not isinstance(value,dict) or set(value) not in ({'started','completed'},{'started','completed','exit_code'})
            or value.get('started') is not True or type(value.get('completed')) is not bool
            or ('exit_code' in value and (type(value['exit_code']) is not int or not -128<=value['exit_code']<=255))
            or value['completed'] and value.get('exit_code')!=0):raise ValueError('Malformed worker completion')
    return value


def helper(module,path,worker,completion):
    if os.getuid()==0 or offline.digest(worker)!=module.worker_hash:raise ValueError('Unprivileged exact worker required')
    os.set_inheritable(module.MARKER,False);child=None;stream=None
    def emit(marker):
        nonlocal child,stream
        module.diagnostics.mark_installer(marker)
        if marker=='sierx-import-stage load-app':
            if child is not None or completion.exists():raise ValueError('Natural workload executes once')
            with completion.open('x') as output:output.write(json.dumps({'started':True,'completed':False})+'\n')
            stream=completion.with_suffix('.private').open('xb')
            child=subprocess.Popen([str(worker)],stdin=subprocess.DEVNULL,stdout=stream,stderr=stream)
    try:module.diagnostics.observe_import(path,emit=emit)
    finally:
        if child is not None:
            code=child.wait(timeout=30);stream.close()
            raw=completion.with_suffix('.private')
            complete=code==0 and raw.stat().st_size==15 and raw.read_bytes()==b'completed=4096\n'
            completion.write_text(json.dumps({'started':True,'completed':complete,'exit_code':code})+'\n')


def compare_cases(run_case):
    result={'result':'inconclusive','cases':[]}
    for mode in ('old','fixed'):
        try:case=run_case(mode)
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
            result.update(result='failed',failure_stage=mode,failure_type=type(error).__name__);break
        if not isinstance(case,dict) or case.get('mode')!=mode:
            result.update(result='failed',failure_stage=mode,failure_type='ValueError');break
        result['cases'].append(case)
        if mode=='old':
            if (case.get('forced_termination') is not False or case.get('thread_stress',{}).get('started') is not True
                    or not expected_old_failure(case.get('import',{}))):break
        else:
            result['result']=('cause-reproduced-and-corrected' if case.get('forced_termination') is False
                and expected_fixed_completion(case.get('import',{}))
                and case.get('thread_stress')=={'started':True,'completed':True,'exit_code':0} else 'failed')
    return result


def controller(bundle,expected,uid):
    if os.geteuid()!=0 or len(os.sched_getaffinity(0))<4:raise ValueError('Owned four-CPU native root comparison required')
    if {row['ifname'] for row in json.loads(subprocess.check_output(['ip','-j','link','show']))}!={'lo'}:raise ValueError('No-NIC namespace required')
    os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:4]));os.umask(0o077)
    state=state_directory();build=json.loads((state/'query-build.json').read_text());validate_build(build)
    user=target_user(build)
    if build.get('owner_uid')!=uid or build.get('arch')!=architecture():raise ValueError('Compared account/build differs')
    worker=state/'import-natural-worker';receipt=validate_worker(json.loads((state/'import-natural-worker.json').read_text()),worker)
    if receipt['owner_uid']!=uid:raise ValueError('Worker account differs')
    data=offline.verify(bundle,expected)
    if data['arch']!=architecture():raise ValueError('Input architecture differs')
    source=suite_digest();parent=offline.digest(Path('/usr/bin/strace'))
    output=ROOT/'dist/historical-native-import-thread-stress-arm64.json'
    if output.exists():raise ValueError('Comparison output must be fresh')
    report={'suite':'offline-native-import-thread-stress-comparison-v1','release_acceptance':False,
        'historical_cause_proven':False,'release':data['release'],'bundle_sha256':expected,'arch':architecture(),
        'cpu_affinity_count':4,'suite_sha256':source,'worker':{key:value for key,value in receipt.items() if key!='owner_uid'},
        'build':public_build(build)}
    def run_case(mode):
        binary=state/('strace-query-'+mode)
        if binary.is_symlink() or offline.digest(binary)!=build['builds'][mode]['sha256']:raise ValueError('Selected tracer changed')
        with tempfile.TemporaryDirectory(prefix='import-thread-',dir=state) as temporary:
            case=Path(temporary);case.chmod(0o700);os.chown(case,uid,os.getgid())
            completion=case/'worker.json';result=case/'result.json'
            command=['unshare','--mount','--net','--pid','--fork','--kill-child','--mount-proc','--propagation','private',
                'sh','-eu','-c','mount --bind "$1" /usr/bin/strace\nshift\nexec "$@"','native-import-thread',str(binary),
                '/usr/bin/python3','-B',str(SCRIPT),'--control',str(worker),receipt['binary_sha256'],str(completion),
                '--probe',str(bundle),expected,str(uid),str(result)]
            forced=False
            with (case/'operation.private.log').open('wb') as private:
                process=subprocess.Popen(command,stdout=private,stderr=private,start_new_session=True)
                try:code=process.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    forced=True;os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10);code=process.returncode
            value={'mode':mode,'forced_termination':forced,'launcher_exit':code,'thread_stress':stress_evidence(completion)}
            if not result.is_file() or result.is_symlink() or result.stat().st_size>65536:raise ValueError('Missing bounded actual import evidence')
            raw=json.loads(result.read_text())
            if raw.get('release')!=data['release'] or raw.get('bundle_sha256')!=expected or raw.get('strace_sha256')!=build['builds'][mode]['sha256']:
                raise ValueError('Import input or selected tracer changed')
            value['import']=public_case(raw)
        value['scratch_cleanup_verified']=not case.exists();return value
    report.update(compare_cases(run_case))
    report['parent_system_binary_unchanged']=offline.digest(Path('/usr/bin/strace'))==parent
    if not report['parent_system_binary_unchanged'] or suite_digest()!=source:report['result']='failed'
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    output.chmod(0o644);return report['result']!='cause-reproduced-and-corrected'


def historical():
    replay=load('thread_original_replay','offline-historical-replay.py')
    if os.geteuid()==0 or architecture()!='arm64' or os.cpu_count()!=4:raise ValueError('Original native ARM64 four-CPU runner required')
    approval=ROOT/'deploy/ci/previous-offline-release.json'
    if offline.digest(approval)!=replay.RETAINED_APPROVAL_SHA256:raise ValueError('Original retained approval differs')
    bundle=replay.verify_input(ROOT/'dist',json.loads((ROOT/'dist/historical-run.json').read_text()))
    proof={'run_id':replay.RUN_ID,'release':replay.RELEASE,'archive_sha256':replay.ARCHIVE_SHA256,
        'bundle_sha256':replay.BUNDLE_SHA256,'retained_approval_sha256':replay.RETAINED_APPROVAL_SHA256,
        'workload':'native-import-stress','natural_cycles':4096,'installer_trace_mode':'ordinary-ptrace',
        'execution_environment':'native-process-namespaces','release_acceptance':False}
    with (ROOT/'dist/historical-replay-input.json').open('x') as stream:stream.write(json.dumps(proof)+'\n')
    import pwd
    return subprocess.run(['sudo','env','SIERX_TRACER_DIAGNOSTIC_STATE='+str(state_directory()),
        'SIERX_TRACER_DIAGNOSTIC_USER='+pwd.getpwuid(os.getuid()).pw_name,
        'unshare','--mount','--net','--pid','--fork','--kill-child','--mount-proc','--propagation','private','sh','-eu','-c',
        'mountpoint -q /sys/kernel/tracing || mount -t tracefs tracefs /sys/kernel/tracing\nexec "$@"','import-thread-stress',
        '/usr/bin/python3','-B',str(SCRIPT),'--compare',str(bundle),replay.BUNDLE_SHA256,str(os.getuid())]).returncode


def main(args):
    if args==['--prepare']:prepare();return 0
    if args==['--historical']:return historical()
    if len(args)==4 and args[0]=='--compare':return controller(Path(args[1]).resolve(),args[2],int(args[3]))
    if len(args)>=5 and args[0]=='--control':
        worker=Path(args[1]);worker_hash=args[2];completion=Path(args[3]);mode,*values=args[4:]
        if (worker.is_symlink() or not worker.is_absolute() or not completion.is_absolute()
                or not re.fullmatch('[a-f0-9]{64}',worker_hash) or offline.digest(worker)!=worker_hash):raise ValueError('Exact owned worker required')
        module=load('stress_native_probe','offline-native-import.py')
        module.worker_hash=worker_hash
        module.PYTHON=('/usr/bin/python3','-B',str(SCRIPT),'--control',str(worker),worker_hash,str(completion))
        if mode=='--trace' and os.geteuid()==0:module.start_trace(Path(values[0]),Path(values[1]),*values[2:]);return 0
        if mode=='--installer' and os.geteuid()!=0:return module.installer(*values)
        if mode=='--helper' and os.geteuid()!=0:helper(module,values[0],worker,completion);return 0
        if mode=='--probe' and os.geteuid()==0:
            bundle,digest,uid,output=values
            result=module.probe(Path(bundle).resolve(),digest,int(uid),query_observed=True)
            with Path(output).open('x') as stream:stream.write(json.dumps(result)+'\n')
            return result['result']!='passed'
    raise ValueError('Unsupported nonaccepting diagnostic mode')


if __name__=='__main__':
    try:sys.exit(main(sys.argv[1:]))
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.SubprocessError):
        raise SystemExit('import-thread-stress: setup or evidence rejected; no acceptance') from None
