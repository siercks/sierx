"""Build matched disposable tracer controls; never install system binaries."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from tracer_diagnostic import state_directory, FIXTURES, ARCHIVE_SHA256, PATCH_SHA256, SOURCE_SHA256, architecture
root = state_directory()
assert os.getuid() != 0
assert os.environ.get('ARCH', architecture()) == architecture()
os.umask(0o077)
inputs = json.loads((FIXTURES/'inputs.json').read_text())
archive = root/'strace-6.8.tar.xz'
packet = json.loads((FIXTURES/'termination-fix.json').read_text())
assert packet['upstream_commit'] == inputs['upstream_commit']
patch_bytes = ''.join(packet['patch_lines']).encode()
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert digest(archive) == inputs['source_archive_sha256'] == ARCHIVE_SHA256
assert hashlib.sha256(patch_bytes).hexdigest() == inputs['patch_sha256'] == PATCH_SHA256
flags = ['--enable-mpers=no', '--with-libunwind=no', '--with-libdw=no', '--with-libiberty=no']
results = {}
with tempfile.TemporaryDirectory(prefix='sierx-strace-control-') as temporary:
    scratch = Path(temporary)
    patch = scratch/'termination-fix.patch'
    patch.write_bytes(patch_bytes)
    with tarfile.open(archive) as stream:
        stream.extractall(scratch, filter='data')
    source = scratch/'strace-6.8'
    original = (source/'src/strace.c').read_bytes()
    for mode in ('old', 'fixed'):
        if mode == 'fixed':
            with (root/'patch.log').open('wb') as log:
                subprocess.run(['patch', '--fuzz=0', '-p1', '--input', str(patch)],
                    cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=15)
            assert (source/'src/strace.c').read_bytes() != original
        build = scratch/('build-'+mode)
        build.mkdir()
        print('control build: '+mode+' configure', flush=True)
        with (root/(mode+'-configure.log')).open('wb') as log:
            subprocess.run([str(source/'configure'), *flags], cwd=build,
                stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        print('control build: '+mode+' compile', flush=True)
        with (root/(mode+'-build.log')).open('wb') as log:
            subprocess.run(['make', '-j4'], cwd=build,
                stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
        binary = build/'src/strace'
        assert digest(source/'src/strace.c') == SOURCE_SHA256[mode]
        version = subprocess.check_output([str(binary), '-V'], text=True).splitlines()[0]
        assert version.endswith('version 6.8')
        destination = root/('strace-'+mode)
        shutil.copyfile(binary, destination)
        destination.chmod(0o755)
        results[mode] = {'sha256':digest(destination), 'version':'6.8',
                        'source_sha256':digest(source/'src/strace.c')}
        print('control build: '+mode+' complete', flush=True)
proof = {**inputs, 'configure_flags':flags, 'builds':results,
         'system_binary_replaced':False, 'release_acceptance':False,
         'owner_uid':os.getuid(), 'arch':architecture()}
(root/'build.json').write_text(json.dumps(proof, indent=2)+'\n')
print(json.dumps(proof, sort_keys=True), flush=True)
