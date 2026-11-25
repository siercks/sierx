"""Build matched query-observed controls in owned scratch; install nothing."""
import hashlib,json,os,shutil,subprocess,tarfile,tempfile
from pathlib import Path
from tracer_diagnostic import state_directory,FIXTURES,ARCHIVE_SHA256,PATCH_SHA256,SOURCE_SHA256,architecture
from native_tracer_diagnostic import observe_queries,OBSERVATION_SHA256,validate_build

root=state_directory()
assert os.getuid()!=0
os.umask(0o077)
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
archive=root/'strace-6.8.tar.xz'
assert digest(archive)==ARCHIVE_SHA256
packet=json.loads((FIXTURES/'termination-fix.json').read_text())
patch_bytes=''.join(packet['patch_lines']).encode()
assert hashlib.sha256(patch_bytes).hexdigest()==PATCH_SHA256
flags=['--enable-mpers=no','--with-libunwind=no','--with-libdw=no','--with-libiberty=no']
rows={}
with tempfile.TemporaryDirectory(prefix='sierx-observed-native-tracer-') as temporary:
    scratch=Path(temporary)
    with tarfile.open(archive) as stream:stream.extractall(scratch,filter='data')
    source=scratch/'strace-6.8'
    original=(source/'src/strace.c').read_bytes()
    assert hashlib.sha256(original).hexdigest()==SOURCE_SHA256['old']
    patch=scratch/'termination-fix.patch';patch.write_bytes(patch_bytes)
    for mode in ('old','fixed'):
        (source/'src/strace.c').write_bytes(original)
        with (root/('query-'+mode+'.private.log')).open('wb') as log:
            if mode=='fixed':
                subprocess.run(['patch','--fuzz=0','-p1','--input',str(patch)],cwd=source,
                    stdout=log,stderr=subprocess.STDOUT,check=True,timeout=15)
            base=(source/'src/strace.c').read_bytes()
            observed=observe_queries(base,mode)
            (source/'src/strace.c').write_bytes(observed)
            build=scratch/('build-'+mode);build.mkdir()
            subprocess.run([str(source/'configure'),*flags],cwd=build,
                stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            subprocess.run(['make','-j4'],cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
        binary=build/'src/strace'
        assert subprocess.check_output([str(binary),'-V'],text=True).splitlines()[0].endswith('version 6.8')
        destination=root/('strace-query-'+mode)
        shutil.copyfile(binary,destination);destination.chmod(0o755)
        rows[mode]={'sha256':digest(destination),'base_source_sha256':SOURCE_SHA256[mode],
                    'observed_source_sha256':hashlib.sha256(observed).hexdigest(),'version':'6.8'}
proof={'source_archive_sha256':ARCHIVE_SHA256,'patch_sha256':PATCH_SHA256,
       'observation_sha256':OBSERVATION_SHA256,'configure_flags':flags,'builds':rows,
       'owner_uid':os.getuid(),'arch':architecture(),'release_acceptance':False}
validate_build(proof)
(root/'query-build.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,sort_keys=True))
