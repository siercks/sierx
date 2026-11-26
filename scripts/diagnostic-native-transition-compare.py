"""Native OS-container causal comparison; never VM audit/release acceptance."""
import hashlib,importlib.util,json,os,re,shutil,signal,subprocess,sys,tarfile,tempfile
from pathlib import Path
from types import SimpleNamespace
import offline,offline_archive,offline_guest_tracer
import offline_host_diagnostics as diagnostics
from native_tracer_diagnostic import validate_build,public_build,query_failure_fields,expected_transition_failure,valid_query_counts

ROOT=Path(__file__).resolve().parent.parent
TRACE_PATHS=(Path('/sys/kernel/tracing/instances/sierx-offline'),diagnostics.INSTALLER_EXIT_TRACE)


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def command(root,machine,cpus):
    if (not re.fullmatch(r'sierx-native-[a-z0-9-]{1,48}',machine) or len(cpus)!=4
            or len(set(cpus))!=4 or any(type(cpu) is not int or cpu<0 for cpu in cpus)):
        raise ValueError('Owned machine and exactly four explicit CPUs required')
    return ['systemd-nspawn','--quiet','--settings=no','--register=no','--directory='+str(root),
        '--machine='+machine,'--private-network','--private-users=no','--link-journal=no',
        '--resolv-conf=off','--timezone=off','--capability=CAP_SYS_ADMIN,CAP_SYS_PTRACE',
        '--cpu-affinity='+','.join(map(str,cpus)),
        '--bind=/sys/kernel/tracing:/sys/kernel/tracing','--console=pipe','--boot','--',
        'systemd.unit=sierx-acceptance.target']


def prepare(root,host,args,binary,binary_hash):
    if not (args.development and args.transition_probe and args.virtual_cpu=='native'
            and not args.ordinary_installer_trace):raise ValueError('Nonaccepting native transition only')
    if binary.is_symlink() or offline.digest(binary)!=binary_hash:raise ValueError('Tracer control changed')
    parent=root/'usr/bin/strace';before=offline.digest(parent)
    host.setup(root,args)
    tests=root/'opt/acceptance/tests';tests.mkdir(parents=True,exist_ok=True);tests.chmod(0o755)
    for name in host.SUITE_FILES:
        shutil.copyfile(ROOT/'scripts'/name,tests/name);(tests/name).chmod(0o644)
    for name in ('package.json','package-lock.json'):
        shutil.copyfile(ROOT/'web'/name,tests/name);(tests/name).chmod(0o644)
    if host.suite_digest(tests,tests)!=args.suite_sha256:raise ValueError('Native snapshot changed')
    trace=tests/'deploy-trace';trace.mkdir(mode=0o755)
    shutil.copyfile(tests/'offline_apply_trace.py',trace/'sitecustomize.py')
    (trace/'sitecustomize.py').chmod(0o644)
    directory=root/'opt/transition-tracer';directory.mkdir(mode=0o755)
    shutil.copyfile(binary,directory/'strace');(directory/'strace').chmod(0o755)
    # Reuse the exact reviewed hash-checking shim, not a receipt bypass.
    shim=load('native_transition_shim','diagnostic-transition-tracer-compare.py').shim(binary_hash)
    (directory/'exec.py').write_text(shim);(directory/'exec.py').chmod(0o644)
    wrapper=root/'usr/sbin/sierx-trace-installer';text=wrapper.read_text()
    if text.count('exec /usr/bin/strace')!=1:raise ValueError('Unknown native installer wrapper')
    wrapper.write_text(text.replace('exec /usr/bin/strace','exec /usr/bin/python3 /opt/transition-tracer/exec.py'))
    if offline.digest(parent)!=before:raise ValueError('Parent observer changed')
    # No host credential, user bus, home, store or network enters the OS.
    # Its root observers retain the same selected calls and independent trace.
    return before


def launch(root,machine,cpus,log,deadline=1900):
    if any(path.exists() for path in TRACE_PATHS):raise ValueError('Reserved observer instance already exists')
    process=None;forced=False
    try:
        with log.open('wb') as stream:
            process=subprocess.Popen(command(root,machine,cpus),stdout=stream,stderr=stream,start_new_session=True)
            try:process.wait(timeout=deadline)
            except subprocess.TimeoutExpired:
                forced=True;process.terminate()
                try:process.wait(timeout=30)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=30)
        return process.returncode,forced
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=30)
        # Only our two previously absent instances can have been created.
        # Never touch the default tracer or any unrelated instance.
        for path in reversed(TRACE_PATHS):
            if path.exists():
                (path/'tracing_on').write_text('0');path.rmdir()


