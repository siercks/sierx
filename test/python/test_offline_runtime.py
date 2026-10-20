"""Runtime failures retain their fixed phase and cannot yield passing evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('runtime_scenarios',ROOT/'scripts/offline-host-scenarios.py')
scenarios=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenarios)


class RuntimeTests(unittest.TestCase):
    def exercise(self,fail=None):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)
            bundle=home/'bundle'
            (bundle/'deploy/quadlet').mkdir(parents=True)
            (bundle/'deploy/quadlet/sierx-maintenance.service').write_text(
                (ROOT/'deploy/quadlet/sierx-maintenance.service').read_text())
            clock=[0]
            phases=[]
            def run(*args):
                if args[2]==fail:raise RuntimeError('private synthetic command failure')
                if args[2]=='show':return 'success' if '--property=Result' in args else '1'
                if args[2]=='list-units':return json.dumps([{'unit':n+'.service'} for n in ('sierx','sierx-postgres','sierx-caddy')])
                if args[2]=='list-timers':return json.dumps([{'unit':'sierx-acceptance-maintenance.timer'}])
                return ''
            def request(path):clock[0]+=1
            def sleep(seconds):clock[0]+=seconds
            with mock.patch.object(scenarios,'HOME',home),mock.patch.object(scenarios,'rejection'), \
                    mock.patch.object(scenarios.time,'monotonic',side_effect=lambda:clock[0]), \
                    mock.patch.object(scenarios.time,'sleep',side_effect=sleep):
                try:
                    result=scenarios.runtime(bundle,120,{},run,home/'private.log',request,phases.append)
                except RuntimeError:
                    return None,phases
                return result,phases

    def test_failure_is_not_converted_to_success_and_progress_contains_no_private_cause(self):
        for command,label in (('daemon-reload','reload-units'),('list-units','inventory-services'),('list-timers','inventory-timers')):
            with self.subTest(command=command):
                result,phases=self.exercise(command)
                self.assertIsNone(result)
                self.assertEqual(phases[-1],'runtime-'+label)
                self.assertNotIn('private',' '.join(phases))

    def test_observation_and_real_unit_inventory_remain_required(self):
        result,phases=self.exercise()
        self.assertGreaterEqual(result['elapsed_seconds'],120)
        self.assertGreaterEqual(result['change_feed_polls'],3)
        self.assertIn('sierx.service',result['services'])
        self.assertIn('sierx-acceptance-maintenance.timer',result['timers'])
        self.assertIn('runtime-verify-maintenance',phases)


if __name__=='__main__':unittest.main()
