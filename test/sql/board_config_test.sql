-- Real constraints and runtime policies; every fixture rolls back.
\set ON_ERROR_STOP on
BEGIN;
INSERT INTO workspace(id,slug,name,origin_id) VALUES
 ('31000000-0000-7000-8000-000000000001','board-a','Board A','31000000-0000-7000-8000-000000000001'),
 ('31000000-0000-7000-8000-000000000002','board-b','Board B','31000000-0000-7000-8000-000000000002');
INSERT INTO project(id,workspace_id,key_prefix,name,kind) VALUES
 ('32000000-0000-7000-8000-000000000001','31000000-0000-7000-8000-000000000001','BDA','A','delivery'),
 ('32000000-0000-7000-8000-000000000002','31000000-0000-7000-8000-000000000002','BDB','B','delivery');
INSERT INTO project_config(project_id,version) VALUES
 ('32000000-0000-7000-8000-000000000001',1),
 ('32000000-0000-7000-8000-000000000001',2),
 ('32000000-0000-7000-8000-000000000002',1);
INSERT INTO status(id,project_id,key,name,category) VALUES
 ('33000000-0000-7000-8000-000000000001','32000000-0000-7000-8000-000000000001','todo','To do','open'),
 ('33000000-0000-7000-8000-000000000002','32000000-0000-7000-8000-000000000001','blocked','Blocked','active'),
 ('33000000-0000-7000-8000-000000000003','32000000-0000-7000-8000-000000000002','todo','To do','open');
INSERT INTO config_status(project_id,version,status_id,display_order) VALUES
 ('32000000-0000-7000-8000-000000000001',1,'33000000-0000-7000-8000-000000000001',0),
 ('32000000-0000-7000-8000-000000000001',1,'33000000-0000-7000-8000-000000000002',1),
 ('32000000-0000-7000-8000-000000000001',2,'33000000-0000-7000-8000-000000000001',0),
 ('32000000-0000-7000-8000-000000000002',1,'33000000-0000-7000-8000-000000000003',0);
INSERT INTO field_def(project_id,key,name,data_type) VALUES
 ('32000000-0000-7000-8000-000000000001','priority','Priority','select');
INSERT INTO board_definition(project_id,version,priority_field_key) VALUES
 ('32000000-0000-7000-8000-000000000001',1,'priority'),
 ('32000000-0000-7000-8000-000000000001',2,NULL),
 ('32000000-0000-7000-8000-000000000002',1,NULL);
INSERT INTO board_column(project_id,version,column_id,name,position,wip_limit,default_status_id) VALUES
 ('32000000-0000-7000-8000-000000000001',1,'34000000-0000-7000-8000-000000000001','Work',0,1,'33000000-0000-7000-8000-000000000001'),
 ('32000000-0000-7000-8000-000000000001',1,'34000000-0000-7000-8000-000000000002','Waiting',1,NULL,NULL),
 ('32000000-0000-7000-8000-000000000001',2,'34000000-0000-7000-8000-000000000001','Renamed',0,NULL,NULL),
 ('32000000-0000-7000-8000-000000000002',1,'34000000-0000-7000-8000-000000000003','Other',0,NULL,NULL);
INSERT INTO board_column_status(project_id,version,column_id,status_id) VALUES
 ('32000000-0000-7000-8000-000000000001',1,'34000000-0000-7000-8000-000000000001','33000000-0000-7000-8000-000000000001'),
 ('32000000-0000-7000-8000-000000000001',1,'34000000-0000-7000-8000-000000000002','33000000-0000-7000-8000-000000000002'),
 ('32000000-0000-7000-8000-000000000001',2,'34000000-0000-7000-8000-000000000001','33000000-0000-7000-8000-000000000001');
INSERT INTO board_blocked_status(project_id,version,status_id) VALUES
 ('32000000-0000-7000-8000-000000000001',1,'33000000-0000-7000-8000-000000000002');
SET CONSTRAINTS board_column_default_mapping_fk IMMEDIATE;

