"""Sanitized input receipts, complete host reports and a skip-aware CI aggregate."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import offline
import offline_host_evidence as evidence

ROOT=Path(__file__).resolve().parent.parent
PROFILES=(('ubuntu24','amd64'),('ubuntu24','arm64'),('rocky10','amd64'))
spec=importlib.util.spec_from_file_location('host_suite',ROOT/'scripts/offline-host.py')
host=importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def required(event,staged=False):
    if staged or 'pull_request' not in event:return True
    base=event['pull_request']['base']['sha']
    if not re.fullmatch(r'[a-f0-9]{40}',base):raise ValueError('Invalid PR base revision')
    names=offline.command('git','diff','--name-only',base,'HEAD',cwd=ROOT).splitlines()
    return any(not (name.endswith('.md') and (name.startswith('docs/') or name in {'README.md','AGENTS.md'})) for name in names)


def receipt(directory,profile,repository,revision):
    arch=offline.native_arch()
    if (profile,arch) not in PROFILES:raise ValueError('Unsupported native host profile')
    bundle=directory/('sierx-offline-'+arch)
    expected=offline.digest(bundle/'bundle.lock.json')
    data=offline.verify(bundle,expected)
    if (data['release']['revision']!=revision
            or not re.fullmatch(re.escape(repository)+r'@sha256:[a-f0-9]{64}',data['release']['image'])):
        raise ValueError('Host inputs differ from the committed native candidate')
    rootfs=directory/f'host-fixture-{profile}-{arch}.tar'
    checksum=rootfs.with_suffix(rootfs.suffix+'.sha256').read_text().split()[0]
    if not re.fullmatch(r'[a-f0-9]{64}',checksum):raise ValueError('Missing prepared OS checksum')
    result={'schema':1,'profile':profile,'arch':arch,'release':data['release'],
            'bundle_sha256':expected,'rootfs_sha256':checksum,'suite_sha256':host.suite_digest(),
            'archive_sha256':offline.digest(directory/f'sierx-offline-{arch}.tar.gz')}
    (directory/f'host-input-{profile}-{arch}.json').write_text(json.dumps(result,indent=2)+'\n')


def verify(directory,repository,revision,previous=None):
    previous=previous or json.loads((ROOT/'deploy/ci/previous-offline-release.json').read_text())
    suite=host.suite_digest()
    for profile,arch in PROFILES:
        inputs=json.loads((directory/f'host-input-{profile}-{arch}.json').read_text())
        report=json.loads((directory/f'host-acceptance-{profile}-{arch}.json').read_text())
        if (inputs.get('schema')!=1 or inputs.get('profile')!=profile or inputs.get('arch')!=arch
                or inputs.get('suite_sha256')!=suite or inputs.get('release',{}).get('revision')!=revision
                or not re.fullmatch(re.escape(repository)+r'@sha256:[a-f0-9]{64}',inputs.get('release',{}).get('image',''))
                or not re.fullmatch(r'[a-f0-9]{64}',inputs.get('bundle_sha256',''))
                or not re.fullmatch(r'[a-f0-9]{64}',inputs.get('rootfs_sha256',''))
                or not re.fullmatch(r'[a-f0-9]{64}',inputs.get('archive_sha256',''))
                or report.get('rootfs_sha256')!=inputs['rootfs_sha256']
                or report.get('archive_sha256')!=inputs['archive_sha256']):
            raise ValueError('Host input receipt is missing, stale or mismatched for '+profile+'/'+arch)
        expected={'arch':arch,'release':inputs['release']}
        evidence.validate_closeout(report,expected,inputs['bundle_sha256'],suite)
        if not re.fullmatch('ubuntu-24\\.04' if profile=='ubuntu24' else 'rocky-10(?:\\.[0-9]+)?',report['profile']):
            raise ValueError('Prepared OS profile differs from required native coverage')
        retained=previous['architectures'][arch]
        release=report['scenarios']['two_release']
        if release['previous']!=retained['release'] or release['previous_bundle_sha256']!=retained['bundle_sha256']:
            raise ValueError('Two-release proof used a different retained approval')


def aggregate(scope_result,is_required,test_result):
    if scope_result!='success' or is_required not in {'true','false'}:
        raise ValueError('Offline delivery relevance could not be established')
    if test_result!=('success' if is_required=='true' else 'skipped'):
        raise ValueError('Required native host coverage failed, was cancelled or was unexpectedly skipped')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('scope','receipt','verify','aggregate'))
    parser.add_argument('--directory',type=Path,default=Path('dist'))
    parser.add_argument('--profile',default=os.environ.get('PROFILE','ubuntu24'))
    parser.add_argument('--repository',default=os.environ.get('SIERX_RELEASE_REPOSITORY','ghcr.io/siercks/sierx'))
    args=parser.parse_args()
    try:
        if args.operation=='aggregate':
            try:
                aggregate(os.environ.get('SCOPE_RESULT'),os.environ.get('HOST_REQUIRED'),os.environ.get('HOST_RESULT'))
            except ValueError as error:
                # These are fixed coverage/status diagnostics, never report
                # contents. Distinguish a failed host job from a stale receipt,
                # even when no candidate/receipts are available to inspect.
                raise SystemExit('offline-host-evidence: '+str(error)) from None
        revision=None
        if args.operation in {'receipt','verify'} or (args.operation=='aggregate' and os.environ['HOST_REQUIRED']=='true'):
            revision=offline.command('git','rev-parse','HEAD',cwd=ROOT)
        if args.operation=='scope':
            event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
            result=str(required(event,os.environ.get('SIERX_STAGED')=='true')).lower()
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write('required='+result+'\n')
        elif args.operation=='receipt':receipt(args.directory,args.profile,args.repository,revision)
        elif args.operation=='verify':verify(args.directory,args.repository,revision)
        else:
            if os.environ['HOST_REQUIRED']=='true':verify(args.directory,args.repository,revision)
        if args.operation=='aggregate' and os.environ['HOST_REQUIRED']=='false':
            print('offline-host-evidence: documentation-only change; host coverage not required')
        else:
            print('offline-host-evidence: required native profile coverage verified' if args.operation in {'verify','aggregate'} else 'offline-host-evidence: '+args.operation+' recorded')
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError):
        raise SystemExit('offline-host-evidence: incomplete or mismatched coverage; no passing closeout claim')
