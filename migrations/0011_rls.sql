-- Effective tenant and operation controls for application-owned data.
-- +goose Up
-- Role creation is also performed by scripts/db-roles.sh so credentials stay
-- outside migrations. These NOLOGIN fallbacks support schema-only validation.
-- +goose StatementBegin
DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sierx_runtime') THEN
    EXECUTE 'CREATE ROLE sierx_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sierx_auth') THEN
    EXECUTE 'CREATE ROLE sierx_auth NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sierx_maintenance') THEN
    EXECUTE 'CREATE ROLE sierx_maintenance NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS';
  END IF;
END
$roles$;
-- +goose StatementEnd

CREATE FUNCTION sierx_current_workspace_id() RETURNS uuid
LANGUAGE sql STABLE
SET search_path = pg_catalog
AS $$ SELECT NULLIF(current_setting('sierx.workspace_id', true), '')::uuid $$;

CREATE FUNCTION sierx_current_user_id() RETURNS uuid
LANGUAGE sql STABLE
SET search_path = pg_catalog
AS $$ SELECT NULLIF(current_setting('sierx.user_id', true), '')::uuid $$;

CREATE FUNCTION sierx_current_role() RETURNS text
LANGUAGE sql STABLE
SET search_path = pg_catalog
AS $$ SELECT NULLIF(current_setting('sierx.role', true), '') $$;

CREATE FUNCTION sierx_project_workspace_id(p_project_id uuid) RETURNS uuid
LANGUAGE sql STABLE
SET search_path = pg_catalog, public
AS $$ SELECT workspace_id FROM public.project WHERE id = p_project_id $$;