-- Expected failure helper: assert the exact SQLSTATE, never count any error as
-- a successful proof. SECURITY INVOKER preserves SET ROLE in policy controls.
CREATE FUNCTION pg_temp.board_reject(command text, expected text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  BEGIN
    EXECUTE command;
  EXCEPTION WHEN OTHERS THEN
    IF SQLSTATE = expected THEN RETURN; END IF;
    RAISE;
  END;
  RAISE EXCEPTION 'board control unexpectedly accepted: %',command;
END $$;

SELECT pg_temp.board_reject($q$INSERT INTO board_column_status VALUES
 ('32000000-0000-7000-8000-000000000001',1,'34000000-0000-7000-8000-000000000002','33000000-0000-7000-8000-000000000001')$q$,'23505');
SELECT pg_temp.board_reject($q$INSERT INTO board_column_status VALUES
 ('32000000-0000-7000-8000-000000000001',1,'34000000-0000-7000-8000-000000000001','33000000-0000-7000-8000-000000000003')$q$,'23503');
SELECT pg_temp.board_reject($q$INSERT INTO board_blocked_status VALUES
 ('32000000-0000-7000-8000-000000000001',2,'33000000-0000-7000-8000-000000000002')$q$,'23503');
SELECT pg_temp.board_reject($q$UPDATE board_column SET default_status_id='33000000-0000-7000-8000-000000000002'
 WHERE project_id='32000000-0000-7000-8000-000000000001' AND version=1 AND position=0$q$,'23503');
SELECT pg_temp.board_reject($q$UPDATE board_definition SET priority_field_key='missing'
 WHERE project_id='32000000-0000-7000-8000-000000000001' AND version=1$q$,'23503');
SELECT pg_temp.board_reject($q$INSERT INTO board_column(project_id,version,name,position) VALUES
 ('32000000-0000-7000-8000-000000000001',1,'Duplicate position',0)$q$,'23505');
SELECT pg_temp.board_reject($q$UPDATE board_column SET wip_limit=0$q$,'23514');
SELECT pg_temp.board_reject($q$UPDATE board_column SET wip_limit=-1$q$,'23514');
SELECT pg_temp.board_reject($q$UPDATE board_column SET position=-1$q$,'23514');
SELECT pg_temp.board_reject($q$UPDATE board_column SET name='  '$q$,'23514');

-- No request context fails closed across every new table.
SET LOCAL ROLE sierx_runtime;
DO $$ BEGIN
  IF (SELECT count(*) FROM board_definition) <> 0 OR (SELECT count(*) FROM board_column) <> 0
    OR (SELECT count(*) FROM board_column_status) <> 0 OR (SELECT count(*) FROM board_blocked_status) <> 0 THEN
    RAISE EXCEPTION 'board data visible without workspace identity';
  END IF;
END $$;
RESET ROLE;
SELECT set_config('sierx.workspace_id','31000000-0000-7000-8000-000000000001',true);
SELECT set_config('sierx.role','member',true);
SET LOCAL ROLE sierx_runtime;
DO $$ BEGIN
  IF (SELECT count(*) FROM board_definition) <> 2 OR (SELECT count(*) FROM board_column) <> 3
    OR (SELECT count(*) FROM board_column_status) <> 3 OR (SELECT count(*) FROM board_blocked_status) <> 1 THEN
    RAISE EXCEPTION 'board policy leaked another workspace or hid own historical snapshot';
  END IF;
  IF (SELECT name FROM board_column WHERE version=1 AND position=0) <> 'Work'
    OR (SELECT name FROM board_column WHERE version=2) <> 'Renamed' THEN
    RAISE EXCEPTION 'column identity/history did not survive snapshot';
  END IF;
END $$;
SELECT pg_temp.board_reject($q$INSERT INTO board_column(project_id,version,name,position) VALUES
 ('32000000-0000-7000-8000-000000000001',1,'Member write',2)$q$,'42501');
SELECT pg_temp.board_reject($q$INSERT INTO board_blocked_status VALUES
 ('32000000-0000-7000-8000-000000000001',1,'33000000-0000-7000-8000-000000000001')$q$,'42501');
SELECT pg_temp.board_reject('UPDATE board_column SET name=''Rewritten history''','42501');
SELECT pg_temp.board_reject('DELETE FROM board_column','42501');
RESET ROLE;
SELECT set_config('sierx.role','admin',true);
SET LOCAL ROLE sierx_runtime;
-- Positive admin control, followed by a forbidden cross-workspace insert.
INSERT INTO board_column(project_id,version,name,position) VALUES
 ('32000000-0000-7000-8000-000000000001',1,'Admin write',2);
SELECT pg_temp.board_reject($q$INSERT INTO board_column(project_id,version,name,position) VALUES
 ('32000000-0000-7000-8000-000000000002',1,'Cross workspace',1)$q$,'42501');
RESET ROLE;
ROLLBACK;
\echo 'board-config: scoped snapshots, mapping/default/limit constraints and runtime policies passed'
