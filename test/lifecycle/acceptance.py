"""Real CLI/HTTP/SQL recovery acceptance in newly created disposable databases."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
def uid(): return str(uuid.uuid4())
def dsn_database(value,name):
    parsed=urllib.parse.urlsplit(value)
    if parsed.scheme not in ('postgres','postgresql') or not parsed.hostname or not parsed.path.strip('/'):
        raise ValueError('explicit PostgreSQL URL required')
    return urllib.parse.urlunsplit(parsed._replace(path='/'+name))
def run(args,env,ok=True):
    result=subprocess.run(args,cwd=ROOT,env=env,text=True,capture_output=True,timeout=60)
    if (result.returncode==0)!=ok:
        raise AssertionError('Lifecycle acceptance command had unexpected status: '+str(args[:2])+'\n'+result.stderr[:1000])
    return result.stdout.strip()
def sql(env,text): return run(['psql',env['DATABASE_URL'],'-X','-qAt','-v','ON_ERROR_STOP=1','-c',text],env)
def action(env,directory,kind,workspace=None,target=None,ok=True,**extra):
    a={'kind':kind,'case_ref':uid(),**extra}
    if workspace:a['workspace_id']=workspace
    if target:a['target_id']=target
    path=directory/'action.json';path.write_text(json.dumps(a));path.chmod(0o600)
    result=run(['bin/sierxctl','lifecycle','apply','--file',str(path)],env,ok=ok)
    return result

class App:
    def __init__(self,env,directory,expect_ready=True):
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        self.origin=f'http://localhost:{port}';self.cookie=''
        config={k:v for k,v in env.items() if k not in ('DATABASE_URL','SIERX_MAINTENANCE_DATABASE_URL','SIERX_LIFECYCLE_JOURNAL','SIERX_LIFECYCLE_KEY_FILE')}
        config.update(SIERX_BASE_URL=self.origin,SIERX_LISTEN_ADDR=f'127.0.0.1:{port}')
        self.log=(directory/(uid()+'.log')).open('w+')
        self.process=subprocess.Popen(['bin/sierx'],cwd=ROOT,env=config,stdout=self.log,stderr=self.log)
        deadline=time.monotonic()+8
        if not expect_ready:
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:self.close();raise AssertionError('restored app served before journal replay')
            assert self.process.returncode!=0
            return
        while time.monotonic()<deadline:
            if self.process.poll() is not None:self.close();raise AssertionError('guarded app exited before readiness')
            try:self.request('/api/v1/healthz');return
            except (OSError,AssertionError):time.sleep(.05)
        self.close();raise AssertionError('guarded app never became ready')
    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.log.close()
    def request(self,path,body=None,method=None,version=None,status=200):
        headers={'Content-Type':'application/json','Origin':self.origin}
        if self.cookie:headers['Cookie']=self.cookie
        if version is not None:headers['If-Match']=f'"{version}"'
        req=urllib.request.Request(self.origin+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
        try:
            response=urllib.request.urlopen(req,timeout=5)
        except urllib.error.HTTPError as e:response=e
        with response:
            raw=response.read().decode();actual=response.status
            assert actual==status,(path,actual,status,raw[:200])
            cookie=response.headers.get('Set-Cookie')
            if cookie:self.cookie=cookie.split(';',1)[0]
        if not raw:return None
        try:return json.loads(raw)
        except json.JSONDecodeError:return raw
    def login(self,email='lifecycle@example.test',password='test-password-12345'):
        return self.request('/api/v1/auth/login',{'email':email,'password':password})

def main():
    admin=os.environ['DATABASE_URL']
    tag=uuid.uuid4().hex[:16]
    source='sierx_lifecycle_'+tag;restored='sierx_lifecycle_restore_'+tag
    names=[];apps=[]
    with tempfile.TemporaryDirectory(prefix='sierx-lifecycle-') as tmp:
        directory=Path(tmp);guard=directory/'guard';guard.mkdir(mode=0o700)
        env=dict(os.environ)
        for key in ('DATABASE_URL','SIERX_RUNTIME_DATABASE_URL','SIERX_AUTH_DATABASE_URL','SIERX_MAINTENANCE_DATABASE_URL'):
            env[key]=dsn_database(os.environ[key],source)
        env.update(SIERX_AUTH_MODE='local',SIERX_ENV='dev',SIERX_SESSION_KEY='lifecycle-only-public-fixture-key-000000000000',
                   SIERX_BOOTSTRAP_WORKSPACE_SLUG='lifecycle',SIERX_BOOTSTRAP_WORKSPACE_NAME='Lifecycle fixture',
                   SIERX_BOOTSTRAP_ADMIN_EMAIL='lifecycle@example.test',SIERX_BOOTSTRAP_ADMIN_PASSWORD='test-password-12345',
                   SIERX_BOOTSTRAP_ADMIN_NAME='Lifecycle operator',SIERX_BOOTSTRAP_PROJECT_PREFIX='LCY',SIERX_BOOTSTRAP_PROJECT_NAME='Lifecycle',
                   SIERX_LIFECYCLE_JOURNAL=str(directory/'journal.jsonl'),SIERX_LIFECYCLE_KEY_FILE=str(directory/'key'),
                   SIERX_LIFECYCLE_CHECKPOINT=str(guard/'checkpoint.json'),SIERX_LIFECYCLE_GUARD_KEY_FILE=str(guard/'verification.key'))
        try:
            run(['createdb','--maintenance-db',admin,'--template=template0','--encoding=UTF8','--locale=C',source],env);names.append(source)
            run(['bash','scripts/migrate.sh','up'],env)
            run(['bin/sierxctl','bootstrap'],env)
            run(['psql',env['DATABASE_URL'],'-X','-v','ON_ERROR_STOP=1','-f','test/sql/lifecycle_fixture.sql'],env)
            run(['bin/sierxctl','lifecycle','init'],env)
            app=App(env,directory);apps.append(app);app.login()
            me=app.request('/api/v1/me');w=me['workspace_id'];owner=me['id']
            parent=app.request('/api/v1/items',{'project':'LCY','type':'epic','title':'Private root fixture','body':'root-secret'},status=201)
            child=app.request('/api/v1/items',{'project':'LCY','type':'story','title':'Private child fixture','body':'child-secret'},status=201)
            child=app.request('/api/v1/items/'+child['key']+'/move',{'parent':parent['key']},version=1)
            comment=app.request('/api/v1/comments',{'item':child['key'],'body':'comment-secret'},version=child['version'],status=201)
            view=app.request('/api/v1/views',{'name':'Private view','query':'project = LCY','layout':'list','shared':True},status=201)
            reader=uid();other=uid();replacement=uid()
            sql(env,f"INSERT INTO user_account(id,email,display_name) VALUES('{reader}','reader@example.test','Reader'),('{replacement}','replacement@example.test','Replacement'); INSERT INTO membership VALUES('{w}','{reader}','member'),('{w}','{replacement}','admin'); UPDATE project SET owner_id='{owner}' WHERE workspace_id='{w}'; INSERT INTO workspace(id,slug,name,origin_id) VALUES('{other}','unrelated','unrelated-secret','{uid()}'); INSERT INTO membership VALUES('{other}','{replacement}','admin'); INSERT INTO saved_view(workspace_id,owner_id,name,query,layout) VALUES('{other}','{replacement}','outside-secret','outside = secret','list');")
            case=uid()
            exported=json.loads(sql(env,f"SELECT row_to_json(x) FROM sierx_create_workspace_export('{w}','{owner}','{case}') x"))
            payload=sql(env,f"SELECT sierx_read_data_export('{exported['export_id']}','{case}')")
            assert 'child-secret' in payload and 'outside-secret' not in payload and 'password_hash' not in payload and 'totp_secret' not in payload
            # Same data before the first lifecycle decision, for a real restore.
            env['SIERX_DUMP_DIR']=str(directory/'backup')
            run(['bash','scripts/backup/driver.sh','pgdump','backup'],env)
            hold=uid();future=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(time.time()+86400))
            action(env,directory,'hold-create',w,hold,authority_ref=uid(),review_at=future)
            before=json.loads((guard/'checkpoint.json').read_text())['sequence']
            action(env,directory,'redact-item',w,parent['id'],ok=False)
            assert json.loads((guard/'checkpoint.json').read_text())['sequence']==before
            assert sql(env,"SELECT count(*) FROM operator_lifecycle_event WHERE outcome='blocked'")=='1'
            action(env,directory,'retention',w,ok=False,cutoff='2000-01-01T00:00:00Z')
            # Inaccessible export evidence is retained while a hold is active.
            action(env,directory,'takedown',w,parent['id'])
            sql(env,f"SELECT test_expire_export('{exported['export_id']}');")
            action(env,directory,'cleanup')
            assert sql(env,f"SELECT (payload IS NOT NULL AND revoked_at IS NOT NULL)::text FROM operator_data_export WHERE id='{exported['export_id']}'")=='true'
            action(env,directory,'restore-content',w,parent['id'])
            action(env,directory,'hold-release',w,hold)
            action(env,directory,'cleanup')
            assert sql(env,f"SELECT (payload IS NULL)::text FROM operator_data_export WHERE id='{exported['export_id']}'")=='true'
            # Overlapping independent notices must survive release of one root.
            action(env,directory,'takedown',w,parent['id'])
            app.request('/api/v1/items/'+parent['key'],status=404)
            app.request('/api/v1/items/'+child['key']+'/history',status=404)
            assert 'child-secret' not in json.dumps(app.request('/api/v1/items?fields=key,title,body,status'))
            runtime=dict(env,DATABASE_URL=env['SIERX_RUNTIME_DATABASE_URL'])
            assert sql(runtime,"SELECT count(*) FROM sierx_project_reserved_ranks")=='0'
            rank_probe=sql(runtime,f"BEGIN; SELECT set_config('sierx.workspace_id','{w}',true); SELECT set_config('sierx.user_id','{owner}',true); SELECT set_config('sierx.role','admin',true); SELECT count(*)||':'||count(id) FROM sierx_project_reserved_ranks; ROLLBACK;")
            assert rank_probe.splitlines()[-1]=='2:0'
            visible=app.request('/api/v1/items',{'project':'LCY','type':'story','title':'Visible with hidden ranks'},status=201)
            run(['psql',env['DATABASE_URL'],'-X','-v','ON_ERROR_STOP=1','-c',f"SET ROLE sierx_maintenance; SELECT sierx_read_data_export('{exported['export_id']}','{case}')"],env,ok=False)
            action(env,directory,'takedown',w,child['id'])
            action(env,directory,'restore-content',w,parent['id'])
            app.request('/api/v1/items/'+parent['key'])
            app.request('/api/v1/items/'+child['key'],status=404)
            # Moving a visible ancestor cannot leave hidden descendants behind.
            run(['psql',env['DATABASE_URL'],'-X','-v','ON_ERROR_STOP=1','-c',f"SELECT test_move_restricted_item('{parent['id']}','{visible['id']}')"],env,ok=False)
            assert sql(env,f"SELECT parent_id IS NULL FROM item WHERE id='{parent['id']}'")=='t'
            action(env,directory,'restore-content',w,child['id'])
            app.request('/api/v1/items/'+child['key'])
            event=int(sql(env,f"SELECT max(seq) FROM change_event WHERE item_id='{child['id']}'"))
            action(env,directory,'correct-history',w,child['id'],event_seq=event,correction='Operator correction fixture')
            assert 'Operator correction fixture' in json.dumps(app.request('/api/v1/items/'+child['key']+'/history'))
            action(env,directory,'redact-comment',w,comment['id'])
            assert sql(env,f"SELECT body FROM comment WHERE id='{comment['id']}'")=='[redacted]'
            assert 'comment-secret' not in sql(env,f"SELECT coalesce(string_agg(old_value::text||new_value::text,''),'') FROM change_event WHERE item_id='{child['id']}'")
            action(env,directory,'redact-view',w,view['id'])
            assert view['id'] not in json.dumps(app.request('/api/v1/views'))
            action(env,directory,'redact-item',w,parent['id'])
            action(env,directory,'restore-content',w,parent['id'])
            app.request('/api/v1/items/'+parent['key'],status=404)
            assert sql(env,f"SELECT count(*) FROM item WHERE id IN ('{parent['id']}','{child['id']}') AND body IS NULL AND fields='{{}}'")=='2'
            assert sql(env,f"SELECT next_key_num FROM project WHERE workspace_id='{w}'")=='4'
            # Expiry is explicit and never touches an active item or workspace.
            retained=app.request('/api/v1/items',{'project':'LCY','type':'story','title':'Retention fixture','body':'retention-secret'},status=201)
            active=app.request('/api/v1/items',{'project':'LCY','type':'story','title':'Active retained fixture'},status=201)
            sql(env,f"SELECT test_mark_expired_item('{retained['id']}');")
            cutoff=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(time.time()-86400))
            policy=directory/'retention.json'
            policy.write_text(json.dumps({'enabled':False}));policy.chmod(0o600)
            run(['bin/sierxctl','lifecycle','maintain','--policy',str(policy)],env)
            assert sql(env,f"SELECT title FROM item WHERE id='{retained['id']}'")=='Retention fixture'
            policy.write_text(json.dumps({'enabled':True,'case_ref':uid(),'workspaces':[{'workspace_id':w,'deleted_content_days':1}]}));policy.chmod(0o600)
            run(['bin/sierxctl','lifecycle','maintain','--policy',str(policy)],env)
            assert sql(env,f"SELECT title FROM item WHERE id='{retained['id']}'")=='[redacted]'
            app.request('/api/v1/items/'+active['key'])
            # Revocation, replacement admin and atomic ownership reassignment.
            action(env,directory,'remove-member',w,owner,replacement_id=reader,ok=False)
            action(env,directory,'remove-member',w,owner,replacement_id=replacement)
            app.request('/api/v1/me',status=401)
            assert sql(env,f"SELECT owner_id FROM project WHERE workspace_id='{w}'")==replacement
            action(env,directory,'anonymize-account',w,replacement,ok=False)
            action(env,directory,'anonymize-account',w,owner)
            assert sql(env,f"SELECT is_active::text||':'||(password_hash IS NULL)::text||':'||(totp_secret IS NULL)::text FROM user_account WHERE id='{owner}'")=='false:true:true'
            run(['psql',env['DATABASE_URL'],'-X','-v','ON_ERROR_STOP=1','-c',f"SELECT sierx_set_account_active('{owner}',true,'{uid()}')"],env,ok=False)
            action(env,directory,'cleanup')
            run(['bin/sierxctl','lifecycle','verify'],env)
            # Guard rechecks the external checkpoint even after startup.
            checkpoint=(guard/'checkpoint.json').read_bytes();(guard/'checkpoint.json').unlink()
            app.request('/api/v1/healthz',status=503)
            (guard/'checkpoint.json').write_bytes(checkpoint);(guard/'checkpoint.json').chmod(0o600)
            app.request('/api/v1/healthz')
            # Restore an old populated backup: access is blocked, then an exact
            # journal replay reapplies the decisions with identical stable IDs.
            restore_env=dict(env)
            for key in ('DATABASE_URL','SIERX_RUNTIME_DATABASE_URL','SIERX_AUTH_DATABASE_URL','SIERX_MAINTENANCE_DATABASE_URL'):
                restore_env[key]=dsn_database(env[key],restored)
            run(['createdb','--maintenance-db',admin,'--template=template0','--encoding=UTF8','--locale=C',restored],env);names.append(restored)
            run(['bash','scripts/backup/driver.sh','pgdump','restore-to',restore_env['DATABASE_URL']],restore_env)
            failed=App(restore_env,directory,expect_ready=False);apps.append(failed)
            run(['bin/sierxctl','lifecycle','verify'],restore_env,ok=False)
            run(['bin/sierxctl','lifecycle','replay'],restore_env)
            run(['bin/sierxctl','lifecycle','verify'],restore_env)
            run(['bin/sierxctl','lifecycle','replay'],restore_env) # exact replay is idempotent
            recovered=App(restore_env,directory);apps.append(recovered)
            recovered.request('/api/v1/auth/login',{'email':'lifecycle@example.test','password':'test-password-12345'},status=401)
            assert sql(restore_env,f"SELECT title FROM item WHERE id='{parent['id']}'")=='[redacted]'
            assert sql(restore_env,f"SELECT body FROM comment WHERE id='{comment['id']}'")=='[redacted]'
            assert sql(restore_env,f"SELECT query FROM saved_view WHERE id='{view['id']}'")==''
            assert sql(restore_env,f"SELECT count(*) FROM membership WHERE user_id='{owner}'")=='0'
            # No ordinary role can alter lifecycle receipts, holds or audits.
            for role in ('sierx_runtime','sierx_auth','sierx_maintenance'):
                run(['psql',env['DATABASE_URL'],'-X','-v','ON_ERROR_STOP=1','-c',f"SET ROLE {role}; DELETE FROM operator_lifecycle_event"],env,ok=False)
            journal=Path(env['SIERX_LIFECYCLE_JOURNAL']);original=journal.read_bytes();journal.write_bytes(original[:-10])
            run(['bin/sierxctl','lifecycle','verify'],restore_env,ok=False)
            run(['bin/sierxctl','lifecycle','replay'],restore_env,ok=False)
            journal.write_bytes(original)
            print('lifecycle acceptance: real CLI, holds, overlapping takedowns, redaction, corrections, retention, membership/session revocation, exports, fail-closed guard, and pre-redaction backup replay passed')
        finally:
            for app in apps:app.close()
            for name in reversed(names):
                subprocess.run(['dropdb','--maintenance-db',admin,'--if-exists',name],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)

if __name__=='__main__':main()