def checked_failure(root):
    for relative in ('home/acceptance/failure.json','home/acceptance/result.json','var/log/sierx-network/service-failure.json'):
        path=root/relative
        if path.is_file() and path.stat().st_size<=65536:
            value=json.loads(path.read_text())
            if value.get('result')=='failed':return diagnostics.sanitize_failure(value)
    return None


def cause_matches(failure,query,forced):
    return (not forced and failure is not None and expected_transition_failure({'result':'failed',
        'tracer_returncode':failure.get('service_exit_code'),'observation':failure,'query_observation':query}))


def compare(run_case):
    result={'result':'inconclusive','cases':[]}
    for mode in ('old','fixed'):
        try:case=run_case(mode)
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
            result.update(result='failed',failure_type=type(error).__name__)
            break
        result['cases'].append(case)
        if mode=='old' and not case['expected_old_cause_observed']:
            if not case['transition_completed']:result['result']='failed'
            break
        if mode=='fixed':
            query=case['query_observation']
            result['result']=('cause-reproduced-and-corrected' if case['transition_completed']
                and query.get('capture')=='observed' and valid_query_counts(query) and query['listen_eio']==0 else 'failed')
    return result


def execute_case(host,args,binary,binary_hash,mode,cpus,rootfs,archive,previous,data,old):
    with tempfile.TemporaryDirectory(prefix='sierx-native-transition-') as temporary:
        scratch=Path(temporary);root=scratch/'root';root.mkdir()
        host.run('tar','-xf',rootfs,'-C',root,'--no-same-owner');root.chmod(0o755)
        offline_guest_tracer.load_receipt(root/offline_guest_tracer.RECEIPT.relative_to('/'),
            root/offline_guest_tracer.BINARY.relative_to('/'))
        parent=prepare(root,host,args,binary,binary_hash)
        staged=root/'opt/.delivery-input'
        delivered=offline_archive.unpack(archive,staged,args.archive_sha256,args.expected_sha256,'arm64')
        delivered.rename(root/'opt/sierx-bundle');staged.rmdir()
        shutil.copytree(previous,root/'opt/previous-bundle',symlinks=True)
        status,forced=launch(root,'sierx-native-transition-'+mode,cpus,scratch/'boot.private.log')
        if offline.digest(root/'usr/bin/strace')!=parent:raise ValueError('Native parent observer changed')
        stderr=root/'var/log/sierx-network/installer.stderr'
        query=(query_failure_fields(stderr.read_text(errors='replace')) if stderr.is_file() and stderr.stat().st_size<=65536
            else {'capture':'invalid-or-truncated'})
        failure=checked_failure(root);completed=False;transition=None
        path=root/'home/acceptance/result.json'
        if not forced and path.is_file() and path.stat().st_size<=65536:
            value=json.loads(path.read_text())
            if value.get('result')=='passed':
                if status!=0 or value.get('virtual_cpus')!=4:raise ValueError('Incomplete native OS completion')
                host.evidence.validate_transition_probe(value,data,args.expected_sha256,args.suite_sha256,old,args.previous_sha256)
                directory=root/'var/log/sierx-network';kernel=json.loads((directory/'kernel.json').read_text())
                if (kernel.get('complete') is not True or kernel.get('suite_sha256')!=args.suite_sha256
                        or offline.digest(directory/'kernel.trace')!=kernel.get('trace_sha256')):
                    raise ValueError('Native independent observer did not finish')
                completed=True;transition=value
        case={'mode':mode,'installer_binary_sha256':binary_hash,'parent_observer_preparation_check_passed':True,
            'parent_observer_unchanged':True,'native_launcher_exit':status,'forced_termination':forced,
            'query_observation':query,'transition_completed':completed}
        if failure is not None:case['failure']=failure
        if transition is not None:case['host_report']=transition
        case['expected_old_cause_observed']=cause_matches(failure,query,forced)
    case['scratch_cleanup_verified']=not scratch.exists()
    return case


