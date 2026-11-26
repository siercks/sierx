"""Smoke errors retain fixed source/status evidence, never credentials or paths."""
import http.client,importlib.util,json,os,socket,ssl,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import offline_smoke_trace as smoke
import offline_host_diagnostics as diagnostics


class SmokeTraceTests(unittest.TestCase):
    def stalled_peer(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(2)
        stop=threading.Event()
        def hold():
            try:
                connection,_=listener.accept()
                with connection:stop.wait(2)
            except OSError:pass
        thread=threading.Thread(target=hold);thread.start()
        self.addCleanup(lambda:thread.join(timeout=3))
        self.addCleanup(listener.close);self.addCleanup(stop.set)
        return listener.getsockname()

    def test_real_http_timeout_is_classified_before_response_headers(self):
        host,port=self.stalled_peer();client=http.client.HTTPConnection(host,port,timeout=0.05)
        self.addCleanup(client.close);client.request('GET','/private-credential')
        try:client.getresponse()
        except TimeoutError as error:
            self.assertEqual(smoke.io_stage(error,error.__traceback__),'response-headers')
            self.assertEqual(diagnostics.classify_https_failure(error,'login')['io_stage'],'response-headers')
        else:self.fail('Controlled peer unexpectedly supplied an HTTP response')

    def test_real_tls_handshake_timeout_is_distinct_from_an_http_response_timeout(self):
        address=self.stalled_peer();connection=socket.create_connection(address,timeout=0.05)
        self.addCleanup(connection.close)
        try:ssl.create_default_context().wrap_socket(connection,server_hostname='localhost')
        except TimeoutError as error:
            self.assertEqual(smoke.io_stage(error,error.__traceback__),'tls-handshake')
            self.assertEqual(diagnostics.classify_https_failure(error,'login')['io_stage'],'tls-handshake')
        else:self.fail('Controlled peer unexpectedly supplied a TLS handshake')

    def test_direct_login_failure_preserves_only_safe_stage_and_known_timeout_class(self):
        failure={'result':'failed','phase':'https-data-check','failure_type':'TimeoutError',
            'https_failure':{'step':'login','kind':'timeout','io_stage':'tls-handshake','private':'credential'}}
        safe=diagnostics.sanitize_failure(diagnostics.sanitize_failure(failure))
        self.assertEqual(safe['failure_type'],'TimeoutError')
        self.assertEqual(safe['https_failure'],{'step':'login','kind':'timeout','io_stage':'tls-handshake'})
        self.assertNotIn('credential',json.dumps(safe))
        self.assertNotIn('io_stage',diagnostics.sanitize_https_failure({**failure['https_failure'],'io_stage':'private-credential'}))

    def test_request_routes_reduce_to_fixed_labels(self):
        for path,label in (('/api/v1/auth/login','login'),('/api/v1/me','account'),
            ('/api/v1/items/PRIVATE-42','item'),('/PRIVATE-42','item-document'),
            ('/?q=private-secret','query-document'),('/private-credential','unknown')):
            self.assertEqual(smoke.request_step(path),label)

    def test_sanitization_and_double_failure_pipeline_drop_private_fields(self):
        value={'step':'login','kind':'HTTPError','lines':[24,27],'http_status':503,
            'transport':'other','io_stage':'response-headers','private':'credential','url':'https://private','headers':{'key':'secret'}}
        safe=smoke.sanitize(value)
        failure={'result':'failed','phase':'two-release-apply-previous','failure_type':'RuntimeError',
            'command_exit_code':1,'smoke_failure':value}
        result=diagnostics.sanitize_failure(diagnostics.sanitize_failure(failure))
        self.assertEqual(result['smoke_failure'],safe)
        self.assertNotIn('credential',json.dumps(result));self.assertNotIn('private',json.dumps(result))
        self.assertNotIn('smoke_failure',diagnostics.sanitize_failure({**failure,'command_exit_code':0}))
        for changed in ({'lines':[True]},{'step':'private'},{'kind':'private'},{'lines':[]}):
            self.assertIsNone(smoke.sanitize({**value,**changed}))

    def test_duplicate_oversized_and_private_markers_are_rejected(self):
        line=(smoke.MARKER+json.dumps({'step':'account','kind':'ValueError','lines':[40]})+'\n').encode()
        self.assertEqual(smoke.stderr_failure(line)['step'],'account')
        for value in (line+line,b'x'*8193,(smoke.MARKER+'private\n').encode()):
            self.assertIsNone(smoke.stderr_failure(value))

    def test_actual_copied_startup_hook_preserves_failure_status_and_original_stdio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);trace=root/'trace';trace.mkdir()
            (trace/'sitecustomize.py').write_bytes((ROOT/'scripts/offline_apply_trace.py').read_bytes())
            (root/'offline_smoke_trace.py').write_bytes((ROOT/'scripts/offline_smoke_trace.py').read_bytes())
            source=root/'release-smoke.py'
            source.write_text('import sys\ntry:\n raise ValueError("private-credential")\nexcept ValueError:\n sys.exit("fixed original error")\n')
            env={**os.environ,'PYTHONPATH':str(trace),'SIERX_DIAGNOSTIC_SMOKE':str(source)}
            before=subprocess.run([sys.executable,'-B',str(source)],env={k:v for k,v in env.items() if k!='SIERX_DIAGNOSTIC_SMOKE'},capture_output=True)
            after=subprocess.run([sys.executable,'-B',str(source)],env=env,capture_output=True)
            self.assertEqual(before.returncode,after.returncode);self.assertEqual(before.stdout,after.stdout)
            self.assertEqual(b'\n'.join(line for line in after.stderr.split(b'\n') if not line.startswith(smoke.MARKER.encode())),before.stderr)
            marker=smoke.stderr_failure(after.stderr)
            self.assertEqual(marker['kind'],'ValueError');self.assertNotIn('private',json.dumps(marker))
