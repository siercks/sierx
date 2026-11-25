"""Compare one real transition per tracer, only after the old cause recurs."""
import hashlib,importlib.util,json,os,re,shutil,sys,tarfile
from pathlib import Path
from types import SimpleNamespace
import offline
import offline_host_diagnostics as diagnostics
from native_tracer_diagnostic import validate_build,public_build,query_failure_fields,expected_transition_failure

ROOT=Path(__file__).resolve().parent.parent


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def shim(binary_hash):
    if not re.fullmatch('[a-f0-9]{64}',binary_hash):raise ValueError('Exact diagnostic binary hash required')
    return ('import hashlib,os,sys\n'
        'from pathlib import Path\n'
        'binary="/opt/transition-tracer/strace"\n'
        'if hashlib.sha256(Path(binary).read_bytes()).hexdigest()!='+repr(binary_hash)+':\n'
        '    raise ValueError("Diagnostic tracer changed")\n'
        'os.execv(binary,["/usr/bin/strace",*sys.argv[1:]])\n')


def prepare_installer(root,args,original_setup,binary,binary_hash):
    if not (args.development and args.transition_probe and args.ordinary_installer_trace
            and args.acceleration=='tcg' and not args.single_tcg):
        raise ValueError('Matched transition tracer requires the nonaccepting four-CPU TCG probe')
    if binary.is_symlink() or offline.digest(binary)!=binary_hash:raise ValueError('Control binary changed')
    original_setup(root,args)
    parent=root/'usr/bin/strace';before=offline.digest(parent)
    directory=root/'opt/transition-tracer';directory.mkdir(mode=0o755)
    selected=directory/'strace';shutil.copyfile(binary,selected);selected.chmod(0o755)
    program=directory/'exec.py';program.write_text(shim(binary_hash));program.chmod(0o644)
    wrapper=root/'usr/sbin/sierx-trace-installer';text=wrapper.read_text()
    if text.count('exec /usr/bin/strace')!=1:raise ValueError('Unknown installer wrapper')
    wrapper.write_text(text.replace('exec /usr/bin/strace','exec /usr/bin/python3 /opt/transition-tracer/exec.py'))
    if offline.digest(parent)!=before:raise ValueError('Parent observer changed during diagnostic preparation')
    # The default guest receipt still checks the unchanged parent executable.
    # This separate, source-pinned installer is bound by the diagnostic report;
    # the ordinary guest options and every receipt/transition assertion remain.


def probe_arguments(bundle,retained,rootfs,rootfs_hash,report):
    return SimpleNamespace(bundle=str(bundle),expected_sha256=retained.BUNDLE_SHA256,
        archive=str(ROOT/'dist/sierx-offline-arm64.tar.gz'),archive_sha256=retained.ARCHIVE_SHA256,
        rootfs=str(rootfs),rootfs_sha256=rootfs_hash,report=str(report),
        previous_bundle=str(ROOT/'dist/previous/sierx-offline-arm64'),
        previous_sha256=json.loads((ROOT/'deploy/ci/previous-offline-release.json').read_text())['architectures']['arm64']['bundle_sha256'],
        previous_evidence=str(ROOT/'dist/previous/offline-acceptance-arm64.json'),development=True,
        transition_probe=True,import_probe=False,runtime_probe=False,acquisition_probe=False,
        transition_stress=False,transition_before_browser=False,single_tcg=False,
        ordinary_installer_trace=True,acceleration='tcg',soak_seconds=120)


