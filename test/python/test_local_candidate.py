"""Local PR candidates retain exact OCI identity without registry publication."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from local_candidate import identity


class LocalCandidateTests(unittest.TestCase):
    def archive(self,path,defect=None):
        config={'os':'linux','architecture':'amd64','config':{'Labels':{'org.opencontainers.image.revision':'a'*40}}}
        if defect=='platform':config['architecture']='unknown'
        if defect=='revision':config['config']['Labels']={}
        content=json.dumps(config).encode()
        config_hash=hashlib.sha256(content).hexdigest()
        manifest=json.dumps({'schemaVersion':2,'config':{'digest':'sha256:'+config_hash},'layers':[]}).encode()
        digest=hashlib.sha256(manifest).hexdigest()
        index={'schemaVersion':2,'manifests':[{'digest':'sha256:'+digest}]}
        if defect=='multiple':index['manifests']*=2
        with tarfile.open(path,'w') as archive:
            for name,data in {'index.json':json.dumps(index).encode(),'blobs/sha256/'+digest:manifest,
                              'blobs/sha256/'+config_hash:b'tampered' if defect=='tamper' else content}.items():
                member=tarfile.TarInfo(name)
                member.size=len(data)
                archive.addfile(member,io.BytesIO(data))
        return {'manifest':'sha256:'+digest,'id':'sha256:'+config_hash,'arch':'amd64','revision':'a'*40}

    def test_manifest_configuration_and_revision_are_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'candidate.tar'
            expected=self.archive(path)
            self.assertEqual(identity(path),expected)

    def test_tampered_metadata_wrong_platform_and_missing_revision_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'candidate.tar'
            for defect in ('tamper','platform','revision','multiple'):
                self.archive(path,defect)
                with self.subTest(defect=defect),self.assertRaises(ValueError):identity(path)


if __name__=='__main__':unittest.main()
