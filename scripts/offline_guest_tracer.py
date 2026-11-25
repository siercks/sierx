"""Pinned termination correction for the disposable acceptance guest observer."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

VERSION = '6.8'
FIX = '3a4f0c7c3969ec6e25e729ed6b36a0391764a375'
ARCHIVE_SHA256 = 'ba6950a96824cdf93a584fa04f0a733896d2a6bc5f0ad9ffe505d9b41e970149'
PATCH_SHA256 = 'f46bb4fa62dd8b039ab27c8d74c9fdb7ed816a3b6814f0fa2448dd75b304f1f9'
ORIGINAL_SHA256 = '21fe0b653612b9354ff783a9ca1643d39682d85fd38bf32a14b09cdea41febd1'
FIXED_SHA256 = 'c54b2296cfffb9dc745fc99cdb54ca5588c8be3a57adde57d7600d7fe27497e6'
# The bundled UAPI keeps the pinned decoder build independent of newer host
# development headers (Rocky 10 changed the PTP reserved-array size).
FLAGS = ['--enable-mpers=no','--with-libunwind=no','--with-libdw=no','--with-libiberty=no',
         '--enable-bundled=yes']
RECEIPT = Path('/usr/share/sierx-offline/tracer.json')
BINARY = Path('/usr/bin/strace')
PINS = {'version':VERSION,'upstream_commit':FIX,'source_archive_sha256':ARCHIVE_SHA256,
        'patch_sha256':PATCH_SHA256,'source_sha256':FIXED_SHA256,'configure_flags':FLAGS}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decode_patch(packet):
    value = json.loads(Path(packet).read_text())
    if (not isinstance(value,dict) or set(value) != {'upstream_commit','patch_lines'}
            or value['upstream_commit'] != FIX or not isinstance(value['patch_lines'],list)
            or not all(isinstance(line,str) for line in value['patch_lines'])):
        raise ValueError('Invalid pinned observer correction packet')
    raw = ''.join(value['patch_lines']).encode()
    if hashlib.sha256(raw).hexdigest() != PATCH_SHA256:
        raise ValueError('Observer correction bytes differ from the verified backport')
    return raw


def validate_receipt(value, binary=None):
    if (not isinstance(value,dict) or set(value) != set(PINS) | {'binary_sha256'}
            or any(value.get(key) != expected for key,expected in PINS.items())
            or not isinstance(value.get('binary_sha256'),str)
            or not re.fullmatch(r'[a-f0-9]{64}',value['binary_sha256'])):
        raise ValueError('Missing exact corrected acceptance observer identity')
    if binary is not None and digest(binary) != value['binary_sha256']:
        raise ValueError('Acceptance observer bytes differ from their pinned build receipt')
    return value


def load_receipt(receipt=RECEIPT, binary=BINARY):
    return validate_receipt(json.loads(Path(receipt).read_text()),binary)


def build(archive, packet, output):
    """Build only in owned scratch; install nothing on the invoking system."""
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError('Acceptance observer archive differs from the verified source')
    patch = decode_patch(packet)
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sierx-guest-tracer-') as temporary:
        scratch = Path(temporary)
        # The archive has already matched the immutable official-source hash.
        # GNU tar also works in the existing Debian builder's Python 3.11,
        # which predates tarfile's extraction-filter keyword.
        subprocess.run(['tar','-xJf',str(Path(archive).resolve()),'-C',str(scratch),
                        '--no-same-owner','--no-same-permissions'],
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=30)
        source = scratch/'strace-6.8'
        if digest(source/'src/strace.c') != ORIGINAL_SHA256:
            raise ValueError('Original observer source does not match the verified control')
        patch_file = scratch/'termination-fix.patch'
        patch_file.write_bytes(patch)
        build_directory = scratch/'build'
        build_directory.mkdir()
        with (output/'build.private.log').open('wb') as log:
            subprocess.run(['patch','--fuzz=0','-p1','--input',str(patch_file)],
                cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=15)
            if digest(source/'src/strace.c') != FIXED_SHA256:
                raise ValueError('Corrected observer source differs from the tested backport')
            subprocess.run([str(source/'configure'),*FLAGS],cwd=build_directory,
                stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            subprocess.run(['make','-j4'],cwd=build_directory,
                stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
        binary = build_directory/'src/strace'
        if not subprocess.check_output([str(binary),'-V'],text=True).splitlines()[0].endswith('version '+VERSION):
            raise ValueError('Unexpected acceptance observer version')
        receipt = {**PINS,'binary_sha256':digest(binary)}
        shutil.copyfile(binary,output/'strace')
        (output/'strace').chmod(0o755)
        validate_receipt(receipt,output/'strace')
        (output/'tracer.json').write_text(json.dumps(receipt,sort_keys=True)+'\n')
        return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True)
    parser.add_argument('--patch',required=True)
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.archive,args.patch,args.output),sort_keys=True))
