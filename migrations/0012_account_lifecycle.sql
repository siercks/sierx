-- Narrow operator workflow for reversible account suspension and session revocation.
-- This migration intentionally does not add content redaction or retention.
-- +goose Up

CREATE TABLE operator_account_action (
  id               uuid PRIMARY KEY DEFAULT uuidv7(),
  occurred_at      timestamptz NOT NULL DEFAULT now(),
  operator_role    text NOT NULL,
  case_ref         uuid NOT NULL,
  user_id          uuid NOT NULL REFERENCES user_account(id) ON DELETE RESTRICT,
  active_before    boolean NOT NULL,
  active_after     boolean NOT NULL,
  sessions_revoked integer NOT NULL CHECK (sessions_revoked >= 0)
);

ALTER TABLE operator_account_action ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_account_action FORCE ROW LEVEL SECURITY;
CREATE POLICY operator_account_action_runtime_deny ON operator_account_action
  FOR ALL TO sierx_runtime USING (false) WITH CHECK (false);
CREATE POLICY operator_account_action_maintenance ON operator_account_action
  FOR ALL TO sierx_maintenance USING (true) WITH CHECK (true);
GRANT SELECT, INSERT ON operator_account_action TO sierx_maintenance;

CREATE POLICY user_account_maintenance ON user_account
  FOR ALL TO sierx_maintenance USING (true) WITH CHECK (true);
GRANT SELECT (id, is_active), UPDATE (is_active) ON user_account TO sierx_maintenance;

CREATE POLICY session_maintenance_delete ON session
  FOR DELETE TO sierx_maintenance USING (true);
CREATE POLICY session_maintenance_select ON session
  FOR SELECT TO sierx_maintenance USING (true);
CREATE POLICY session_maintenance_insert ON session
  FOR INSERT TO sierx_maintenance WITH CHECK (true);
GRANT SELECT (user_id), INSERT (id_hash, user_id, expires_at), DELETE ON session TO sierx_maintenance;
REVOKE INSERT ON session FROM sierx_auth;

-- The narrowly scoped function is owned by the maintenance login. That role
-- has only the columns and row operations needed here, and no direct access to
-- email, password hashes, MFA secrets, or session token hashes.
-- +goose StatementBegin
CREATE FUNCTION sierx_set_account_active(p_user_id uuid, p_active boolean, p_case_ref uuid)
RETURNS TABLE (account_id uuid, active_before boolean, active_after boolean, sessions_revoked integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  prior_active boolean;
  revoked integer;
BEGIN
  IF p_case_ref IS NULL THEN
    RAISE EXCEPTION 'a case reference is required' USING ERRCODE = '22023';
  END IF;

  SELECT u.is_active INTO prior_active
  FROM public.user_account u
  WHERE u.id = p_user_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'account not found' USING ERRCODE = 'P0002';
  END IF;

  UPDATE public.user_account SET is_active = p_active WHERE id = p_user_id;
  DELETE FROM public.session WHERE user_id = p_user_id;
  GET DIAGNOSTICS revoked = ROW_COUNT;

  INSERT INTO public.operator_account_action (
    operator_role, case_ref, user_id, active_before, active_after, sessions_revoked
  ) VALUES (
    session_user, p_case_ref, p_user_id, prior_active, p_active, revoked
  );

  RETURN QUERY SELECT p_user_id, prior_active, p_active, revoked;
END
$$;
-- +goose StatementEnd

-- Serialize login session creation with suspension on the account row. If a
-- login already owns the row lock, suspension waits and then revokes its new
-- session. If suspension wins, a waiting login rechecks the inactive row and
-- cannot create a token that might become valid after later reactivation.
-- +goose StatementBegin
CREATE FUNCTION sierx_create_session(p_hash bytea, p_user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  account_active boolean;
BEGIN
  SELECT u.is_active INTO account_active
  FROM public.user_account u
  WHERE u.id = p_user_id
  FOR UPDATE;
  IF NOT FOUND OR NOT account_active THEN
    RETURN false;
  END IF;

  INSERT INTO public.session (id_hash,user_id,expires_at)
  VALUES (p_hash,p_user_id,now()+interval '12 hours');
  RETURN true;
END
$$;
-- +goose StatementEnd

GRANT CREATE ON SCHEMA public TO sierx_maintenance;
ALTER FUNCTION sierx_set_account_active(uuid, boolean, uuid) OWNER TO sierx_maintenance;
ALTER FUNCTION sierx_create_session(bytea, uuid) OWNER TO sierx_maintenance;
REVOKE CREATE ON SCHEMA public FROM sierx_maintenance;
REVOKE ALL ON FUNCTION sierx_set_account_active(uuid, boolean, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION sierx_create_session(bytea, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_set_account_active(uuid, boolean, uuid) TO sierx_maintenance;
GRANT EXECUTE ON FUNCTION sierx_create_session(bytea, uuid) TO sierx_auth;

-- +goose Down
REVOKE EXECUTE ON FUNCTION sierx_create_session(bytea, uuid) FROM sierx_auth;
DROP FUNCTION sierx_create_session(bytea, uuid);
REVOKE EXECUTE ON FUNCTION sierx_set_account_active(uuid, boolean, uuid) FROM sierx_maintenance;
DROP FUNCTION sierx_set_account_active(uuid, boolean, uuid);
GRANT INSERT ON session TO sierx_auth;
REVOKE SELECT (user_id), INSERT (id_hash, user_id, expires_at), DELETE ON session FROM sierx_maintenance;
DROP POLICY session_maintenance_insert ON session;
DROP POLICY session_maintenance_select ON session;
DROP POLICY session_maintenance_delete ON session;
REVOKE SELECT (id, is_active), UPDATE (is_active) ON user_account FROM sierx_maintenance;
DROP POLICY user_account_maintenance ON user_account;
REVOKE SELECT, INSERT ON operator_account_action FROM sierx_maintenance;
DROP POLICY operator_account_action_maintenance ON operator_account_action;
DROP POLICY operator_account_action_runtime_deny ON operator_account_action;
DROP TABLE operator_account_action;
