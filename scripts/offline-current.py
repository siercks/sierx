"""Unpack the current run's baseline-tested candidate for isolated host tests."""
import importlib.util
import json
from pathlib import Path
import offline

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('retained',ROOT/'scripts/offline-previous.py')
retained=importlib.util.module_from_spec(spec)
spec.loader.exec_module(retained)


def main():
    directory=ROOT/'dist'
    arch=offline.native_arch()
    revision=offline.command('git','rev-parse','HEAD',cwd=ROOT)
    report=json.loads((directory/f'offline-acceptance-{arch}.json').read_text())
    if report.get('release',{}).get('revision')!=revision:
        raise ValueError('Candidate artifact does not belong to the checked-out revision')
    approval={'schema':1,'revision':revision,'architectures':{arch:{'release':report['release'],
        'bundle_sha256':(directory/f'sierx-offline-{arch}.lock.sha256').read_text().strip(),
        'archive_sha256':(directory/f'sierx-offline-{arch}.tar.gz.sha256').read_text().split()[0]}}}
    retained.verify(directory,approval,arch)
    print('offline-current: current native artifact and baseline evidence verified before host acceptance')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError):raise SystemExit('offline-current: missing or mismatched current candidate')
