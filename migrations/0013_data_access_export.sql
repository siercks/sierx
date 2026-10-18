-- Bounded, operator-mediated access export. This does not claim completeness.
-- The payload is available for one hour; only its metadata survives expiry.
-- +goose Up

CREATE TABLE operator_data_export (
  id          uuid PRIMARY KEY DEFAULT uuidv7(),
  user_id     uuid NOT NULL REFERENCES user_account(id) ON DELETE RESTRICT,
  case_ref    uuid NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  payload     jsonb,
  CHECK (expires_at > created_at)
);
CREATE INDEX operator_data_export_expiry
  ON operator_data_export (expires_at) WHERE payload IS NOT NULL;

CREATE TABLE operator_data_export_event (
  id          uuid PRIMARY KEY DEFAULT uuidv7(),
  export_id   uuid NOT NULL REFERENCES operator_data_export(id) ON DELETE RESTRICT,
  operator_role text NOT NULL,
  case_ref    uuid NOT NULL,
  event       text NOT NULL CHECK (event IN ('created','downloaded','expired')),
  occurred_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE operator_data_export ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_data_export FORCE ROW LEVEL SECURITY;
CREATE POLICY operator_data_export_runtime_deny ON operator_data_export
  FOR ALL TO sierx_runtime USING (false) WITH CHECK (false);
CREATE POLICY operator_data_export_maintenance ON operator_data_export
  FOR ALL TO sierx_maintenance USING (true) WITH CHECK (true);
GRANT SELECT, INSERT ON operator_data_export TO sierx_maintenance;
GRANT UPDATE (payload) ON operator_data_export TO sierx_maintenance;

ALTER TABLE operator_data_export_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_data_export_event FORCE ROW LEVEL SECURITY;
CREATE POLICY operator_data_export_event_runtime_deny ON operator_data_export_event
  FOR ALL TO sierx_runtime USING (false) WITH CHECK (false);
CREATE POLICY operator_data_export_event_maintenance ON operator_data_export_event
  FOR ALL TO sierx_maintenance USING (true) WITH CHECK (true);
GRANT SELECT, INSERT ON operator_data_export_event TO sierx_maintenance;

CREATE POLICY membership_maintenance ON membership
  FOR SELECT TO sierx_maintenance USING (true);
CREATE POLICY workspace_maintenance ON workspace
  FOR SELECT TO sierx_maintenance USING (true);
CREATE POLICY comment_maintenance ON comment
  FOR SELECT TO sierx_maintenance USING (true);
CREATE POLICY saved_view_maintenance ON saved_view
  FOR SELECT TO sierx_maintenance USING (true);
GRANT SELECT ON membership, workspace TO sierx_maintenance;
GRANT SELECT (id, item_id, author_id, body, created_at, edited_at, deleted_at)
  ON comment TO sierx_maintenance;
GRANT SELECT (id, workspace_id, owner_id, name, query, layout, shared)
  ON saved_view TO sierx_maintenance;
GRANT SELECT (id, email, display_name, theme, reduced_motion, is_active, created_at)
  ON user_account TO sierx_maintenance;

-- Build only fields with a reliable direct account relationship. Item bodies
-- and change-event old/new values are intentionally excluded.
-- +goose StatementBegin
CREATE FUNCTION sierx_create_data_export(p_user_id uuid, p_case_ref uuid)
RETURNS TABLE (export_id uuid, expires_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  export_payload jsonb;
  new_id uuid;
  expiry timestamptz := now() + interval '1 hour';
BEGIN
  IF p_case_ref IS NULL THEN
    RAISE EXCEPTION 'a case reference is required' USING ERRCODE = '22023';
  END IF;

  -- Erase expired payloads while retaining the audit metadata.
  UPDATE public.operator_data_export e
     SET payload = NULL
   WHERE e.expires_at <= now() AND e.payload IS NOT NULL;
  INSERT INTO public.operator_data_export_event(export_id,operator_role,case_ref,event)
    SELECT e.id, session_user, e.case_ref, 'expired'
      FROM public.operator_data_export e
     WHERE e.expires_at <= now() AND e.payload IS NULL
       AND NOT EXISTS (
         SELECT 1 FROM public.operator_data_export_event ev
          WHERE ev.export_id=e.id AND ev.event='expired'
       );

  SELECT jsonb_build_object(
    'scope', 'sierx-account-export-v1-limited',
    'completeness', 'This export is limited and is not a complete personal-data export.',
    'included', jsonb_build_array('account profile', 'workspace memberships',
                                  'authored comments', 'owned saved views'),
    'excluded', jsonb_build_array('password hashes', 'MFA secrets', 'session token hashes',
                                  'item content without author attribution',
                                  'change-event old/new values', 'unrelated workspace content'),
    'limits', jsonb_build_object(
      'comments_max_rows', 512, 'saved_views_max_rows', 512,
      'comment_body_max_characters', 4096, 'saved_view_query_max_characters', 4096,
      'maximum_payload_bytes', 20971520
    ),
    'account', jsonb_build_object(
      'id', u.id, 'email', u.email, 'display_name', u.display_name,
      'theme', u.theme, 'reduced_motion', u.reduced_motion,
      'is_active', u.is_active, 'created_at', u.created_at
    ),
    'memberships', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'workspace_id', w.id, 'workspace_slug', w.slug,
        'workspace_name', w.name, 'role', m.role
      ) ORDER BY w.slug)
      FROM public.membership m JOIN public.workspace w ON w.id=m.workspace_id
      WHERE m.user_id=u.id
    ), '[]'::jsonb),
    'authored_comments_truncated', (
      SELECT count(*) > 512 FROM public.comment c WHERE c.author_id=u.id
    ),
    'authored_comments', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'id', c.id, 'item_id', c.item_id,
        'body', CASE WHEN c.deleted_at IS NULL THEN left(c.body,4096) ELSE NULL END,
        'body_truncated', c.deleted_at IS NULL AND char_length(c.body)>4096,
        'created_at', c.created_at, 'edited_at', c.edited_at,
        'deleted_at', c.deleted_at
      ) ORDER BY c.created_at, c.id)
      FROM (
        SELECT * FROM public.comment
         WHERE author_id=u.id ORDER BY created_at,id LIMIT 512
      ) c
    ), '[]'::jsonb),
    'owned_saved_views_truncated', (
      SELECT count(*) > 512 FROM public.saved_view v WHERE v.owner_id=u.id
    ),
    'owned_saved_views', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'id', v.id, 'workspace_id', v.workspace_id, 'name', v.name,
        'query', left(v.query,4096), 'query_truncated', char_length(v.query)>4096,
        'layout', v.layout, 'shared', v.shared
      ) ORDER BY v.id)
      FROM (
        SELECT * FROM public.saved_view
         WHERE owner_id=u.id ORDER BY id LIMIT 512
      ) v
    ), '[]'::jsonb)
  ) INTO export_payload
  FROM public.user_account u WHERE u.id=p_user_id;

  IF export_payload IS NULL THEN
    RAISE EXCEPTION 'account not found' USING ERRCODE = 'P0002';
  END IF;
  IF octet_length(export_payload::text) > 20971520 THEN
    RAISE EXCEPTION 'bounded export exceeds maximum payload size' USING ERRCODE = '54000';
  END IF;

  INSERT INTO public.operator_data_export(user_id,case_ref,expires_at,payload)
  VALUES (p_user_id,p_case_ref,expiry,export_payload)
  RETURNING id INTO new_id;
  INSERT INTO public.operator_data_export_event(export_id,operator_role,case_ref,event)
  VALUES (new_id,session_user,p_case_ref,'created');

  RETURN QUERY SELECT new_id, expiry;
