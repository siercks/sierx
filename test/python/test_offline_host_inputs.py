"""Fault fixtures must reject and must not corrupt their approved source."""
from pathlib import Path
import sys
import tempfile
import unittest
import json

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import offline
from offline_host_inputs import invalid_bundles, isolated_storage, require_empty_storage
from test_offline import fixture


class InvalidDeliveryTests(unittest.TestCase):
    def test_empty_store_checks_actual_selected_paths_and_rejects_reused_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'isolated'
            runroot=Path(temporary)/'run'
            env=isolated_storage(root,runroot,{'HOME':'/synthetic','CONTAINERS_STORAGE_CONF':'/old'})
            self.assertNotIn('CONTAINERS_STORAGE_CONF',env)
            self.assertEqual(env['HOME'],'/synthetic')
            self.assertEqual(Path(env['XDG_CONFIG_HOME']),root/'config')
            config=(root/'config/containers/storage.conf').read_text()
            self.assertIn('rootless_storage_path='+json.dumps(str(root/'images')),config)
            store={'graphRoot':str(root/'images'),'runRoot':str(runroot),'imageStore':{'number':0}}
            require_empty_storage({'store':store},root,runroot)
            for field,value in (('graphRoot',str(root.parent)),('runRoot',str(root.parent)),('imageStore',{'number':1})):
                with self.subTest(field=field),self.assertRaises(ValueError):
                    require_empty_storage({'store':{**store,field:value}},root,runroot)
            with self.assertRaises(ValueError):isolated_storage(root,runroot,{})

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
