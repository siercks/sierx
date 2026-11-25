import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import native_tracer_diagnostic as diagnostic


class NativeTracerDiagnosticTests(unittest.TestCase):
    def test_query_pair_requires_same_target_order_and_no_ambiguity(self):
        query='SIERX_PTRACE_QUERY pid=42 errno=3\n'
        listen='strace: ptrace(PTRACE_LISTEN,pid:42,sig:0): Input/output error\n'
        value=diagnostic.query_failure_fields('private credential\n'+query+listen)
        self.assertTrue(value['unique_same_target_pair'])
        self.assertNotIn('42',str(value));self.assertNotIn('credential',str(value))
        for text in (listen+query,query+listen.replace('pid:42','pid:43'),query+query+listen,
                     query+listen+listen,'SIERX_PTRACE_QUERY private\n'+listen):
            with self.subTest(text=text):self.assertFalse(diagnostic.query_failure_fields(text)['unique_same_target_pair'])
        self.assertEqual(diagnostic.query_failure_fields('x'*65537),{'capture':'invalid-or-truncated'})

    def test_natural_import_cause_requires_independent_ordered_kernel_errors_and_all_exits(self):
        roles={role:{'task_exited':True} for role in ('installer','import-helper')}
        roles['tracer']={'task_exited':True,'requested_exit_code':1}
        report={'result':'failed','tracer_returncode':1,'query_observation':{'capture':'observed','unique_same_target_pair':True,
                'failed_queries':1,'esrch_queries':1,'listen_eio':1},
            'observation':{'kernel_exit_capture':'observed','kernel_exit':roles,'tracer_syscall_errors':[
                {'call':'ptrace','errno':3,'age_ms':10},{'call':'ptrace','errno':5,'age_ms':9}]}}
        self.assertTrue(diagnostic.expected_old_failure(report))
        for fault in ('lost','missing-task','own-exit','reversed','ambiguous','old-errors','boolean-code','boolean-task-exit'):
            value=copy.deepcopy(report)
            if fault=='lost':value['observation']['kernel_exit_capture']='lost-events'
            elif fault=='missing-task':value['observation']['kernel_exit'].pop('import-helper')
            elif fault=='own-exit':value['observation']['kernel_exit']['installer']['requested_exit_code']=1
            elif fault=='reversed':value['observation']['tracer_syscall_errors'].reverse()
            elif fault=='ambiguous':value['observation']['tracer_syscall_errors']*=2
            elif fault=='old-errors':value['observation']['tracer_syscall_errors'][0]['age_ms']=2001
            elif fault=='boolean-task-exit':value['observation']['kernel_exit']['tracer']['requested_exit_code']=True
            else:value['tracer_returncode']=True
            with self.subTest(fault=fault):self.assertFalse(diagnostic.expected_old_failure(value))

    def test_fixed_import_requires_complete_observed_zero_exits_and_no_listen_error(self):
        report={'result':'passed','tracer_returncode':0,'query_observation':{'capture':'observed','listen_eio':0,
                'failed_queries':0,'esrch_queries':0},
            'observation':{'kernel_exit_capture':'observed','import_stage':'import-complete','kernel_exit':{
                role:{'task_exited':True,'requested_exit_code':0} for role in ('installer','tracer','import-helper')}}}
        self.assertTrue(diagnostic.expected_fixed_completion(report))
        report['observation']['kernel_exit']['installer']['requested_exit_code']=False
        self.assertFalse(diagnostic.expected_fixed_completion(report))

    def test_public_case_drops_every_unknown_message_pid_and_nested_field(self):
        value={'suite':'offline-native-import-probe-v1','release_acceptance':False,'result':'failed',
            'tracer_returncode':1,'kernel_release':'6.8.0-public','fresh_rootless_overlay':True,
            'loopback_only':True,'installer_trace_mode':'ordinary-ptrace','strace_sha256':'a'*64,
            'podman_sha256':'b'*64,'private':'credential','observation':{'private':'credential'},
            'query_observation':{'capture':'observed','failed_queries':1,'esrch_queries':1,'listen_eio':1,
                'unique_same_target_pair':True,'pid':4242,'private':'credential'}}
        safe=diagnostic.public_case(value)
        self.assertNotIn('credential',str(safe));self.assertNotIn('4242',str(safe))
        self.assertNotIn('pid',safe['query_observation'])
        value['kernel_release']='private/path'
        with self.assertRaises(ValueError):diagnostic.public_case(value)

    def test_matched_build_rejects_changed_observer_source_flags_and_patch(self):
        build={'source_archive_sha256':diagnostic.ARCHIVE_SHA256,'patch_sha256':diagnostic.PATCH_SHA256,
            'observation_sha256':diagnostic.OBSERVATION_SHA256,'configure_flags':diagnostic.CONFIGURE_FLAGS,
            'release_acceptance':False,'builds':{mode:{'version':'6.8','sha256':letter*64,
                'base_source_sha256':diagnostic.SOURCE_SHA256[mode],
                'observed_source_sha256':diagnostic.OBSERVED_SOURCE_SHA256[mode]}
                for mode,letter in (('old','a'),('fixed','b'))}}
        diagnostic.validate_build(build)
        build['private']='credential';build['builds']['old']['private']='credential'
        self.assertNotIn('credential',str(diagnostic.public_build(build)))
        for fault in ('source','flags','patch','same-binary'):
            value=copy.deepcopy(build)
            if fault=='source':value['builds']['fixed']['observed_source_sha256']='c'*64
            elif fault=='flags':value['configure_flags']=[]
            elif fault=='patch':value['patch_sha256']='c'*64
            else:value['builds']['fixed']['sha256']='a'*64
            with self.subTest(fault=fault),self.assertRaises(ValueError):diagnostic.validate_build(value)
