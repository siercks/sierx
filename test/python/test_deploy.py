"""Release input and rendering controls; host acceptance is a separate run."""
import importlib.util
import pathlib
import tempfile
import unittest
import os
import io
import json
import contextlib
from unittest import mock
from urllib.error import URLError

spec=importlib.util.spec_from_file_location('deploy',pathlib.Path(__file__).parents[2]/'scripts/deploy.py')
deploy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

class DeploymentTests(unittest.TestCase):
    def test_every_unit_has_an_installer_and_restore_runs_on_host(self):
        deploy.unit_inventory()
        for mode in deploy.TIMERS:
            files = deploy.timer_files(mode, {"SIERX_CHECKOUT": "/opt/sierx", "SIERX_OPERATOR_BIN": "/opt/accepted/sierxctl"})
            self.assertEqual(len(files), 2)
        restore = deploy.timer_files("install-restore-timer", {"SIERX_CHECKOUT": "/opt/sierx", "SIERX_OPERATOR_BIN": "/opt/accepted/sierxctl"})["sierx-restoretest.service"]
        self.assertIn('"/opt/accepted/sierxctl" restore-test', restore)
        self.assertNotIn("podman exec", restore)
        self.assertIn("WorkingDirectory=/opt/sierx", restore)
        with mock.patch.dict(deploy.UNIT_INSTALLERS, {"unshipped.timer": "manual"}):
            with self.assertRaises(ValueError): deploy.unit_inventory()
    def test_pinned_release(self):
        release={'image':'example.test/team/sierx@sha256:'+'a'*64,'revision':'b'*40}
        self.assertEqual(deploy.validate_manifest(release,'example.test/team/sierx'),release)
        for bad in [None,[],{},dict(release,image='example.test/team/sierx:latest'),dict(release,image='other.test/sierx@sha256:'+'a'*64),dict(release,revision='main'),dict(release,revision=1),dict(release,command='unexpected')]:
            with self.subTest(bad=bad),self.assertRaises(ValueError): deploy.validate_manifest(bad,'example.test/team/sierx')
    def test_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            path=pathlib.Path(root)/'nested/current.json'
            deploy.atomic(path,'old');deploy.atomic(path,'new')
            self.assertEqual(path.read_text(),'new')
            self.assertFalse(path.with_name('current.json.pending').exists())
    def test_templates_require_complete_inputs(self):
        with self.assertRaises(ValueError): deploy.render('deploy/quadlet/sierx.container.tmpl',{})
        text=deploy.render('deploy/quadlet/sierx.container.tmpl',{'SIERX_IMAGE':'example.test/sierx@sha256:'+'a'*64})
        self.assertIn('ReadOnly=true',text)
        self.assertIn('Network=host',text)
        self.assertNotIn('@SIERX_',text)
        gateway=deploy.render('deploy/Caddyfile.tmpl',{'SIERX_HOST':'example.test','SIERX_APP_PORT':'8080'})
        self.assertIn('h1 h2 h3',gateway)
        self.assertIn('127.0.0.1:8080',gateway)

class RollbackTests(unittest.TestCase):
    def test_failed_health_restores_previous_units_or_stops_first_install(self):
        for existing in [False,True]:
            with self.subTest(existing=existing),tempfile.TemporaryDirectory() as temporary:
                home=pathlib.Path(temporary)
                config=home/'.config/sierx';config.mkdir(parents=True)
                app=config/'app.env';app.write_text('SIERX_LISTEN_ADDR=127.0.0.1:8080\nSIERX_BASE_URL=https://example.test\n')
                units=home/'.config/containers/systemd';units.mkdir(parents=True)
                old=units/'sierx.container'
                if existing:old.write_text('prior accepted unit')
                release={'image':'example.test/sierx@sha256:'+'a'*64,'revision':'b'*40}
                response=mock.MagicMock();response.__enter__.return_value=response;response.read.return_value=json.dumps(release).encode()
                real_stat=pathlib.Path.stat
                def private_stat(path,*args,**kwargs):
                    result=real_stat(path,*args,**kwargs)
                    if path==app:
                        fields=list(result);fields[0]=0o100600;return os.stat_result(fields)
                    return result
                commands=[]
                def run(*args):
                    commands.append(args)
                    if args[:3]==('podman','image','inspect'):return json.dumps([{'Labels':{'org.opencontainers.image.revision':release['revision']}}])
                    if args[:2]==('podman','create'):return 'test-container'
                    if args[:2]==('podman','cp'):(pathlib.Path(args[-1])/'test-hash.js').write_text('fixture')
                    return ''
                environment={'SIERX_DEPLOY_MANIFEST_URL':'https://example.test/release.json','SIERX_IMAGE_REPOSITORY':'example.test/sierx','SIERX_BASE_URL':'https://example.test','SIERX_APP_PORT':'8080','SIERX_CADDY_IMAGE':'example.test/caddy@sha256:'+'c'*64}
                with mock.patch.dict(os.environ,environment),mock.patch.object(pathlib.Path,'home',return_value=home),mock.patch.object(pathlib.Path,'stat',private_stat),mock.patch.object(deploy,'run',side_effect=run),mock.patch.object(deploy.time,'sleep'),mock.patch.object(deploy.urllib.request,'urlopen',side_effect=[response]+[URLError('offline')]*20),contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(URLError):deploy.main('apply')
                self.assertFalse((home/'.local/share/sierx/current.json').exists())
                if existing:self.assertEqual(old.read_text(),'prior accepted unit')
                else:
                    self.assertFalse(old.exists())
                    self.assertIn(('systemctl','--user','stop','sierx.service','sierx-caddy.service'),commands)

if __name__=='__main__':unittest.main()
