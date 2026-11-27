"""One original import per matched tracer inside an isolated TCG guest."""
import hashlib,importlib.util,json,os,re,shutil,signal,subprocess,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
import offline
import offline_archive
import offline_guest_tracer
from native_tracer_diagnostic import validate_build,public_build,public_case,expected_old_failure,expected_fixed_completion

ROOT=Path(__file__).resolve().parent.parent
GUEST_ROOT=Path('/opt/causal')
GUEST_REPORT=GUEST_ROOT/'dist/historical-native-import-arm64.json'
GUEST_OPTIONS=GUEST_ROOT/'guest-input.json'
SCRIPTS=('diagnostic-guest-import-compare.py','diagnostic-native-import-compare.py',
    'offline-native-import.py','native_tracer_diagnostic.py','tracer_diagnostic.py',
    'offline.py','offline_archive.py','offline_host_diagnostics.py','offline_guest_tracer.py','offline_guest_podman.py','offline_import_trace.py',
    'kernel_network_evidence.py','network_observer.py','offline_apply_trace.py','offline_host_evidence.py','offline_smoke_trace.py')


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def suite_digest():
    value=hashlib.sha256()
    for name in SCRIPTS:value.update(name.encode()+b'\0'+(ROOT/'scripts'/name).read_bytes())
    return value.hexdigest()


def checked_comparison(report,build,release,bundle):
    """Accept only bounded fixed metadata, never private probe output."""
    validate_build(build)
    basic={'suite','release_acceptance','historical_cause_proven',
        'arch','release','bundle_sha256','build','result','cases','parent_system_binary_unchanged'}
    if (not isinstance(report,dict) or set(report)-{'failure_stage','failure_type'}!=basic
            or report['suite']!='offline-native-tracer-comparison-v1' or report['arch']!=build.get('arch')
            or build.get('arch') not in {'amd64','arm64'}
            or report['release_acceptance'] is not False or report['historical_cause_proven'] is not False
            or report['release']!=release or report['bundle_sha256']!=bundle
            or report['build']!=public_build(build) or type(report['parent_system_binary_unchanged']) is not bool
            or report['result'] not in {'inconclusive','cause-reproduced-and-corrected','failed'}):
        raise ValueError('Guest comparison did not produce complete exact-input evidence')
    if set(report)!=basic:
        if (report['result']!='failed' or report.get('failure_stage') not in {'old','fixed','verify-inputs'}
                or report.get('failure_type') not in {'OSError','ValueError','KeyError','TypeError',
                    'TimeoutExpired','CalledProcessError','PermissionError','FileNotFoundError'}):
            raise ValueError('Unknown private comparison failure fields')
    if report['result']!='failed' and report['parent_system_binary_unchanged'] is not True:
        raise ValueError('Changed parent binary cannot produce a passing or inconclusive result')
    cases=report['cases']
    if not isinstance(cases,list) or not (0 if report['result']=='failed' else 1)<=len(cases)<=2:
        raise ValueError('Each tracer runs at most once')
    for case,mode in zip(cases,('old','fixed')):
        if (case.get('mode')!=mode or public_case(case)!={key:value for key,value in case.items() if key!='mode'}
                or case['strace_sha256']!=build['builds'][mode]['sha256']):
            raise ValueError('Guest case includes unknown or mismatched fields')
    if report['result']=='inconclusive':
        if len(cases)!=1 or expected_old_failure(cases[0]):raise ValueError('Inconclusive case must stop before fixed')
    elif report['result']=='cause-reproduced-and-corrected' and (
            len(cases)!=2 or not expected_old_failure(cases[0]) or not expected_fixed_completion(cases[1])):
        raise ValueError('Cause claim requires real old failure and fixed completion')
    return report


