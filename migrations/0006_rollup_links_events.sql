-- SPEC §4.5 Rollups, §4.6 Links, §4.7 Event log. Transcribed verbatim.
-- change_event is range-partitioned by month on `at`; this migration creates
-- the month it was written in plus the next two (BUILD task 0.4). Ongoing
-- partition creation is task 0.6's `sierxctl partitions ensure`. No pruning,
-- ever (§4.7).
-- +goose Up
CREATE TABLE item_rollup (
  item_id          uuid PRIMARY KEY REFERENCES item(id) ON DELETE CASCADE,
  descendant_count int NOT NULL DEFAULT 0,
  done_count       int NOT NULL DEFAULT 0,
  points_total     numeric(10,2),
  points_done      numeric(10,2),
  earliest_start   date,
  latest_due       date,
  computed_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE item_link (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  from_item_id uuid NOT NULL REFERENCES item(id),
  to_item_id   uuid NOT NULL REFERENCES item(id),
  kind         text NOT NULL CHECK (kind IN
                 ('blocks','duplicates','relates','implements','discovered_from')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  created_by   uuid REFERENCES user_account(id),
  CHECK (from_item_id <> to_item_id),
  UNIQUE (from_item_id, to_item_id, kind)
);

CREATE INDEX item_link_to ON item_link (to_item_id, kind);

CREATE TABLE change_event (
  workspace_id uuid   NOT NULL,
  seq          bigint NOT NULL,                  -- §5.1: allocated from seq_counter
  at           timestamptz NOT NULL DEFAULT now(),
  item_id      uuid,
  actor_id     uuid,
  kind         text NOT NULL,                    -- created | field_changed |
                                                 -- status_changed | moved | linked |
                                                 -- unlinked | promoted | deleted
  field        text,
  old_value    jsonb,
  new_value    jsonb,
  PRIMARY KEY (workspace_id, seq, at)
) PARTITION BY RANGE (at);

CREATE INDEX change_event_ws_seq ON change_event (workspace_id, seq);
CREATE INDEX change_event_item   ON change_event (item_id, at DESC);

CREATE TABLE change_event_2026_09 PARTITION OF change_event
  FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');
CREATE TABLE change_event_2026_10 PARTITION OF change_event
  FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');
CREATE TABLE change_event_2026_11 PARTITION OF change_event
  FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');

CREATE TABLE seq_counter (
  workspace_id uuid PRIMARY KEY REFERENCES workspace(id),
  value        bigint NOT NULL DEFAULT 0
);

-- +goose Down
DROP TABLE seq_counter;
DROP TABLE change_event;      -- drops its partitions with it
DROP TABLE item_link;
DROP TABLE item_rollup;