REVOKE ALL ON FUNCTION sierx_current_workspace_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION sierx_current_user_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION sierx_current_role() FROM PUBLIC;
REVOKE ALL ON FUNCTION sierx_project_workspace_id(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_current_workspace_id() TO sierx_runtime;
GRANT EXECUTE ON FUNCTION sierx_current_user_id() TO sierx_runtime;
GRANT EXECUTE ON FUNCTION sierx_current_role() TO sierx_runtime;
GRANT EXECUTE ON FUNCTION sierx_project_workspace_id(uuid) TO sierx_runtime;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM sierx_runtime, sierx_auth, sierx_maintenance;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM sierx_runtime, sierx_auth, sierx_maintenance;
REVOKE CREATE ON SCHEMA public FROM sierx_runtime, sierx_auth, sierx_maintenance;
-- Database names cannot be used as expressions in GRANT/REVOKE syntax.
-- Resolve the current database and quote it as an identifier.
-- +goose StatementBegin
DO $database_privileges$
BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
END
$database_privileges$;
-- +goose StatementEnd
GRANT USAGE ON SCHEMA public TO sierx_runtime, sierx_auth, sierx_maintenance;

-- The API role can read the active workspace and roster fields, but cannot
-- retrieve email addresses, password hashes, or encrypted MFA state.
GRANT SELECT ON workspace, membership TO sierx_runtime;
GRANT SELECT (id, display_name, is_active, theme, reduced_motion) ON user_account TO sierx_runtime;
GRANT UPDATE (display_name, theme, reduced_motion) ON user_account TO sierx_runtime;
GRANT SELECT ON project TO sierx_runtime;
GRANT INSERT (workspace_id, key_prefix, name, kind, owner_id) ON project TO sierx_runtime;
GRANT UPDATE (name, owner_id, version, updated_at, next_key_num) ON project TO sierx_runtime;
GRANT SELECT ON project_config, status, item_type, config_status,
  config_type, config_transition, field_def TO sierx_runtime;
GRANT INSERT ON project_config, status, item_type, config_status,
  config_type, config_transition, field_def TO sierx_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON item, item_rollup, item_link,
  sprint, sprint_item, comment, saved_view TO sierx_runtime;
GRANT SELECT, INSERT ON change_event TO sierx_runtime;
GRANT SELECT, UPDATE ON seq_counter TO sierx_runtime;

-- These indirect ownership checks join from project/item to the protected
-- child rows. Index the join keys used by those policies and workspace views.
CREATE INDEX sprint_project_rls ON sprint (project_id);
CREATE INDEX comment_item_rls ON comment (item_id);
CREATE INDEX saved_view_workspace_owner_rls ON saved_view (workspace_id, owner_id);

-- The separate authentication connection gets only columns and tables needed
-- by local/proxy login, session lifecycle and TOTP enrollment/verification.
GRANT SELECT (id, email, display_name, password_hash, totp_secret, is_active,
  theme, reduced_motion) ON user_account TO sierx_auth;
GRANT UPDATE (totp_secret) ON user_account TO sierx_auth;
GRANT SELECT ON membership TO sierx_auth;
GRANT SELECT, INSERT, DELETE ON session TO sierx_auth;

-- No direct grants on Goose metadata, extensions, or arbitrary future tables.
-- New application tables must receive an explicit policy and grant in the same
-- migration; the catalog gate checks this inventory.

ALTER TABLE workspace ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace FORCE ROW LEVEL SECURITY;
ALTER TABLE user_account ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_account FORCE ROW LEVEL SECURITY;
ALTER TABLE membership ENABLE ROW LEVEL SECURITY;
ALTER TABLE membership FORCE ROW LEVEL SECURITY;
ALTER TABLE session ENABLE ROW LEVEL SECURITY;
ALTER TABLE session FORCE ROW LEVEL SECURITY;
ALTER TABLE project ENABLE ROW LEVEL SECURITY;
ALTER TABLE project FORCE ROW LEVEL SECURITY;
ALTER TABLE project_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_config FORCE ROW LEVEL SECURITY;
ALTER TABLE status ENABLE ROW LEVEL SECURITY;
ALTER TABLE status FORCE ROW LEVEL SECURITY;
ALTER TABLE item_type ENABLE ROW LEVEL SECURITY;
ALTER TABLE item_type FORCE ROW LEVEL SECURITY;
ALTER TABLE config_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE config_status FORCE ROW LEVEL SECURITY;
ALTER TABLE config_type ENABLE ROW LEVEL SECURITY;
ALTER TABLE config_type FORCE ROW LEVEL SECURITY;
ALTER TABLE config_transition ENABLE ROW LEVEL SECURITY;
ALTER TABLE config_transition FORCE ROW LEVEL SECURITY;
ALTER TABLE field_def ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_def FORCE ROW LEVEL SECURITY;
ALTER TABLE item ENABLE ROW LEVEL SECURITY;
ALTER TABLE item FORCE ROW LEVEL SECURITY;
ALTER TABLE item_rollup ENABLE ROW LEVEL SECURITY;
ALTER TABLE item_rollup FORCE ROW LEVEL SECURITY;
ALTER TABLE item_link ENABLE ROW LEVEL SECURITY;
ALTER TABLE item_link FORCE ROW LEVEL SECURITY;
ALTER TABLE change_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_event FORCE ROW LEVEL SECURITY;
ALTER TABLE seq_counter ENABLE ROW LEVEL SECURITY;
ALTER TABLE seq_counter FORCE ROW LEVEL SECURITY;
ALTER TABLE sprint ENABLE ROW LEVEL SECURITY;
ALTER TABLE sprint FORCE ROW LEVEL SECURITY;
ALTER TABLE sprint_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE sprint_item FORCE ROW LEVEL SECURITY;
ALTER TABLE comment ENABLE ROW LEVEL SECURITY;
ALTER TABLE comment FORCE ROW LEVEL SECURITY;
ALTER TABLE saved_view ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_view FORCE ROW LEVEL SECURITY;

CREATE POLICY workspace_runtime ON workspace FOR SELECT TO sierx_runtime
  USING (id = public.sierx_current_workspace_id());
CREATE POLICY user_account_runtime_read ON user_account FOR SELECT TO sierx_runtime
  USING (id = public.sierx_current_user_id() OR EXISTS (
    SELECT 1 FROM membership m
    WHERE m.workspace_id = public.sierx_current_workspace_id()
      AND m.user_id = user_account.id));
CREATE POLICY user_account_runtime_update ON user_account FOR UPDATE TO sierx_runtime
  USING (id = public.sierx_current_user_id())
  WITH CHECK (id = public.sierx_current_user_id());
CREATE POLICY user_account_auth ON user_account FOR ALL TO sierx_auth
  USING (true) WITH CHECK (true);
CREATE POLICY membership_runtime ON membership FOR SELECT TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id());
CREATE POLICY membership_auth ON membership FOR SELECT TO sierx_auth USING (true);
CREATE POLICY session_auth ON session FOR ALL TO sierx_auth USING (true) WITH CHECK (true);

