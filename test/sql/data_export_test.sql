-- The limited export includes only directly attributed fields and expires.
\set ON_ERROR_STOP on
BEGIN;

DO $$
BEGIN
  IF (SELECT pg_get_userbyid(p.proowner) FROM pg_proc p
      WHERE p.oid='public.sierx_create_data_export(uuid,uuid)'::regprocedure) <> 'sierx_maintenance'
     OR (SELECT pg_get_userbyid(p.proowner) FROM pg_proc p
         WHERE p.oid='public.sierx_read_data_export(uuid,uuid)'::regprocedure) <> 'sierx_maintenance' THEN
    RAISE EXCEPTION 'export functions are not owned by maintenance role';
  END IF;
  IF has_function_privilege('sierx_runtime','public.sierx_create_data_export(uuid,uuid)','EXECUTE')
     OR has_function_privilege('sierx_runtime','public.sierx_read_data_export(uuid,uuid)','EXECUTE')
     OR has_table_privilege('sierx_runtime','public.operator_data_export','SELECT')
     OR has_table_privilege('sierx_runtime','public.operator_data_export_event','SELECT') THEN
    RAISE EXCEPTION 'runtime role can access operator export artifacts';
  END IF;
  IF has_column_privilege('sierx_maintenance','public.user_account','password_hash','SELECT')
     OR has_column_privilege('sierx_maintenance','public.user_account','totp_secret','SELECT')
     OR has_column_privilege('sierx_maintenance','public.session','id_hash','SELECT') THEN
    RAISE EXCEPTION 'maintenance role can read authentication secrets';
  END IF;
  IF has_column_privilege('sierx_maintenance','public.operator_data_export','expires_at','UPDATE')
     OR has_column_privilege('sierx_maintenance','public.operator_data_export','case_ref','UPDATE')
     OR has_table_privilege('sierx_maintenance','public.operator_data_export_event','UPDATE')
     OR has_table_privilege('sierx_maintenance','public.operator_data_export_event','DELETE') THEN
    RAISE EXCEPTION 'maintenance role can change export expiry/case scope or edit the audit trail';
  END IF;
END $$;

INSERT INTO user_account (id,email,display_name,password_hash,totp_secret)
VALUES
 ('14000000-0000-7000-8000-000000000001','export-a@example.test','Export A','never-export-this',decode(repeat('ef',20),'hex')),
 ('14000000-0000-7000-8000-000000000002','export-b@example.test','Export B','other-account-secret',decode(repeat('aa',20),'hex'));
INSERT INTO workspace (id,slug,name,origin_id)
VALUES
 ('14000000-0000-7000-8000-000000000011','export-a','Export Workspace','14000000-0000-7000-8000-000000000021'),
 ('14000000-0000-7000-8000-000000000012','export-b','Unrelated Workspace','14000000-0000-7000-8000-000000000022');
INSERT INTO membership (workspace_id,user_id,role)
VALUES
 ('14000000-0000-7000-8000-000000000011','14000000-0000-7000-8000-000000000001','admin'),
 ('14000000-0000-7000-8000-000000000012','14000000-0000-7000-8000-000000000002','member');
INSERT INTO project (id,workspace_id,key_prefix,name,kind)
VALUES ('14000000-0000-7000-8000-000000000041','14000000-0000-7000-8000-000000000011','EXP','Export Project','delivery');
INSERT INTO project_config (project_id,version)
VALUES ('14000000-0000-7000-8000-000000000041',1);
INSERT INTO status (id,project_id,key,name,category)
VALUES ('14000000-0000-7000-8000-000000000051','14000000-0000-7000-8000-000000000041','open','Open','open');
INSERT INTO item_type (id,project_id,key,name,level)
VALUES ('14000000-0000-7000-8000-000000000052','14000000-0000-7000-8000-000000000041','task','Task',0);
INSERT INTO item (id,workspace_id,project_id,key,item_type_id,status_id,config_version,path,title,rank,change_seq,origin_id)
VALUES ('14000000-0000-7000-8000-000000000061','14000000-0000-7000-8000-000000000011',
        '14000000-0000-7000-8000-000000000041','EXP-1','14000000-0000-7000-8000-000000000052',
        '14000000-0000-7000-8000-000000000051',1,'14000000-0000-7000-8000-000000000061',
        'Export test item','a',0,'14000000-0000-7000-8000-000000000021');
INSERT INTO comment (id,item_id,author_id,body,deleted_at)
VALUES
 ('14000000-0000-7000-8000-000000000071','14000000-0000-7000-8000-000000000061',
  '14000000-0000-7000-8000-000000000001',repeat('x',4097),NULL),
 ('14000000-0000-7000-8000-000000000072','14000000-0000-7000-8000-000000000061',
  '14000000-0000-7000-8000-000000000001','deleted-body-secret',now()),
 ('14000000-0000-7000-8000-000000000073','14000000-0000-7000-8000-000000000061',
  '14000000-0000-7000-8000-000000000002','other-account-comment-secret',NULL);
