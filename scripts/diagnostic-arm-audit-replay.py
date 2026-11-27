"""Replay the exact failed ARM64 audit delivery in a fresh no-NIC VM; never promotion."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import offline
import offline_host_diagnostics as diagnostics

ROOT=Path(__file__).resolve().parent.parent
RUN_ID=46019157095
REVISION='015813a402fd335e012c0fab06183fd61bc64f1f'
RELEASE={'revision':REVISION,'image':'ghcr.io/siercks/sierx@sha256:81e6f7816abd733b1c8343b14196a1ccdded44d390b3dd3cf6343ad5c867b230'}
ARCHIVE_SHA256='157a3d7568a3ba35e6422400802ed460de7667ae6b3ad9c1482086b1e8acb6b9'
BUNDLE_SHA256='40cc751a357211a82d9050000b6d83163df477072aeed3a690f9972c70911ea1'
RETAINED_APPROVAL_SHA256='beb4c703ac072f24c9c571f592148d40684a8c60d2f669eacf994b02aacacd9c'
PROFILE,ARCH='ubuntu24','arm64'
REPORT='arm-audit-replay-ubuntu24-arm64.json'


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def verify_input(directory,run):
    if (not isinstance(run,dict) or run.get('id')!=RUN_ID or run.get('head_sha')!=REVISION
            or run.get('path')!='.github/workflows/release.yml' or run.get('event')!='workflow_dispatch'
            or run.get('status')!='completed' or run.get('conclusion')!='failure'):
        raise ValueError('ARM64 audit replay requires the exact failed staged release')
    archive=(directory/'sierx-offline-arm64.tar.gz.sha256').read_text().split()
    lock=(directory/'sierx-offline-arm64.lock.sha256').read_text().strip()
    if not archive or archive[0]!=ARCHIVE_SHA256 or lock!=BUNDLE_SHA256:
        raise ValueError('ARM64 audit replay checksums differ from the original failed receipt')
    target=directory/'sierx-offline-arm64'
    if target.exists() or target.is_symlink():
        raise ValueError('ARM64 audit replay requires a fresh extraction')
    verifier=load('arm_audit_replay_bundle','offline-previous.py')
    return verifier.verify(directory,{'schema':1,'revision':REVISION,'architectures':{ARCH:{
        'release':RELEASE,'archive_sha256':ARCHIVE_SHA256,'bundle_sha256':BUNDLE_SHA256}}},ARCH)


def vm_command(directory,bundle,retained,rootfs_hash):
    if not re.fullmatch('[a-f0-9]{64}',rootfs_hash):
        raise ValueError('Invalid prepared ARM64 audit OS checksum')
    return ['sudo','env','PATH='+os.environ['PATH'],'python3','-B',str(ROOT/'scripts/offline-host.py'),
        '--bundle',str(bundle),'--expected-sha256',BUNDLE_SHA256,
        '--archive',str(directory/'sierx-offline-arm64.tar.gz'),'--archive-sha256',ARCHIVE_SHA256,
        '--rootfs',str(directory/'host-fixture-ubuntu24-arm64.tar'),'--rootfs-sha256',rootfs_hash,
        '--previous-bundle',str(directory/'previous/sierx-offline-arm64'),
        '--previous-sha256',retained['bundle_sha256'],
        '--previous-evidence',str(directory/'previous/offline-acceptance-arm64.json'),
        '--report',str(directory/REPORT),'--diagnostic-report']


def source_revision():
    revision=os.environ.get('GITHUB_SHA','')
    if (not re.fullmatch('[a-f0-9]{40}',revision)
            or offline.command('git','rev-parse','HEAD',cwd=ROOT)!=revision
            or offline.command('git','status','--porcelain',cwd=ROOT)):
        raise ValueError('Diagnostic requires exact clean committed source')
    return revision


def main():
    if offline.native_arch()!=ARCH:
        raise ValueError('ARM64 audit replay requires native Linux ARM64')
    revision=source_revision()
    directory=ROOT/'dist'
    approval=ROOT/'deploy/ci/previous-offline-release.json'
    if offline.digest(approval)!=RETAINED_APPROVAL_SHA256:
        raise ValueError('ARM64 audit retained approval differs from the original run')
    bundle=verify_input(directory,json.loads((directory/'arm-audit-original-run.json').read_text()))
    retained=json.loads(approval.read_text())['architectures'][ARCH]
    receipts=load('arm_audit_replay_receipts','offline-host-evidence.py')
    receipts.receipt(directory,PROFILE,'ghcr.io/siercks/sierx',REVISION)
    rootfs=directory/'host-fixture-ubuntu24-arm64.tar'
    rootfs_hash=rootfs.with_suffix('.tar.sha256').read_text().split()[0]
    proof={'run_id':RUN_ID,'release':RELEASE,'archive_sha256':ARCHIVE_SHA256,
        'bundle_sha256':BUNDLE_SHA256,'retained_approval_sha256':RETAINED_APPROVAL_SHA256,
        'diagnostic_revision':revision,'profile':PROFILE,'arch':ARCH,'fresh_prepared_os':True,
        'workload':'all-normal-scenarios-and-independent-audit','release_acceptance':False}
    (directory/'arm-audit-replay-input.json').write_text(json.dumps(proof,indent=2)+'\n')
    return subprocess.run(vm_command(directory,bundle,retained,rootfs_hash)).returncode


def package():
    revision=source_revision()
    directory=ROOT/'dist';directory.mkdir(exist_ok=True)
    result={'suite':'arm-audit-replay-diagnostic-v1','revision':revision,'release_acceptance':False}
    for key,name in (('replay_input','arm-audit-replay-input.json'),
                     ('input_receipt','host-input-ubuntu24-arm64.json'),
                     ('host_report',REPORT),('failure',Path(REPORT).with_suffix('.failure.json').name),
                     ('preparation_failure','host-preparation-failure.json')):
        path=directory/name
        if not path.exists():continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size>1024*1024:
            raise ValueError('Invalid diagnostic evidence file')
        value=json.loads(path.read_text())
        if key=='host_report':
            if value.get('release_acceptance') is not False:
                raise ValueError('Diagnostic raw report must reject promotion')
        elif key=='failure':value=diagnostics.sanitize_failure(value)
        elif key=='preparation_failure':
            value=diagnostics.sanitize_preparation_failure(value)
            if value is None:continue
        result[key]=value
    (directory/'arm-audit-diagnostic-arm64.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',action='store_true')
    args=parser.parse_args()
    try:sys.exit(package() if args.package else main())
    except (ValueError,OSError,TypeError,KeyError,IndexError,tarfile.TarError,subprocess.SubprocessError):
        raise SystemExit('arm-audit-replay: failed or mismatched input; no diagnostic acceptance') from None
