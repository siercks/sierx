"""Fault fixtures must reject and must not corrupt their approved source."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import offline
from offline_host_inputs import invalid_bundles
from test_offline import fixture


class InvalidDeliveryTests(unittest.TestCase):
    def test_each_fault_rejects_without_writing_shared_source_inodes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)/'approved'
            source.mkdir()
            data, expected = fixture(source)
            destination = Path(temporary)/'invalid'
            hashes = invalid_bundles(source,destination)
            for name, checksum in hashes.items():
                with self.subTest(name=name),self.assertRaises(ValueError):
                    offline.verify(destination/name,checksum,'amd64')
                self.assertEqual(offline.verify(source,expected,'amd64'),data)
            self.assertEqual(hashes['missing-image'],expected)
            self.assertNotEqual(hashes['wrong-architecture'],expected)

    def test_existing_or_overlapping_destinations_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)/'approved'
            source.mkdir()
            fixture(source)
            for destination in (source,source/'invalid',source.parent):
                with self.subTest(destination=destination),self.assertRaises(ValueError):
                    invalid_bundles(source,destination)


if __name__=='__main__':unittest.main()