INSERT INTO saved_view (id,workspace_id,owner_id,name,query,layout,shared)
VALUES ('14000000-0000-7000-8000-000000000031','14000000-0000-7000-8000-000000000011',
        '14000000-0000-7000-8000-000000000001','My view','status = open','list',false),
       ('14000000-0000-7000-8000-000000000032','14000000-0000-7000-8000-000000000012',
        '14000000-0000-7000-8000-000000000002','Other view','secret = true','board',false);

CREATE TEMP TABLE export_fixture(id uuid, expires_at timestamptz);
GRANT SELECT, INSERT ON export_fixture TO sierx_maintenance;
SET ROLE sierx_maintenance;
INSERT INTO export_fixture
SELECT * FROM public.sierx_create_data_export(
  '14000000-0000-7000-8000-000000000001','14000000-0000-7000-8000-000000000099'
);
DO $$
DECLARE p jsonb; export_key uuid; expiry timestamptz;
BEGIN
  SELECT id,expires_at INTO export_key,expiry FROM export_fixture;
  SELECT payload INTO p FROM public.operator_data_export WHERE id=export_key;
  IF expiry < now()+interval '59 minutes' OR expiry > now()+interval '61 minutes' THEN
    RAISE EXCEPTION 'export expiry is not the documented one-hour window';
  END IF;
  IF p->>'scope' <> 'sierx-account-export-v1-limited'
     OR p->>'completeness' NOT LIKE 'This export is limited%'
     OR p->'account'->>'email' <> 'export-a@example.test'
     OR p->'account' ? 'password_hash' OR p->'account' ? 'totp_secret'
     OR p::text LIKE '%never-export-this%' OR p::text LIKE '%other-account-secret%'
     OR p::text LIKE '%Unrelated Workspace%' OR p::text LIKE '%other@example.test%' THEN
    RAISE EXCEPTION 'export includes secrets, unrelated account/workspace data, or omits its limited-scope marker';
  END IF;
  IF jsonb_array_length(p->'memberships') <> 1 OR p->'memberships'->0->>'workspace_slug' <> 'export-a' THEN
    RAISE EXCEPTION 'export membership mismatch: %', p->'memberships';
  END IF;
  IF jsonb_array_length(p->'owned_saved_views') <> 1 OR p->'owned_saved_views'->0->>'name' <> 'My view' THEN
    RAISE EXCEPTION 'export saved-view mismatch: %', p->'owned_saved_views';
  END IF;
  IF jsonb_array_length(p->'authored_comments') <> 2 THEN
    RAISE EXCEPTION 'export comment count mismatch: %', p->'authored_comments';
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(p->'authored_comments') c
        WHERE c->>'body_truncated'='true' AND char_length(c->>'body')=4096
     ) THEN
    RAISE EXCEPTION 'export comment body truncation mismatch: %', p->'authored_comments';
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(p->'authored_comments') c
        WHERE c->>'deleted_at' IS NOT NULL AND c->'body'='null'::jsonb
     )
     OR p::text LIKE '%deleted-body-secret%' THEN
    RAISE EXCEPTION 'soft-deleted comment body was not omitted: %', p->'authored_comments';
  END IF;
  IF p::text LIKE '%other-account-comment-secret%' THEN
    RAISE EXCEPTION 'comment authored by another account was included';
  END IF;
  IF (SELECT count(*) FROM public.operator_data_export_event
      WHERE export_id=export_key AND event='created') <> 1 THEN
    RAISE EXCEPTION 'export creation was not audited';
  END IF;
  IF public.sierx_read_data_export(export_key,'14000000-0000-7000-8000-000000000099') <> p THEN
    RAISE EXCEPTION 'case-bound download returned a different payload';
  END IF;
  IF (SELECT count(*) FROM public.operator_data_export_event
      WHERE export_id=export_key AND event='downloaded') <> 1 THEN
    RAISE EXCEPTION 'export download was not audited';
  END IF;
END $$;
RESET ROLE;

-- Simulate elapsed time as the fixture owner; maintenance cannot alter expiry.
UPDATE operator_data_export
   SET created_at=now()-interval '2 hours',expires_at=now()-interval '1 second'
 WHERE id=(SELECT id FROM export_fixture ORDER BY expires_at LIMIT 1);
SET ROLE sierx_maintenance;
INSERT INTO export_fixture
SELECT * FROM public.sierx_create_data_export(
  '14000000-0000-7000-8000-000000000001','14000000-0000-7000-8000-000000000099'
);
DO $$
DECLARE expired_id uuid;
BEGIN
  SELECT id INTO expired_id FROM export_fixture ORDER BY expires_at LIMIT 1;
  BEGIN
    PERFORM public.sierx_read_data_export(expired_id,'14000000-0000-7000-8000-000000000099');
    RAISE EXCEPTION 'expired export was readable';
  EXCEPTION WHEN no_data_found THEN NULL;
  END;
  IF (SELECT payload FROM public.operator_data_export WHERE id=expired_id) IS NOT NULL
     OR NOT EXISTS (
       SELECT 1 FROM public.operator_data_export_event
        WHERE export_id=expired_id AND event='expired'
     ) THEN
    RAISE EXCEPTION 'expired payload was not cleared and recorded during the next creation';
  END IF;
END $$;
RESET ROLE;

ROLLBACK;
\echo 'data-export: bounded scope, secret exclusion, case-bound one-hour access, and creation/download audit passed'