CREATE POLICY project_runtime_read ON project FOR SELECT TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id());
CREATE POLICY project_runtime_insert ON project FOR INSERT TO sierx_runtime
  WITH CHECK (workspace_id = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');
CREATE POLICY project_runtime_update ON project FOR UPDATE TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin')
  WITH CHECK (workspace_id = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');
-- Item creation consumes one project key for ordinary members. Keep that
-- operation workspace-scoped, while a trigger below protects metadata fields.
CREATE POLICY project_runtime_key_counter ON project FOR UPDATE TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id())
  WITH CHECK (workspace_id = public.sierx_current_workspace_id());

-- RLS controls rows, while this guard protects admin-only metadata columns on
-- the shared runtime role and keeps the item key counter strictly monotonic.
-- +goose StatementBegin
CREATE FUNCTION project_runtime_update_guard() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
  IF NEW.key_prefix IS DISTINCT FROM OLD.key_prefix OR NEW.kind IS DISTINCT FROM OLD.kind THEN
    RAISE EXCEPTION 'project key_prefix and kind are immutable';
  END IF;
  IF current_user = 'sierx_runtime' THEN
    IF NEW.next_key_num IS DISTINCT FROM OLD.next_key_num
       AND NEW.next_key_num <> OLD.next_key_num + 1 THEN
      RAISE EXCEPTION 'project key counter may only advance by one';
    END IF;
    IF NEW.name IS DISTINCT FROM OLD.name
       OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.archived_at IS DISTINCT FROM OLD.archived_at
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.updated_at IS DISTINCT FROM OLD.updated_at THEN
      IF public.sierx_current_role() IS DISTINCT FROM 'admin' THEN
        RAISE EXCEPTION 'project metadata updates require workspace admin';
      END IF;
      IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'project metadata update must increment version';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;
-- +goose StatementEnd
CREATE TRIGGER project_runtime_update_guard_trg
  BEFORE UPDATE ON project FOR EACH ROW EXECUTE FUNCTION project_runtime_update_guard();
REVOKE ALL ON FUNCTION project_runtime_update_guard() FROM PUBLIC;

CREATE POLICY project_config_runtime_read ON project_config FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY project_config_runtime_write ON project_config FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');
CREATE POLICY status_runtime_read ON status FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY status_runtime_write ON status FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');
CREATE POLICY item_type_runtime_read ON item_type FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY item_type_runtime_write ON item_type FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');
CREATE POLICY config_status_runtime_read ON config_status FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY config_status_runtime_write ON config_status FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');
CREATE POLICY config_type_runtime_read ON config_type FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY config_type_runtime_write ON config_type FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');
CREATE POLICY config_transition_runtime_read ON config_transition FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY config_transition_runtime_write ON config_transition FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');
CREATE POLICY field_def_runtime_read ON field_def FOR SELECT TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY field_def_runtime_write ON field_def FOR INSERT TO sierx_runtime
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id() AND public.sierx_current_role() = 'admin');

