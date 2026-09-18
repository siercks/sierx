-- BUILD task 0.6: the sequence counter row and partition maintenance.
--   §5.1  seq_counter has exactly one row per workspace, created alongside the
--         workspace — a bootstrap invariant, so it lives with the schema.
--   §4.7  change_event partitions are created ahead of time, never pruned.
--         The idempotent creation logic is a SQL function so it is testable
--         from psql and so `sierxctl partitions ensure` is a one-line caller.
-- +goose Up
-- +goose StatementBegin
CREATE FUNCTION workspace_create_seq_counter() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO seq_counter (workspace_id) VALUES (NEW.id);
  RETURN NEW;
END $$;
-- +goose StatementEnd

CREATE TRIGGER workspace_create_seq_counter_trg
  AFTER INSERT ON workspace FOR EACH ROW EXECUTE FUNCTION workspace_create_seq_counter();

-- backfill any workspace created before this migration
INSERT INTO seq_counter (workspace_id)
  SELECT id FROM workspace WHERE id NOT IN (SELECT workspace_id FROM seq_counter);

-- change_event_ensure_partitions(months_ahead): creates the monthly partition
-- for the current UTC month and each of the next months_ahead months if it is
-- missing. Returns the names it created (empty when nothing was missing), so a
-- second call is provably a no-op. There is deliberately no counterpart that
-- drops anything (§4.7).
-- +goose StatementBegin
CREATE FUNCTION change_event_ensure_partitions(months_ahead int)
RETURNS SETOF text
LANGUAGE plpgsql AS $$
DECLARE
  m        int;
  start_at timestamptz;
  end_at   timestamptz;
  pname    text;
BEGIN
  IF months_ahead < 0 THEN
    RAISE EXCEPTION 'months_ahead must be >= 0';
  END IF;
  FOR m IN 0..months_ahead LOOP
    start_at := date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                + make_interval(months => m);
    end_at   := start_at + interval '1 month';
    pname    := 'change_event_' || to_char(start_at AT TIME ZONE 'UTC', 'YYYY_MM');
    IF to_regclass(pname) IS NULL THEN
      EXECUTE format(
        'CREATE TABLE %I PARTITION OF change_event FOR VALUES FROM (%L) TO (%L)',
        pname, start_at, end_at);
      RETURN NEXT pname;
    END IF;
  END LOOP;
  RETURN;
END $$;
-- +goose StatementEnd

-- +goose Down
DROP FUNCTION change_event_ensure_partitions(int);
DROP TRIGGER workspace_create_seq_counter_trg ON workspace;
DROP FUNCTION workspace_create_seq_counter();
