"""Stage a verified local-only manifest for secret-free PR delivery acceptance."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from local_candidate import identity
import offline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--repository',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9._:/-]+',args.repository):
        raise ValueError('Invalid local candidate repository')
    revision=offline.command('git','rev-parse','HEAD',cwd=offline.ROOT)
    if offline.command('git','status','--porcelain',cwd=offline.ROOT):
        raise ValueError('Local candidates require a clean committed checkout')
    data=identity(args.archive)
    if data['arch']!=offline.native_arch() or data['revision']!=revision:
        raise ValueError('Local candidate differs from native committed source')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'image':args.repository+'@'+data['manifest'],'revision':revision},indent=2)+'\n')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,subprocess.SubprocessError):
        raise SystemExit('offline-local-candidate: invalid local candidate; no registry publication attempted')
