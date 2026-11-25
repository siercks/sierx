"""Stale, substituted or uncorrected observers cannot satisfy host acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import offline_guest_tracer as tracer
import offline_host_evidence as evidence
import tracer_diagnostic as diagnostic
from offline_host_fixture import full_host_report


class GuestTracerTests(unittest.TestCase):
    def test_guest_backport_is_byte_identical_to_the_verified_native_controls(self):
        packet = ROOT/'test/diagnostics/tracer-termination/termination-fix.json'
        self.assertEqual(tracer.ARCHIVE_SHA256,diagnostic.ARCHIVE_SHA256)
        self.assertEqual(tracer.PATCH_SHA256,diagnostic.PATCH_SHA256)
        self.assertEqual(tracer.ORIGINAL_SHA256,diagnostic.SOURCE_SHA256['old'])
        self.assertEqual(tracer.FIXED_SHA256,diagnostic.SOURCE_SHA256['fixed'])
        raw = tracer.decode_patch(packet)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),diagnostic.PATCH_SHA256)
        with tempfile.TemporaryDirectory() as temporary:
            altered = Path(temporary)/'packet.json'
            value = json.loads(packet.read_text())
            value['patch_lines'][0] += 'substituted source'
            altered.write_text(json.dumps(value))
            with self.assertRaises(ValueError):tracer.decode_patch(altered)

    def test_changed_archive_is_rejected_before_compilation_or_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root/'source.tar.xz'
            archive.write_bytes(b'not the approved upstream source')
            output = root/'output'
            with patch.object(tracer.subprocess,'run') as execute, self.assertRaises(ValueError):
                tracer.build(archive,ROOT/'test/diagnostics/tracer-termination/termination-fix.json',output)
            execute.assert_not_called()
            self.assertFalse(output.exists())

    def test_old_missing_or_forged_receipts_are_rejected(self):
        for defect in ('missing','unpatched','different-fix','wrong-version','wrong-flags','unknown-field','invalid-binary'):
            receipt = {**tracer.PINS,'binary_sha256':'a'*64}
            if defect == 'missing':receipt = None
            elif defect == 'unpatched':receipt['source_sha256'] = tracer.ORIGINAL_SHA256
            elif defect == 'different-fix':receipt['patch_sha256'] = 'b'*64
            elif defect == 'wrong-version':receipt['version'] = '6.9'
            elif defect == 'wrong-flags':receipt['configure_flags'] = ['--enable-bundled=no']
            elif defect == 'unknown-field':receipt['unverified_override'] = True
            elif defect == 'invalid-binary':receipt['binary_sha256'] = False
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                tracer.validate_receipt(receipt)

    def test_changed_guest_binary_is_rejected_even_with_valid_source_pins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary,packet = root/'strace',root/'tracer.json'
            binary.write_bytes(b'approved binary fixture')
            receipt = {**tracer.PINS,'binary_sha256':tracer.digest(binary)}
            packet.write_text(json.dumps(receipt))
            self.assertEqual(tracer.load_receipt(packet,binary),receipt)
            binary.write_bytes(b'substituted observer')
            with self.assertRaises(ValueError):tracer.load_receipt(packet,binary)

    def test_otherwise_complete_host_report_cannot_omit_or_change_the_correction(self):
        bundle = {'arch':'arm64','release':{'revision':'a'*40,'image':'example/app@sha256:'+'b'*64}}
        previous = {'release':{'revision':'c'*40,'image':'example/app@sha256:'+'d'*64},'bundle_sha256':'e'*64}
        report = full_host_report(bundle,'f'*64,'1'*64,'ubuntu-24.04',previous)
        evidence.validate_closeout(report,bundle,'f'*64,'1'*64)
        for defect in ('missing','old-source','missing-binary'):
            altered = copy.deepcopy(report)
            if defect == 'missing':altered.pop('tracer')
            elif defect == 'old-source':altered['tracer']['source_sha256'] = tracer.ORIGINAL_SHA256
            else:altered['tracer'].pop('binary_sha256')
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                evidence.validate_closeout(altered,bundle,'f'*64,'1'*64)
