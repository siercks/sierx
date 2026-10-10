-- Database-level tenant isolation and role posture checks for migration 0011.
-- Run as the privileged disposable test operator; no fixtures survive rollback.
\set ON_ERROR_STOP on
BEGIN;

-- Exercise operator maintenance as its own login role and prove newly
-- generated partitions receive the same direct-access policy.
SET LOCAL ROLE sierx_maintenance;
SELECT * FROM change_event_ensure_partitions(12);
RESET ROLE;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhrelid
    WHERE i.inhparent='public.change_event'::regclass
      AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity
        OR NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid AND p.polname='change_event_partition_runtime')
        OR NOT has_table_privilege('sierx_runtime',c.oid,'SELECT')
        OR NOT has_table_privilege('sierx_runtime',c.oid,'INSERT'))
  ) THEN RAISE EXCEPTION 'a generated event partition is missing forced RLS, policy, or runtime grants'; END IF;
END $$;

INSERT INTO workspace (id, slug, name, origin_id) VALUES
 ('11000000-0000-7000-8000-000000000001','rls-a','RLS A','11000000-0000-7000-8000-000000000001'),
 ('11000000-0000-7000-8000-000000000002','rls-b','RLS B','11000000-0000-7000-8000-000000000002');
INSERT INTO user_account (id, email, display_name, password_hash) VALUES
 ('12000000-0000-7000-8000-000000000001','rls-a@example.test','RLS A','fixture-hash-a'),
 ('12000000-0000-7000-8000-000000000002','rls-b@example.test','RLS B','fixture-hash-b'),
 ('12000000-0000-7000-8000-000000000003','rls-member@example.test','RLS member','fixture-hash-member'),
 ('12000000-0000-7000-8000-000000000004','rls-admin@example.test','RLS admin','fixture-hash-admin');
INSERT INTO membership (workspace_id,user_id,role) VALUES
 ('11000000-0000-7000-8000-000000000001','12000000-0000-7000-8000-000000000001','member'),
 ('11000000-0000-7000-8000-000000000002','12000000-0000-7000-8000-000000000002','admin'),
 ('11000000-0000-7000-8000-000000000001','12000000-0000-7000-8000-000000000003','member'),
 ('11000000-0000-7000-8000-000000000001','12000000-0000-7000-8000-000000000004','admin');
INSERT INTO project (id,workspace_id,key_prefix,name,kind) VALUES
 ('13000000-0000-7000-8000-000000000001','11000000-0000-7000-8000-000000000001','RLA','A','delivery'),
 ('13000000-0000-7000-8000-000000000002','11000000-0000-7000-8000-000000000002','RLB','B','delivery');
INSERT INTO project_config(project_id,version) VALUES
 ('13000000-0000-7000-8000-000000000001',1),('13000000-0000-7000-8000-000000000002',1);
INSERT INTO status(id,project_id,key,name,category) VALUES
 ('14000000-0000-7000-8000-000000000001','13000000-0000-7000-8000-000000000001','todo','To do','open'),
 ('14000000-0000-7000-8000-000000000002','13000000-0000-7000-8000-000000000002','todo','To do','open');
INSERT INTO item_type(id,project_id,key,name,level) VALUES
 ('15000000-0000-7000-8000-000000000001','13000000-0000-7000-8000-000000000001','task','Task',0),
 ('15000000-0000-7000-8000-000000000002','13000000-0000-7000-8000-000000000002','task','Task',0);
INSERT INTO item(id,workspace_id,project_id,key,item_type_id,status_id,config_version,path,title,rank,change_seq,origin_id) VALUES
 ('16000000-0000-7000-8000-000000000001','11000000-0000-7000-8000-000000000001','13000000-0000-7000-8000-000000000001','RLA-1','15000000-0000-7000-8000-000000000001','14000000-0000-7000-8000-000000000001',1,'16000000-0000-7000-8000-000000000001','A item','a',1,'11000000-0000-7000-8000-000000000001'),
 ('16000000-0000-7000-8000-000000000002','11000000-0000-7000-8000-000000000002','13000000-0000-7000-8000-000000000002','RLB-1','15000000-0000-7000-8000-000000000002','14000000-0000-7000-8000-000000000002',1,'16000000-0000-7000-8000-000000000002','B item','a',1,'11000000-0000-7000-8000-000000000002');
INSERT INTO item_link(from_item_id,to_item_id,kind) VALUES
 ('16000000-0000-7000-8000-000000000001','16000000-0000-7000-8000-000000000002','relates');
