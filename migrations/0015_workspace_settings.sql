-- Admin-only workspace display-name editing; identity and URLs remain stable.
-- +goose Up
ALTER TABLE workspace ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0);
GRANT UPDATE (name, version) ON workspace TO sierx_runtime;
CREATE POLICY workspace_runtime_update ON workspace FOR UPDATE TO sierx_runtime
  USING (id = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin')
  WITH CHECK (id = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');

-- +goose Down
DROP POLICY workspace_runtime_update ON workspace;
REVOKE UPDATE (name, version) ON workspace FROM sierx_runtime;
ALTER TABLE workspace DROP COLUMN version;
