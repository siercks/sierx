"""A partial, lossy, mismatched or unsanitized mechanism probe cannot pass."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import tracer_diagnostic as diagnostic


def inputs():
    build={'arch':diagnostic.architecture(),'owner_uid':1000,
        'source_archive_sha256':diagnostic.ARCHIVE_SHA256,'patch_sha256':diagnostic.PATCH_SHA256,
        'system_binary_replaced':False,'release_acceptance':False,'builds':{
            mode:{'sha256':letter*64,'source_sha256':diagnostic.SOURCE_SHA256[mode],'version':'6.8'}
            for mode,letter in (('old','a'),('fixed','b'))}}
    controlled={'build':copy.deepcopy(build),'release_acceptance':False,'historical_cause_proven':False,'cases':[]}
    for mode in ('old','fixed'):
        fixed=mode=='fixed'
        roles={role:{'task_exited':True,'requested_exit_code':0} for role in ('installer','tracer')}
        if not fixed:roles={'installer':{'task_exited':True},'tracer':{'task_exited':True,'requested_exit_code':1}}
        for trace in ('ordinary','seccomp'):
            controlled['cases'].append({'case':mode+'-'+trace,'forced_query_esrch_observed':True,
                'subsequent_listen_eio_observed':not fixed,'tracer_return':0 if fixed else 1,
                'installer_survived':fixed,'kernel_exit_capture':'observed','kernel_exit':copy.deepcopy(roles)})
    natural={'build':copy.deepcopy(build),'fault_injection':False,'natural_failure_reproduced':True,
        'narrow_fix_verified_on_natural_workload':True,'historical_cause_proven':False,
        'release_acceptance':False,'cases':[]}
    for mode,index in (('old',0),('fixed',2)):
        controlled_row=controlled['cases'][index]
        natural['cases'].append({'mode':mode,'tracer_return':controlled_row['tracer_return'],
            'listen_eio':mode=='old','completed_4096':mode=='fixed','fault_injection':False,
            'deadline_reached':False,'kernel':{key:copy.deepcopy(controlled_row[key])
                for key in ('kernel_exit_capture','kernel_exit')}})
    return build,controlled,natural


class TracerDiagnosticTests(unittest.TestCase):
    def test_failed_progress_cannot_disclose_private_messages_or_extra_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            log=Path(temporary)/'private.log'
            log.write_text('credential and private traceback\n'+json.dumps({'mode':'old',
                'tracer_return':1,'listen_eio':True,'private':'credential',
                'kernel':{'kernel_exit_capture':'observed','private':'credential'}})+'\n')
            result=diagnostic.safe_probe_progress(log)
            self.assertEqual(result,{'case':'natural-old','tracer_return':1,'listen_eio':True,
                                     'kernel_exit_capture':'observed'})
            self.assertNotIn('credential',json.dumps(result))

    def test_partial_lost_or_false_positive_mechanism_cannot_pass(self):
        for defect in ('missing-case','kernel-loss','installer-alive','no-natural-failure',
                       'timeout','wrong-source','same-binary','boolean-exit','nonboolean-task','release-claim'):
            build,controlled,natural=inputs()
            if defect=='missing-case':controlled['cases'].pop()
            elif defect=='kernel-loss':controlled['cases'][0]['kernel_exit_capture']='lost-events'
            elif defect=='installer-alive':controlled['cases'][0]['kernel_exit']['installer']['task_exited']=False
            elif defect=='no-natural-failure':natural['natural_failure_reproduced']=False
            elif defect=='timeout':natural['cases'][1]['deadline_reached']=True
            elif defect=='wrong-source':build['patch_sha256']='c'*64
            elif defect=='same-binary':build['builds']['fixed']['sha256']='a'*64
            elif defect=='boolean-exit':natural['cases'][1]['kernel']['kernel_exit']['installer']['requested_exit_code']=False
            elif defect=='nonboolean-task':controlled['cases'][0]['kernel_exit']['installer']['task_exited']=1
            elif defect=='release-claim':controlled['release_acceptance']=True
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                diagnostic.verify_result(build,controlled,natural,'d'*40)

    def test_success_stays_nonpromotable_and_never_copies_private_extra_fields(self):
        build,controlled,natural=inputs()
        controlled['cases'][0]['private']='credential'
        natural['cases'][1]['kernel']['private']='credential'
        build['builds']['old']['private']='credential'
        controlled['build']=copy.deepcopy(build);natural['build']=copy.deepcopy(build)
        result=diagnostic.verify_result(build,controlled,natural,'d'*40)
        self.assertEqual(result['result'],'passed')
        self.assertEqual(result['fixed_completed_cycles'],4096)
        self.assertIs(result['release_acceptance'],False)
        self.assertIs(result['historical_cause_proven'],False)
        self.assertNotIn('credential',json.dumps(result))

    def test_results_must_bind_both_exact_builds(self):
        build,controlled,natural=inputs()
        natural['build']['builds']['fixed']['sha256']='e'*64
        with self.assertRaises(ValueError):diagnostic.verify_result(build,controlled,natural,'d'*40)

    def test_only_the_original_nonroot_preparer_can_be_the_synthetic_tracee(self):
        build,_,_=inputs()
        with patch.dict(os.environ,SIERX_TRACER_DIAGNOSTIC_USER='runner'), \
                patch.object(diagnostic.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1000)):
            self.assertEqual(diagnostic.target_user(build),'runner')
            for uid in (0,1001):
                with patch.object(diagnostic.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=uid)), \
                        self.assertRaises(ValueError):diagnostic.target_user(build)

    def test_control_environment_does_not_inherit_credentials_or_fault_libraries(self):
        with patch.dict(os.environ,GH_TOKEN='credential',LD_PRELOAD='/private/library'):
            result=diagnostic.clean_environment(Path('/synthetic'))
        self.assertNotIn('GH_TOKEN',result)
        self.assertNotIn('LD_PRELOAD',result)
        self.assertNotIn('credential',json.dumps(result))

    def test_state_cannot_escape_dist_or_follow_a_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);dist=root/'dist';dist.mkdir()
            state=dist/'tracer-race-arm64';state.mkdir()
            with patch.object(diagnostic,'ROOT',root),patch.dict(os.environ,SIERX_TRACER_DIAGNOSTIC_STATE=str(state)):
                self.assertEqual(diagnostic.state_directory(),state)
                state.rmdir();state.symlink_to(root,target_is_directory=True)
                with self.assertRaises(ValueError):diagnostic.state_directory()
