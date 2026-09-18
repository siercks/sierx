-- SPEC §4.2 Projects. Transcribed verbatim.
-- +goose Up
CREATE TABLE project (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  key_prefix   text NOT NULL CHECK (key_prefix ~ '^[A-Z][A-Z0-9]{1,9}$'),
  name         text NOT NULL,
  kind         text NOT NULL CHECK (kind IN ('delivery','discovery','portfolio')),
  next_key_num int  NOT NULL DEFAULT 1,          -- monotonic, never reset (§A.1)
  archived_at  timestamptz,
  UNIQUE (workspace_id, key_prefix)
);

-- +goose Down
DROP TABLE project;