CREATE POLICY item_runtime ON item FOR ALL TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id()
     AND public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id())
  WITH CHECK (workspace_id = public.sierx_current_workspace_id()
          AND public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY item_rollup_runtime ON item_rollup FOR ALL TO sierx_runtime
  USING (EXISTS (SELECT 1 FROM item i WHERE i.id = item_rollup.item_id))
  WITH CHECK (EXISTS (SELECT 1 FROM item i WHERE i.id = item_rollup.item_id));
CREATE POLICY item_link_runtime ON item_link FOR ALL TO sierx_runtime
  USING (EXISTS (SELECT 1 FROM item i WHERE i.id = item_link.from_item_id)
     AND EXISTS (SELECT 1 FROM item i WHERE i.id = item_link.to_item_id))
  WITH CHECK (EXISTS (SELECT 1 FROM item i WHERE i.id = item_link.from_item_id)
          AND EXISTS (SELECT 1 FROM item i WHERE i.id = item_link.to_item_id));
CREATE POLICY change_event_runtime ON change_event FOR ALL TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id())
  WITH CHECK (workspace_id = public.sierx_current_workspace_id());
CREATE POLICY seq_counter_runtime ON seq_counter FOR SELECT TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id());
CREATE POLICY seq_counter_runtime_update ON seq_counter FOR UPDATE TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id())
  WITH CHECK (workspace_id = public.sierx_current_workspace_id());
CREATE POLICY sprint_runtime ON sprint FOR ALL TO sierx_runtime
  USING (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id())
  WITH CHECK (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id());
CREATE POLICY sprint_item_runtime ON sprint_item FOR ALL TO sierx_runtime
  USING (EXISTS (SELECT 1 FROM item i JOIN sprint s ON s.project_id = i.project_id
                 WHERE i.id = sprint_item.item_id AND s.id = sprint_item.sprint_id))
  WITH CHECK (EXISTS (SELECT 1 FROM item i JOIN sprint s ON s.project_id = i.project_id
                      WHERE i.id = sprint_item.item_id AND s.id = sprint_item.sprint_id));
CREATE POLICY comment_runtime_read ON comment FOR SELECT TO sierx_runtime
  USING (EXISTS (SELECT 1 FROM item i WHERE i.id = comment.item_id));
CREATE POLICY comment_runtime_insert ON comment FOR INSERT TO sierx_runtime
  WITH CHECK (author_id = public.sierx_current_user_id()
          AND EXISTS (SELECT 1 FROM item i WHERE i.id = comment.item_id));
CREATE POLICY comment_runtime_update ON comment FOR UPDATE TO sierx_runtime
  USING (EXISTS (SELECT 1 FROM item i WHERE i.id = comment.item_id)
     AND (author_id = public.sierx_current_user_id() OR public.sierx_current_role() = 'admin'))
  WITH CHECK (EXISTS (SELECT 1 FROM item i WHERE i.id = comment.item_id)
          AND (author_id = public.sierx_current_user_id() OR public.sierx_current_role() = 'admin'));
CREATE POLICY saved_view_runtime_read ON saved_view FOR SELECT TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id()
     AND (shared OR owner_id = public.sierx_current_user_id()));
CREATE POLICY saved_view_runtime_insert ON saved_view FOR INSERT TO sierx_runtime
  WITH CHECK (workspace_id = public.sierx_current_workspace_id()
          AND owner_id = public.sierx_current_user_id());
CREATE POLICY saved_view_runtime_update ON saved_view FOR UPDATE TO sierx_runtime
  USING (workspace_id = public.sierx_current_workspace_id()
     AND owner_id = public.sierx_current_user_id())
  WITH CHECK (workspace_id = public.sierx_current_workspace_id()
          AND owner_id = public.sierx_current_user_id());

-- Harden every existing event partition for direct access as well as access
-- through the partitioned parent.
-- +goose StatementBegin
DO $partitions$
DECLARE child regclass;
BEGIN
  FOR child IN
    SELECT inhrelid FROM pg_inherits WHERE inhparent = 'public.change_event'::regclass
  LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', child);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', child);
    EXECUTE format('CREATE POLICY change_event_partition_runtime ON %s FOR ALL TO sierx_runtime USING (workspace_id = public.sierx_current_workspace_id()) WITH CHECK (workspace_id = public.sierx_current_workspace_id())', child);
    EXECUTE format('GRANT SELECT, INSERT ON %s TO sierx_runtime', child);
  END LOOP;
