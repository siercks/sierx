"""Explicit acquisition from a synthetic HTTPS registry, inside the no-NIC VM.

Only already-approved OCI blobs are served over loopback. This is a separate
opt-in scenario; normal offline installation never references this registry.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import tarfile
import threading
from offline_host_inputs import isolated_storage, require_empty_storage


def main(bundle, lock, env, run):
    home=Path(os.environ['HOME'])
    archive=bundle/'images/app.tar'
    with tarfile.open(archive) as stream:
        index=json.load(stream.extractfile('index.json'))
    if len(index.get('manifests',[]))!=1:
        raise ValueError('Synthetic acquisition requires one explicit native manifest')
    manifest=index['manifests'][0]
    digest=manifest['digest']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',digest):
        raise ValueError('Invalid synthetic registry manifest')
    counts={'manifest':0,'blob':0}
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_HEAD(self):self.document(False)
        def do_GET(self):self.document(True)
        def document(self,body):
            if self.path in {'/v2/','/v2'}:
                self.send_response(200)
                self.send_header('Content-Length','2')
                self.send_header('Docker-Distribution-API-Version','registry/2.0')
                self.end_headers()
                if body:self.wfile.write(b'{}')
                return
            if self.path=='/v2/sierx/manifests/'+digest:
                name='blobs/sha256/'+digest[7:]
                kind='manifest'
                media=manifest.get('mediaType','application/vnd.oci.image.manifest.v1+json')
                blob_digest=digest
            else:
                match=re.fullmatch(r'/v2/sierx/blobs/(sha256:[a-f0-9]{64})',self.path)
                if not match:
                    self.send_error(404)
                    return
                blob_digest=match[1]
                name='blobs/sha256/'+blob_digest[7:]
                kind='blob'
                media='application/octet-stream'
            with tarfile.open(archive) as stream:
                try:member=stream.getmember(name)
                except KeyError:
                    self.send_error(404)
                    return
                if not member.isfile():
                    self.send_error(400)
                    return
                self.send_response(200)
                self.send_header('Content-Length',str(member.size))
                self.send_header('Content-Type',media)
                self.send_header('Docker-Content-Digest',blob_digest)
                self.end_headers()
                if body:
                    counts[kind]+=1
                    shutil.copyfileobj(stream.extractfile(member),self.wfile)
    server=ThreadingHTTPServer(('127.0.0.1',19444),Handler)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(home/'.config/sierx/tls/server.crt',home/'.config/sierx/tls/server.key')
    server.socket=tls.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    storage,runroot=home/'acquisition-store',Path(env['XDG_RUNTIME_DIR'])/'acquisition-store'
    certs=home/'acquisition-trust'
    certs.mkdir()
    shutil.copyfile(Path(env['SSL_CERT_FILE']),certs/'ca.crt')
    auth=home/'acquisition-auth.json'
    auth.write_text('{"auths":{}}')
    isolated=isolated_storage(storage,runroot,env)
    def acquire(*args):return run(*args,env=isolated)
    try:
        require_empty_storage(json.loads(acquire('podman','info','--format','json')),storage,runroot)
        if json.loads(acquire('podman','images','--format','json')):
            raise ValueError('Synthetic acquisition store was not empty')
        source='localhost:19444/sierx@'+digest
        acquire('podman','pull','--retry=0','--tls-verify=true','--cert-dir',certs,'--authfile',auth,source)
        metadata=json.loads(acquire('podman','image','inspect',lock['images']['app']['id']))[0]
        if (metadata['Id'].removeprefix('sha256:')!=lock['images']['app']['id'].removeprefix('sha256:')
                or metadata['Labels']['org.opencontainers.image.revision']!=lock['release']['revision']
                or not counts['manifest'] or not counts['blob']):
            raise ValueError('Explicit acquisition did not fetch the approved native image over trusted HTTPS')
        return {'result':'passed','opt_in':True,'source':'synthetic-loopback-registry','https_verified':True,
                'empty_store':True,'image_identity_verified':True,'manifest_requests':counts['manifest'],
                'blob_requests':counts['blob']}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
