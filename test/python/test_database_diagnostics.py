"""Failed database diagnostics preserve failure and disclose only fixed metadata."""
import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import offline_host_diagnostics as diagnostics


class DatabaseDiagnosticsTests(unittest.TestCase):
    def capture(self,state,journal=b'private credential\ncrun: keyring: Operation not permitted\n'):
        commands=[]
        def run(args,*,stdout,stderr,timeout):
            commands.append(args)
            self.assertEqual(timeout,8)
            self.assertEqual(stderr,subprocess.DEVNULL)
            stdout.write(state if args[0]=='systemctl' else journal)
            return subprocess.CompletedProcess(args,0)
        with patch.object(diagnostics.subprocess,'run',side_effect=run):
            result=diagnostics.database_service_failure()
        self.assertEqual(len(commands),2)
        self.assertEqual(commands[0][:4],('systemctl','--user','show','--no-pager'))
        self.assertEqual(commands[0][-1],'sierx-postgres.service')
        self.assertEqual(commands[1],('journalctl','--user','--no-pager','--all','--output=cat',
                                      '-u','sierx-postgres.service','-n','40'))
        return result

    def test_current_state_and_bounded_journal_are_fixed_metadata_without_private_output(self):
        state=(b'Id=sierx-postgres.service\nResult=exit-code\nLoadState=loaded\n'
               b'ActiveState=activating\nSubState=auto-restart\nExecMainCode=1\n'
               b'ExecMainStatus=126\nNRestarts=2\nDescription=private credential\n')
        result=self.capture(state)
        self.assertEqual(result,{'state_capture':'observed','journal_capture':'observed',
            'state':{'Result':'exit-code','LoadState':'loaded','ActiveState':'activating',
                     'SubState':'auto-restart','ExecMainCode':1,'ExecMainStatus':126,'NRestarts':2},
            'journal_tail_truncated':False,
            'categories':['keyring-error','operation-not-permitted','runtime-crun-error']})
        failure={'result':'failed','phase':'rootless-database','failure_type':'RuntimeError',
                 'command_exit_code':1,'database_failure':result}
        self.assertEqual(diagnostics.sanitize_failure(failure),failure)
        self.assertNotIn('database_failure',diagnostics.sanitize_failure({**failure,'phase':'import'}))
        self.assertNotIn('private',json.dumps(result))
        self.assertNotIn('sierx-postgres.service',json.dumps(result))
        with self.assertRaises(ValueError):diagnostics.sanitize_failure({**failure,'result':'passed'})

    def test_malformed_duplicate_wrong_unit_and_truncated_state_are_inconclusive(self):
        for state in (b'Id=other-private.service\nResult=exit-code\n',
                      b'Id=sierx-postgres.service\nId=sierx-postgres.service\nResult=exit-code\n',
                      b'Id=sierx-postgres.service\nnot an assignment\n',
                      b'Id=sierx-postgres.service\nResult=private\n',b'\xff\n',
                      b'x'*8193+b'\nId=sierx-postgres.service\nResult=exit-code\n'):
            with self.subTest(state=state[:20]):
                result=self.capture(state,b'private')
                self.assertEqual(result['state_capture'],'invalid')
                self.assertNotIn('state',result)
                self.assertNotIn('private',json.dumps(result))
        result=self.capture(b'Id=sierx-postgres.service\nResult=exit-code\n',
                            b'keyring private secret'+b'x'*65536)
        self.assertTrue(result['journal_tail_truncated'])
        self.assertEqual(result['categories'],[])

    def test_unavailable_reads_and_invalid_fields_never_claim_success_or_echo_values(self):
        for error in (OSError('private path'),subprocess.TimeoutExpired(['private'],8)):
            with patch.object(diagnostics.subprocess,'run',side_effect=error):
                self.assertEqual(diagnostics.database_service_failure(),
                                 {'state_capture':'unavailable','journal_capture':'unavailable'})
        result=diagnostics.sanitize_database_failure({'state_capture':'observed',
            'state':{'Result':'exit-code','ExecMainCode':True,'ExecMainStatus':256,'NRestarts':10**9,
                     'private':'credential'},'journal_capture':'observed',
            'categories':['private credential'],'journal_tail_truncated':False})
        self.assertEqual(result,{'state_capture':'observed','state':{'Result':'exit-code'},
                                 'journal_capture':'invalid'})
        self.assertIsNone(diagnostics.sanitize_database_failure('private'))

    def test_real_guest_failure_checkpoint_precedes_reads_and_survives_optional_capture_failure(self):
        tree=ast.parse((ROOT/'scripts/offline-host-guest.py').read_text())
        main_guard=tree.body[-1]
        for capture_fails in (False,True):
            with self.subTest(capture_fails=capture_fails),tempfile.TemporaryDirectory() as temporary:
                home=Path(temporary)
                def main():
                    error=RuntimeError('private database error')
                    error.fixture_exit_code=1
                    raise error
                def capture():
                    checkpoint=json.loads((home/'failure.json').read_text())
                    self.assertEqual(checkpoint['phase'],'rootless-database')
                    self.assertEqual(checkpoint['command_exit_code'],1)
                    if capture_fails:raise OSError('private diagnostic error')
                    return {'state_capture':'unavailable','journal_capture':'unavailable'}
                safe=SimpleNamespace(failure_record=diagnostics.failure_record,
                    checkpoint_failure=diagnostics.checkpoint_failure,
                    database_service_failure=capture,emit_resources=lambda:None)
                namespace={'__name__':'__main__','sys':SimpleNamespace(argv=['guest.py'],exit=sys.exit),
                    'OPTIONS':{},'main':main,'LOG':home/'private.log','PHASE':'rootless-database',
                    'diagnostics':safe,'HOME':home,'json':json,'os':SimpleNamespace(sync=lambda:None),
                    'subprocess':SimpleNamespace(run=lambda *a,**k:None,TimeoutExpired=subprocess.TimeoutExpired)}
                with contextlib.redirect_stdout(io.StringIO()) as output,self.assertRaises(SystemExit) as error:
                    exec(compile(ast.Module(body=[main_guard],type_ignores=[]),'offline-host-guest.py','exec'),namespace)
                self.assertEqual(error.exception.code,1)
                result=json.loads((home/'result.json').read_text())
                self.assertEqual(result['result'],'failed')
                self.assertEqual(result['command_exit_code'],1)
                self.assertEqual('database_failure' in result,not capture_fails)
                self.assertNotIn('private',output.getvalue()+json.dumps(result))


if __name__=='__main__':unittest.main()
