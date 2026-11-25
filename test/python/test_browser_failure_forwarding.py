"""Browser labels must survive the actual sanitized artifact boundary."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import offline_host_diagnostics as diagnostics
import offline_host_evidence as evidence
spec=importlib.util.spec_from_file_location('browser_failure_host',ROOT/'scripts/offline-host.py')
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)


class BrowserFailureForwardingTests(unittest.TestCase):
    def test_host_browser_detail_survives_workflow_re_sanitization_without_private_messages(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'report.json'
            private=b'credential and private traceback\noffline-browser: failed at firefox-comment (AssertionError); no passing report\n'
            private+=b'offline-browser: reason ambiguous-locator\noffline-browser: matcher toBeVisible\noffline-browser: http-status 503\n'
            host.record_failure(path,{'result':'failed','phase':'delivered-browser-workflows',
                'failure_type':'RuntimeError','command_exit_code':1},private,'arm64','c'*64,'a'*40)
            # This is the workflow's second sanitizer, which used to drop
            # every previously parsed browser detail.
            uploaded=diagnostics.sanitize_failure(json.loads(path.with_suffix('.failure.json').read_text()))
            self.assertEqual(uploaded.get('browser_failure'),{'phase':'firefox-comment','error':'AssertionError',
                'reason':'ambiguous-locator','matcher':'toBeVisible','http_statuses':[503]})
            self.assertNotIn('credential',json.dumps(uploaded))
            self.assertNotIn('traceback',json.dumps(uploaded))

    def test_early_guest_exception_capture_is_idempotent_and_drops_unknown_fields(self):
        error=RuntimeError('private message')
        error.browser_failure={'phase':'chromium-login-submit','error':'TimeoutError',
            'reason':'wait-timeout','private':'credential','http_statuses':[503]}
        failure=diagnostics.failure_record(error,'delivered-browser-workflows')
        self.assertEqual(failure.get('browser_failure'),{'phase':'chromium-login-submit','error':'TimeoutError',
            'reason':'wait-timeout','http_statuses':[503]})
        self.assertEqual(diagnostics.sanitize_failure(failure),failure)
        self.assertNotIn('credential',json.dumps(failure))
        self.assertNotIn('browser_failure',diagnostics.failure_record(error,'import'))

    def test_unknown_browser_labels_and_noninteger_statuses_are_not_forwarded(self):
        for value in ({'phase':'private','error':'Error'}, {'phase':'firefox-login','error':'PrivateError'}):
            self.assertIsNone(evidence.sanitize_browser_failure(value))
        value=evidence.sanitize_browser_failure({'phase':'firefox-login','error':'Error',
            'reason':'credential','matcher':'credential','http_statuses':[True,'503',999],
            'private':'credential'})
        self.assertEqual(value,{'phase':'firefox-login','error':'Error'})
