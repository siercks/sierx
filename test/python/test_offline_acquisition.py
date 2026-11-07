"""An acquisition failure must retain its operation during server cleanup."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
import offline_host_diagnostics as diagnostics
spec = importlib.util.spec_from_file_location('registry_fixture', ROOT/'scripts/offline-local-registry.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


class AcquisitionTests(unittest.TestCase):
    def test_failure_phase_survives_server_cleanup_without_leaking_command(self):
        for operation, phase in (('info','store-info'), ('images','empty-store'),
                                 ('pull','pull'), ('image','inspect')):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                (home/'bundle/images').mkdir(parents=True)
                ca = home/'ca.crt'
                ca.write_text('synthetic certificate')
                with tarfile.open(home/'bundle/images/app.tar','w') as archive:
                    data = json.dumps({'manifests':[{'digest':'sha256:'+'a'*64}]}).encode()
                    entry = tarfile.TarInfo('index.json')
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
                phases = []
                error = RuntimeError('private credential')
                error.fixture_exit_code = 125

                def run(*args, **kwargs):
                    if args[1] == operation:
                        raise error
                    if args[1] == 'info':
                        return json.dumps({'store':{'graphRoot':str(home/'acquisition-store/images'),
                            'runRoot':str(home/'runtime/acquisition-store'), 'imageStore':{'number':0}}})
                    if args[1] == 'images':
                        return '[]'
                    return ''

                server = MagicMock()
                with patch.object(registry, 'ThreadingHTTPServer', return_value=server), \
                        patch.object(registry.ssl, 'SSLContext'), \
                        patch.object(registry.threading, 'Thread') as thread, \
                        self.assertRaises(RuntimeError) as caught:
                    registry.main(home/'bundle', {'images':{'app':{'id':'fixture-id'}}},
                        {'XDG_RUNTIME_DIR':str(home/'runtime'),'SSL_CERT_FILE':str(ca)},
                        run, phases.append, fixture_home=home)
                self.assertIs(caught.exception, error)
                self.assertEqual(phases[-1], 'acquisition-'+phase)
                self.assertTrue(set(phases) <= diagnostics.FAILURE_PHASES)
                server.shutdown.assert_called_once()
                server.server_close.assert_called_once()
                thread.return_value.join.assert_called_once()
                failure = diagnostics.failure_record(error, phases[-1])
                self.assertNotIn('private', json.dumps(failure))
                self.assertEqual(failure['command_exit_code'], 125)


if __name__ == '__main__':
    unittest.main()
