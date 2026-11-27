"""A compatible fixture must bind source, security features and ALL helpers."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import offline_guest_podman as runtime
import offline_host_evidence as evidence
from offline_host_fixture import full_host_report


def receipt():
    return {**copy.deepcopy(runtime.PINS), 'signature_policy': {'source': 'packaged-default-link', 'sha256': 'e' * 64}, 'artifacts_sha256': {
        name: runtime.CONFIG_SHA256 if name == 'containers.conf' else 'a' * 64
        for name in runtime.FILES}}


def os_release(root, profile='rocky'):
    (root / 'etc').mkdir(parents=True)
    (root / 'etc/os-release').write_text('ID=' + profile + '\nVERSION_ID="' +
                                       ('10.2' if profile == 'rocky' else '24.04') + '"\n')


class GuestPodmanTests(unittest.TestCase):
    def test_missing_old_or_incomplete_build_and_security_identity_is_rejected(self):
        for defect in ('missing', 'version', 'compiler', 'source', 'cgo', 'boolean',
                       'seccomp', 'systemd', 'subid', 'prefix', 'helper', 'hash', 'config', 'policy', 'policy-hash', 'extra'):
            value = receipt()
            if defect == 'missing': value = None
            elif defect == 'version': value['version'] = '6.1.4'
            elif defect == 'compiler': value['compiler_image'] = 'golang:latest'
            elif defect == 'source': value['source_archive_sha256'] = 'b' * 64
            elif defect == 'cgo': value['cgo_enabled'] = False
            elif defect == 'boolean': value['cgo_enabled'] = 1
            elif defect in {'seccomp', 'systemd'}: value['build_tags'].remove(defect)
            elif defect == 'subid': value['build_tags'].remove('libsubid')
            elif defect == 'prefix': value['prefix'] = '/usr/local'
            elif defect == 'helper': del value['artifacts_sha256']['quadlet']
            elif defect == 'hash': value['artifacts_sha256']['rootlessport'] = True
            elif defect == 'config': value['artifacts_sha256']['containers.conf'] = 'c' * 64
            elif defect == 'policy': del value['signature_policy']
            elif defect == 'policy-hash': value['signature_policy']['sha256'] = True
            else: value['unverified_override'] = True
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                runtime.validate_receipt(value)

    def test_bad_archive_stops_before_compiler_or_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'source.tar.gz'
            archive.write_bytes(b'changed source')
            with patch.object(runtime.subprocess, 'check_output') as execute, self.assertRaises(ValueError):
                runtime.build(archive, root / 'out')
            execute.assert_not_called()
            self.assertFalse((root / 'out').exists())

    def test_real_installation_and_preboot_checks_reject_each_changed_artifact_and_generator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'fixture'
            source = Path(temporary) / 'build'
            source.mkdir()
            os_release(root)
            packaged = root / runtime.PACKAGED_POLICY.relative_to('/')
            packaged.parent.mkdir(parents=True)
            packaged.write_bytes(b'{"default":[{"type":"reject"}]}\n')
            for name in runtime.FILES:
                (source / name).write_bytes(('synthetic fixture ' + name).encode())
            with patch.object(runtime, 'CONFIG_SHA256', runtime.digest(source / 'containers.conf')):
                value = {**copy.deepcopy(runtime.PINS), 'artifacts_sha256': {
                    name: runtime.digest(source / name) for name in runtime.FILES}}
                (source / 'podman.json').write_text(json.dumps(value))
                value = {**value, 'signature_policy': {'source': 'packaged-default-link', 'sha256': runtime.digest(packaged)}}
                self.assertEqual(runtime.install(source, root), value)
                for name, destination in runtime.FILES.items():
                    target = root / Path(destination).relative_to('/')
                    original = target.read_bytes()
                    target.write_bytes(b'substituted helper/configuration')
                    with self.subTest(artifact=name), self.assertRaises(ValueError):
                        runtime.load_fixture(root)
                    target.write_bytes(original)
                for generator in runtime.GENERATORS:
                    target = root / Path(generator).relative_to('/')
                    target.unlink()
                    target.symlink_to('/usr/libexec/podman/old-quadlet')
                    with self.subTest(generator=generator), self.assertRaises(ValueError):
                        runtime.load_fixture(root)
                    target.unlink()
                    target.symlink_to(runtime.FILES['quadlet'])
                self.assertEqual(runtime.load_fixture(root), value)

    def test_relocated_package_policy_is_preserved_exactly_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packaged = root / runtime.PACKAGED_POLICY.relative_to('/')
            packaged.parent.mkdir(parents=True)
            original = b'{ "default": [{ "type": "reject" }], "transports": {} }\n'
            packaged.write_bytes(original)
            value = runtime.preserve_signature_policy(root)
            effective = root / runtime.SYSTEM_POLICY.relative_to('/')
            self.assertTrue(effective.is_symlink())
            self.assertEqual(str(effective.readlink()), str(runtime.PACKAGED_POLICY))
            self.assertEqual(packaged.read_bytes(), original)
            self.assertEqual(value, runtime.verify_signature_policy(root))
            packaged.write_bytes(b'{"default":[{"type":"insecureAcceptAnything"}]}')
            with self.assertRaises(ValueError): runtime.verify_signature_policy(root)
            packaged.write_bytes(original)
            effective.unlink()
            effective.write_bytes(original)
            with self.assertRaises(ValueError): runtime.verify_signature_policy(root)

    def test_existing_stricter_system_override_is_never_replaced_by_packaged_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            effective = root / runtime.SYSTEM_POLICY.relative_to('/')
            effective.parent.mkdir(parents=True)
            original = b'{"default":[{"type":"reject"}]}\n'
            effective.write_bytes(original)
            value = runtime.preserve_signature_policy(root)
            self.assertEqual(value['source'], 'existing-system')
            self.assertFalse(effective.is_symlink())
            self.assertEqual(effective.read_bytes(), original)
            self.assertEqual(value, runtime.verify_signature_policy(root))
            self.assertEqual(value, runtime.preserve_signature_policy(root))

    def test_missing_oversized_or_unknown_policy_is_rejected_without_fallback_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            effective = root / runtime.SYSTEM_POLICY.relative_to('/')
            with self.assertRaises(ValueError): runtime.preserve_signature_policy(root)
            self.assertFalse(effective.exists())
            packaged = root / runtime.PACKAGED_POLICY.relative_to('/')
            packaged.parent.mkdir(parents=True)
            packaged.write_bytes(b'x' * 65537)
            with self.assertRaises(ValueError): runtime.preserve_signature_policy(root)
            self.assertFalse(effective.exists())
            effective.parent.mkdir(parents=True)
            effective.symlink_to('/unknown-policy')
            with self.assertRaises(ValueError): runtime.preserve_signature_policy(root)
            self.assertEqual(str(effective.readlink()), '/unknown-policy')

    def test_ubuntu_keeps_distribution_runtime_and_rejects_a_source_runtime_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os_release(root, 'ubuntu')
            self.assertIsNone(runtime.load_fixture(root))
            packet = root / runtime.RECEIPT.relative_to('/')
            packet.parent.mkdir(parents=True)
            packet.write_text(json.dumps(receipt()))
            with self.assertRaises(ValueError): runtime.load_fixture(root)
            with self.assertRaises(ValueError): runtime.install(root, root)

    def test_os_identity_cannot_be_ambiguous_unsupported_or_escape_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'fixture'
            os_release(root)
            release = root / 'etc/os-release'
            for content in ('ID=rocky\nID=ubuntu\nVERSION_ID=10\n',
                            'ID=rocky\nVERSION_ID=9\n', 'ID=ubuntu\nVERSION_ID=22.04\n'):
                release.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError): runtime.load_fixture(root)
            outside = Path(temporary) / 'outside'
            outside.write_text('ID=rocky\nVERSION_ID=10\n')
            release.unlink()
            release.symlink_to(outside)
            with self.assertRaises(ValueError): runtime.load_fixture(root)

    def test_complete_host_evidence_requires_exact_runtime_and_actual_version(self):
        bundle = {'arch': 'amd64', 'release': {'revision': 'a' * 40, 'image': 'example/app@sha256:' + 'b' * 64}}
        previous = {'release': {'revision': 'c' * 40, 'image': 'example/app@sha256:' + 'd' * 64}, 'bundle_sha256': 'e' * 64}
        for profile in ('ubuntu-24.04', 'rocky-10.2'):
            report = full_host_report(bundle, 'f' * 64, '1' * 64, profile, previous)
            evidence.validate_closeout(report, bundle, 'f' * 64, '1' * 64)
            for defect in ('missing', 'substitute'):
                altered = copy.deepcopy(report)
                if defect == 'missing': altered.pop('podman_build')
                elif profile.startswith('rocky-'): altered['host_versions']['podman'] = 'podman version 6.1.4'
                else: altered['podman_build'] = receipt()
                with self.subTest(profile=profile, defect=defect), self.assertRaises(ValueError):
                    evidence.validate_closeout(altered, bundle, 'f' * 64, '1' * 64)
