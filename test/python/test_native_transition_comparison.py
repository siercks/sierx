import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('native_transition_comparison',ROOT/'scripts/diagnostic-native-transition-compare.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)


class NativeTransitionTests(unittest.TestCase):
    def test_launcher_keeps_private_namespaces_no_network_or_host_identity_integration(self):
        value=native.command(Path('/owned/root'),'sierx-native-control-old',[0,1,2,3])
        for argument in ('--private-network','--private-users=no','--register=no','--settings=no','--link-journal=no',
                '--cpu-affinity=0,1,2,3','--bind=/sys/kernel/tracing:/sys/kernel/tracing'):
            self.assertIn(argument,value)
        self.assertFalse(any(argument.startswith(('--network-veth','--bind-user','--port=')) for argument in value))
        for name,cpus in (('operator',[0,1,2,3]),('sierx-native-x',[0,1]),('sierx-native-x',[0,1,2,2])):
            with self.assertRaises(ValueError):native.command(Path('/owned/root'),name,cpus)

    def test_existing_trace_instance_blocks_launch_before_any_process_starts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)
            with mock.patch.object(native,'TRACE_PATHS',(path,)),mock.patch.object(native.subprocess,'Popen') as start:
                with self.assertRaises(ValueError):native.launch(path,'sierx-native-test',[0,1,2,3],path/'log')
                start.assert_not_called()

    def test_caught_guest_failure_preserves_http_detail_and_early_exit_uses_root_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);guest=root/'home/acceptance/failure.json';service=root/'var/log/sierx-network/service-failure.json'
            guest.parent.mkdir(parents=True);service.parent.mkdir(parents=True)
            service.write_text(json.dumps({'result':'failed','phase':'import','failure_type':'ServiceExit','service_exit_code':1}))
            guest.write_text(json.dumps({'result':'failed','phase':'https-data-check','failure_type':'TimeoutError',
                'https_failure':{'step':'login','kind':'timeout','io_stage':'response-headers','private':'credential'}}))
            self.assertEqual(native.checked_failure(root)['https_failure']['io_stage'],'response-headers')
            self.assertNotIn('credential',str(native.checked_failure(root)))
            guest.unlink();self.assertEqual(native.checked_failure(root)['service_exit_code'],1)

    def test_old_success_or_unrelated_failure_never_runs_fixed_or_retries(self):
        for completed,expected in ((True,'inconclusive'),(False,'failed')):
            calls=[]
            def run(mode):
                calls.append(mode);return {'transition_completed':completed,'expected_old_cause_observed':False}
            self.assertEqual(native.compare(run)['result'],expected);self.assertEqual(calls,['old'])

    def test_causal_pair_requires_real_failure_then_complete_fixed_with_valid_queries(self):
        good={'transition_completed':True,'expected_old_cause_observed':False,
            'query_observation':{'capture':'observed','failed_queries':0,'esrch_queries':0,'listen_eio':0}}
        for fault in (None,'incomplete','lost','listen','boolean'):
            calls=[];fixed=copy.deepcopy(good)
            if fault=='incomplete':fixed['transition_completed']=False
            elif fault=='lost':fixed['query_observation']['capture']='invalid-or-truncated'
            elif fault=='listen':fixed['query_observation']['listen_eio']=1
            elif fault=='boolean':fixed['query_observation']['failed_queries']=False
            def run(mode):
                calls.append(mode)
                return {'transition_completed':False,'expected_old_cause_observed':True} if mode=='old' else fixed
            self.assertEqual(native.compare(run)['result'],'cause-reproduced-and-corrected' if fault is None else 'failed')
            self.assertEqual(calls,['old','fixed'])

    def test_launcher_timeout_cannot_supply_cause_even_with_matching_termination_metadata(self):
        failure={'service_exit_code':1,'kernel_exit_capture':'observed','kernel_exit':{
            'installer':{'task_exited':True},'tracer':{'task_exited':True,'requested_exit_code':1}},
            'tracer_syscall_errors':[{'call':'ptrace','errno':3,'age_ms':10},{'call':'ptrace','errno':5,'age_ms':9}]}
        query={'capture':'observed','unique_same_target_pair':True,'failed_queries':1,'esrch_queries':1,'listen_eio':1}
        self.assertTrue(native.cause_matches(failure,query,False))
        self.assertFalse(native.cause_matches(failure,query,True))

    def test_fixed_setup_failure_preserves_the_already_recorded_old_cause_without_retry(self):
        calls=[];old={'transition_completed':False,'expected_old_cause_observed':True}
        def run(mode):
            calls.append(mode)
            if mode=='fixed':raise ValueError('private setup detail')
            return old
        result=native.compare(run)
        self.assertEqual(result,{'result':'failed','cases':[old],'failure_type':'ValueError'})
        self.assertEqual(calls,['old','fixed']);self.assertNotIn('private',str(result))