def main():
    if os.geteuid()!=0 or offline.native_arch()!='arm64':raise ValueError('Owned native ARM64 runner required')
    cpus=sorted(os.sched_getaffinity(0))
    if len(cpus)!=4 or os.cpu_count()!=4:raise ValueError('Exactly four native CPUs required')
    if not shutil.which('systemd-nspawn'):raise ValueError('Missing native OS launcher')
    # Run only inside the workflow's private mount namespace. No host-wide
    # mount is installed; trace instances are checked absent and removed.
    if os.readlink('/proc/self/ns/mnt')==os.readlink('/proc/1/ns/mnt'):
        raise ValueError('Private outer mount namespace required')
    tracing=Path('/sys/kernel/tracing')
    if not (tracing/'trace_clock').is_file():
        subprocess.run(['mount','-t','tracefs','nodev',str(tracing)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    os.umask(0o077);dist=ROOT/'dist';output=dist/'historical-native-transition-tracers-arm64.json'
    if output.exists():raise ValueError('Native transition comparison must be fresh')
    historical=load('native_transition_original','offline-historical-replay.py')
    if offline.digest(ROOT/'deploy/ci/previous-offline-release.json')!=historical.RETAINED_APPROVAL_SHA256:
        raise ValueError('Original retained approval changed')
    bundle=historical.verify_input(dist,json.loads((dist/'historical-run.json').read_text()))
    data=offline.verify(bundle,historical.BUNDLE_SHA256)
    previous=dist/'previous/sierx-offline-arm64'
    approval=json.loads((ROOT/'deploy/ci/previous-offline-release.json').read_text())
    previous_hash=approval['architectures']['arm64']['bundle_sha256']
    old=offline.verify(previous,previous_hash)
    offline.verify_evidence(old,previous_hash,json.loads((dist/'previous/offline-acceptance-arm64.json').read_text()))
    build=json.loads((dist/'tracer-race-arm64/query-build.json').read_text());validate_build(build)
    if build.get('arch')!='arm64':raise ValueError('Native ARM64 controls required')
    host=load('native_transition_host','offline-host.py');rootfs=dist/'host-fixture-ubuntu24-arm64.tar'
    rootfs_hash=rootfs.with_suffix('.tar.sha256').read_text().split()[0];host.verify_rootfs(rootfs,rootfs_hash)
    kernel=os.uname().release
    if not re.fullmatch(r'[A-Za-z0-9.+_-]{1,128}',kernel):raise ValueError('Invalid native kernel release')
    result={'suite':'offline-native-transition-tracer-comparison-v1','release_acceptance':False,'historical_cause_proven':False,
        'diagnostic_source_sha256':offline.digest(Path(__file__)),'suite_sha256':host.suite_digest(),
        'execution_environment':'native-os-container','kernel_release':kernel,'virtual_cpu':'native','virtual_cpus':4,
        'original_run':historical.RUN_ID,'release':historical.RELEASE,'archive_sha256':historical.ARCHIVE_SHA256,
        'bundle_sha256':historical.BUNDLE_SHA256,'retained_approval_sha256':historical.RETAINED_APPROVAL_SHA256,
        'rootfs_sha256':rootfs_hash,'build':public_build(build),'result':'inconclusive','cases':[]}
    replay={key:result[key] for key in ('release','archive_sha256','bundle_sha256','retained_approval_sha256',
        'rootfs_sha256','suite_sha256','execution_environment','kernel_release','virtual_cpu','virtual_cpus','release_acceptance')}
    replay.update(run_id=historical.RUN_ID,workload='native-transition',transition_probe=True,installer_trace_mode='seccomp-bpf')
    (dist/'historical-replay-input.json').write_text(json.dumps(replay,indent=2)+'\n')
    (dist/'historical-replay-input.json').chmod(0o644)
    args=SimpleNamespace(development=True,transition_probe=True,transition_stress=False,ordinary_installer_trace=False,
        virtual_cpu='native',suite_sha256=host.suite_digest(),expected_sha256=historical.BUNDLE_SHA256,
        previous_sha256=previous_hash,soak_seconds=120,archive_sha256=historical.ARCHIVE_SHA256)
    try:
        result.update(compare(lambda mode:execute_case(host,args,dist/'tracer-race-arm64'/('strace-query-'+mode),
            build['builds'][mode]['sha256'],mode,cpus,rootfs,dist/'sierx-offline-arm64.tar.gz',previous,data,old)))
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        result.update(result='failed',failure_type=type(error).__name__)
    finally:
        with output.open('x') as stream:stream.write(json.dumps(result,indent=2)+'\n')
        output.chmod(0o644)
    return 0 if result['result']=='cause-reproduced-and-corrected' else 1


if __name__=='__main__':
    try:code=main()
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        print('native-transition-comparison: failed ('+type(error).__name__+')',file=sys.stderr);code=1
    sys.exit(code)