END
$partitions$;
-- +goose StatementEnd

-- Partition creation remains an operator function, never a runtime DDL grant.
-- The fixed search path and bounded interval prevent caller-controlled DDL.
-- +goose StatementBegin
CREATE OR REPLACE FUNCTION change_event_ensure_partitions(months_ahead int)
RETURNS SETOF text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  m        int;
  start_at timestamptz;
  end_at   timestamptz;
  pname    text;
BEGIN
  IF months_ahead < 0 OR months_ahead > 12 THEN
    RAISE EXCEPTION 'months_ahead must be from 0 through 12';
  END IF;
  FOR m IN 0..months_ahead LOOP
    start_at := date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                + make_interval(months => m);
    end_at   := start_at + interval '1 month';
    pname    := 'change_event_' || to_char(start_at AT TIME ZONE 'UTC', 'YYYY_MM');
    IF to_regclass(format('public.%I', pname)) IS NULL THEN
      EXECUTE format(
        'CREATE TABLE public.%I PARTITION OF public.change_event FOR VALUES FROM (%L) TO (%L)',
        pname, start_at, end_at);
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', pname);
      EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', pname);
      EXECUTE format('CREATE POLICY change_event_partition_runtime ON public.%I FOR ALL TO sierx_runtime USING (workspace_id = public.sierx_current_workspace_id()) WITH CHECK (workspace_id = public.sierx_current_workspace_id())', pname);
      EXECUTE format('GRANT SELECT, INSERT ON public.%I TO sierx_runtime', pname);
      RETURN NEXT pname;
    END IF;
  END LOOP;
  RETURN;
END $$;
-- +goose StatementEnd
REVOKE ALL ON FUNCTION change_event_ensure_partitions(int) FROM PUBLIC;
REVOKE ALL ON FUNCTION change_event_ensure_partitions(int) FROM sierx_runtime, sierx_auth;
GRANT EXECUTE ON FUNCTION change_event_ensure_partitions(int) TO sierx_maintenance;

-- Remove inherited default DDL rights that would otherwise defeat the role
-- boundary. PostgreSQL 15+ already revokes schema CREATE on fresh databases;
-- this also closes older clusters using the legacy PUBLIC default.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- +goose StatementBegin
DO $database_privileges$
BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
END
$database_privileges$;
-- +goose StatementEnd

-- +goose Down
-- Keep the bounded, maintenance-only partition function and the shared
-- PUBLIC DDL revocations in place when rolling back row policies. Reverting
-- either would re-expose partition DDL to application logins.
DROP INDEX saved_view_workspace_owner_rls;
DROP INDEX comment_item_rls;
DROP INDEX sprint_project_rls;

-- Remove partition-level policies and restore legacy partition defaults.
-- +goose StatementBegin
DO $partitions$
DECLARE child regclass;
BEGIN
  FOR child IN
    SELECT inhrelid FROM pg_inherits WHERE inhparent = 'public.change_event'::regclass
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS change_event_partition_runtime ON %s', child);
    EXECUTE format('ALTER TABLE %s NO FORCE ROW LEVEL SECURITY', child);
    EXECUTE format('ALTER TABLE %s DISABLE ROW LEVEL SECURITY', child);
  END LOOP;
END
$partitions$;
-- +goose StatementEnd