INSERT INTO item_rollup(item_id) VALUES
 ('16000000-0000-7000-8000-000000000001'),('16000000-0000-7000-8000-000000000002');
INSERT INTO comment(item_id,author_id,body) VALUES
 ('16000000-0000-7000-8000-000000000001','12000000-0000-7000-8000-000000000001','A comment'),
 ('16000000-0000-7000-8000-000000000002','12000000-0000-7000-8000-000000000002','B comment');
INSERT INTO saved_view(workspace_id,owner_id,name,query,layout,shared) VALUES
 ('11000000-0000-7000-8000-000000000001','12000000-0000-7000-8000-000000000001','A private','', 'list',false),
 ('11000000-0000-7000-8000-000000000001','12000000-0000-7000-8000-000000000001','A shared','', 'list',true),
 ('11000000-0000-7000-8000-000000000001','12000000-0000-7000-8000-000000000003','Member private','', 'list',false),
 ('11000000-0000-7000-8000-000000000002','12000000-0000-7000-8000-000000000002','B shared','', 'list',true);
INSERT INTO sprint(id,project_id,name,starts_on,ends_on,state) VALUES
 ('17000000-0000-7000-8000-000000000001','13000000-0000-7000-8000-000000000001','A sprint',CURRENT_DATE,CURRENT_DATE+30,'active'),
 ('17000000-0000-7000-8000-000000000002','13000000-0000-7000-8000-000000000002','B sprint',CURRENT_DATE,CURRENT_DATE+30,'active');
INSERT INTO sprint_item(sprint_id,item_id) VALUES
 ('17000000-0000-7000-8000-000000000001','16000000-0000-7000-8000-000000000001'),
 ('17000000-0000-7000-8000-000000000002','16000000-0000-7000-8000-000000000002');

-- Missing identity fails closed, even when the connection is reused.
SET LOCAL ROLE sierx_runtime;
DO $$ BEGIN
  IF (SELECT count(*) FROM workspace) <> 0 OR (SELECT count(*) FROM item) <> 0 THEN
    RAISE EXCEPTION 'runtime without transaction-local identity saw tenant data';
  END IF;
END $$;
RESET ROLE;

-- Member scope: direct SQL isolation and positive controls, without endpoint predicates.
SELECT set_config('sierx.workspace_id','11000000-0000-7000-8000-000000000001',true);
SELECT set_config('sierx.user_id','12000000-0000-7000-8000-000000000001',true);
SELECT set_config('sierx.role','member',true);
SET LOCAL ROLE sierx_runtime;
DO $$ DECLARE event_rows integer; BEGIN
  IF (SELECT count(*) FROM workspace) <> 1 OR (SELECT count(*) FROM project) <> 1 OR (SELECT count(*) FROM item) <> 1 THEN
    RAISE EXCEPTION 'member scope did not select exactly its workspace/project/item';
  END IF;
  IF (SELECT count(*) FROM item_link) <> 0 OR (SELECT count(*) FROM comment) <> 1 THEN
    RAISE EXCEPTION 'linked item or comment policy leaked cross-workspace content';
  END IF;
  IF (SELECT count(*) FROM project_config) <> 1 OR (SELECT count(*) FROM status) <> 1
     OR (SELECT count(*) FROM item_type) <> 1 OR (SELECT count(*) FROM item_rollup) <> 1
     OR (SELECT count(*) FROM sprint) <> 1 OR (SELECT count(*) FROM sprint_item) <> 1
     OR (SELECT count(*) FROM seq_counter) <> 1 THEN
    RAISE EXCEPTION 'derived project/item rows or sequence counters escaped tenant scope';
  END IF;
  IF (SELECT count(*) FROM saved_view) <> 2 THEN
    RAISE EXCEPTION 'saved view owner/shared visibility is incorrect';
  END IF;
  EXECUTE format('SELECT count(*) FROM public.%I', 'change_event_' || to_char(now() AT TIME ZONE 'UTC','YYYY_MM')) INTO event_rows;
  IF event_rows <> 0 THEN RAISE EXCEPTION 'direct partition SELECT leaked event rows without a row scope'; END IF;
  IF (SELECT count(*) FROM item WHERE id='16000000-0000-7000-8000-000000000002') <> 0 THEN
    RAISE EXCEPTION 'cross-workspace item SELECT was not filtered';
  END IF;
  UPDATE item SET title='should not change' WHERE id='16000000-0000-7000-8000-000000000002';
  IF FOUND THEN RAISE EXCEPTION 'cross-workspace UPDATE affected a row'; END IF;
  DELETE FROM item WHERE id='16000000-0000-7000-8000-000000000002';
  IF FOUND THEN RAISE EXCEPTION 'cross-workspace DELETE affected a row'; END IF;
  INSERT INTO change_event(workspace_id,seq,item_id,actor_id,kind)
  VALUES ('11000000-0000-7000-8000-000000000001',1,'16000000-0000-7000-8000-000000000001','12000000-0000-7000-8000-000000000001','created');
  BEGIN
    INSERT INTO change_event(workspace_id,seq,item_id,actor_id,kind)
    VALUES ('11000000-0000-7000-8000-000000000002',2,'16000000-0000-7000-8000-000000000002','12000000-0000-7000-8000-000000000002','created');
    RAISE EXCEPTION 'cross-workspace event INSERT unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  EXECUTE format('SELECT count(*) FROM public.%I', 'change_event_' || to_char(now() AT TIME ZONE 'UTC','YYYY_MM')) INTO event_rows;
  IF event_rows <> 1 THEN RAISE EXCEPTION 'direct partition SELECT did not apply tenant isolation'; END IF;
  BEGIN
    INSERT INTO item(id,workspace_id,project_id,key,item_type_id,status_id,config_version,path,title,rank,change_seq,origin_id)
    VALUES ('16000000-0000-7000-8000-000000000003','11000000-0000-7000-8000-000000000002','13000000-0000-7000-8000-000000000002','RLB-2','15000000-0000-7000-8000-000000000002','14000000-0000-7000-8000-000000000002',1,'16000000-0000-7000-8000-000000000003','bad','b',2,'11000000-0000-7000-8000-000000000002');
    RAISE EXCEPTION 'cross-workspace INSERT unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
