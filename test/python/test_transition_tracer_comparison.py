"""The transition comparison cannot become release coverage or alter parent receipts."""
import copy,hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import native_tracer_diagnostic as diagnostic
spec=importlib.util.spec_from_file_location('causal_transition',ROOT/'scripts/diagnostic-transition-tracer-compare.py')
driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)


class TransitionTracerComparisonTests(unittest.TestCase):
    def test_transition_signature_requires_installer_and_tracer_but_no_invented_import_helper(self):
        value={'result':'failed','tracer_returncode':1,'query_observation':{'capture':'observed',
            'failed_queries':1,'esrch_queries':1,'listen_eio':1,'unique_same_target_pair':True},
            'observation':{'kernel_exit_capture':'observed','kernel_exit':{
                'installer':{'task_exited':True},'tracer':{'task_exited':True,'requested_exit_code':1}},
                'tracer_syscall_errors':[{'call':'ptrace','errno':3,'age_ms':8},{'call':'ptrace','errno':5,'age_ms':7}]}}
        self.assertTrue(diagnostic.expected_transition_failure(value))
        self.assertFalse(diagnostic.expected_old_failure(value))
        for fault in ('lost','own-exit','query-missing','extra-role'):
            report=copy.deepcopy(value)
            if fault=='lost':report['observation']['kernel_exit_capture']='lost-events'
            elif fault=='own-exit':report['observation']['kernel_exit']['installer']['requested_exit_code']=1
            elif fault=='query-missing':report['query_observation']['unique_same_target_pair']=False
            else:report['observation']['kernel_exit']['import-helper']={'task_exited':True}
            with self.subTest(fault=fault):self.assertFalse(diagnostic.expected_transition_failure(report))

    def test_preparation_selects_only_installer_and_preserves_parent_binary_and_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'opt').mkdir();(root/'usr/sbin').mkdir(parents=True);(root/'usr/bin').mkdir()
            parent=root/'usr/bin/strace';parent.write_bytes(b'parent')
            receipt=root/'receipt.json';receipt.write_text('fixed receipt')
            binary=root/'control';binary.write_bytes(b'old control');expected=hashlib.sha256(binary.read_bytes()).hexdigest()
            wrapper=root/'usr/sbin/sierx-trace-installer'
            def original(path,args):wrapper.write_text('#!/bin/sh\nexec /usr/bin/strace -q -f\n')
            args=SimpleNamespace(development=True,transition_probe=True,ordinary_installer_trace=True,acceleration='tcg',single_tcg=False)
            driver.prepare_installer(root,args,original,binary,expected)
            self.assertEqual(parent.read_bytes(),b'parent');self.assertEqual(receipt.read_text(),'fixed receipt')
            self.assertIn('/usr/bin/python3 /opt/transition-tracer/exec.py',wrapper.read_text())
            self.assertEqual((root/'opt/transition-tracer/strace').read_bytes(),binary.read_bytes())
            self.assertIn(expected,(root/'opt/transition-tracer/exec.py').read_text())
            self.assertFalse((root/'usr/sbin/sierx-trace-manager').exists())

    def test_accepting_or_other_modes_cannot_prepare_selected_tracer(self):
        args=SimpleNamespace(development=True,transition_probe=True,ordinary_installer_trace=True,acceleration='tcg',single_tcg=False)
        for key,value in (('development',False),('transition_probe',False),('ordinary_installer_trace',False),
                          ('acceleration','kvm'),('single_tcg',True)):
            options=copy.copy(args);setattr(options,key,value)
            with self.subTest(key=key),self.assertRaises(ValueError):
                driver.prepare_installer(Path('/unused'),options,lambda *a:None,Path('/unused'),'a'*64)
