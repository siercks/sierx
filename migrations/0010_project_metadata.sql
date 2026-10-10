-- Project accountability metadata; it never grants access.
-- +goose Up
ALTER TABLE project
  ADD COLUMN owner_id uuid,
  ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE project
  ADD CONSTRAINT project_owner_membership_fk
  FOREIGN KEY (workspace_id, owner_id)
  REFERENCES membership(workspace_id, user_id)
  ON DELETE RESTRICT;

CREATE INDEX project_owner_membership_idx ON project (workspace_id, owner_id) WHERE owner_id IS NOT NULL;

-- +goose Down
DROP INDEX project_owner_membership_idx;
ALTER TABLE project DROP CONSTRAINT project_owner_membership_fk;
ALTER TABLE project DROP COLUMN updated_at;
ALTER TABLE project DROP COLUMN version;
ALTER TABLE project DROP COLUMN owner_id;
