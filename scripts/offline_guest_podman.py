"""Compatible, source-pinned Podman for the disposable Rocky acceptance OS only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

VERSION = '5.8.11'
GO_VERSION = '1.27.4'
COMPILER = 'docker.io/library/golang@sha256:ce59b41415e2524ae99926fe1f37ce48ba8c194dcbd2a56a65436cdcefa2bd34'
SOURCE_URL = 'https://codeload.github.com/podman-container-tools/podman/tar.gz/refs/tags/v5.8.11'
ARCHIVE_SHA256 = '2d366d599ef0577f5485265983dbb26e824813c40948d1d102dabd860b438006'
CONFIG_SHA256 = '0131c140948c665098c461b0772693171f5e6a01a1205486fe8679ad9e46f0b1'
TAGS = ['grpcnotrace', 'systemd', 'libsubid', 'seccomp',
        'containers_image_openpgp', 'exclude_graphdriver_btrfs']
PINS = {'version': VERSION, 'go_version': GO_VERSION, 'compiler_image': COMPILER,
        'source_archive_sha256': ARCHIVE_SHA256, 'build_tags': TAGS,
        'cgo_enabled': True, 'prefix': '/usr'}
FILES = {'podman': '/usr/bin/podman', 'quadlet': '/usr/libexec/podman/quadlet',
         'rootlessport': '/usr/libexec/podman/rootlessport',
         'containers.conf': '/usr/share/containers/containers.conf'}
GENERATORS = ('/usr/lib/systemd/system-generators/podman-system-generator',
              '/usr/lib/systemd/user-generators/podman-user-generator')
RECEIPT = Path('/usr/share/sierx-offline/podman.json')
POLICY_RECEIPT = Path('/usr/share/sierx-offline/podman-policy.json')
SYSTEM_POLICY = Path('/etc/containers/policy.json')
PACKAGED_POLICY = Path('/usr/share/containers/policy.json')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_build_receipt(value):
    if (not isinstance(value, dict) or set(value) != set(PINS) | {'artifacts_sha256'}
            or any(value.get(key) != expected for key, expected in PINS.items())
            or value.get('cgo_enabled') is not True):
        raise ValueError('Missing exact compatible Rocky runtime build identity')
    artifacts = value['artifacts_sha256']
    if (not isinstance(artifacts, dict) or set(artifacts) != set(FILES)
            or any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v)
                   for v in artifacts.values())
            or artifacts['containers.conf'] != CONFIG_SHA256):
        raise ValueError('Incomplete matching runtime/helper/configuration receipts')
    return value


def validate_policy_receipt(value):
    if (not isinstance(value, dict) or set(value) != {'source', 'sha256'}
            or not isinstance(value.get('source'), str)
            or value['source'] not in {'existing-system', 'packaged-default-link'}
            or not isinstance(value.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', value['sha256'])):
        raise ValueError('Missing preserved signature policy identity')
    return value


def validate_receipt(value):
    if not isinstance(value, dict) or 'signature_policy' not in value:
        raise ValueError('Missing installed runtime signature policy binding')
    validate_build_receipt({key: item for key, item in value.items() if key != 'signature_policy'})
    validate_policy_receipt(value['signature_policy'])
    return value


def verify_files(value, paths):
    validate_build_receipt(value)
    if set(paths) != set(FILES):
        raise ValueError('Every runtime/helper/configuration artifact must be checked')
    for name, path in paths.items():
        path = Path(path)
        if path.is_symlink() or not path.is_file() or digest(path) != value['artifacts_sha256'][name]:
            raise ValueError('Runtime or matching helper differs from its build receipt')
    return value


def policy_bytes(path, root):
    path, root = Path(path), Path(root).resolve()
    if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root)
            or not 0 < path.stat().st_size <= 65536):
        raise ValueError('Missing bounded regular signature policy in the fixture')
    return path.read_bytes()


def preserve_signature_policy(root):
    """Keep every packaged rule and existing system override byte for byte."""
    root = Path(root)
    effective = root / SYSTEM_POLICY.relative_to('/')
    packaged = root / PACKAGED_POLICY.relative_to('/')
    if effective.is_symlink():
        if str(effective.readlink()) != str(PACKAGED_POLICY):
            raise ValueError('Existing signature policy link must not be replaced')
        raw, source = policy_bytes(packaged, root), 'packaged-default-link'
    elif effective.exists():
        raw, source = policy_bytes(effective, root), 'existing-system'
    else:
        raw, source = policy_bytes(packaged, root), 'packaged-default-link'
        effective.parent.mkdir(parents=True, exist_ok=True)
        effective.symlink_to(PACKAGED_POLICY)
    value = {'source': source, 'sha256': hashlib.sha256(raw).hexdigest()}
    validate_policy_receipt(value)
    packet = root / POLICY_RECEIPT.relative_to('/')
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(json.dumps(value, sort_keys=True) + '\n')
    packet.chmod(0o644)
    return value


def verify_signature_policy(root):
    root = Path(root)
    packet = root / POLICY_RECEIPT.relative_to('/')
    if packet.is_symlink():
        raise ValueError('Signature policy receipt must be a regular fixture file')
    value = validate_policy_receipt(json.loads(packet.read_text()))
    effective = root / SYSTEM_POLICY.relative_to('/')
    if value['source'] == 'packaged-default-link':
        if not effective.is_symlink() or str(effective.readlink()) != str(PACKAGED_POLICY):
            raise ValueError('Packaged signature policy compatibility link changed')
        raw = policy_bytes(root / PACKAGED_POLICY.relative_to('/'), root)
    else:
        raw = policy_bytes(effective, root)
    if hashlib.sha256(raw).hexdigest() != value['sha256']:
        raise ValueError('Signature policy rules differ from the preserved fixture policy')
    return value


def fixture_profile(root):
    root = Path(root).resolve()
    path = root / 'etc/os-release'
    if not path.resolve().is_relative_to(root):
        raise ValueError('Acceptance OS identity leaves the fixture')
    text = path.read_text()
    fields = {}
    for name in ('ID', 'VERSION_ID'):
        matches = re.findall(r'^' + name + r'=(?:"([a-zA-Z0-9.]+)"|([a-zA-Z0-9.]+))$', text, re.M)
        if len(matches) != 1:
            raise ValueError('Missing unambiguous acceptance OS identity')
        fields[name] = ''.join(matches[0])
    profile = fields['ID'] + '-' + fields['VERSION_ID']
    if not re.fullmatch(r'ubuntu-24\.04|rocky-10(?:\.[0-9]+)?', profile):
        raise ValueError('Unsupported acceptance OS runtime profile')
    return profile


def load_fixture(root=Path('/')):
    root = Path(root)
    profile = fixture_profile(root)
    packet = root / RECEIPT.relative_to('/')
    if profile == 'ubuntu-24.04':
        policy_packet = root / POLICY_RECEIPT.relative_to('/')
        if packet.exists() or packet.is_symlink() or policy_packet.exists() or policy_packet.is_symlink():
            raise ValueError('Ubuntu must retain its ordinary distribution runtime')
        return None
    if packet.is_symlink():
        raise ValueError('Runtime receipt must be a regular fixture file')
    value = json.loads(packet.read_text())
    verify_files(value, {name: root / Path(path).relative_to('/') for name, path in FILES.items()})
    for generator in GENERATORS:
        path = root / Path(generator).relative_to('/')
        if not path.is_symlink() or str(path.readlink()) != FILES['quadlet']:
            raise ValueError('System and user managers require the matching Quadlet generator')
    return validate_receipt({**value, 'signature_policy': verify_signature_policy(root)})


def validate_report(report):
    if 'podman_build' not in report:
        raise ValueError('Missing independently bound acceptance runtime identity')
    if report['profile'] == 'ubuntu-24.04':
        if report['podman_build'] is not None:
            raise ValueError('Ubuntu distribution runtime was unexpectedly replaced')
    else:
        validate_receipt(report['podman_build'])
        if report['host_versions']['podman'] != 'podman version ' + VERSION:
            raise ValueError('Rocky runtime version differs from the compatible baseline')


def install(source, root=Path('/')):
    """Called only while constructing the disposable Rocky image, never live."""
    source, root = Path(source), Path(root)
    if not fixture_profile(root).startswith('rocky-10'):
        raise ValueError('Compatible runtime installation is limited to the Rocky fixture')
    value = json.loads((source / 'podman.json').read_text())
    verify_files(value, {name: source / name for name in FILES})
    for name, destination in FILES.items():
        path = root / Path(destination).relative_to('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            path.unlink()
        shutil.copyfile(source / name, path)
        path.chmod(0o644 if name == 'containers.conf' else 0o755)
    for generator in GENERATORS:
        path = root / Path(generator).relative_to('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        path.symlink_to(FILES['quadlet'])
    packet = root / RECEIPT.relative_to('/')
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(json.dumps(value, sort_keys=True) + '\n')
    packet.chmod(0o644)
    preserve_signature_policy(root)
    return load_fixture(root)


def build(archive, output):
    """Build in owned scratch; export only matching artifacts and their receipt."""
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError('Runtime source differs from the maintained official archive')
    if subprocess.check_output(['go', 'version'], text=True).split()[2] != 'go' + GO_VERSION:
        raise ValueError('Runtime compiler differs from its pinned version')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='sierx-rocky-podman-') as temporary:
        scratch = Path(temporary)
        subprocess.run(['tar', '-xzf', str(Path(archive).resolve()), '-C', str(scratch),
                        '--no-same-owner', '--no-same-permissions'], check=True, timeout=30)
        source = scratch / ('podman-' + VERSION)
        config = source / 'vendor/go.podman.io/common/pkg/config/containers.conf'
        if digest(config) != CONFIG_SHA256:
            raise ValueError('Matching upstream runtime configuration changed')
        # Only public source/compiler output enters the connected builder log.
        # No build log, compiler or development package is exported to the VM.
        subprocess.run(['make', 'PREFIX=/usr', 'CGO_ENABLED=1',
                        'BUILDFLAGS=-trimpath -mod=vendor', 'BUILDTAGS=' + ' '.join(TAGS),
                        'bin/podman', 'bin/quadlet', 'bin/rootlessport'], cwd=source,
                       check=True, timeout=1500)
        if subprocess.check_output([str(source / 'bin/podman'), '--version'], text=True).strip() != 'podman version ' + VERSION:
            raise ValueError('Built runtime has an unexpected version')
        for name in ('podman', 'quadlet', 'rootlessport'):
            metadata = subprocess.check_output(['go', 'version', '-m', str(source / 'bin' / name)], text=True)
            if (metadata.splitlines()[0].split()[-1] != 'go' + GO_VERSION
                    or '\tbuild\tCGO_ENABLED=1\n' not in metadata):
                raise ValueError('Runtime/helper compiler or CGO identity changed')
            if name != 'rootlessport':
                tags = re.findall(r'^\s*build\s+-tags=(.*)$', metadata, re.M)
                if len(tags) != 1 or tags[0].strip('"').split(',') != TAGS:
                    raise ValueError('Runtime/helper security build features changed')
            shutil.copyfile(source / 'bin' / name, output / name)
            (output / name).chmod(0o755)
        shutil.copyfile(config, output / 'containers.conf')
        (output / 'containers.conf').chmod(0o644)
        value = {**PINS, 'artifacts_sha256': {name: digest(output / name) for name in FILES}}
        validate_build_receipt(value)
        (output / 'podman.json').write_text(json.dumps(value, sort_keys=True) + '\n')
        return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--compiler-image', action='store_true')
    action.add_argument('--source-url', action='store_true')
    action.add_argument('--archive', type=Path)
    action.add_argument('--install', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.compiler_image:
        print(COMPILER)
    elif args.source_url:
        print(SOURCE_URL)
    elif args.install:
        print(json.dumps(install(args.install), sort_keys=True))
    else:
        if args.output is None:
            parser.error('--archive requires --output')
        print(json.dumps(build(args.archive, args.output), sort_keys=True))
