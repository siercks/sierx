"""Historical diagnosis cannot substitute inputs or become release acceptance."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('replay',ROOT/'scripts/offline-historical-replay.py')
replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)


def metadata():
    return {'id':replay.RUN_ID,'head_sha':replay.REVISION,'path':'.github/workflows/release.yml',
            'event':'workflow_dispatch','status':'completed','conclusion':'failure'}


class HistoricalReplayTests(unittest.TestCase):
    def test_wrong_run_or_revision_never_reaches_bundle_verification(self):
        for key,value in (('id',1),('head_sha','0'*40),('path','other'),('event','push'),
                          ('status','in_progress'),('conclusion','success')):
            with self.subTest(key=key),patch.object(replay,'load') as load:
                with self.assertRaisesRegex(ValueError,'original failed exact release'):
                    replay.verify_input(Path('/unused'),{**metadata(),key:value})
                load.assert_not_called()

    def test_mismatched_hash_or_preexisting_extraction_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            archive=directory/'sierx-offline-arm64.tar.gz.sha256'
            lock=directory/'sierx-offline-arm64.lock.sha256'
            archive.write_text(replay.ARCHIVE_SHA256+'  sierx-offline-arm64.tar.gz\n')
            lock.write_text(replay.BUNDLE_SHA256+'\n')
            for path in (archive,lock):
                old=path.read_text();path.write_text('0'*64)
                with self.subTest(path=path.name),patch.object(replay,'load') as load:
                    with self.assertRaisesRegex(ValueError,'original host receipt'):
                        replay.verify_input(directory,metadata())
                    load.assert_not_called()
                path.write_text(old)
            (directory/'sierx-offline-arm64').mkdir()
            with patch.object(replay,'load') as load:
                with self.assertRaisesRegex(ValueError,'fresh artifact extraction'):
                    replay.verify_input(directory,metadata())
                load.assert_not_called()

    def test_correct_receipts_still_require_verification_of_actual_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/'sierx-offline-arm64.tar.gz.sha256').write_text(replay.ARCHIVE_SHA256+'\n')
            (directory/'sierx-offline-arm64.lock.sha256').write_text(replay.BUNDLE_SHA256+'\n')
            verifier=Mock();verifier.verify.side_effect=ValueError('altered archive bytes')
            with patch.object(replay,'load',return_value=verifier):
                with self.assertRaisesRegex(ValueError,'altered archive bytes'):
                    replay.verify_input(directory,metadata())
            _,approval,arch=verifier.verify.call_args.args
            self.assertEqual(arch,'arm64')
            self.assertEqual(approval['architectures']['arm64'],{'release':replay.RELEASE,
                'archive_sha256':replay.ARCHIVE_SHA256,'bundle_sha256':replay.BUNDLE_SHA256})

    def test_replay_is_native_arm_only_and_not_a_release_workflow_input(self):
        with patch.object(replay.offline,'native_arch',return_value='amd64'),patch.object(replay,'verify_input') as verify:
            with self.assertRaisesRegex(ValueError,'native ARM64'):replay.main()
            verify.assert_not_called()
        release=(ROOT/'.github/workflows/release.yml').read_text()
        workflow=(ROOT/'.github/workflows/host-audit-diagnostic.yml').read_text()
        self.assertNotIn('historical-replay',release)
        self.assertNotIn('packages: write',workflow)
        self.assertIn("if replay and key=='host_report':value['release_acceptance']=False",workflow)
        self.assertIn('path: dist/host-audit-diagnostic-${{ env.ARCH }}.json',workflow)

    def test_changed_retained_approval_blocks_replay_before_extraction(self):
        with patch.object(replay.offline,'native_arch',return_value='arm64'), \
                patch.object(replay.offline,'digest',return_value='0'*64),patch.object(replay,'verify_input') as verify:
            with self.assertRaisesRegex(ValueError,'retained-release approval differs'):
                replay.main()
            verify.assert_not_called()

    def test_native_probe_keeps_historical_verification_and_uses_disposable_namespaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            approval = root/'deploy/ci/previous-offline-release.json'
            approval.parent.mkdir(parents=True)
            approval.write_text('{"architectures":{"arm64":{}}}')
            dist = root/'dist'
            dist.mkdir()
            (dist/'historical-run.json').write_text(json.dumps(metadata()))
            bundle = dist/'sierx-offline-arm64'
            with patch.object(replay, 'ROOT', root), \
                    patch.object(replay.offline, 'native_arch', return_value='arm64'), \
                    patch.object(replay.offline, 'digest', return_value=replay.RETAINED_APPROVAL_SHA256), \
                    patch.object(replay, 'verify_input', return_value=bundle) as verify, \
                    patch.object(replay.subprocess, 'run', return_value=Mock(returncode=1)) as run:
                self.assertEqual(replay.main(native_import=True), 1)
            verify.assert_called_once_with(dist, metadata())
            args = run.call_args.args[0]
            self.assertTrue({'--mount', '--net', '--pid', '--kill-child'}.issubset(args))
            self.assertIn(str(bundle), args)
            self.assertIn(replay.BUNDLE_SHA256, args)
            receipt = json.loads((dist/'historical-replay-input.json').read_text())
            self.assertIs(receipt['release_acceptance'], False)
            self.assertIs(receipt['native_import'], True)
            self.assertIs(receipt['import_probe'], False)
            self.assertEqual(receipt['installer_trace_mode'], 'ordinary-ptrace')
            self.assertEqual(receipt['archive_sha256'], replay.ARCHIVE_SHA256)


if __name__=='__main__':unittest.main()
