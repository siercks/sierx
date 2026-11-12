"""Replay one exact failed ARM64 bundle with current diagnostic instrumentation."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import offline

ROOT=Path(__file__).resolve().parent.parent
RUN_ID=42413538496
REVISION='aee4c402425a95a5345526c1903a1f0e1bebb087'
RELEASE={'revision':REVISION,'image':'ghcr.io/siercks/sierx@sha256:b90b17e802601ae809821d1f381ee5ec5b4fcc0136123bb586f21b65229900a4'}
ARCHIVE_SHA256='3a04f0cf152d04b06a9875ad61131af1abb61b0f67d93a1d26882f68dee971d5'
BUNDLE_SHA256='24728a1707465c11fdf3b8ed6f2ec65da9d7932b9e4269348ccbd134f74b48e9'
RETAINED_APPROVAL_SHA256='beb4c703ac072f24c9c571f592148d40684a8c60d2f669eacf994b02aacacd9c'
PROFILE,ARCH='ubuntu24','arm64'


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_input(directory,run):
    if (not isinstance(run,dict) or run.get('id')!=RUN_ID or run.get('head_sha')!=REVISION
            or run.get('path')!='.github/workflows/release.yml' or run.get('event')!='workflow_dispatch'
            or run.get('status')!='completed' or run.get('conclusion')!='failure'):
        raise ValueError('Replay requires the original failed exact release run')
    archive_hash=(directory/'sierx-offline-arm64.tar.gz.sha256').read_text().split()
    lock_hash=(directory/'sierx-offline-arm64.lock.sha256').read_text().strip()
    if not archive_hash or archive_hash[0]!=ARCHIVE_SHA256 or lock_hash!=BUNDLE_SHA256:
        raise ValueError('Replay artifact checksums differ from the original host receipt')
    if (directory/'sierx-offline-arm64').exists() or (directory/'sierx-offline-arm64').is_symlink():
        raise ValueError('Replay requires a fresh artifact extraction')
    verifier=load('replay_bundle_verifier','offline-previous.py')
    return verifier.verify(directory,{'schema':1,'revision':REVISION,'architectures':{ARCH:{
        'release':RELEASE,'archive_sha256':ARCHIVE_SHA256,'bundle_sha256':BUNDLE_SHA256}}},ARCH)


def main(transition_stress=False):
    if offline.native_arch()!=ARCH:
        raise ValueError('Historical replay requires the original native ARM64 host architecture')
    directory=ROOT/'dist'
    approval=ROOT/'deploy/ci/previous-offline-release.json'
    if offline.digest(approval)!=RETAINED_APPROVAL_SHA256:
        raise ValueError('Replay retained-release approval differs from the original run')
    retained=json.loads(approval.read_text())['architectures'][ARCH]
    bundle=verify_input(directory,json.loads((directory/'historical-run.json').read_text()))
    proof={'run_id':RUN_ID,'release':RELEASE,'archive_sha256':ARCHIVE_SHA256,
           'bundle_sha256':BUNDLE_SHA256,'retained_approval_sha256':RETAINED_APPROVAL_SHA256,
           'transition_stress':transition_stress,'transition_before_browser':transition_stress,
           'installer_trace_mode':'ordinary-ptrace' if transition_stress else 'seccomp-bpf',
           'release_acceptance':False}
    (directory/'historical-replay-input.json').write_text(json.dumps(proof,indent=2)+'\n')
    receipts=load('replay_host_receipts','offline-host-evidence.py')
    receipts.receipt(directory,PROFILE,'ghcr.io/siercks/sierx',REVISION)
    rootfs=directory/'host-fixture-ubuntu24-arm64.tar'
    rootfs_hash=rootfs.with_suffix('.tar.sha256').read_text().split()[0]
    print('offline-historical-replay: original failed ARM64 archive, lock and baseline evidence verified',flush=True)
    command = ['sudo','env','PATH='+os.environ['PATH'],'python3','-B',str(ROOT/'scripts/offline-host.py'),
        '--bundle',str(bundle),'--expected-sha256',BUNDLE_SHA256,
        '--archive',str(directory/'sierx-offline-arm64.tar.gz'),'--archive-sha256',ARCHIVE_SHA256,
        '--rootfs',str(rootfs),'--rootfs-sha256',rootfs_hash,
        '--previous-bundle',str(directory/'previous/sierx-offline-arm64'),
        '--previous-sha256',retained['bundle_sha256'],
        '--previous-evidence',str(directory/'previous/offline-acceptance-arm64.json'),
        '--report',str(directory/'historical-replay-ubuntu24-arm64.json')]
    if transition_stress:
        command.extend(('--transition-stress', '--transition-before-browser', '--ordinary-installer-trace'))
    return subprocess.run(command).returncode


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transition-stress', action='store_true')
    try:sys.exit(main(parser.parse_args().transition_stress))
    except (ValueError,OSError,TypeError,KeyError,IndexError,tarfile.TarError):
        raise SystemExit('offline-historical-replay: missing or mismatched input; no diagnostic pass') from None
