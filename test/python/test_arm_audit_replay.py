"""Exact staged ARM64 audit diagnostics cannot retry failures or authorize promotion."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import offline_host_evidence as evidence
from offline_host_fixture import full_host_report


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


replay=load('arm_audit_replay',ROOT/'scripts/diagnostic-arm-audit-replay.py')
host=load('arm_audit_host_writer',ROOT/'scripts/offline-host.py')


def metadata():
    return {'id':replay.RUN_ID,'head_sha':replay.REVISION,'path':'.github/workflows/release.yml',
            'event':'workflow_dispatch','status':'completed','conclusion':'failure'}


class ArmAuditReplayTests(unittest.TestCase):
    def test_wrong_run_metadata_and_checksums_never_reach_archive_or_guest(self):
        for key,value in (('id',42413538496),('head_sha','a'*40),('path','other'),
                          ('event','push'),('status','in_progress'),('conclusion','success')):
            with self.subTest(key=key),patch.object(replay,'load') as archive:
                with self.assertRaises(ValueError):replay.verify_input(Path('/unused'),{**metadata(),key:value})
                archive.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            checksum=directory/'sierx-offline-arm64.tar.gz.sha256'
            lock=directory/'sierx-offline-arm64.lock.sha256'
            checksum.write_text(replay.ARCHIVE_SHA256+'  sierx-offline-arm64.tar.gz\n')
            lock.write_text(replay.BUNDLE_SHA256+'\n')
            for path in (checksum,lock):
                content=path.read_text();path.write_text('0'*64)
                with patch.object(replay,'load') as archive,self.assertRaises(ValueError):
                    replay.verify_input(directory,metadata())
                archive.assert_not_called();path.write_text(content)
            target=directory/'sierx-offline-arm64';target.mkdir()
            with patch.object(replay,'load') as archive,self.assertRaises(ValueError):
                replay.verify_input(directory,metadata())
            archive.assert_not_called();target.rmdir()
            verifier=Mock();verifier.verify.return_value=target
            with patch.object(replay,'load',return_value=verifier):
                self.assertEqual(replay.verify_input(directory,metadata()),target)
            self.assertEqual(verifier.verify.call_args.args,(directory,{
                'schema':1,'revision':replay.REVISION,'architectures':{'arm64':{
                'release':replay.RELEASE,'archive_sha256':replay.ARCHIVE_SHA256,
                'bundle_sha256':replay.BUNDLE_SHA256}}},'arm64'))

    def test_full_guest_command_preserves_normal_workload_and_marks_raw_report(self):
        command=replay.vm_command(Path('/fixture'),Path('/fixture/sierx-offline-arm64'),
                                  {'bundle_sha256':'b'*64},'c'*64)
        self.assertIn('--diagnostic-report',command)
        for flag in ('--development','--runtime-probe','--transition-probe','--import-probe',
                     '--transition-stress','--ordinary-installer-trace','--single-tcg'):
            self.assertNotIn(flag,command)
        self.assertIn(replay.ARCHIVE_SHA256,command);self.assertIn(replay.BUNDLE_SHA256,command)
        self.assertIn('/fixture/host-fixture-ubuntu24-arm64.tar',command)
        self.assertIn('/fixture/previous/offline-acceptance-arm64.json',command)
        with self.assertRaises(ValueError):replay.vm_command(Path('/fixture'),Path('/bundle'),{},'private')

    def test_failed_guest_runs_once_and_retains_exact_nonaccepting_replay_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'dist';directory.mkdir()
            approval=root/'deploy/ci/previous-offline-release.json';approval.parent.mkdir(parents=True)
            retained={'bundle_sha256':'b'*64}
            approval.write_text(json.dumps({'architectures':{'arm64':retained}}))
            (directory/'arm-audit-original-run.json').write_text(json.dumps(metadata()))
            (directory/'host-fixture-ubuntu24-arm64.tar.sha256').write_text('c'*64+' fixture\n')
            with patch.object(replay,'ROOT',root),patch.object(replay,'source_revision',return_value='a'*40), \
                    patch.object(replay.offline,'native_arch',return_value='arm64'), \
                    patch.object(replay.offline,'digest',return_value=replay.RETAINED_APPROVAL_SHA256), \
                    patch.object(replay,'verify_input',return_value=directory/'sierx-offline-arm64'), \
                    patch.object(replay,'load',return_value=Mock()) as receipts, \
                    patch.object(replay.subprocess,'run',return_value=Mock(returncode=1)) as invoke:
                self.assertEqual(replay.main(),1)
            invoke.assert_called_once()
            self.assertIn('--diagnostic-report',invoke.call_args.args[0])
            receipts.return_value.receipt.assert_called_once_with(directory,'ubuntu24','ghcr.io/siercks/sierx',replay.REVISION)
            proof=json.loads((directory/'arm-audit-replay-input.json').read_text())
            self.assertFalse(proof['release_acceptance'])
            self.assertEqual(proof['run_id'],46019157095)
            self.assertEqual(proof['release'],replay.RELEASE)
            self.assertEqual(proof['workload'],'all-normal-scenarios-and-independent-audit')

    def test_wrong_architecture_or_retained_approval_never_launches_guest(self):
        with patch.object(replay.offline,'native_arch',return_value='amd64'), \
                patch.object(replay.subprocess,'run') as invoke,self.assertRaises(ValueError):replay.main()
        invoke.assert_not_called()
        with patch.object(replay.offline,'native_arch',return_value='arm64'), \
                patch.object(replay,'source_revision',return_value='a'*40), \
                patch.object(replay.offline,'digest',return_value='0'*64), \
                patch.object(replay,'verify_input') as verify, \
                patch.object(replay.subprocess,'run') as invoke,self.assertRaises(ValueError):replay.main()
        verify.assert_not_called();invoke.assert_not_called()

    def test_actual_raw_diagnostic_report_and_envelope_both_reject_normal_promotion(self):
        bundle={'arch':'arm64','release':replay.RELEASE};expected='b'*64;suite='c'*64
        previous={'release':{'revision':'a'*40,'image':'registry.test/retained@sha256:'+'a'*64},'bundle_sha256':'d'*64}
        value=full_host_report(bundle,expected,suite,'ubuntu-24.04',previous)
        evidence.validate_closeout(value,bundle,expected,suite)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'dist';directory.mkdir()
            report=directory/replay.REPORT
            host.write_closeout_report(report,value)
            self.assertEqual(json.loads(report.read_text()),value)
            host.write_closeout_report(report,value,True)
            raw=json.loads(report.read_text())
            self.assertFalse(raw['release_acceptance']);self.assertNotIn('release_acceptance',value)
            with self.assertRaises(ValueError):evidence.validate_closeout(raw,bundle,expected,suite)
            with patch.object(replay,'ROOT',root),patch.object(replay,'source_revision',return_value='a'*40):replay.package()
            envelope=json.loads((directory/'arm-audit-diagnostic-arm64.json').read_text())
            self.assertFalse(envelope['release_acceptance'])
            with self.assertRaises(ValueError):evidence.validate_closeout(envelope,bundle,expected,suite)
            host.write_closeout_report(report,value)
            with patch.object(replay,'ROOT',root),patch.object(replay,'source_revision',return_value='a'*40), \
                    self.assertRaises(ValueError):replay.package()

    def test_workflow_registration_cannot_start_host_and_upload_is_one_safe_file(self):
        workflow=(ROOT/'.github/workflows/arm-audit-diagnostic.yml').read_text()
        self.assertIn("if: github.event_name == 'workflow_dispatch'",workflow)
        self.assertIn('name: offline-delivery-arm64',workflow.replace('--name ','name: '))
        self.assertIn('path: dist/arm-audit-diagnostic-arm64.json',workflow)
        self.assertNotIn('packages: write',workflow)
        self.assertNotIn('release-manifest',workflow)


if __name__=='__main__':unittest.main()