DROP POLICY saved_view_runtime_update ON saved_view;
DROP POLICY saved_view_runtime_insert ON saved_view;
DROP POLICY saved_view_runtime_read ON saved_view;
DROP POLICY comment_runtime_update ON comment;
DROP POLICY comment_runtime_insert ON comment;
DROP POLICY comment_runtime_read ON comment;
DROP POLICY sprint_item_runtime ON sprint_item;
DROP POLICY sprint_runtime ON sprint;
DROP POLICY seq_counter_runtime_update ON seq_counter;
DROP POLICY seq_counter_runtime ON seq_counter;
DROP POLICY change_event_runtime ON change_event;
DROP POLICY item_link_runtime ON item_link;
DROP POLICY item_rollup_runtime ON item_rollup;
DROP POLICY item_runtime ON item;
DROP POLICY field_def_runtime_write ON field_def;
DROP POLICY field_def_runtime_read ON field_def;
DROP POLICY config_transition_runtime_write ON config_transition;
DROP POLICY config_transition_runtime_read ON config_transition;
DROP POLICY config_type_runtime_write ON config_type;
DROP POLICY config_type_runtime_read ON config_type;
DROP POLICY config_status_runtime_write ON config_status;
DROP POLICY config_status_runtime_read ON config_status;
DROP POLICY item_type_runtime_write ON item_type;
DROP POLICY item_type_runtime_read ON item_type;
DROP POLICY status_runtime_write ON status;
DROP POLICY status_runtime_read ON status;
DROP POLICY project_config_runtime_write ON project_config;
DROP POLICY project_config_runtime_read ON project_config;
DROP POLICY project_runtime_update ON project;
DROP POLICY project_runtime_key_counter ON project;
DROP POLICY project_runtime_insert ON project;
DROP POLICY project_runtime_read ON project;
DROP POLICY session_auth ON session;
DROP POLICY membership_auth ON membership;
DROP POLICY membership_runtime ON membership;
DROP POLICY user_account_auth ON user_account;
DROP POLICY user_account_runtime_update ON user_account;
DROP POLICY user_account_runtime_read ON user_account;
DROP POLICY workspace_runtime ON workspace;

ALTER TABLE workspace NO FORCE ROW LEVEL SECURITY;
ALTER TABLE workspace DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_account NO FORCE ROW LEVEL SECURITY;
ALTER TABLE user_account DISABLE ROW LEVEL SECURITY;
ALTER TABLE membership NO FORCE ROW LEVEL SECURITY;
ALTER TABLE membership DISABLE ROW LEVEL SECURITY;
ALTER TABLE session NO FORCE ROW LEVEL SECURITY;
ALTER TABLE session DISABLE ROW LEVEL SECURITY;
ALTER TABLE project NO FORCE ROW LEVEL SECURITY;
ALTER TABLE project DISABLE ROW LEVEL SECURITY;
ALTER TABLE project_config NO FORCE ROW LEVEL SECURITY;
ALTER TABLE project_config DISABLE ROW LEVEL SECURITY;
ALTER TABLE status NO FORCE ROW LEVEL SECURITY;
ALTER TABLE status DISABLE ROW LEVEL SECURITY;
ALTER TABLE item_type NO FORCE ROW LEVEL SECURITY;
ALTER TABLE item_type DISABLE ROW LEVEL SECURITY;
ALTER TABLE config_status NO FORCE ROW LEVEL SECURITY;
ALTER TABLE config_status DISABLE ROW LEVEL SECURITY;
ALTER TABLE config_type NO FORCE ROW LEVEL SECURITY;
ALTER TABLE config_type DISABLE ROW LEVEL SECURITY;
ALTER TABLE config_transition NO FORCE ROW LEVEL SECURITY;
ALTER TABLE config_transition DISABLE ROW LEVEL SECURITY;
ALTER TABLE field_def NO FORCE ROW LEVEL SECURITY;
ALTER TABLE field_def DISABLE ROW LEVEL SECURITY;
ALTER TABLE item NO FORCE ROW LEVEL SECURITY;
ALTER TABLE item DISABLE ROW LEVEL SECURITY;
ALTER TABLE item_rollup NO FORCE ROW LEVEL SECURITY;
ALTER TABLE item_rollup DISABLE ROW LEVEL SECURITY;
ALTER TABLE item_link NO FORCE ROW LEVEL SECURITY;
ALTER TABLE item_link DISABLE ROW LEVEL SECURITY;
ALTER TABLE change_event NO FORCE ROW LEVEL SECURITY;
ALTER TABLE change_event DISABLE ROW LEVEL SECURITY;
ALTER TABLE seq_counter NO FORCE ROW LEVEL SECURITY;
ALTER TABLE seq_counter DISABLE ROW LEVEL SECURITY;
ALTER TABLE sprint NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sprint DISABLE ROW LEVEL SECURITY;
ALTER TABLE sprint_item NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sprint_item DISABLE ROW LEVEL SECURITY;
ALTER TABLE comment NO FORCE ROW LEVEL SECURITY;
ALTER TABLE comment DISABLE ROW LEVEL SECURITY;
ALTER TABLE saved_view NO FORCE ROW LEVEL SECURITY;
ALTER TABLE saved_view DISABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM sierx_runtime, sierx_auth, sierx_maintenance;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM sierx_runtime, sierx_auth, sierx_maintenance;
REVOKE SELECT (id, display_name, is_active, theme, reduced_motion),
  UPDATE (display_name, theme, reduced_motion) ON user_account FROM sierx_runtime;
