"""Private invalid-delivery fixtures; approved source files are never modified."""
import hashlib
import json
import os
from pathlib import Path
import shutil


def isolated_storage(directory,runroot,env):
    """Use the user config path: older Podman ignores graphroot via its env override."""
    directory,runroot=Path(directory),Path(runroot)
    if directory.exists() or not directory.is_absolute() or not runroot.is_absolute():
        raise ValueError('Isolated storage requires a fresh absolute directory')
    config=directory/'config/containers'
    config.mkdir(parents=True,mode=0o700)
    graph=directory/'images'
    (config/'storage.conf').write_text('[storage]\ndriver="vfs"\ngraphroot='+json.dumps(str(graph))+
        '\nrootless_storage_path='+json.dumps(str(graph))+'\nrunroot='+json.dumps(str(runroot))+'\n')
    isolated={**env,'XDG_CONFIG_HOME':str(directory/'config')}
    isolated.pop('CONTAINERS_STORAGE_CONF',None)
    return isolated


def require_empty_storage(info,directory,runroot):
    store=info['store']
    if (Path(store['graphRoot']).resolve()!=(Path(directory)/'images').resolve()
            or Path(store['runRoot']).resolve()!=Path(runroot).resolve()
            or store['imageStore']['number']!=0):
        raise ValueError('Podman did not select the separate empty image/runtime store')


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
