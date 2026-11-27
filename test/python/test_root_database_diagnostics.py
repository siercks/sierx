"""A root-only failed DB journal checkpoint never overrides acceptance or state."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import offline_host_diagnostics as diagnostics


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


host=load('root_db_host','offline-host.py')
kernel=load('root_db_kernel','offline-kernel-observer.py')
FAILED={'result':'failed','phase':'rootless-database','failure_type':'RuntimeError','command_exit_code':1,
        'database_failure':{'state_capture':'observed','journal_capture':'unavailable',
                            'state':{'Result':'exit-code','ExecMainCode':1,'ExecMainStatus':125}}}


class RootDatabaseDiagnosticsTests(unittest.TestCase):
    def test_upstream_removal_error_requires_exact_static_condition_and_retains_unit_correlation(self):
        message='Error: slirp4netns support has been removed, use --network=pasta instead; private context'
        for matched in (False,True):
            record={'_UID':'1001','_COMM':'podman','MESSAGE':message}
            if matched:record['_SYSTEMD_USER_UNIT']='sierx-postgres.service'
            value=diagnostics.database_journal_records(json.dumps(record).encode(),False)
            self.assertIn('slirp4netns-support-removed',value['journal_runtime_error_categories'])
            self.assertEqual('slirp4netns-support-removed' in value['journal_database_unit_categories'],matched)
            self.assertNotIn('private',json.dumps(value))
        record={'_UID':'1001','_COMM':'podman','MESSAGE':'Error: pasta failed; slirp4netns helper not usable'}
        value=diagnostics.database_journal_records(json.dumps(record).encode(),False)
        self.assertNotIn('slirp4netns-support-removed',value['categories'])
        planted={**value,'journal_database_unit_categories':['slirp4netns-support-removed']}
        self.assertEqual(diagnostics.sanitize_database_failure(planted)['journal_capture'],'invalid')

    def test_numeric_installed_podman_version_rejects_private_unbounded_and_failed_output(self):
        for raw,code,expected in ((b'podman version 6.0.2\n',0,[6,0,2]),
                (b'podman version 5.8.0-rc1\n',0,[5,8,0]),(b'private credential',0,None),
                (b'podman version 6.0.2\nprivate',0,None),(b'x'*257,0,None),
                (b'podman version 1000.0.0',0,None),(b'podman version 6.0.2',1,None)):
            def run(args,*,stdout,stderr,timeout):
                self.assertEqual(args,('/usr/bin/podman','--version'));self.assertEqual(timeout,3)
                self.assertEqual(stderr,subprocess.DEVNULL);stdout.write(raw)
                return subprocess.CompletedProcess(args,code)
            with self.subTest(raw=raw[:20],code=code),patch.object(diagnostics.subprocess,'run',side_effect=run):
                self.assertEqual(diagnostics.database_podman_version(),expected)
        with patch.object(diagnostics.subprocess,'run',side_effect=subprocess.TimeoutExpired('private',3)):
            self.assertIsNone(diagnostics.database_podman_version())
        value=diagnostics.sanitize_database_failure({'state_capture':'unavailable','journal_capture':'unavailable',
                                                    'journal_podman_version':[True,0,0]})
        self.assertNotIn('journal_podman_version',value)

    def test_structured_counts_distinguish_empty_unclassified_and_scoped_runtime_errors(self):
        empty=diagnostics.database_journal_records(b'',False)
        self.assertEqual(empty['journal_capture'],'observed')
        self.assertEqual(empty['journal_records'],0)
        self.assertEqual(empty['journal_bytes'],0)
        self.assertEqual(empty['categories'],[])
        records=[{'_UID':'1001','_COMM':'podman','MESSAGE':'Error: private opaque failure'},
                 {'_UID':'1001','_COMM':'private-command','MESSAGE':'Error: permission denied private credential'},
                 {'_UID':'1001','_COMM':'crun','MESSAGE':'Error: slirp4netns executable file not found'}]
        raw=('\n'.join(json.dumps(record) for record in records)+'\n').encode()
        value=diagnostics.database_journal_records(raw,False)
        self.assertEqual(value['journal_scope'],'root-synthetic-user')
        self.assertEqual(value['journal_records'],3)
        self.assertEqual(value['journal_database_unit_records'],0)
        self.assertEqual(value['journal_runtime_error_records'],2)
        self.assertEqual(value['journal_unclassified_error_records'],1)
        self.assertEqual(value['categories'],['executable-missing','network-helper-mentioned'])
        self.assertEqual(value['journal_sources']['other'],1)
        self.assertNotIn('private',json.dumps(value))
        self.assertNotIn('permission-denied',value['categories'])

    def test_wrong_uid_malformed_truncated_and_inconsistent_counts_are_inconclusive(self):
        record={'_UID':'1001','_COMM':'podman','MESSAGE':'Error: private opaque'}
        for raw,truncated in ((b'-- No entries --',False),(b'{broken private',False),
              (json.dumps({**record,'_UID':'0'}).encode(),False),
              (json.dumps({**record,'MESSAGE':[1,2]}).encode(),False),
              ((json.dumps(record)+'\n').encode()*41,False),
              (b'x'*65537,False),(json.dumps(record).encode(),True)):
            with self.subTest(length=len(raw),truncated=truncated):
                value=diagnostics.database_journal_records(raw,truncated)
                self.assertEqual(value['journal_capture'],'invalid')
                self.assertNotIn('categories',value)
                self.assertNotIn('private',json.dumps(value))
        valid=diagnostics.database_journal_records(json.dumps(record).encode(),False)
        for key,item in (('journal_records',True),('journal_records',2),
                         ('journal_database_unit_records',2),('journal_runtime_error_records',0),
                         ('journal_unclassified_error_records',2),('journal_bytes',65537),
                         ('journal_sources',{'private':1})):
            planted={**valid,key:item}
            self.assertEqual(diagnostics.sanitize_database_failure(planted)['journal_capture'],'invalid')

    def checkpoint(self,directory,response=None,error=None):
        def run(args,*,stdout,stderr,timeout):
            if args==('/usr/bin/podman','--version'):
                self.assertEqual(timeout,3)
                stdout.write(b'podman version 6.0.2\n')
                return subprocess.CompletedProcess(args,0)
            self.assertEqual(args,('journalctl','--no-pager','--all','--output=json','_UID=1001','-n','40'))
            self.assertEqual(stderr,subprocess.DEVNULL);self.assertEqual(timeout,8)
            if error:raise error
            stdout.write((json.dumps({'_UID':'1001','_COMM':'podman','_SYSTEMD_USER_UNIT':'sierx-postgres.service',
                'MESSAGE':'Error: private credential crun: keyring: Operation not permitted'})+'\n').encode())
            return subprocess.CompletedProcess(args,response or 0)
        with patch.object(diagnostics.os,'geteuid',return_value=0), \
                patch.object(diagnostics.subprocess,'run',side_effect=run):
            return diagnostics.checkpoint_database_journal(FAILED,directory)

    def test_root_checkpoint_is_suite_bound_private_and_merges_only_fixed_journal_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);directory.chmod(0o700)
            (directory/'suite.sha256').write_text('a'*64)
            value=self.checkpoint(directory)
            target=directory/'database-failure.json'
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(target.read_text()),value)
            self.assertFalse((directory/'database-failure.pending.json').exists())
            self.assertNotIn('private',json.dumps(value))
            merged=diagnostics.merge_database_journal(FAILED,value,'a'*64)
            self.assertEqual(merged['database_failure']['state'],FAILED['database_failure']['state'])
            self.assertEqual(merged['database_failure']['categories'],
                             ['keyring-error','operation-not-permitted','runtime-crun-error'])
            self.assertEqual(merged['command_exit_code'],1)
            self.assertEqual(merged['result'],'failed')
            self.assertEqual(merged['database_failure']['journal_scope'],'root-synthetic-user')
            self.assertEqual(merged['database_failure']['journal_records'],1)
            self.assertEqual(merged['database_failure']['journal_database_unit_records'],1)
            self.assertEqual(merged['database_failure']['journal_podman_version'],[6,0,2])
            self.assertEqual(diagnostics.sanitize_failure(merged),merged)
            with self.assertRaises(ValueError):self.checkpoint(directory)

    def test_optional_reader_failures_remain_failure_metadata_not_exception_messages(self):
        for response,error,reason in ((1,None,'command-exit'),(None,OSError('private'),'io-error'),
                                     (None,subprocess.TimeoutExpired('private',8),'timeout')):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary);directory.chmod(0o700);(directory/'suite.sha256').write_text('a'*64)
                value=self.checkpoint(directory,response,error)
                self.assertEqual(value['database_failure']['journal_capture'],'unavailable')
                self.assertEqual(value['database_failure']['journal_failure'],reason)
                self.assertNotIn('private',json.dumps(value))

    def test_wrong_phase_pass_or_unprivileged_caller_cannot_read_root_journal(self):
        with patch.object(diagnostics.subprocess,'run') as query:
            for result in ({'result':'passed','phase':'rootless-database'},None,
                           {'result':'failed','phase':'import'}):
                self.assertIsNone(diagnostics.checkpoint_database_journal(result,Path('/unused')))
            query.assert_not_called()
            with patch.object(diagnostics.os,'geteuid',return_value=1001),self.assertRaises(PermissionError):
                diagnostics.checkpoint_database_journal(FAILED,Path('/unused'))
            query.assert_not_called()

    def test_stale_wrong_scope_malformed_root_and_passing_results_never_merge(self):
        value={'schema':1,'suite':'offline-database-failure-v1','suite_sha256':'a'*64,
               'result':'failed','phase':'rootless-database','database_failure':{
               'state_capture':'unavailable','journal_capture':'observed','journal_scope':'root-system-user-unit',
               'categories':[],'journal_tail_truncated':False}}
        variants=[{**value,'suite_sha256':'b'*64},{**value,'schema':True},{**value,'result':'passed'},
                  {**value,'private':'credential'},{**value,'database_failure':None}]
        for key,item in (('journal_scope','guest-user'),('categories',['private credential']),
                         ('private','credential')):
            planted=copy.deepcopy(value);planted['database_failure'][key]=item;variants.append(planted)
        for planted in variants:
            self.assertIs(diagnostics.merge_database_journal(FAILED,planted,'a'*64),FAILED)
        passed={**FAILED,'result':'passed'}
        self.assertIs(diagnostics.merge_database_journal(passed,value,'a'*64),passed)
        observed=copy.deepcopy(FAILED);observed['database_failure'].update(
            journal_capture='observed',categories=['postgres-fatal'],journal_tail_truncated=False)
        unavailable=copy.deepcopy(value);unavailable['database_failure']={
            'state_capture':'unavailable','journal_capture':'unavailable','journal_scope':'root-system-user-unit'}
        self.assertIs(diagnostics.merge_database_journal(observed,unavailable,'a'*64),observed)

    def test_host_only_reads_fixed_checkpoint_for_failed_database_and_preserves_primary_on_error(self):
        for result in ({'result':'passed'},{'result':'failed','phase':'import'}):
            with patch.object(host,'disk_file') as read:
                self.assertIs(host.enrich_database_failure('/disk',result,'a'*64),result)
                read.assert_not_called()
        for raw in (b'{private malformed',b'x'*65537,b'{"database_failure":null}'):
            with patch.object(host,'disk_file',return_value=raw) as read:
                self.assertIs(host.enrich_database_failure('/disk',FAILED,'a'*64),FAILED)
                read.assert_called_once_with('/disk','database-failure.json')

    def test_actual_root_finish_collects_before_marker_and_optional_failure_cannot_change_result(self):
        for result,capture_fails in ((FAILED,False),(FAILED,True),({'result':'passed','phase':'complete'},False)):
            with self.subTest(result=result['result'],capture_fails=capture_fails),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);directory=root/'metadata';directory.mkdir();trace=root/'trace';trace.mkdir()
                (directory/'suite.sha256').write_text('a'*64)
                (directory/'kernel-start.json').write_text('{}');(trace/'tracing_on').write_text('1')
                (trace/'trace').write_text('');(trace/'per_cpu').mkdir()
                original_read=Path.read_text
                def read(path,*args,**kwargs):
                    if str(path)=='/home/acceptance/result.json':return json.dumps(result)
                    return original_read(path,*args,**kwargs)
                def capture(result,target):
                    self.assertEqual(result,FAILED);self.assertEqual(target,directory)
                    self.assertTrue((directory/'kernel.json').exists())
                    self.assertEqual((trace/'tracing_on').read_text(),'0')
                    self.assertNotIn('SIERX_FINISHED',output.getvalue())
                    if capture_fails:raise OSError('private diagnostic error')
                with patch.object(kernel,'DIRECTORY',directory),patch.object(kernel,'TRACE',trace), \
                        patch.object(kernel,'control',return_value={}),patch.object(kernel,'sample',return_value=[]), \
                        patch.object(kernel,'configuration',return_value={}),patch.object(Path,'read_text',read), \
                        patch.object(diagnostics,'checkpoint_database_journal',side_effect=capture) as collect, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    kernel.finish()
                if result['result']=='failed':collect.assert_called_once()
                else:collect.assert_not_called()
                self.assertEqual(output.getvalue(),'SIERX_FINISHED: '+'a'*64+' '+result['result']+'\n')


if __name__=='__main__':unittest.main()
