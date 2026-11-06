"""Verify/extract the explicitly retained approved release, before isolation."""
import argparse
import json
from pathlib import Path
import re
import tarfile
import offline


def verify(directory, fixture, arch):
    if fixture.get('schema') != 1 or arch not in fixture.get('architectures',{}):
        raise ValueError('Invalid retained release approval')
    expected=fixture['architectures'][arch]
    if (not re.fullmatch(r'[a-f0-9]{40}',fixture.get('revision',''))
            or expected.get('release',{}).get('revision')!=fixture['revision']):
        raise ValueError('Retained release identity mismatch')
    archive=directory/('sierx-offline-'+arch+'.tar.gz')
    if offline.digest(archive)!=expected['archive_sha256']:
        raise ValueError('Retained release archive differs from the explicit approval')
    stem='sierx-offline-'+arch
    target=directory/stem
    if target.is_symlink():
        raise ValueError('Retained release destination must not be a symbolic link')
    with tarfile.open(archive) as stream:
        for entry in stream.getmembers():
            if (not (entry.isdir() or entry.isfile()) or not Path(entry.name).parts or Path(entry.name).parts[0]!=stem
                    or entry.name.startswith('/') or '..' in Path(entry.name).parts):
                raise ValueError('Invalid retained release archive path/type')
        if not target.exists():
            stream.extractall(directory,filter='data')
    data=offline.verify(target,expected['bundle_sha256'],arch)
    if data['release']!=expected['release']:
        raise ValueError('Retained approved release identity mismatch')
    report=json.loads((directory/('offline-acceptance-'+arch+'.json')).read_text())
    offline.verify_evidence(data,expected['bundle_sha256'],report)
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,default=Path('deploy/ci/previous-offline-release.json'))
    args=parser.parse_args()
    try:
        verify(args.directory,json.loads(args.fixture.read_text()),offline.native_arch())
        print('offline-previous: explicitly retained native release and matching approval evidence verified')
    except (ValueError,OSError,KeyError,tarfile.TarError):
        raise SystemExit('offline-previous: retained approved release is missing or invalid')
