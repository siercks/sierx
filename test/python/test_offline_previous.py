"""Retained-release evidence is explicit, immutable and independently checked."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import offline
from test_offline import fixture
spec=importlib.util.spec_from_file_location('previous',ROOT/'scripts/offline-previous.py')
previous=importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)


class PreviousReleaseTests(unittest.TestCase):
    def setup_fixture(self,parent,hostile=False):
        source=parent/'source'
        source.mkdir()
        data,digest=fixture(source)
        archive=parent/'sierx-offline-amd64.tar.gz'
        with tarfile.open(archive,'w:gz') as stream:
            if hostile:
                entry=tarfile.TarInfo('sierx-offline-amd64/../../escape')
                stream.addfile(entry)
            else:
                stream.add(source,arcname='sierx-offline-amd64')
        report={**{key:data[key] for key in ('arch','release')},'bundle_sha256':digest,
                'external_interfaces':[],'checks':offline.ACCEPTANCE_CHECKS,'result':'passed'}
        (parent/'offline-acceptance-amd64.json').write_text(json.dumps(report))
        return {'schema':1,'revision':data['release']['revision'],'architectures':{'amd64':{
            'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'bundle_sha256':digest,'release':data['release']}}}

    def test_exact_approved_release_and_matching_baseline_evidence_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary)
            approval=self.setup_fixture(parent)
            target=previous.verify(parent,approval,'amd64')
            self.assertEqual(target.name,'sierx-offline-amd64')
            path=parent/'offline-acceptance-amd64.json'
            report=json.loads(path.read_text())
            report['checks']=[]
            path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):previous.verify(parent,approval,'amd64')

    def test_archive_tamper_and_traversal_cannot_be_extracted(self):
        for hostile in (False,True):
            with self.subTest(hostile=hostile),tempfile.TemporaryDirectory() as temporary:
                parent=Path(temporary)
                approval=self.setup_fixture(parent,hostile)
                if not hostile:
                    with (parent/'sierx-offline-amd64.tar.gz').open('ab') as stream:stream.write(b'tampered')
                with self.assertRaises(ValueError):previous.verify(parent,approval,'amd64')
                self.assertFalse((parent/'sierx-offline-amd64').exists())


if __name__=='__main__':unittest.main()
