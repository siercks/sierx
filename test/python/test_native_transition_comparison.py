import copy,errno,importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('native_transition_comparison',ROOT/'scripts/diagnostic-native-transition-compare.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)


class NativeTransitionTests(unittest.TestCase):
    def test_private_launcher_umask_does_not_hide_public_diagnostic_code_from_tracee(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'usr/bin').mkdir(parents=True);(root/'usr/bin/strace').write_bytes(b'parent')
            (root/'usr/sbin').mkdir();(root/'usr/sbin/sierx-trace-installer').write_text('exec /usr/bin/strace --seccomp-bpf\n')
            (root/'opt/acceptance').mkdir(parents=True)
            binary=root/'control';binary.write_bytes(b'control')
            host=SimpleNamespace(setup=lambda *_:None,SUITE_FILES=('offline_apply_trace.py',),suite_digest=lambda *_:'suite')
            args=SimpleNamespace(development=True,transition_probe=True,virtual_cpu='native',ordinary_installer_trace=False,suite_sha256='suite')
            before=os.umask(0o077)
            try:native.prepare(root,host,args,binary,native.offline.digest(binary))
            finally:os.umask(before)
            for name in ('opt/acceptance/tests','opt/acceptance/tests/deploy-trace','opt/transition-tracer'):
                self.assertEqual((root/name).stat().st_mode&0o777,0o755)
            self.assertEqual((root/'usr/bin/strace').read_bytes(),b'parent')

    def test_cleanup_waits_only_for_busy_owned_instance_teardown(self):
        path=mock.MagicMock();path.exists.return_value=True
        path.rmdir.side_effect=[OSError(errno.EBUSY,'private'),None]
        with mock.patch.object(native.time,'sleep') as pause:native.cleanup_instances((path,))
        self.assertEqual(path.rmdir.call_count,2);pause.assert_called_once_with(0.1)
        for number in (errno.EPERM,errno.EBUSY):
            path.rmdir.side_effect=OSError(number,'private')
            with self.assertRaises(OSError):native.cleanup_instances((path,),timeout=0)

    def test_database_error_categories_never_copy_journal_message_path_or_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'private.log'
            self.assertEqual(native.database_diagnostic(path),{'capture':'unavailable'})
            path.write_bytes(b'postgres://private-user:credential@private-host\nJob for sierx-postgres.service failed\ncrun: private/path: Operation not permitted\n')
            value=native.database_diagnostic(path)
            self.assertEqual(value,{'capture':'observed','tail_truncated':False,
                'categories':['operation-not-permitted','runtime-crun-error','start-job-failed']})
            self.assertNotIn('private',str(value));self.assertNotIn('credential',str(value))
            path.write_bytes(b'permission denied'+b'x'*65536)
            self.assertEqual(native.database_diagnostic(path),{'capture':'observed','tail_truncated':True,'categories':[]})
            target=path.with_name('private-target');target.write_text('permission denied credential')
            path.unlink();path.symlink_to(target)
            self.assertEqual(native.database_diagnostic(path),{'capture':'unavailable'})
            path.unlink();path.write_text('offline: Restore executable permissions on bin/goose and bin/sierxctl\ncrun: create keyring: Operation not permitted\n')
            self.assertEqual(native.database_diagnostic(path)['categories'],['keyring-error','operation-not-permitted','runtime-crun-error','tools-not-executable'])

    def test_launcher_keeps_private_namespaces_no_network_or_host_identity_integration(self):
        value=native.command(Path('/owned/root'),'sierx-native-control-old',[0,1,2,3])
        for argument in ('--private-network','--private-users=no','--register=no','--settings=no','--link-journal=no',
                '--cpu-affinity=0,1,2,3','--bind=/sys/kernel/tracing:/sys/kernel/tracing','--kill-signal=SIGKILL'):
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