RESET ROLE;

-- A different same-workspace member sees shared, not another user's private
-- views, and cannot edit another author's comment.
SELECT set_config('sierx.user_id','12000000-0000-7000-8000-000000000003',true);
SELECT set_config('sierx.role','member',true);
SET LOCAL ROLE sierx_runtime;
DO $$ BEGIN
  IF (SELECT count(*) FROM item) <> 1
     OR (SELECT count(*) FROM saved_view WHERE name='A shared') <> 1
     OR (SELECT count(*) FROM saved_view WHERE name='Member private') <> 1
     OR (SELECT count(*) FROM saved_view WHERE name='A private') <> 0 THEN
    RAISE EXCEPTION 'same-workspace member visibility or shared/private view isolation failed';
  END IF;
  UPDATE comment SET body='tampered' WHERE item_id='16000000-0000-7000-8000-000000000001';
  IF FOUND THEN RAISE EXCEPTION 'member edited another author''s comment'; END IF;
END $$;
RESET ROLE;

-- Same-workspace admin can apply the optimistic metadata update contract.
SELECT set_config('sierx.user_id','12000000-0000-7000-8000-000000000004',true);
SELECT set_config('sierx.role','admin',true);
SET LOCAL ROLE sierx_runtime;
DO $$ BEGIN
  UPDATE project SET name='A renamed',version=version+1,updated_at=now()
   WHERE id='13000000-0000-7000-8000-000000000001';
  IF NOT FOUND THEN RAISE EXCEPTION 'workspace admin could not update project metadata'; END IF;
END $$;
RESET ROLE;

-- Authentication is intentionally global on a separate constrained role;
-- credential access does not imply any application item visibility.
SET LOCAL ROLE sierx_auth;
DO $$ BEGIN
  IF (SELECT count(id) FROM user_account) <> 4 THEN RAISE EXCEPTION 'auth role cannot resolve users globally'; END IF;
  IF (SELECT count(*) FROM user_account WHERE email='rls-b@example.test' AND password_hash='fixture-hash-b') <> 1 THEN
    RAISE EXCEPTION 'auth role cannot read the required credential fields';
  END IF;
  INSERT INTO session(id_hash,user_id,expires_at) VALUES (decode(repeat('ab',32),'hex'),'12000000-0000-7000-8000-000000000002',now()+interval '1 hour');
  DELETE FROM session WHERE id_hash=decode(repeat('ab',32),'hex');
END $$;
RESET ROLE;
ROLLBACK;
\echo 'test-rls: generated partitions, auth path, missing context, tenant CRUD, project roles, linked rows, comments and saved views passed'
