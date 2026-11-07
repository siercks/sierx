"""Runtime failures retain their fixed phase and cannot yield passing evidence."""
import importlib.util
import ast
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import offline_host_evidence as evidence
import offline_host_diagnostics as diagnostics
spec=importlib.util.spec_from_file_location('runtime_scenarios',ROOT/'scripts/offline-host-scenarios.py')
scenarios=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenarios)


class RuntimeTests(unittest.TestCase):
    def test_invalid_delivery_progress_keeps_all_rejections_and_service_preservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);config=home/'config';(config/'tls').mkdir(parents=True)
            (config/'tls/server.crt').write_text('synthetic certificate')
            phases=[]
            def run(*args,**kwargs):
                self.assertEqual(args,('podman','info','--format','json'))
                return json.dumps({'store':{'graphRoot':str(home/'empty-store/images'),
                    'runRoot':str(home/'run/empty-store'),'imageStore':{'number':0}}})
            with mock.patch.object(scenarios,'HOME',home),mock.patch.object(scenarios,'CONFIG',config), \
                    mock.patch.object(scenarios,'service_snapshot',return_value={'unchanged':True}) as snapshot, \
                    mock.patch.object(scenarios,'installer') as installer:
                result=scenarios.delivery_failures(home/'bundle',{'bundle_sha256':'a'*64,
                    'invalid_hashes':dict.fromkeys(('missing-image','altered-archive','wrong-architecture'),'b'*64)},
                    {'XDG_RUNTIME_DIR':str(home/'run')},run,home/'private.log',phases.append)
            self.assertEqual(result,evidence.INVALID_DELIVERIES)
            self.assertEqual(installer.call_count,6)
            self.assertEqual(snapshot.call_count,2)
            self.assertEqual(phases[-1],'invalid-delivery-snapshot-after')
            self.assertEqual(len(phases),10)
            self.assertTrue(set(phases)<=diagnostics.FAILURE_PHASES)

    def test_guest_command_keeps_streaming_stderr_and_classifies_only_its_own_tail(self):
        source=(ROOT/'scripts/offline-host-guest.py').read_text()
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='run')
        for timeout in (False,True):
            with self.subTest(timeout=timeout),tempfile.TemporaryDirectory() as temporary:
                log=Path(temporary)/'private.log';log.write_bytes(b'old database configuration mismatch\n')
                def child(args,**kwargs):
                    os.write(kwargs['stderr'].fileno(),b'private credential: cannot clone\n')
                    if timeout:raise scenarios.subprocess.TimeoutExpired(args,1800)
                    return scenarios.subprocess.CompletedProcess(args,125,stdout=b'database configuration mismatch\n')
                namespace={'subprocess':mock.Mock(run=child),'LOG':log,'OPTIONS':{'virtual_cpu':'tcg'},
                    'PHASE':'invalid-delivery-empty-store-info','ENV':{},'BUNDLE':Path(temporary),'diagnostics':diagnostics}
                exec(compile(ast.Module(body=[node],type_ignores=[]),'guest-run-test','exec'),namespace)
                expected=scenarios.subprocess.TimeoutExpired if timeout else RuntimeError
                with self.assertRaises(expected) as caught:namespace['run']('podman','info')
                self.assertIn(b'private credential',log.read_bytes())
                if not timeout:
                    result=diagnostics.failure_record(caught.exception,namespace['PHASE'])
                    self.assertEqual(result['guest_command_detail'],'namespace-clone')
                    self.assertNotIn('private',json.dumps(result))

    def test_podman_failure_metadata_exposes_only_fixed_operation_and_category(self):
        secret=b'private-password /private/path https://private.invalid/?token=private'
        for message,category in ((b'database configuration mismatch','storage-configuration'),
                                 (b'cannot clone: Operation not permitted','namespace-clone'),
                                 (secret,'other')):
            detail=diagnostics.guest_command_failure(('podman','info','--private-argument'),secret+b' '+message)
            self.assertEqual(detail,{'guest_command':'podman-info','guest_command_detail':category})
            error=RuntimeError('private exception');error.fixture_exit_code=125
            error.fixture_command=detail['guest_command'];error.fixture_command_detail=detail['guest_command_detail']
            value=diagnostics.failure_record(error,'invalid-delivery-empty-store-info')
            self.assertEqual(value['guest_command_detail'],category)
            self.assertNotIn('private',json.dumps(value))
        self.assertEqual(diagnostics.guest_command_failure(('psql','private URL'),secret),{})
        value=diagnostics.sanitize_failure({'result':'failed','phase':'invalid-delivery-empty-store-info',
            'guest_command':'private command','guest_command_detail':'private error'})
        self.assertNotIn('guest_command',value)

    def test_acquisition_failure_keeps_only_fixed_pull_or_inspect_metadata(self):
        private = b'private credential and registry path '
        for arguments, message, operation, category in (
            (('podman','pull','private-reference'), b'x509: private authority', 'podman-pull', 'tls-verification'),
            (('podman','pull','private-reference'), b'connection refused', 'podman-pull', 'connection-refused'),
            (('podman','image','inspect','private-id'), private, 'podman-inspect', 'other'),
        ):
            detail = diagnostics.guest_command_failure(arguments, private+message)
            self.assertEqual(detail, {'guest_command':operation, 'guest_command_detail':category})
            failure = diagnostics.sanitize_failure({'result':'failed','phase':'acquisition-pull',
                'failure_type':'RuntimeError', **detail})
            self.assertNotIn('private', json.dumps(failure))
        self.assertEqual(diagnostics.guest_command_failure(('podman','login','private'), private), {})

    def test_invalid_delivery_failure_keeps_exact_substep_and_restores_certificate(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);config=home/'config';(config/'tls').mkdir(parents=True)
            certificate=config/'tls/server.crt';certificate.write_text('synthetic certificate')
            phases=[]
            def run(*args,**kwargs):
                self.assertEqual(args,('podman','info','--format','json'))
                error=RuntimeError('private subprocess stderr must not enter public evidence')
                error.fixture_exit_code=125
                raise error
            with mock.patch.object(scenarios,'HOME',home),mock.patch.object(scenarios,'CONFIG',config), \
                    mock.patch.object(scenarios,'service_snapshot',return_value={'unchanged':True}), \
                    mock.patch.object(scenarios,'installer') as installer:
                try:
                    scenarios.delivery_failures(home/'bundle',{'bundle_sha256':'a'*64,
                        'invalid_hashes':dict.fromkeys(('missing-image','altered-archive','wrong-architecture'),'b'*64)},
                        {'XDG_RUNTIME_DIR':str(home/'run')},run,home/'private.log',phases.append)
                except RuntimeError as error:
                    result=diagnostics.failure_record(error,phases[-1])
                else:self.fail('Invalid-delivery setup failure must propagate')
            self.assertEqual(result,{'result':'failed','phase':'invalid-delivery-empty-store-info',
                                     'failure_type':'RuntimeError','command_exit_code':125})
            self.assertTrue(set(phases)<=diagnostics.FAILURE_PHASES)
            self.assertEqual(installer.call_count,5)
            self.assertEqual(certificate.read_text(),'synthetic certificate')
            self.assertFalse(certificate.with_suffix('.parked').exists())
            self.assertNotIn('private',json.dumps(result))

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
