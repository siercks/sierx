"""Negative controls for the Phase 3 acceptance scaffold."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('phase3', Path(__file__).parents[2] / 'scripts/phase3.py')
phase3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase3)


class Phase3EvidenceTest(unittest.TestCase):
    def test_missing_stale_and_incomplete_evidence(self):
        revision = 'a' * 40
        report = {
            'revision': revision,
            'checks': {name: {'result': 'passed', 'evidence': 'synthetic proof only'}
                       for name in phase3.SCENARIOS},
            'reference_hardware': 'synthetic test', 'iphone_safari': 'synthetic test',
            'owner_review': 'synthetic test',
            'board_benchmark': {'fixture': 'synthetic', 'request_scope': 'synthetic',
                'sampling': 'synthetic', 'first_load': 'synthetic', 'additional_page': 'synthetic',
                'item_count': 500, 'server_p95_ms': 149},
        }
        phase3.validate_evidence(report, revision)  # baseline must pass first
        with self.assertRaisesRegex(ValueError, 'not for this commit'):
            phase3.validate_evidence(report, 'b' * 40)
        for name in phase3.SCENARIOS:
            planted = copy.deepcopy(report)
            planted['checks'][name]['result'] = 'deferred'
            with self.assertRaisesRegex(ValueError, name):
                phase3.validate_evidence(planted, revision)
        for name in ('reference_hardware', 'iphone_safari', 'owner_review'):
            planted = copy.deepcopy(report)
            del planted[name]
            with self.assertRaisesRegex(ValueError, name):
                phase3.validate_evidence(planted, revision)
        for p95 in (150, 200, 0, -1, None, True, float('nan'), float('inf')):
            planted = copy.deepcopy(report)
            planted['board_benchmark']['server_p95_ms'] = p95
            with self.assertRaisesRegex(ValueError, 'p95'):
                phase3.validate_evidence(planted, revision)


if __name__ == '__main__':
    unittest.main()