def main():
    historical=load('transition_causal_original','offline-historical-replay.py')
    if os.geteuid()!=0 or offline.native_arch()!='arm64':raise ValueError('Owned native ARM64 launcher required')
    os.umask(0o077)
    dist=ROOT/'dist';output=dist/'historical-transition-tracers-arm64.json'
    if output.exists():raise ValueError('Transition comparison must be fresh')
    if offline.digest(ROOT/'deploy/ci/previous-offline-release.json')!=historical.RETAINED_APPROVAL_SHA256:
        raise ValueError('Original retained approval changed')
    bundle=historical.verify_input(dist,json.loads((dist/'historical-run.json').read_text()))
    build=json.loads((dist/'tracer-race-arm64/query-build.json').read_text());validate_build(build)
    if build.get('arch')!='arm64':raise ValueError('Native ARM64 matched controls required')
    rootfs=dist/'host-fixture-ubuntu24-arm64.tar'
    rootfs_hash=rootfs.with_suffix('.tar.sha256').read_text().split()[0]
    base=load('transition_causal_os','offline-host.py');base.verify_rootfs(rootfs,rootfs_hash)
    with tarfile.open(rootfs) as stream:
        kernels=[member for member in stream if re.fullmatch(r'(?:\./)?boot/vmlinuz-[^/]+',member.name) and member.isfile()]
        if len(kernels)!=1:raise ValueError('One exact guest kernel required')
        kernel_hash=hashlib.sha256(stream.extractfile(kernels[0]).read()).hexdigest()
    result={'suite':'offline-transition-tracer-comparison-v1','release_acceptance':False,'historical_cause_proven':False,
        'diagnostic_source_sha256':offline.digest(Path(__file__)),
        'suite_sha256':base.suite_digest(),'original_run':historical.RUN_ID,'release':historical.RELEASE,
        'archive_sha256':historical.ARCHIVE_SHA256,'bundle_sha256':historical.BUNDLE_SHA256,
        'retained_approval_sha256':historical.RETAINED_APPROVAL_SHA256,
        'rootfs_sha256':rootfs_hash,'kernel_sha256':kernel_hash,'virtual_cpu':'tcg',
        'virtual_cpus':4,'tcg_thread_mode':'multi','build':public_build(build),'result':'inconclusive','cases':[]}
    replay={key:result[key] for key in ('release','archive_sha256','bundle_sha256','retained_approval_sha256',
        'rootfs_sha256','kernel_sha256','suite_sha256','virtual_cpu','virtual_cpus','tcg_thread_mode','release_acceptance')}
    replay.update(run_id=historical.RUN_ID,workload='transition',transition_probe=True,installer_trace_mode='ordinary-ptrace')
    (dist/'historical-replay-input.json').write_text(json.dumps(replay,indent=2)+'\n')
    (dist/'historical-replay-input.json').chmod(0o644)
    try:
        for mode in ('old','fixed'):
            host=load('transition_causal_'+mode,'offline-host.py')
            report=dist/('transition-control-'+mode+'.json')
            if report.exists() or report.with_suffix('.failure.json').exists():raise ValueError('Each control executes at most once')
            args=probe_arguments(bundle,historical,rootfs,rootfs_hash,report)
            original_setup=host.setup
            binary=dist/'tracer-race-arm64'/('strace-query-'+mode)
            binary_hash=build['builds'][mode]['sha256']
            prepared=[]
            def setup(root,options):
                prepare_installer(root,options,original_setup,binary,binary_hash)
                prepared.append(True)
            host.setup=setup
            completed=False;failure=None
            try:host.execute(args);completed=True
            except (OSError,ValueError,host.subprocess.SubprocessError):
                path=report.with_suffix('.failure.json')
                if path.is_file():failure=diagnostics.sanitize_failure(json.loads(path.read_text()))
            stderr=report.with_suffix('.private.installer.stderr')
            query=(query_failure_fields(stderr.read_text(errors='replace')) if stderr.is_file() and stderr.stat().st_size<=65536
                   else {'capture':'invalid-or-truncated'})
            case={'mode':mode,'installer_binary_sha256':binary_hash,'query_observation':query,
                'parent_observer_preparation_check_passed':bool(prepared),'transition_completed':completed}
            if failure is not None:case['failure']=failure
            if completed:
                transition=json.loads(report.read_text())
                if (transition.get('suite')!='offline-transition-probe-v1' or transition.get('release_acceptance') is not False
                        or transition.get('virtual_cpu')!='tcg' or transition.get('virtual_cpus')!=4
                        or transition.get('rootfs_sha256')!=rootfs_hash or transition.get('kernel_sha256')!=kernel_hash):
                    raise ValueError('Transition result differs from the exact guest inputs')
                case['host_report']=transition
            matched=(failure is not None and expected_transition_failure({'result':'failed',
                'tracer_returncode':failure.get('service_exit_code'),'observation':failure,'query_observation':query}))
            case['expected_old_cause_observed']=matched
            result['cases'].append(case)
            if mode=='old' and not matched:
                if not completed:result['result']='failed'
                break
            if mode=='fixed':
                result['result']=('cause-reproduced-and-corrected' if completed and query.get('capture')=='observed'
                    and query.get('listen_eio')==0 else 'failed')
    except (OSError,ValueError,KeyError,TypeError,base.subprocess.SubprocessError) as error:
        result.update(result='failed',failure_type=type(error).__name__)
    finally:
        with output.open('x') as stream:stream.write(json.dumps(result,indent=2)+'\n')
        output.chmod(0o644)
    return 0 if result['result']=='cause-reproduced-and-corrected' else 1


if __name__=='__main__':
    try:code=main()
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('transition-tracer-comparison: failed ('+type(error).__name__+')',file=sys.stderr);code=1
    sys.exit(code)
