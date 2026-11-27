import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('import_thread_stress',ROOT/'scripts/diagnostic-import-thread-stress.py')
stress=importlib.util.module_from_spec(spec);spec.loader.exec_module(stress)


def old_case():
    return {'mode':'old','forced_termination':False,'thread_stress':{'started':True,'completed':False},
        'import':{'result':'failed','tracer_returncode':1,
            'query_observation':{'capture':'observed','unique_same_target_pair':True,'failed_queries':1,'esrch_queries':1,'listen_eio':1},
            'observation':{'kernel_exit_capture':'observed','kernel_exit':{
                'installer':{'task_exited':True},'import-helper':{'task_exited':True},'tracer':{'task_exited':True,'requested_exit_code':1}},
                'tracer_syscall_errors':[{'call':'ptrace','errno':3,'age_ms':1},{'call':'ptrace','errno':5,'age_ms':0}]}}}


def fixed_case():
    return {'mode':'fixed','forced_termination':False,'thread_stress':{'started':True,'completed':True,'exit_code':0},
        'import':{'result':'passed','tracer_returncode':0,
            'query_observation':{'capture':'observed','listen_eio':0,'failed_queries':3,'esrch_queries':3},
            'observation':{'kernel_exit_capture':'observed','import_stage':'import-complete','kernel_exit':{
                role:{'task_exited':True,'requested_exit_code':0} for role in ('installer','tracer','import-helper')}}}}


class ImportThreadStressTests(unittest.TestCase):
    def test_old_then_fixed_once_requires_real_old_and_complete_fixed(self):
        called=[]
        def run(mode):called.append(mode);return old_case() if mode=='old' else fixed_case()
        value=stress.compare_cases(run)
        self.assertEqual(called,['old','fixed']);self.assertEqual(value['result'],'cause-reproduced-and-corrected')

    def test_unrelated_old_termination_never_executes_fixed_or_retries(self):
        for fault in ('force','not-started','lost','own-exit','other-target','missing-role'):
            case=old_case();called=[]
            if fault=='force':case['forced_termination']=True
            elif fault=='not-started':case['thread_stress']['started']=False
            elif fault=='lost':case['import']['observation']['kernel_exit_capture']='lost-events'
            elif fault=='own-exit':case['import']['observation']['kernel_exit']['import-helper']['requested_exit_code']=1
            elif fault=='other-target':case['import']['query_observation']['unique_same_target_pair']=False
            else:case['import']['observation']['kernel_exit'].pop('installer')
            def run(mode):called.append(mode);return case
            with self.subTest(fault=fault):
                self.assertEqual(stress.compare_cases(run)['result'],'inconclusive');self.assertEqual(called,['old'])

    def test_fixed_requires_worker_completion_even_when_import_passes(self):
        for fault in ('worker','force','listen','exit'):
            case=fixed_case()
            if fault=='worker':case['thread_stress']['completed']=False
            elif fault=='force':case['forced_termination']=True
            elif fault=='listen':case['import']['query_observation']['listen_eio']=1
            else:case['import']['observation']['kernel_exit']['installer']['requested_exit_code']=1
            with self.subTest(fault=fault):
                value=stress.compare_cases(lambda mode:old_case() if mode=='old' else case)
                self.assertEqual(value['result'],'failed')

    def test_fixed_setup_failure_preserves_old_without_exception_message(self):
        def run(mode):
            if mode=='fixed':raise ValueError('credential /private/path argv')
            return old_case()
        value=stress.compare_cases(run)
        self.assertEqual(len(value['cases']),1);self.assertEqual(value['failure_type'],'ValueError')
        self.assertNotIn('credential',str(value));self.assertNotIn('/private/path',str(value))

    def test_wrong_case_order_is_rejected(self):
        value=stress.compare_cases(lambda _:fixed_case())
        self.assertEqual(value['result'],'failed');self.assertEqual(value['cases'],[])

    def test_checkpoint_rejects_unknown_private_fields_booleans_and_large_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'worker.json'
            self.assertEqual(stress.stress_evidence(path),{'started':False,'completed':False})
            for value in ({'started':True,'completed':True,'exit_code':False},
                    {'started':True,'completed':True,'exit_code':7},
                    {'started':True,'completed':False,'private':'credential'},
                    {'started':1,'completed':False}):
                path.write_text(json.dumps(value))
                with self.subTest(value=value),self.assertRaises(ValueError):stress.stress_evidence(path)
            path.write_text('x'*1025)
            with self.assertRaises(ValueError):stress.stress_evidence(path)

    @unittest.skipIf(sys.platform=='win32','Owned POSIX symlinks')
    def test_checkpoint_rejects_even_broken_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'worker.json';path.symlink_to(Path(directory)/'missing')
            with self.assertRaises(ValueError):stress.stress_evidence(path)

    def test_worker_receipt_binds_source_binary_arch_account_and_no_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'worker';binary.write_bytes(b'public-worker')
            receipt={'source_sha256':stress.NATURAL_SHA,'binary_sha256':stress.offline.digest(binary),
                'flags':['-O2','-pthread'],'cycles':4096,'arch':stress.architecture(),'owner_uid':1001,'release_acceptance':False}
            stress.validate_worker(receipt,binary)
            for key,value in (('cycles',True),('cycles',4095),('source_sha256','a'*64),('flags',[]),
                    ('owner_uid',0),('release_acceptance',True),('binary_sha256','b'*64),('private','credential')):
                item=copy.deepcopy(receipt);item[key]=value
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):stress.validate_worker(item,binary)

    def test_normal_workload_does_not_import_new_diagnostic(self):
        for name in ('offline-native-import.py','offline-host.py','offline-host-guest.py'):
            self.assertNotIn('diagnostic-import-thread-stress',(ROOT/'scripts'/name).read_text())

    def test_workflow_exposes_explicit_nonpromotable_native_stress_mode(self):
        text=(ROOT/'.github/workflows/historical-import-compare.yml').read_text()
        self.assertIn('native-import-stress',text);self.assertIn("if: env.COMPARISON_WORKLOAD != 'native-import-stress'",text)
        self.assertIn("'release_acceptance':False",text)
        self.assertIn('historical-native-import-thread-stress-arm64.json',text)


if __name__=='__main__':unittest.main()
