"""Private invalid-delivery fixtures; approved source files are never modified."""
import hashlib
import json
import os
from pathlib import Path
import shutil


def invalid_bundles(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Invalid fixtures require a fresh separate destination')
    data = json.loads((source/'bundle.lock.json').read_text())
    original = hashlib.sha256((source/'bundle.lock.json').read_bytes()).hexdigest()
    destination.mkdir(mode=0o755)
    hashes = {}
    for name in ('missing-image','altered-archive','wrong-architecture'):
        root = destination/name
        shutil.copytree(source,root,copy_function=os.link)
        hashes[name] = original
        if name == 'missing-image':
            (root/'images/app.tar').unlink()
        elif name == 'altered-archive':
            path = root/'images/app.tar'
            path.unlink()  # Never write through a shared inode.
            path.write_bytes(b'Deliberately damaged synthetic archive\n')
            path.chmod(0o644)
        else:
            path = root/'bundle.lock.json'
            path.unlink()
            path.write_text(json.dumps({**data,'arch':'arm64' if data['arch']=='amd64' else 'amd64'}))
            path.chmod(0o644)
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes
