"""Identify a native local OCI candidate without publishing it to a registry."""
import hashlib
import json
from pathlib import Path
import re
import tarfile


def identity(path):
    with tarfile.open(path) as archive:
        def document(name, expected=None):
            member=archive.getmember(name)
            if not member.isfile() or member.size > 4*1024*1024:
                raise ValueError('OCI candidate metadata must be a bounded regular file')
            content=archive.extractfile(member).read()
            if expected and hashlib.sha256(content).hexdigest()!=expected:
                raise ValueError('OCI candidate metadata digest mismatch')
            return json.loads(content)
        index=document('index.json')
        if index.get('schemaVersion')!=2 or len(index.get('manifests',[]))!=1:
            raise ValueError('Local candidate must contain exactly one native image')
        digest=index['manifests'][0].get('digest','')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',digest):
            raise ValueError('Invalid local OCI manifest digest')
        manifest=document('blobs/sha256/'+digest[7:],digest[7:])
        config=manifest.get('config',{}).get('digest','')
        if manifest.get('schemaVersion')!=2 or not re.fullmatch(r'sha256:[a-f0-9]{64}',config):
            raise ValueError('Invalid local OCI image configuration')
        metadata=document('blobs/sha256/'+config[7:],config[7:])
        if metadata.get('os')!='linux' or metadata.get('architecture') not in {'amd64','arm64'}:
            raise ValueError('Unsupported local candidate platform')
        revision=metadata.get('config',{}).get('Labels',{}).get('org.opencontainers.image.revision','')
        if not re.fullmatch(r'[a-f0-9]{40}',revision):
            raise ValueError('Local candidate is missing its committed source revision')
        return {'manifest':digest,'id':config,'arch':metadata['architecture'],'revision':revision}