REVOKE SELECT (id, email, display_name, password_hash, totp_secret, is_active,
  theme, reduced_motion), UPDATE (totp_secret) ON user_account FROM sierx_auth;
REVOKE SELECT ON project FROM sierx_runtime;
REVOKE INSERT (workspace_id, key_prefix, name, kind, owner_id),
  UPDATE (name, owner_id, version, updated_at, next_key_num) ON project FROM sierx_runtime;
DROP TRIGGER project_runtime_update_guard_trg ON project;
DROP FUNCTION project_runtime_update_guard();
REVOKE ALL ON FUNCTION sierx_current_workspace_id() FROM PUBLIC, sierx_runtime;
REVOKE ALL ON FUNCTION sierx_current_user_id() FROM PUBLIC, sierx_runtime;
REVOKE ALL ON FUNCTION sierx_current_role() FROM PUBLIC, sierx_runtime;
REVOKE ALL ON FUNCTION sierx_project_workspace_id(uuid) FROM PUBLIC, sierx_runtime;
DROP FUNCTION sierx_current_workspace_id();
DROP FUNCTION sierx_current_user_id();
DROP FUNCTION sierx_current_role();
DROP FUNCTION sierx_project_workspace_id(uuid);

-- PUBLIC CREATE/TEMP hardening is a host posture correction and remains in
-- place after schema rollback; restoring those shared defaults would make the
-- still-provisioned application logins capable of creating objects again.
-- Restore the pre-0011 partition helper for a down-to-0010 rollback, but keep
-- execution operator-only. A subsequent down-to-zero then lets migration 0009
-- drop the helper as it originally did.
-- +goose StatementBegin
CREATE OR REPLACE FUNCTION change_event_ensure_partitions(months_ahead int)
RETURNS SETOF text
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
  m int;
  start_at timestamptz;
  end_at timestamptz;
  pname text;
BEGIN
  IF months_ahead < 0 OR months_ahead > 12 THEN RAISE EXCEPTION 'months_ahead must be from 0 through 12'; END IF;
  FOR m IN 0..months_ahead LOOP
    start_at := date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                + make_interval(months => m);
    end_at := start_at + interval '1 month';
    pname := 'change_event_' || to_char(start_at AT TIME ZONE 'UTC','YYYY_MM');
    IF to_regclass(format('public.%I',pname)) IS NULL THEN
      EXECUTE format('CREATE TABLE public.%I PARTITION OF public.change_event FOR VALUES FROM (%L) TO (%L)',pname,start_at,end_at);
      RETURN NEXT pname;
    END IF;
  END LOOP;
  RETURN;
END $$;
-- +goose StatementEnd
REVOKE ALL ON FUNCTION change_event_ensure_partitions(int) FROM PUBLIC, sierx_runtime, sierx_auth;
GRANT EXECUTE ON FUNCTION change_event_ensure_partitions(int) TO sierx_maintenance;
