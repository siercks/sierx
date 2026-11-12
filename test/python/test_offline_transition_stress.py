"""A bounded transition reproduction must never approve a release or retry failure."""
import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import offline_host_evidence as evidence
from offline_host_fixture import full_host_report


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


host=load('stress_host','offline-host.py')
scenarios=load('stress_scenarios','offline-host-scenarios.py')


class TransitionStressTests(unittest.TestCase):
    def setUp(self):
        self.bundle={'arch':'amd64','release':{'image':'ghcr.io/example/sierx@sha256:'+'a'*64,'revision':'b'*40}}
        self.report=full_host_report(self.bundle,'d'*64,'c'*64,'ubuntu-24.04',
            {'release':{'image':'ghcr.io/example/sierx@sha256:'+'e'*64,'revision':'f'*40},'bundle_sha256':'e'*64})

    def test_two_complete_matching_cycles_make_only_a_non_promotion_envelope(self):
        expected=self.report['scenarios']['two_release']
        result=host.transition_stress_envelope(self.report,[copy.deepcopy(expected),copy.deepcopy(expected)])
        self.assertIs(result['release_acceptance'],False)
        self.assertEqual(result['suite'],'offline-transition-stress-v1')
        self.assertEqual(len(result['transition_cycles']),2)
        evidence.validate_closeout(self.report,self.bundle,'d'*64,'c'*64)
        with self.assertRaises(ValueError):evidence.validate_closeout(result,self.bundle,'d'*64,'c'*64)
        raw=copy.deepcopy(self.report);raw['transition_stress']=[expected,expected]
        with self.assertRaises(ValueError):evidence.validate_closeout(raw,self.bundle,'d'*64,'c'*64)

    def test_missing_failed_or_mismatched_cycles_are_never_packaged_as_success(self):
        expected=self.report['scenarios']['two_release']
        failed={**expected,'compatible_rollback':False}
        different={**expected,'previous_bundle_sha256':'0'*64}
        for cycles in (None,[],[expected],[expected]*3,[failed,expected],[expected,failed],[different,expected]):
            with self.subTest(cycles=cycles),self.assertRaises(ValueError):
                host.transition_stress_envelope(self.report,cycles)

    def test_stress_stops_at_first_failed_cycle_without_retrying_or_masking_it(self):
        error=RuntimeError('private synthetic transition failure')
        for failed_cycle in (1,2):
            operation=Mock(side_effect=([{}]*(failed_cycle-1))+[error])
            progress=Mock()
            with patch.object(scenarios,'two_release',operation):
                with self.assertRaises(RuntimeError) as caught:
                    scenarios.transition_stress(None,None,None,None,None,None,progress)
            self.assertIs(caught.exception,error)
            self.assertEqual(operation.call_count,failed_cycle)
            self.assertEqual([c.args[0] for c in progress.call_args_list],
                             ['two-release-stress-'+str(i) for i in range(1,failed_cycle+1)])

    def test_stress_requires_full_normal_scenarios_and_retained_approval(self):
        for flags in ({'development':True},{'runtime_probe':True},{'acquisition_probe':True}):
            values={'transition_stress':True,'development':False,'runtime_probe':False,'acquisition_probe':False,**flags}
            with self.subTest(flags=flags),self.assertRaises(ValueError):host.main(SimpleNamespace(**values))
        launcher=(ROOT/'scripts/offline-host-release.sh').read_text()
        self.assertIn('extra+=(--transition-stress)',launcher)
        self.assertIn('report=$PWD/dist/transition-stress-$profile-$arch.json',launcher)
        self.assertIn('--previous-evidence "$PWD/dist/previous/offline-acceptance-$arch.json"',launcher)

    def test_early_transition_is_counted_once_and_requires_the_full_stress_mode(self):
        earlier = self.report['scenarios']['two_release']
        later = copy.deepcopy(earlier)
        progress = Mock()
        with patch.object(scenarios, 'two_release', return_value=later) as transition:
            cycles = scenarios.transition_stress(None, None, None, None, None, None, progress,
                                                first_cycle=earlier)
        self.assertEqual(cycles, [earlier, later])
        transition.assert_called_once()
        progress.assert_called_once_with('two-release-stress-2')
        with self.assertRaisesRegex(ValueError, 'Early transition requires'):
            host.main(SimpleNamespace(development=False, transition_before_browser=True))
        with self.assertRaisesRegex(ValueError, 'Ordinary installer tracing requires'):
            host.main(SimpleNamespace(development=False, ordinary_installer_trace=True))

    def test_early_transition_probe_validates_exact_inputs_and_cannot_pass_promotion(self):
        bundle = {**self.bundle, 'arch': 'arm64'}
        transition = self.report['scenarios']['two_release']
        retained = {'release': transition['previous']}
        report = {'schema': 1, 'suite': 'offline-transition-probe-v1',
                  'release_acceptance': False, 'result': 'passed',
                  'profile': 'ubuntu-24.04', 'arch': 'arm64', 'release': bundle['release'],
                  'bundle_sha256': 'd'*64, 'suite_sha256': 'c'*64,
                  'virtual_cpus': 4, 'transition': transition}
        evidence.validate_transition_probe(report, bundle, 'd'*64, 'c'*64, retained, 'e'*64)
        for invalid in (
            {**report, 'release_acceptance': True},
            {**report, 'private': 'raw output'},
            {**report, 'transition': {**transition, 'previous_bundle_sha256': '0'*64}},
            {**report, 'transition': {**transition, 'fingerprint_preserved': False}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                evidence.validate_transition_probe(invalid, bundle, 'd'*64, 'c'*64, retained, 'e'*64)
        with self.assertRaises(ValueError):
            evidence.validate_closeout(report, bundle, 'd'*64, 'c'*64)
        with self.assertRaisesRegex(ValueError, 'require --development'):
            host.main(SimpleNamespace(development=False, transition_probe=True))
        with self.assertRaisesRegex(ValueError, 'approved retained release'):
            host.main(SimpleNamespace(development=True, transition_probe=True))

    def test_cold_import_probe_is_bound_to_the_exact_bundle_and_cannot_be_promoted(self):
        bundle = {**self.bundle, 'arch': 'arm64'}
        report = {'schema': 1, 'suite': 'offline-import-probe-v1',
                  'release_acceptance': False, 'result': 'passed',
                  'profile': 'ubuntu-24.04', 'arch': 'arm64', 'release': bundle['release'],
                  'bundle_sha256': 'd'*64, 'suite_sha256': 'c'*64,
                  'virtual_cpus': 4, 'import_complete': True}
        evidence.validate_import_probe(report, bundle, 'd'*64, 'c'*64)
        for change in ({'release_acceptance': True}, {'import_complete': False}, {'arch': 'amd64'},
                       {'bundle_sha256': 'e'*64}, {'private': 'raw output'}):
            with self.assertRaises(ValueError):
                evidence.validate_import_probe({**report, **change}, bundle, 'd'*64, 'c'*64)
        with self.assertRaises(ValueError):
            evidence.validate_closeout(report, bundle, 'd'*64, 'c'*64)
        with self.assertRaisesRegex(ValueError, 'require --development'):
            host.main(SimpleNamespace(development=False, import_probe=True))
        with self.assertRaisesRegex(ValueError, 'approved retained release'):
            host.main(SimpleNamespace(development=True, import_probe=True))


if __name__=='__main__':unittest.main()
