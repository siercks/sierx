"""A private root-launcher umask must not alter delivered directory access."""
import hashlib
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from offline_archive import unpack
from test_offline import fixture


class DeliveryArchiveTests(unittest.TestCase):
    def test_exact_delivery_preserves_directory_modes_under_private_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary)
            source=parent/'source'
            source.mkdir(mode=0o755)
            _,lock=fixture(source)
            archive=parent/'delivery.tar.gz'
            with tarfile.open(archive,'w:gz') as stream:stream.add(source,arcname='sierx-offline-amd64')
            checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
            mask=os.umask(0o077)
            try:result=unpack(archive,parent/'extracted',checksum,lock,'amd64')
            finally:os.umask(mask)
            self.assertEqual(result.stat().st_mode & 0o777,0o755)
            self.assertEqual((result/'images').stat().st_mode & 0o777,0o755)
            self.assertTrue(os.access(result/'bin/goose',os.X_OK))

    def test_hostile_or_duplicate_members_are_rejected_before_extraction(self):
        for defect in ('../escape','sierx-offline-amd64/../escape','duplicate','symlink','privileged'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as temporary:
                parent=Path(temporary)
                archive=parent/'delivery.tar'
                with tarfile.open(archive,'w') as stream:
                    entry=tarfile.TarInfo('sierx-offline-amd64/file' if defect in {'duplicate','symlink','privileged'} else defect)
                    if defect=='symlink':entry.type=tarfile.SYMTYPE;entry.linkname='/etc'
                    if defect=='privileged':entry.mode=0o4755
                    stream.addfile(entry,io.BytesIO())
                    if defect=='duplicate':stream.addfile(entry,io.BytesIO())
                checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):unpack(archive,parent/'extracted',checksum,'0'*64,'amd64')
                self.assertFalse((parent/'extracted').exists())
