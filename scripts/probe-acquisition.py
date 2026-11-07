"""Native no-NIC acquisition diagnostic; never produces release acceptance.

Runs only within probe-acquisition.sh's fresh network namespace as the original
unprivileged user. All stores/certificates are disposable synthetic fixtures.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

import offline_host_diagnostics as diagnostics

SCRIPT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('registry_probe', SCRIPT/'offline-local-registry.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.report.unlink(missing_ok=True)
    args.report.with_suffix('.failure.json').unlink(missing_ok=True)
    phase_name = 'acquisition-prepare'

    def phase(name):
        nonlocal phase_name
        if name not in diagnostics.FAILURE_PHASES:
            raise ValueError('Unknown diagnostic phase')
        phase_name = name
        print('acquisition diagnostic: '+name, flush=True)

    with tempfile.TemporaryDirectory(prefix='sierx-acquisition-') as temporary:
        scratch = Path(temporary)
        private = scratch/'commands.private.log'

        def run(*command, env=None):
            with private.open('ab') as log:
                result = subprocess.run(list(map(str, command)), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
                log.write(result.stderr)
            if result.returncode:
                error = RuntimeError('Synthetic acquisition command failed')
                error.fixture_exit_code = result.returncode
                detail = diagnostics.guest_command_failure(command, result.stderr[-8192:])
                error.fixture_command = detail.get('guest_command')
                error.fixture_command_detail = detail.get('guest_command_detail')
                raise error
            return result.stdout.decode().strip()

        try:
            if os.geteuid() == 0:
                raise ValueError('Diagnostic must run as an unprivileged user')
            if {entry['ifname'] for entry in json.loads(run('ip','-j','link','show'))} != {'lo'}:
                raise ValueError('Diagnostic requires its fresh no-NIC namespace')
            arch = {'x86_64':'amd64','aarch64':'arm64'}[platform.machine()]
            with tarfile.open(args.archive) as archive:
                index = json.load(archive.extractfile('index.json'))
                manifest_digest = index['manifests'][0]['digest']
                manifest = json.load(archive.extractfile('blobs/sha256/'+manifest_digest[7:]))
                config_digest = manifest['config']['digest']
                config_bytes = archive.extractfile('blobs/sha256/'+config_digest[7:]).read()
                config = json.loads(config_bytes)
                if (hashlib.sha256(config_bytes).hexdigest() != config_digest[7:]
                        or config['architecture'] != arch or config['os'] != 'linux'
                        or config['config']['Labels']['org.opencontainers.image.revision'] != args.revision):
                    raise ValueError('Diagnostic archive identity differs')
            bundle = scratch/'bundle'
            (bundle/'images').mkdir(parents=True)
            shutil.copyfile(args.archive, bundle/'images/app.tar')
            home = scratch/'fixture'
            tls = home/'.config/sierx/tls'
            tls.mkdir(parents=True)
            ca = home/'fixture-ca'
            ca.mkdir()
            run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                '-keyout',ca/'ca.key','-out',ca/'ca.crt','-subj','/CN=Sierx fixture CA',
                '-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
            run('openssl','req','-new','-newkey','rsa:2048','-nodes','-keyout',tls/'server.key',
                '-out',ca/'server.csr','-subj','/CN=localhost')
            (ca/'server.ext').write_text('basicConstraints=critical,CA:FALSE\n'
                'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n'
                'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1\n')
            run('openssl','x509','-req','-in',ca/'server.csr','-CA',ca/'ca.crt','-CAkey',ca/'ca.key',
                '-CAcreateserial','-out',tls/'server.crt','-days','1','-extfile',ca/'server.ext')
            runtime = scratch/'runtime'
            runtime.mkdir(mode=0o700)
            env = {**os.environ, 'XDG_RUNTIME_DIR':str(runtime), 'SSL_CERT_FILE':str(ca/'ca.crt')}
            result = registry.main(bundle, {'images':{'app':{'id':config_digest}},
                'release':{'revision':args.revision}}, env, run, phase, fixture_home=home)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({'suite':'acquisition-diagnostic-v1',
                'release_acceptance':False,'arch':arch,'revision':args.revision,
                'archive_sha256':hashlib.sha256(args.archive.read_bytes()).hexdigest(), **result}, indent=2)+'\n')
            print('acquisition diagnostic: passed; no release acceptance issued', flush=True)
        except Exception as error:
            failure = diagnostics.failure_record(error, phase_name)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.with_suffix('.failure.json').write_text(json.dumps({
                'suite':'acquisition-diagnostic-v1', 'release_acceptance':False,
                'revision':args.revision, **failure}, indent=2)+'\n')
            print('acquisition diagnostic: '+json.dumps(failure, sort_keys=True), flush=True)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
