-- ADR-031 / P3-03: structural board snapshot foundation. P3-04 owns population,
-- complete-coverage validation and atomic workflow/board snapshot carry-forward.
-- Existing project configurations are deliberately not half-populated here.
-- +goose Up
CREATE TABLE board_definition (
  project_id uuid NOT NULL,
  version integer NOT NULL,
  priority_field_key text,
  PRIMARY KEY (project_id, version),
  FOREIGN KEY (project_id, version) REFERENCES project_config(project_id, version),
  FOREIGN KEY (project_id, priority_field_key) REFERENCES field_def(project_id, key)
);

CREATE TABLE board_column (
  project_id uuid NOT NULL,
  version integer NOT NULL,
  column_id uuid NOT NULL DEFAULT uuidv7(),
  name text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 80),
  position integer NOT NULL CHECK (position >= 0),
  wip_limit integer CHECK (wip_limit > 0),
  default_status_id uuid,
  PRIMARY KEY (project_id, version, column_id),
  UNIQUE (project_id, version, position),
  FOREIGN KEY (project_id, version) REFERENCES board_definition(project_id, version)
);

CREATE TABLE board_column_status (
  project_id uuid NOT NULL,
  version integer NOT NULL,
  column_id uuid NOT NULL,
  status_id uuid NOT NULL,
  PRIMARY KEY (project_id, version, status_id),
  UNIQUE (project_id, version, column_id, status_id),
  FOREIGN KEY (project_id, version, column_id) REFERENCES board_column(project_id, version, column_id),
  FOREIGN KEY (project_id, version, status_id) REFERENCES config_status(project_id, version, status_id),
  FOREIGN KEY (project_id, status_id) REFERENCES status(project_id, id)
);

-- Deferred so a snapshot can insert columns before their mappings. COMMIT still
-- rejects a default belonging to a different column, project or config version.
ALTER TABLE board_column ADD CONSTRAINT board_column_default_mapping_fk
  FOREIGN KEY (project_id, version, column_id, default_status_id)
  REFERENCES board_column_status(project_id, version, column_id, status_id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE board_blocked_status (
  project_id uuid NOT NULL,
  version integer NOT NULL,
  status_id uuid NOT NULL,
  PRIMARY KEY (project_id, version, status_id),
  FOREIGN KEY (project_id, version) REFERENCES board_definition(project_id, version),
  FOREIGN KEY (project_id, version, status_id) REFERENCES config_status(project_id, version, status_id),
  FOREIGN KEY (project_id, status_id) REFERENCES status(project_id, id)
);

-- Snapshots are insert-only like the existing workflow snapshots. Editing
-- publishes a new version, never mutates historical configuration.
GRANT SELECT, INSERT ON board_definition, board_column, board_column_status,
  board_blocked_status TO sierx_runtime;

ALTER TABLE board_definition ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_definition FORCE ROW LEVEL SECURITY;
ALTER TABLE board_column ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_column FORCE ROW LEVEL SECURITY;
ALTER TABLE board_column_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_column_status FORCE ROW LEVEL SECURITY;
ALTER TABLE board_blocked_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_blocked_status FORCE ROW LEVEL SECURITY;

CREATE POLICY board_definition_read ON board_definition FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY board_definition_insert ON board_definition FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()
    AND public.sierx_current_role() = 'admin');
CREATE POLICY board_column_read ON board_column FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY board_column_insert ON board_column FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()
    AND public.sierx_current_role() = 'admin');
CREATE POLICY board_column_status_read ON board_column_status FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY board_column_status_insert ON board_column_status FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()
    AND public.sierx_current_role() = 'admin');
CREATE POLICY board_blocked_status_read ON board_blocked_status FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY board_blocked_status_insert ON board_blocked_status FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()
    AND public.sierx_current_role() = 'admin');

-- +goose Down
DROP TABLE board_blocked_status;
ALTER TABLE board_column DROP CONSTRAINT board_column_default_mapping_fk;
DROP TABLE board_column_status;
DROP TABLE board_column;
DROP TABLE board_definition;