def guest():
    if os.geteuid()!=0 or ROOT!=GUEST_ROOT or len(os.sched_getaffinity(0))!=4:
        raise ValueError('Comparison requires the owned four-CPU guest')
    options=json.loads(GUEST_OPTIONS.read_text())
    if (options.get('suite_sha256')!=suite_digest() or options.get('virtual_cpu')!='tcg'
            or options.get('virtual_cpus')!=4 or options.get('release_acceptance') is not False):
        raise ValueError('Guest comparison snapshot differs from host')
    state=ROOT/'dist/tracer-race-arm64'
    build=json.loads((state/'query-build.json').read_text());validate_build(build)
    os.umask(0o077)
    command=['unshare','--mount','--net','--pid','--fork','--kill-child','--mount-proc',
        '--propagation','private','sh','-eu','-c',
        'mountpoint -q /sys/kernel/tracing || mount -t tracefs tracefs /sys/kernel/tracing\nexec "$@"',
        'guest-tracer-comparison','/usr/bin/python3','-B',str(ROOT/'scripts/diagnostic-native-import-compare.py'),
        '--bundle','/opt/sierx-bundle','--sha256',options['bundle_sha256'],'--uid','1001','--guest-tcg']
    environment={**os.environ,'SIERX_TRACER_DIAGNOSTIC_STATE':str(state),
                 'SIERX_TRACER_DIAGNOSTIC_USER':'acceptance','PYTHONDONTWRITEBYTECODE':'1'}
    with (ROOT/'dist/comparison.private.log').open('wb') as private:
        process=subprocess.Popen(command,env=environment,stdout=private,stderr=subprocess.STDOUT,start_new_session=True)
        try:code=process.wait(timeout=10000)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
            raise ValueError('Guest comparison exceeded the declared bound') from None
    if code not in {0,1} or not GUEST_REPORT.is_file() or GUEST_REPORT.stat().st_size>65536:
        raise ValueError('Guest comparison has no bounded result')
    report=checked_comparison(json.loads(GUEST_REPORT.read_text()),build,options['release'],options['bundle_sha256'])
    result={'suite':'offline-guest-tracer-comparison-v1','release_acceptance':False,'historical_cause_proven':False,
        'guest_input':options,'comparison':report}
    result_path=Path('/home/acceptance/result.json')
    with result_path.open('x') as stream:stream.write(json.dumps(result,indent=2)+'\n')
    os.sync()
    print('SIERX_COMPARE_FINISHED: '+offline.digest(result_path),flush=True)
    return 0


def configure(root,host,options,build,*,source_state=None):
    args=SimpleNamespace(suite_sha256=options['suite_sha256'],expected_sha256=options['bundle_sha256'],
        previous_sha256=None,soak_seconds=120,development=True,virtual_cpu='tcg')
    host.setup(root,args)
    destination=root/GUEST_ROOT.relative_to('/')
    scripts=destination/'scripts';scripts.mkdir(parents=True)
    destination.chmod(0o755);scripts.chmod(0o755)
    for name in SCRIPTS:
        target=scripts/name;shutil.copyfile(ROOT/'scripts'/name,target);target.chmod(0o644)
    (destination/'guest-input.json').write_text(json.dumps(options)+'\n')
    state=destination/'dist/tracer-race-arm64';state.mkdir(parents=True)
    state.parent.chmod(0o700);state.chmod(0o700)
    # Only the owned diagnostic account changes across the host/guest boundary.
    # Source and binary bindings remain exact and are checked on both sides.
    guest_build={**build,'owner_uid':1001}
    (state/'query-build.json').write_text(json.dumps(guest_build)+'\n')
    (state/'query-build.json').chmod(0o600)
    source_state=source_state or ROOT/'dist/tracer-race-arm64'
    for mode in ('old','fixed'):
        source=source_state/('strace-query-'+mode)
        if source.is_symlink() or offline.digest(source)!=build['builds'][mode]['sha256']:
            raise ValueError('Prepared comparison binary changed')
        target=state/source.name;shutil.copyfile(source,target);target.chmod(0o755)
    (root/'etc/systemd/system/sierx-tracer-compare.service').write_text('''[Unit]
After=basic.target
SuccessAction=poweroff-force
FailureAction=poweroff-force
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -B /opt/causal/scripts/diagnostic-guest-import-compare.py --guest
TimeoutStartSec=10700
StandardOutput=journal+console
StandardError=journal
''')
    (root/'etc/systemd/system/sierx-tracer-compare.target').write_text('''[Unit]
Requires=basic.target sierx-tracer-compare.service
After=basic.target
''')


