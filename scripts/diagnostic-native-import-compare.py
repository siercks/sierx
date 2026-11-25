"""One real historical import per compared tracer; no retries or acceptance."""
import argparse,json,os,re,signal,subprocess,sys
from pathlib import Path
import offline
from tracer_diagnostic import state_directory,target_user,architecture
from native_tracer_diagnostic import validate_build,expected_old_failure,expected_fixed_completion,public_case,public_build

ROOT=Path(__file__).resolve().parent.parent


def run(args):
    state=state_directory()
    if os.geteuid()!=0:raise ValueError('Owned root diagnostic namespace required')
    if {row['ifname'] for row in json.loads(subprocess.check_output(['ip','-j','link','show']))}!={'lo'}:
        raise ValueError('Comparison requires a no-NIC namespace')
    os.umask(0o077)
    os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:4]))
    build=json.loads((state/'query-build.json').read_text())
    validate_build(build)
    if build.get('arch')!=architecture() or type(build.get('owner_uid')) is not int or build['owner_uid']!=args.uid:
        raise ValueError('Compared build differs from native preparer')
    target_user(build)
    bundle=Path(args.bundle).resolve()
    data=offline.verify(bundle,args.sha256)
    if data['arch']!=architecture():raise ValueError('Historical input differs from native architecture')
    parent_hash=offline.digest(Path('/usr/bin/strace'))
    output=ROOT/'dist/historical-native-import-arm64.json'
    if output.exists():raise ValueError('Comparison output must be fresh')
    result={'suite':'offline-native-tracer-comparison-v1','release_acceptance':False,
            'historical_cause_proven':False,'arch':architecture(),'release':data['release'],
            'bundle_sha256':args.sha256,'build':public_build(build),'result':'inconclusive','cases':[]}
    stage='old'
    try:
        for mode in ('old','fixed'):
            stage=mode
            binary=state/('strace-query-'+mode)
            if binary.is_symlink() or offline.digest(binary)!=build['builds'][mode]['sha256']:
                raise ValueError('Compared binary changed after verified build')
            report_path=state/('native-'+mode+'.json')
            if report_path.exists():raise ValueError('Each actual import executes at most once')
            # Both mounts are private. No source binary or operator manager is
            # changed; each probe gets its own PID/netns/store and child lifetime.
            command=['unshare','--mount','--net','--pid','--fork','--kill-child','--mount-proc',
                '--propagation','private','sh','-eu','-c',
                'mount --bind "$1" /usr/bin/strace\nshift\nexec "$@"',
                'native-tracer-import',str(binary),sys.executable,'-B',str(ROOT/'scripts/offline-native-import.py'),
                '--probe-query',str(bundle),args.sha256,str(args.uid),str(report_path)]
            with (state/('native-'+mode+'.private.log')).open('wb') as private:
                process=subprocess.Popen(command,stdout=private,stderr=subprocess.STDOUT,start_new_session=True)
                try:code=process.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
                    raise ValueError('Bounded native import comparison timed out') from None
            if code not in {0,1} or not report_path.is_file():
                raise ValueError('Native import did not produce bounded safe evidence')
            report=json.loads(report_path.read_text())
            if (report.get('suite')!='offline-native-import-probe-v1' or report.get('release')!=data['release']
                    or report.get('bundle_sha256')!=args.sha256 or report.get('strace_sha256')!=build['builds'][mode]['sha256']
                    or report.get('release_acceptance') is not False or report.get('fresh_rootless_overlay') is not True
                    or report.get('loopback_only') is not True or report.get('installer_trace_mode')!='ordinary-ptrace'):
                raise ValueError('Native operation evidence differs from exact inputs')
            safe=public_case(report)
            result['cases'].append({'mode':mode,**safe})
            if mode=='old' and not expected_old_failure(safe):break
            if mode=='fixed':
                result['result']='cause-reproduced-and-corrected' if expected_fixed_completion(safe) else 'failed'
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        result.update(result='failed',failure_stage=stage,failure_type=type(error).__name__)
    finally:
        unchanged=offline.digest(Path('/usr/bin/strace'))==parent_hash
        result['parent_system_binary_unchanged']=unchanged
        if not unchanged:result['result']='failed'
        with output.open('x') as stream:stream.write(json.dumps(result,indent=2)+'\n')
        output.chmod(0o644)
    return 0 if result['result']=='cause-reproduced-and-corrected' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--uid',type=int,required=True)
    try:code=run(parser.parse_args())
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        output=ROOT/'dist/historical-native-import-arm64.json'
        output.parent.mkdir(exist_ok=True)
        if not output.exists():
            with output.open('x') as stream:stream.write(json.dumps({
                'suite':'offline-native-tracer-comparison-v1','release_acceptance':False,
                'historical_cause_proven':False,'result':'failed','failure_stage':'verify-inputs',
                'failure_type':type(error).__name__})+'\n')
            output.chmod(0o644)
        code=1
    sys.exit(code)
