-- test/sql/invariants_test.sql — every forbidden operation is attempted and
-- asserted to raise (BUILD task 0.5). Runs inside one transaction that is
-- rolled back, so it leaves the database as it found it.
--
-- This file writes item directly ON PURPOSE. test/sql/ is on gate-nodirect's
-- allowlist (task 0.8) for this reason and no other.
\set ON_ERROR_STOP on
\set QUIET on
\pset footer off
\o /dev/null
BEGIN;

CREATE TEMP TABLE t_result (label text, ok boolean);

-- expect_error(label, sql): passes iff sql raises
CREATE FUNCTION pg_temp.expect_error(label text, sql text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  BEGIN
    EXECUTE sql;
  EXCEPTION WHEN OTHERS THEN
    INSERT INTO t_result VALUES (label, true);
    RAISE NOTICE 'ok   raised  %  [% %]', label, SQLSTATE, left(SQLERRM, 90);
    RETURN;
  END;
  INSERT INTO t_result VALUES (label, false);
  RAISE WARNING 'FAIL silent  %  (no exception)', label;
END $$;

-- expect_ok(label, sql): positive control — passes iff sql does NOT raise
CREATE FUNCTION pg_temp.expect_ok(label text, sql text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  BEGIN
    EXECUTE sql;
  EXCEPTION WHEN OTHERS THEN
    INSERT INTO t_result VALUES (label, false);
    RAISE WARNING 'FAIL raised  %  [% %]', label, SQLSTATE, SQLERRM;
    RETURN;
  END;
  INSERT INTO t_result VALUES (label, true);
  RAISE NOTICE 'ok   allowed %', label;
END $$;

-- ---- fixture: one workspace, two projects with config v1 ----------------
INSERT INTO workspace (id, slug, name, origin_id) VALUES
  ('01000000-0000-7000-8000-000000000001', 'w', 'W', '01000000-0000-7000-8000-000000000001');
INSERT INTO project (id, workspace_id, key_prefix, name, kind) VALUES
  ('02000000-0000-7000-8000-000000000001', '01000000-0000-7000-8000-000000000001', 'AAA', 'A', 'delivery'),
  ('02000000-0000-7000-8000-000000000002', '01000000-0000-7000-8000-000000000001', 'BBB', 'B', 'delivery');
INSERT INTO project_config (project_id, version) VALUES
  ('02000000-0000-7000-8000-000000000001', 1),
  ('02000000-0000-7000-8000-000000000002', 1);
INSERT INTO status (id, project_id, key, name, category) VALUES
  ('03000000-0000-7000-8000-000000000001', '02000000-0000-7000-8000-000000000001', 'todo', 'To do', 'open'),
  ('03000000-0000-7000-8000-000000000002', '02000000-0000-7000-8000-000000000002', 'todo', 'To do', 'open');
INSERT INTO item_type (id, project_id, key, name, level) VALUES
  ('04000000-0000-7000-8000-000000000001', '02000000-0000-7000-8000-000000000001', 'task', 'Task', 0),
  ('04000000-0000-7000-8000-000000000002', '02000000-0000-7000-8000-000000000002', 'task', 'Task', 0);

-- mk_item(id, parent_id, path, rank[, status, type, cfg]) inserts a project-A item.
-- The key is derived from the WHOLE id: a truncation collides between fixture
-- families (05...005 and 06...005 share their last 12 characters), which made
-- the composite-FK checks below raise a unique violation on
-- item_workspace_id_key_key and pass for the wrong reason.
CREATE FUNCTION pg_temp.mk_item(i uuid, p uuid, pth ltree, rk text,
                                st uuid DEFAULT '03000000-0000-7000-8000-000000000001',
                                ty uuid DEFAULT '04000000-0000-7000-8000-000000000001',
                                cfg int DEFAULT 1) RETURNS void
LANGUAGE sql AS $$
  INSERT INTO item (id, workspace_id, project_id, key, item_type_id, status_id, config_version,
                    parent_id, path, title, rank, change_seq, origin_id)
  VALUES (i, '01000000-0000-7000-8000-000000000001', '02000000-0000-7000-8000-000000000001',
          'AAA-' || replace(i::text, '-', ''), ty, st, cfg, p, pth, 'item ' || rk, rk, 0,
          '01000000-0000-7000-8000-000000000001');
$$;

-- a chain root -> d2 -> ... -> d8 (depth 8 is the ceiling)
SELECT pg_temp.mk_item('05000000-0000-7000-8000-000000000001', NULL,
  '05000000-0000-7000-8000-000000000001', 'a');
DO $$
DECLARE prev uuid := '05000000-0000-7000-8000-000000000001'; cur uuid; pth ltree := prev::text::ltree; n int;
BEGIN
  FOR n IN 2..8 LOOP
    cur := ('05000000-0000-7000-8000-00000000000' || n)::uuid;
    pth := pth || cur::text::ltree;
    PERFORM pg_temp.mk_item(cur, prev, pth, 'a' || n);
    prev := cur;
  END LOOP;
END $$;

-- ---- §5.6 / A.6 config immutability --------------------------------------
SELECT pg_temp.expect_error('status.name update',
  $$UPDATE status SET name = 'Renamed' WHERE id = '03000000-0000-7000-8000-000000000001'$$);
SELECT pg_temp.expect_error('status.key update',
  $$UPDATE status SET key = 'todo2' WHERE id = '03000000-0000-7000-8000-000000000001'$$);
SELECT pg_temp.expect_error('status.category update',
  $$UPDATE status SET category = 'done' WHERE id = '03000000-0000-7000-8000-000000000001'$$);
SELECT pg_temp.expect_error('item_type.name update',
  $$UPDATE item_type SET name = 'Renamed' WHERE id = '04000000-0000-7000-8000-000000000001'$$);
SELECT pg_temp.expect_error('item_type.level update',
  $$UPDATE item_type SET level = 1 WHERE id = '04000000-0000-7000-8000-000000000001'$$);
SELECT pg_temp.expect_ok('item_type.is_idea update (not immutable by spec)',
  $$UPDATE item_type SET is_idea = true WHERE id = '04000000-0000-7000-8000-000000000001'$$);

-- ---- §5.3 depth ceiling ------------------------------------------------------
SELECT pg_temp.expect_error('depth-9 insert',
  $$SELECT pg_temp.mk_item('05000000-0000-7000-8000-000000000009', '05000000-0000-7000-8000-000000000008',
    (SELECT path FROM item WHERE id = '05000000-0000-7000-8000-000000000008')
      || '05000000-0000-7000-8000-000000000009'::text::ltree, 'a9')$$);
SELECT pg_temp.expect_ok('depth-8 exists (positive control)',
  $q$DO $x$ BEGIN IF (SELECT nlevel(path) FROM item WHERE id = '05000000-0000-7000-8000-000000000008') <> 8
    THEN RAISE EXCEPTION 'depth-8 fixture missing'; END IF; END $x$$q$);

-- ---- §5.3 path ends with own id ------------------------------------------
SELECT pg_temp.expect_error('path not ending in own id',
  $$SELECT pg_temp.mk_item('06000000-0000-7000-8000-000000000001', NULL,
    '05000000-0000-7000-8000-000000000001', 'b')$$);

-- ---- parent_id / path disagreement ---------------------------------------
SELECT pg_temp.expect_error('parent_id set, path penultimate label is someone else',
  $$SELECT pg_temp.mk_item('06000000-0000-7000-8000-000000000002', '05000000-0000-7000-8000-000000000001',
    '05000000-0000-7000-8000-000000000002.06000000-0000-7000-8000-000000000002', 'c')$$);
SELECT pg_temp.expect_error('parent_id NULL, path has two labels',
  $$SELECT pg_temp.mk_item('06000000-0000-7000-8000-000000000003', NULL,
    '05000000-0000-7000-8000-000000000001.06000000-0000-7000-8000-000000000003', 'd')$$);
SELECT pg_temp.expect_error('parent_id set, single-label path',
  $$SELECT pg_temp.mk_item('06000000-0000-7000-8000-000000000004', '05000000-0000-7000-8000-000000000001',
    '06000000-0000-7000-8000-000000000004', 'e')$$);
SELECT pg_temp.expect_error('update parent_id without rewriting path',
  $$UPDATE item SET parent_id = '05000000-0000-7000-8000-000000000001'
    WHERE id = '05000000-0000-7000-8000-000000000003'$$);

-- ---- §5.3 self-ancestry ------------------------------------------------------
SELECT pg_temp.expect_error('self-ancestry reparent (root under its grandchild)',
  $$UPDATE item SET parent_id = '05000000-0000-7000-8000-000000000003',
      path = '05000000-0000-7000-8000-000000000003.05000000-0000-7000-8000-000000000001'
    WHERE id = '05000000-0000-7000-8000-000000000001'$$);
SELECT pg_temp.expect_error('reparent under itself',
  $$UPDATE item SET parent_id = '05000000-0000-7000-8000-000000000002',
      path = '05000000-0000-7000-8000-000000000002.05000000-0000-7000-8000-000000000002'
    WHERE id = '05000000-0000-7000-8000-000000000002'$$);
-- positive control: a legal reparent of d3 (and its subtree) under the root,
-- rewritten in one statement as §5.3 prescribes
SELECT pg_temp.expect_ok('legal subtree reparent in one statement',
  $$UPDATE item SET
      parent_id = CASE WHEN id = '05000000-0000-7000-8000-000000000003'
                       THEN '05000000-0000-7000-8000-000000000001'::uuid ELSE parent_id END,
      path = '05000000-0000-7000-8000-000000000001'::ltree
             || subpath(path, nlevel('05000000-0000-7000-8000-000000000001.05000000-0000-7000-8000-000000000002'::ltree))
    WHERE path <@ '05000000-0000-7000-8000-000000000001.05000000-0000-7000-8000-000000000002.05000000-0000-7000-8000-000000000003'::ltree$$);
SELECT pg_temp.expect_ok('subtree paths consistent after reparent',
  $q$DO $x$ BEGIN
    IF (SELECT path::text FROM item WHERE id = '05000000-0000-7000-8000-000000000004')
       <> '05000000-0000-7000-8000-000000000001.05000000-0000-7000-8000-000000000003.05000000-0000-7000-8000-000000000004'
    THEN RAISE EXCEPTION 'descendant path not rewritten'; END IF; END $x$$q$);

-- ---- ADR-012 composite FKs -----------------------------------------------
SELECT pg_temp.expect_error('item pointing at another project''s status',
  $$SELECT pg_temp.mk_item('06000000-0000-7000-8000-000000000005', NULL,
    '06000000-0000-7000-8000-000000000005', 'f', st => '03000000-0000-7000-8000-000000000002')$$);
SELECT pg_temp.expect_error('item pointing at another project''s type',
  $$SELECT pg_temp.mk_item('06000000-0000-7000-8000-000000000006', NULL,
    '06000000-0000-7000-8000-000000000006', 'g', ty => '04000000-0000-7000-8000-000000000002')$$);
SELECT pg_temp.expect_error('item pointing at a nonexistent config version',
  $$SELECT pg_temp.mk_item('06000000-0000-7000-8000-000000000007', NULL,
    '06000000-0000-7000-8000-000000000007', 'h', cfg => 7)$$);

-- ---- ADR-003 rank uniqueness, deferrable ------------------------------------
SELECT pg_temp.expect_error('duplicate rank within a project (immediate)',
  $$SELECT pg_temp.mk_item('06000000-0000-7000-8000-000000000018', NULL,
    '06000000-0000-7000-8000-000000000018', 'a')$$);

-- ADR-003: item_project_rank_uniq is DEFERRABLE. A deferrable unique
-- constraint is checked at the END of each statement while immediate (not per
-- row), so the single-statement rebalance of §5.5 commits even without
-- SET CONSTRAINTS DEFERRED; a collision that survives a statement still raises
-- immediately, which is the retryable-409 behaviour the ADR wants.
SELECT pg_temp.expect_ok('single-statement rank swap with the constraint immediate',
  $$UPDATE item SET rank = CASE rank WHEN 'a' THEN 'a2' ELSE 'a' END WHERE rank IN ('a','a2')$$);
SELECT pg_temp.expect_error('rank collision surviving a statement raises immediately',
  $$UPDATE item SET rank = 'a2' WHERE rank = 'a'$$);
SELECT pg_temp.expect_ok('same collision tolerated mid-transaction when deferred',
  $$SET CONSTRAINTS item_project_rank_uniq DEFERRED;
    UPDATE item SET rank = 'a2' WHERE rank = 'a';
    UPDATE item SET rank = 'a' WHERE rank = 'a2' AND id <> '05000000-0000-7000-8000-000000000001';
    SET CONSTRAINTS item_project_rank_uniq IMMEDIATE$$);

-- ---- verdict ----------------------------------------------------------------
DO $$
DECLARE failed int; total int;
BEGIN
  SELECT count(*) FILTER (WHERE NOT ok), count(*) INTO failed, total FROM t_result;
  IF failed > 0 THEN
    RAISE EXCEPTION 'test-sql: % of % checks FAILED', failed, total;
  END IF;
  RAISE NOTICE 'test-sql: % checks passed', total;
END $$;

ROLLBACK;