END
$$;
-- +goose StatementEnd

-- Download access is case-bound, audited, and unavailable after one hour.
-- +goose StatementBegin
CREATE FUNCTION sierx_read_data_export(p_export_id uuid, p_case_ref uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  result jsonb;
BEGIN
  SELECT e.payload INTO result
    FROM public.operator_data_export e
   WHERE e.id=p_export_id AND e.case_ref=p_case_ref AND e.expires_at>now()
   FOR UPDATE;
  IF NOT FOUND OR result IS NULL THEN
    RAISE EXCEPTION 'export not found or expired' USING ERRCODE = 'P0002';
  END IF;
  INSERT INTO public.operator_data_export_event(export_id,operator_role,case_ref,event)
  VALUES (p_export_id,session_user,p_case_ref,'downloaded');
  RETURN result;
END
$$;
-- +goose StatementEnd

GRANT CREATE ON SCHEMA public TO sierx_maintenance;
ALTER FUNCTION sierx_create_data_export(uuid, uuid) OWNER TO sierx_maintenance;
ALTER FUNCTION sierx_read_data_export(uuid, uuid) OWNER TO sierx_maintenance;
REVOKE CREATE ON SCHEMA public FROM sierx_maintenance;
REVOKE ALL ON FUNCTION sierx_create_data_export(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION sierx_read_data_export(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_create_data_export(uuid, uuid) TO sierx_maintenance;
GRANT EXECUTE ON FUNCTION sierx_read_data_export(uuid, uuid) TO sierx_maintenance;

-- +goose Down
REVOKE EXECUTE ON FUNCTION sierx_read_data_export(uuid, uuid) FROM sierx_maintenance;
DROP FUNCTION sierx_read_data_export(uuid, uuid);
REVOKE EXECUTE ON FUNCTION sierx_create_data_export(uuid, uuid) FROM sierx_maintenance;
DROP FUNCTION sierx_create_data_export(uuid, uuid);
REVOKE SELECT (id, email, display_name, theme, reduced_motion, is_active, created_at)
  ON user_account FROM sierx_maintenance;
REVOKE SELECT (id, workspace_id, owner_id, name, query, layout, shared)
  ON saved_view FROM sierx_maintenance;
REVOKE SELECT (id, item_id, author_id, body, created_at, edited_at, deleted_at)
  ON comment FROM sierx_maintenance;
REVOKE SELECT ON membership, workspace FROM sierx_maintenance;
DROP POLICY saved_view_maintenance ON saved_view;
DROP POLICY comment_maintenance ON comment;
DROP POLICY workspace_maintenance ON workspace;
DROP POLICY membership_maintenance ON membership;
REVOKE SELECT, INSERT ON operator_data_export_event FROM sierx_maintenance;
DROP POLICY operator_data_export_event_maintenance ON operator_data_export_event;
DROP POLICY operator_data_export_event_runtime_deny ON operator_data_export_event;
DROP TABLE operator_data_export_event;
REVOKE UPDATE (payload) ON operator_data_export FROM sierx_maintenance;
REVOKE SELECT, INSERT ON operator_data_export FROM sierx_maintenance;
DROP POLICY operator_data_export_maintenance ON operator_data_export;
DROP POLICY operator_data_export_runtime_deny ON operator_data_export;
DROP TABLE operator_data_export;
