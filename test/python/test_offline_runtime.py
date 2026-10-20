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
import offline_host_evidence as evidence
spec=importlib.util.spec_from_file_location('runtime_scenarios',ROOT/'scripts/offline-host-scenarios.py')
scenarios=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenarios)


class RuntimeTests(unittest.TestCase):
    def exercise(self,fail=None,emulated=False,inventory_delay=0,active_state='inactive'):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)
            bundle=home/'bundle'
            (bundle/'deploy/quadlet').mkdir(parents=True)
            (bundle/'deploy/quadlet/sierx-maintenance.service').write_text(
                (ROOT/'deploy/quadlet/sierx-maintenance.service').read_text())
            clock=[0]
            phases=[]
            def run(*args,**kwargs):
                if args[2]==fail:raise RuntimeError('private synthetic command failure')
                if args[2]=='show':return 'Result=success\nActiveState='+active_state+'\nExecMainStatus=0\nExecMainStartTimestampMonotonic=1'
                if args[2]=='list-units':return json.dumps([{'unit':n+'.service'} for n in ('sierx','sierx-postgres','sierx-caddy')])
                if args[2]=='list-timers':return json.dumps([{'unit':'sierx-acceptance-maintenance.timer'}])
                if args[2]=='list-unit-files':
                    self.assertEqual(kwargs['env'].get('SYSTEMD_BUS_TIMEOUT'),'180s' if emulated else None)
                    clock[0]+=inventory_delay
                return ''
            def request(path):clock[0]+=1
            def sleep(seconds):clock[0]+=seconds
            with mock.patch.object(scenarios,'HOME',home),mock.patch.object(scenarios,'rejection'), \
                    mock.patch.object(scenarios.time,'monotonic',side_effect=lambda:clock[0]), \
                    mock.patch.object(scenarios.time,'sleep',side_effect=sleep):
                try:
                    env={'SIERX_TEST_EMULATED':'1' if emulated else '0','SYSTEMD_BUS_TIMEOUT':'999999s'}
                    result=scenarios.runtime(bundle,120,env,run,home/'private.log',request,phases.append)
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
        evidence.validate_runtime(result)

    def test_slow_emulated_inventory_is_not_counted_as_runtime_observation(self):
        result,_=self.exercise(emulated=True,inventory_delay=70)
        self.assertGreaterEqual(result['elapsed_seconds'],120)
        self.assertLessEqual(result['elapsed_seconds'],180)
        self.assertEqual(result['inventory_seconds'],70)
        self.assertEqual(result['unit_file_inventory_seconds'],70)
        evidence.validate_runtime(result,emulated=True)
        with self.assertRaises(ValueError):evidence.validate_runtime(result)
        result,_=self.exercise(inventory_delay=70)
        with self.assertRaises(ValueError):evidence.validate_runtime(result)

    def test_unfinished_maintenance_cannot_report_success(self):
        with self.assertRaisesRegex(ValueError,'maintenance failed'):
            self.exercise(active_state='activating')

    def test_inventory_timing_and_actual_mode_are_required(self):
        result,_=self.exercise()
        for name,value in (('elapsed_seconds',1),('inventory_seconds',float('nan')),
                           ('unit_file_inventory_seconds',500),('unit_file_bus_timeout_seconds',180),
                           ('maintenance_completed',False)):
            with self.subTest(name=name),self.assertRaises(ValueError):
                evidence.validate_runtime({**result,name:value})


if __name__=='__main__':unittest.main()
