-- test/sql/partitions_test.sql — change_event partition maintenance is
-- idempotent and next month's partition exists (BUILD task 0.6), plus the
-- seq_counter-per-workspace invariant (§5.1). Rolled back.
\set ON_ERROR_STOP on
\set QUIET on
\o /dev/null
BEGIN;

DO $$
DECLARE first_run int; second_run int; next_month text; n_ws int; n_ctr int;
BEGIN
  SELECT count(*) INTO first_run  FROM change_event_ensure_partitions(1);
  SELECT count(*) INTO second_run FROM change_event_ensure_partitions(1);
  IF second_run <> 0 THEN
    RAISE EXCEPTION 'ensure is not idempotent: second run created % partition(s)', second_run;
  END IF;
  next_month := 'change_event_' || to_char(date_trunc('month', now() AT TIME ZONE 'UTC') + interval '1 month', 'YYYY_MM');
  IF to_regclass(next_month) IS NULL THEN
    RAISE EXCEPTION 'next month partition % does not exist after ensure', next_month;
  END IF;
  IF (SELECT count(*) FROM pg_inherits WHERE inhparent = 'change_event'::regclass) < 2 THEN
    RAISE EXCEPTION 'expected at least the current and next month partitions';
  END IF;
  RAISE NOTICE 'ok   ensure(1): first run created %, second run created 0, % present', first_run, next_month;

  -- a further-ahead run creates exactly the missing months, and only those
  SELECT count(*) INTO first_run FROM change_event_ensure_partitions(6);
  SELECT count(*) INTO second_run FROM change_event_ensure_partitions(6);
  IF second_run <> 0 THEN RAISE EXCEPTION 'ensure(6) not idempotent'; END IF;
  RAISE NOTICE 'ok   ensure(6): created % more, then 0', first_run;

  -- §5.1: creating a workspace creates its counter, at zero
  INSERT INTO workspace (slug, name, origin_id) VALUES ('t', 'T', uuidv7());
  SELECT count(*) INTO n_ws  FROM workspace;
  SELECT count(*) INTO n_ctr FROM seq_counter c JOIN workspace w ON w.id = c.workspace_id AND c.value = 0;
  IF n_ws <> n_ctr THEN RAISE EXCEPTION 'workspace/seq_counter mismatch: % vs %', n_ws, n_ctr; END IF;
  RAISE NOTICE 'ok   every workspace has a seq_counter row (%)', n_ws;

  -- an event lands in the right partition
  INSERT INTO change_event (workspace_id, seq, kind) SELECT id, 1, 'created' FROM workspace WHERE slug = 't';
  IF (SELECT tableoid::regclass::text FROM change_event WHERE seq = 1 AND kind = 'created' LIMIT 1)
     <> 'change_event_' || to_char(now() AT TIME ZONE 'UTC', 'YYYY_MM') THEN
    RAISE EXCEPTION 'event did not route to the current month partition';
  END IF;
  RAISE NOTICE 'ok   event routed to the current-month partition';
  RAISE NOTICE 'test-partitions: passed';
END $$;

ROLLBACK;
