-- Private administrator provisioning; no registration or invitation delivery.
-- +goose Up
-- A non-login function owner can insert only account/membership columns.
-- Runtime receives EXECUTE, never direct credential/table-write privileges.
-- +goose StatementBegin
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sierx_member_provisioner') THEN
    CREATE ROLE sierx_member_provisioner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sierx_member_provisioner'
    AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolbypassrls OR rolreplication))
    OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='sierx_member_provisioner')
      OR roleid=(SELECT oid FROM pg_roles WHERE rolname='sierx_member_provisioner')) THEN
    RAISE EXCEPTION 'member provisioner role must be isolated and non-login';
  END IF;
END $$;
-- +goose StatementEnd
GRANT USAGE ON SCHEMA public TO sierx_member_provisioner;
GRANT SELECT ON membership TO sierx_member_provisioner;
GRANT SELECT (id,email,display_name,is_active) ON user_account TO sierx_member_provisioner;
GRANT INSERT (email,display_name,password_hash) ON user_account TO sierx_member_provisioner;
GRANT INSERT (workspace_id,user_id,role) ON membership TO sierx_member_provisioner;
GRANT EXECUTE ON FUNCTION sierx_current_workspace_id(),sierx_current_user_id(),sierx_current_role() TO sierx_member_provisioner;
CREATE POLICY user_account_member_provisioner_read ON user_account FOR SELECT TO sierx_member_provisioner USING (true);
CREATE POLICY user_account_member_provisioner_insert ON user_account FOR INSERT TO sierx_member_provisioner WITH CHECK (true);
CREATE POLICY membership_member_provisioner_read ON membership FOR SELECT TO sierx_member_provisioner USING (true);
CREATE POLICY membership_member_provisioner_insert ON membership FOR INSERT TO sierx_member_provisioner
  WITH CHECK (workspace_id=public.sierx_current_workspace_id() AND role='member');

-- +goose StatementBegin
CREATE FUNCTION sierx_admin_add_member(p_email text,p_name text,p_hash text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE new_id uuid;
BEGIN
  IF public.sierx_current_role() IS DISTINCT FROM 'admin' THEN
    RAISE EXCEPTION 'workspace administrator required' USING ERRCODE='42501';
  END IF;
  PERFORM 1 FROM public.membership m JOIN public.user_account u ON u.id=m.user_id
    WHERE m.workspace_id=public.sierx_current_workspace_id()
      AND m.user_id=public.sierx_current_user_id() AND m.role='admin' AND u.is_active;
  IF NOT FOUND THEN RAISE EXCEPTION 'workspace administrator required' USING ERRCODE='42501'; END IF;
  IF p_email IS NULL OR length(p_email)>320 OR p_email<>btrim(p_email)
    OR p_email !~ '^[^[:space:]@]+@[^[:space:]@]+$'
    OR p_name IS NULL OR length(btrim(p_name)) NOT BETWEEN 1 AND 200
    OR p_name<>btrim(p_name)
    OR p_hash IS NULL OR p_hash !~ '^\$argon2id\$v=19\$m=65536,t=3,p=1\$[A-Za-z0-9+/]{22}\$[A-Za-z0-9+/]{43}$' THEN
    RAISE EXCEPTION 'invalid member inputs' USING ERRCODE='22023';
  END IF;
  INSERT INTO public.user_account(email,display_name,password_hash)
    VALUES(p_email,p_name,p_hash) RETURNING id INTO new_id;
  INSERT INTO public.membership(workspace_id,user_id,role)
    VALUES(public.sierx_current_workspace_id(),new_id,'member');
  RETURN new_id;
END $$;
-- +goose StatementEnd

-- +goose StatementBegin
CREATE FUNCTION sierx_admin_list_members(p_after uuid,p_upper uuid,p_search text,p_limit integer)
RETURNS TABLE(id uuid,display_name text,email text,role text,is_active boolean)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
  IF public.sierx_current_role() IS DISTINCT FROM 'admin' OR NOT EXISTS (
    SELECT 1 FROM public.membership m JOIN public.user_account u ON u.id=m.user_id
      WHERE m.workspace_id=public.sierx_current_workspace_id()
        AND m.user_id=public.sierx_current_user_id() AND m.role='admin' AND u.is_active
  ) THEN RAISE EXCEPTION 'workspace administrator required' USING ERRCODE='42501'; END IF;
  IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 201 OR p_search IS NULL OR length(p_search)>100 THEN
    RAISE EXCEPTION 'invalid member query' USING ERRCODE='22023';
  END IF;
  RETURN QUERY SELECT u.id,u.display_name,u.email::text,m.role,u.is_active
    FROM public.user_account u JOIN public.membership m ON m.user_id=u.id
    WHERE m.workspace_id=public.sierx_current_workspace_id() AND u.id>p_after AND u.id<=p_upper
      AND (u.display_name ILIKE '%'||p_search||'%' OR u.email ILIKE '%'||p_search||'%')
    ORDER BY u.id LIMIT p_limit;
END $$;
-- +goose StatementEnd
GRANT CREATE ON SCHEMA public TO sierx_member_provisioner;
ALTER FUNCTION sierx_admin_add_member(text,text,text) OWNER TO sierx_member_provisioner;
ALTER FUNCTION sierx_admin_list_members(uuid,uuid,text,integer) OWNER TO sierx_member_provisioner;
REVOKE CREATE ON SCHEMA public FROM sierx_member_provisioner;
REVOKE ALL ON FUNCTION sierx_admin_add_member(text,text,text),sierx_admin_list_members(uuid,uuid,text,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_admin_add_member(text,text,text),sierx_admin_list_members(uuid,uuid,text,integer) TO sierx_runtime;

-- +goose Down
DROP FUNCTION sierx_admin_list_members(uuid,uuid,text,integer);
DROP FUNCTION sierx_admin_add_member(text,text,text);
DROP POLICY membership_member_provisioner_insert ON membership;
DROP POLICY membership_member_provisioner_read ON membership;
DROP POLICY user_account_member_provisioner_insert ON user_account;
DROP POLICY user_account_member_provisioner_read ON user_account;
REVOKE ALL ON membership,user_account FROM sierx_member_provisioner;
REVOKE SELECT (id,email,display_name,is_active),INSERT (email,display_name,password_hash) ON user_account FROM sierx_member_provisioner;
REVOKE INSERT (workspace_id,user_id,role) ON membership FROM sierx_member_provisioner;
REVOKE EXECUTE ON FUNCTION sierx_current_workspace_id(),sierx_current_user_id(),sierx_current_role() FROM sierx_member_provisioner;
REVOKE USAGE ON SCHEMA public FROM sierx_member_provisioner;
-- The isolated NOLOGIN role may be shared by other databases; leave it in place.