def host_run():
    replay=load('causal_original_inputs','offline-historical-replay.py')
    host=load('causal_guest_launcher','offline-host.py')
    if os.geteuid()!=0 or offline.native_arch()!='arm64':raise ValueError('Native ARM64 root launcher required')
    dist=ROOT/'dist';output=dist/'historical-guest-import-arm64.json'
    if output.exists():raise ValueError('Comparison output must be fresh')
    approval=ROOT/'deploy/ci/previous-offline-release.json'
    if offline.digest(approval)!=replay.RETAINED_APPROVAL_SHA256:raise ValueError('Retained approval changed')
    replay.verify_input(dist,json.loads((dist/'historical-run.json').read_text()))
    build=json.loads((dist/'tracer-race-arm64/query-build.json').read_text());validate_build(build)
    if build.get('arch')!='arm64':raise ValueError('Hosted comparison requires native ARM64 controls')
    rootfs=dist/'host-fixture-ubuntu24-arm64.tar'
    rootfs_sha=rootfs.with_suffix('.tar.sha256').read_text().split()[0]
    host.verify_rootfs(rootfs,rootfs_sha)
    proof={'run_id':replay.RUN_ID,'release':replay.RELEASE,'archive_sha256':replay.ARCHIVE_SHA256,
        'bundle_sha256':replay.BUNDLE_SHA256,'retained_approval_sha256':replay.RETAINED_APPROVAL_SHA256,
        'execution_environment':'guest-tcg','arch':'arm64','virtual_cpus':4,'tcg_thread_mode':'multi',
        'suite_sha256':suite_digest(),'rootfs_sha256':rootfs_sha,'release_acceptance':False}
    (dist/'historical-replay-input.json').write_text(json.dumps(proof,indent=2)+'\n')
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='sierx-guest-causal-') as temporary:
        scratch=Path(temporary);root=scratch/'root';root.mkdir()
        host.run('tar','-xf',rootfs,'-C',root,'--no-same-owner');root.chmod(0o755)
        offline_guest_tracer.load_receipt(root/offline_guest_tracer.RECEIPT.relative_to('/'),
                                          root/offline_guest_tracer.BINARY.relative_to('/'))
        kernels=sorted((root/'boot').glob('vmlinuz-*'))
        if len(kernels)!=1:raise ValueError('Guest requires one exact kernel')
        kernel=kernels[0];version=kernel.name.removeprefix('vmlinuz-')
        initrd=root/'boot'/('initrd.img-'+version)
        if not initrd.is_file():raise ValueError('Guest requires its matching initramfs')
        options={**proof,'virtual_cpu':'tcg','kernel_sha256':offline.digest(kernel)}
        configure(root,host,options,build)
        staged=root/'opt/.delivery-input'
        delivered=offline_archive.unpack(dist/'sierx-offline-arm64.tar.gz',staged,
            replay.ARCHIVE_SHA256,replay.BUNDLE_SHA256,'arm64')
        delivered.rename(root/'opt/sierx-bundle');staged.rmdir()
        disk=scratch/'guest.ext4'
        with disk.open('wb') as stream:stream.truncate(24*1024**3)
        host.run('mkfs.ext4','-q','-F','-i','65536','-d',root,disk)
        boot_kernel,boot_initrd=scratch/'kernel',scratch/'initrd'
        shutil.copyfile(kernel,boot_kernel);shutil.copyfile(initrd,boot_initrd)
        if root.resolve().parent!=scratch.resolve():raise ValueError('Owned guest cleanup escaped scratch')
        shutil.rmtree(root)
        serial=scratch/'serial.private.log'
        command=host.qemu_command('arm64','tcg',disk,boot_kernel,boot_initrd,serial)
        command[-1]=command[-1].replace('systemd.unit=sierx-acceptance.target','systemd.unit=sierx-tracer-compare.target')
        process=None;completed=None
        with (dist/'guest-compare.private.log').open('wb') as private:
            try:
                process=subprocess.Popen(command,stdout=private,stderr=subprocess.STDOUT,start_new_session=True)
                deadline=time.monotonic()+10800
                while process.poll() is None and time.monotonic()<deadline:
                    if serial.exists():
                        text=serial.read_text(errors='replace')
                        markers=re.findall(r'SIERX_COMPARE_FINISHED: ([a-f0-9]{64})',text)
                        if markers:
                            if len(markers)!=1:raise ValueError('Ambiguous guest completion')
                            completed=markers[0];break
                    time.sleep(1)
                if completed is None and serial.exists():
                    markers=re.findall(r'SIERX_COMPARE_FINISHED: ([a-f0-9]{64})',serial.read_text(errors='replace'))
                    if len(markers)==1:completed=markers[0]
                if completed is None:raise ValueError('Guest stopped or exceeded bound without complete evidence')
            finally:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=30)
        host.recover_disk(disk)
        raw=host.disk_file(disk,'result.json')
        if len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=completed:
            raise ValueError('Guest report differs from synced completion')
        value=json.loads(raw)
        if (set(value)!={'suite','release_acceptance','historical_cause_proven','guest_input','comparison'}
                or value['suite']!='offline-guest-tracer-comparison-v1' or value['guest_input']!=options
                or value['release_acceptance'] is not False or value['historical_cause_proven'] is not False):
            raise ValueError('Guest result differs from exact input snapshot')
        checked_comparison(value['comparison'],build,replay.RELEASE,replay.BUNDLE_SHA256)
        with output.open('x') as stream:stream.write(json.dumps(value,indent=2)+'\n')
        output.chmod(0o644)
        return 0 if value['comparison']['result']=='cause-reproduced-and-corrected' else 1


if __name__=='__main__':
    try:code=guest() if sys.argv[1:]==['--guest'] else host_run()
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        # Fixed class only. Private guest logs and exception text stay local.
        print('guest-import-comparison: failed ('+type(error).__name__+')',file=sys.stderr)
        code=1
    sys.exit(code)
