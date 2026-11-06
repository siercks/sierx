"""Extract a checksum-approved delivery archive into a fresh owned directory."""
from pathlib import Path
import re
import tarfile
import offline


def unpack(archive,directory,expected_archive,expected_lock,arch):
    archive,directory=Path(archive),Path(directory)
    if not re.fullmatch(r'[a-f0-9]{64}',expected_archive or '') or offline.digest(archive)!=expected_archive:
        raise ValueError('Delivery archive differs from the independently supplied checksum')
    if directory.exists():raise ValueError('Delivery extraction requires a fresh separate directory')
    stem='sierx-offline-'+arch
    with tarfile.open(archive) as stream:
        seen=set()
        for entry in stream.getmembers():
            name=entry.name.rstrip('/') if entry.isdir() else entry.name
            parts=name.split('/')
            if (not parts or parts[0]!=stem or any(part in {'','.','..'} for part in parts)
                    or name in seen or not (entry.isdir() or entry.isfile()) or entry.mode & 0o7000):
                raise ValueError('Delivery archive contains an unsafe, duplicate or privileged member')
            seen.add(name)
        directory.mkdir(mode=0o700)
        stream.extractall(directory,filter='data')
        # Python's data filter deliberately omits directory permissions. Restore
        # the vetted archive modes: the root launcher has a private umask, while
        # the actual installer must traverse the delivered public source tree.
        for entry in stream.getmembers():
            if entry.isdir():(directory/entry.name).chmod(entry.mode & 0o777)
    root=directory/stem
    offline.verify(root,expected_lock,arch)
    return root
