--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: citext; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;


--
-- Name: EXTENSION citext; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION citext IS 'data type for case-insensitive character strings';


--
-- Name: ltree; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS ltree WITH SCHEMA public;


--
-- Name: EXTENSION ltree; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION ltree IS 'data type for hierarchical tree-like structures';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: change_event_ensure_partitions(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.change_event_ensure_partitions(months_ahead integer) RETURNS SETOF text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
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
      EXECUTE format('CREATE POLICY event_lifecycle ON public.%I AS RESTRICTIVE FOR ALL TO sierx_runtime USING(public.sierx_lifecycle_event_visible(workspace_id,item_id,old_value,new_value)) WITH CHECK(public.sierx_lifecycle_event_visible(workspace_id,item_id,old_value,new_value))', pname);
      EXECUTE format('GRANT SELECT, INSERT ON public.%I TO sierx_runtime', pname);
      RETURN NEXT pname;
    END IF;
  END LOOP;
  RETURN;
END $$;


--
-- Name: item_path_check(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.item_path_check() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  depth       int := nlevel(NEW.path);
  parent_path ltree;
BEGIN
  -- §5.3: maximum depth 8 (a root item has depth 1)
  IF depth > 8 THEN
    RAISE EXCEPTION 'item % would be at depth %, maximum is 8 (SPEC §5.3)',
      NEW.id, depth USING ERRCODE = 'check_violation';
  END IF;

  -- §5.3: path always ends with the item's own id
  IF ltree2text(subpath(NEW.path, -1)) <> NEW.id::text THEN
    RAISE EXCEPTION 'item % path % does not end with its own id (SPEC §5.3)',
      NEW.id, NEW.path USING ERRCODE = 'check_violation';
  END IF;

  -- task 0.5: path and parent_id must agree
  IF NEW.parent_id IS NULL THEN
    IF depth <> 1 THEN
      RAISE EXCEPTION 'item % has no parent but path % has % labels; a root path is the id alone',
        NEW.id, NEW.path, depth USING ERRCODE = 'check_violation';
    END IF;
  ELSE
    IF depth < 2 OR ltree2text(subpath(NEW.path, -2, 1)) <> NEW.parent_id::text THEN
      RAISE EXCEPTION 'item % path % disagrees with parent_id % (penultimate label must be the parent)',
        NEW.id, NEW.path, NEW.parent_id USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  -- §5.3: reject a reparent that would make the item its own ancestor.
  -- Checked only when parent_id changes: a subtree rewrite in one statement
  -- (§5.3) leaves descendants' parent_id untouched and must not be re-judged
  -- row by row against paths that are mid-rewrite.
  IF TG_OP = 'UPDATE' AND NEW.parent_id IS NOT NULL
     AND NEW.parent_id IS DISTINCT FROM OLD.parent_id THEN
    SELECT path INTO parent_path FROM item WHERE id = NEW.parent_id;
    IF parent_path <@ OLD.path THEN
      RAISE EXCEPTION 'reparenting item % under % would make it its own ancestor (SPEC §5.3)',
        NEW.id, NEW.parent_id USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  RETURN NEW;
END $$;


--
-- Name: item_type_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.item_type_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.key   IS DISTINCT FROM OLD.key
  OR NEW.name  IS DISTINCT FROM OLD.name
  OR NEW.level IS DISTINCT FROM OLD.level THEN
    RAISE EXCEPTION 'item_type % is immutable: key, name, level cannot change (SPEC §5.6); insert a new row and a new config version',
      OLD.id USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;


--
-- Name: project_runtime_update_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.project_runtime_update_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
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


--
-- Name: sierx_create_data_export(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_create_data_export(p_user_id uuid, p_case_ref uuid) RETURNS TABLE(export_id uuid, expires_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
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
   WHERE e.expires_at <= now() AND e.payload IS NOT NULL
     AND NOT public.sierx_lifecycle_has_hold();
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
        SELECT c.* FROM public.comment c JOIN public.item i ON i.id=c.item_id
         WHERE c.author_id=u.id AND public.sierx_lifecycle_visible('item',i.id,i.workspace_id,i.path) AND public.sierx_lifecycle_visible('comment',c.id,i.workspace_id) ORDER BY c.created_at,c.id LIMIT 512
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
         WHERE owner_id=u.id AND public.sierx_lifecycle_visible('view',id,workspace_id) ORDER BY id LIMIT 512
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


--
-- Name: sierx_create_session(bytea, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_create_session(p_hash bytea, p_user_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
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


--
-- Name: sierx_create_workspace_export(uuid, uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_create_workspace_export(p_workspace uuid, p_user uuid, p_case uuid) RETURNS TABLE(export_id uuid, expires_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE payload_json jsonb; new_id uuid; expiry timestamptz:=now()+interval '1 hour';
BEGIN
 IF p_case IS NULL OR NOT EXISTS(SELECT 1 FROM public.membership WHERE workspace_id=p_workspace AND user_id=p_user) THEN
  RAISE EXCEPTION 'case and requester workspace membership required'; END IF;
 SELECT jsonb_build_object(
  'scope','sierx-workspace-export-v1-limited','completeness','Operator-reviewed shared workspace export; not a complete personal-data export.',
  'workspace_id',p_workspace,'excluded',jsonb_build_array('credentials','sessions','unrelated workspaces','restricted content','history payloads'),
  'limits',jsonb_build_object('rows_per_group',512,'text_characters',4096,'maximum_payload_bytes',20971520),
  'projects',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.id),'[]') FROM (SELECT id,key_prefix,name,kind,owner_id,version FROM public.project WHERE workspace_id=p_workspace ORDER BY id LIMIT 512) p),
  'projects_truncated',(SELECT count(*)>512 FROM public.project WHERE workspace_id=p_workspace),
  'items',(SELECT coalesce(jsonb_agg(to_jsonb(i) ORDER BY i.id),'[]') FROM (
   SELECT id,key,project_id,parent_id,left(title,4096) title,left(body,4096) body,
    char_length(body)>4096 body_truncated,fields,version,deleted_at
   FROM public.item WHERE workspace_id=p_workspace AND public.sierx_lifecycle_visible('item',id,workspace_id,path)
   ORDER BY id LIMIT 512) i),
  'items_truncated',(SELECT count(*)>512 FROM public.item WHERE workspace_id=p_workspace AND public.sierx_lifecycle_visible('item',id,workspace_id,path)),
  'comments',(SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY c.id),'[]') FROM (
   SELECT c.id,c.item_id,c.author_id,CASE WHEN c.deleted_at IS NULL THEN left(c.body,4096) ELSE NULL END body,c.deleted_at,c.created_at,char_length(c.body)>4096 body_truncated
   FROM public.comment c JOIN public.item i ON i.id=c.item_id WHERE i.workspace_id=p_workspace
   AND public.sierx_lifecycle_visible('item',i.id,i.workspace_id,i.path) AND public.sierx_lifecycle_visible('comment',c.id,p_workspace)
   ORDER BY c.id LIMIT 512) c),
  'comments_truncated',(SELECT count(*)>512 FROM public.comment c JOIN public.item i ON i.id=c.item_id WHERE i.workspace_id=p_workspace AND public.sierx_lifecycle_visible('item',i.id,i.workspace_id,i.path) AND public.sierx_lifecycle_visible('comment',c.id,p_workspace)),
  'saved_views',(SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY v.id),'[]') FROM (
   SELECT id,owner_id,left(name,4096) name,left(query,4096) query,char_length(query)>4096 query_truncated,shared,layout FROM public.saved_view
   WHERE workspace_id=p_workspace AND public.sierx_lifecycle_visible('view',id,workspace_id) ORDER BY id LIMIT 512) v),
  'views_truncated',(SELECT count(*)>512 FROM public.saved_view WHERE workspace_id=p_workspace AND public.sierx_lifecycle_visible('view',id,workspace_id))
 ) INTO payload_json;
 IF octet_length(payload_json::text)>20971520 THEN RAISE EXCEPTION 'export exceeds size limit'; END IF;
 INSERT INTO public.operator_data_export(user_id,workspace_id,case_ref,expires_at,payload) VALUES(p_user,p_workspace,p_case,expiry,payload_json) RETURNING id INTO new_id;
 INSERT INTO public.operator_data_export_event(export_id,operator_role,case_ref,event) VALUES(new_id,session_user,p_case,'created');
 RETURN QUERY SELECT new_id,expiry;
END $$;


--
-- Name: sierx_current_role(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_current_role() RETURNS text
    LANGUAGE sql STABLE
    SET search_path TO 'pg_catalog'
    AS $$ SELECT NULLIF(current_setting('sierx.role', true), '') $$;


--
-- Name: sierx_current_user_id(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_current_user_id() RETURNS uuid
    LANGUAGE sql STABLE
    SET search_path TO 'pg_catalog'
    AS $$ SELECT NULLIF(current_setting('sierx.user_id', true), '')::uuid $$;


--
-- Name: sierx_current_workspace_id(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_current_workspace_id() RETURNS uuid
    LANGUAGE sql STABLE
    SET search_path TO 'pg_catalog'
    AS $$ SELECT NULLIF(current_setting('sierx.workspace_id', true), '')::uuid $$;


--
-- Name: sierx_erased_account_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_erased_account_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.operator_content_restriction WHERE kind='account' AND target_id=OLD.id AND permanent)
 AND (NEW.email IS DISTINCT FROM OLD.email OR NEW.display_name IS DISTINCT FROM OLD.display_name
 OR NEW.password_hash IS NOT NULL OR NEW.totp_secret IS NOT NULL OR NEW.is_active) THEN
  RAISE EXCEPTION 'anonymized account cannot be reactivated or repopulated';
 END IF;
 RETURN NEW;
END $$;


--
-- Name: sierx_lifecycle_apply(jsonb, bigint, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_lifecycle_apply(a jsonb, p_sequence bigint, p_previous text, p_head text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $_$
DECLARE
 s public.operator_lifecycle_state; k text:=a->>'kind'; w uuid:=NULLIF(a->>'workspace_id','')::uuid;
 t uuid:=NULLIF(a->>'target_id','')::uuid; c uuid:=(a->>'case_ref')::uuid;
 stamp timestamptz:=(a->>'at')::timestamptz;
 ids uuid[]; comments uuid[]; views uuid[]; root ltree;
BEGIN
 PERFORM public.sierx_lifecycle_lock();
 SELECT * INTO s FROM public.operator_lifecycle_state WHERE singleton;
 IF s.instance_id IS DISTINCT FROM (a->>'instance_id')::uuid OR c IS NULL OR stamp IS NULL
 OR p_sequence IS NULL OR p_previous IS NULL OR p_head IS NULL OR p_sequence<>s.sequence+1 OR p_previous<>s.head OR p_head !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'decision journal does not extend this database' USING ERRCODE='55000'; END IF;
 IF w IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.workspace WHERE id=w AND origin_id=(a->>'workspace_origin')::uuid) THEN
  RAISE EXCEPTION 'workspace origin mismatch' USING ERRCODE='55000'; END IF;
 IF k IN ('redact-item','redact-comment','redact-view','redact-history','correct-history','retention','remove-member','anonymize-account')
 AND EXISTS(SELECT 1 FROM public.operator_lifecycle_hold WHERE workspace_id=w AND released_at IS NULL) THEN
  RAISE EXCEPTION 'workspace hold blocks operation' USING ERRCODE='55000'; END IF;
 SELECT coalesce(array_agg(value::uuid),'{}') INTO ids FROM jsonb_array_elements_text(a->'item_ids');
 SELECT coalesce(array_agg(value::uuid),'{}') INTO comments FROM jsonb_array_elements_text(a->'comment_ids');
 SELECT coalesce(array_agg(value::uuid),'{}') INTO views FROM jsonb_array_elements_text(a->'view_ids');
 IF cardinality(ids)>512 OR cardinality(comments)>10000 OR cardinality(views)>512
 OR EXISTS(SELECT 1 FROM public.item WHERE id=ANY(ids) AND workspace_id<>w)
 OR (k<>'anonymize-account' AND (EXISTS(SELECT 1 FROM public.comment c JOIN public.item i ON i.id=c.item_id WHERE c.id=ANY(comments) AND i.workspace_id<>w)
 OR EXISTS(SELECT 1 FROM public.saved_view WHERE id=ANY(views) AND workspace_id<>w))) THEN
  RAISE EXCEPTION 'decision target crosses workspace or exceeds bounds'; END IF;
 CASE k
 WHEN 'hold-create' THEN
  INSERT INTO public.operator_lifecycle_hold(id,workspace_id,case_ref,authority_ref,started_at,review_at)
  VALUES(t,w,c,(a->>'authority_ref')::uuid,stamp,(a->>'review_at')::timestamptz);
 WHEN 'hold-release' THEN
  UPDATE public.operator_lifecycle_hold SET released_at=stamp,release_case=c WHERE id=t AND workspace_id=w AND released_at IS NULL;
 WHEN 'takedown' THEN
  SELECT path INTO root FROM public.item WHERE id=t AND workspace_id=w;
  INSERT INTO public.operator_content_restriction(kind,target_id,workspace_id,root_path,permanent,case_ref,restriction_ref)
  SELECT 'item',i.id,w,CASE WHEN i.id=t THEN root ELSE NULL END,false,c,t FROM public.item i WHERE i.id=ANY(ids)
  ON CONFLICT(kind,target_id,permanent,restriction_ref) DO UPDATE SET root_path=excluded.root_path,case_ref=excluded.case_ref;
 WHEN 'restore-content' THEN
  DELETE FROM public.operator_content_restriction WHERE kind='item' AND workspace_id=w AND restriction_ref=t AND NOT permanent;
 WHEN 'remove-member' THEN
  IF NOT EXISTS(SELECT 1 FROM public.membership m JOIN public.user_account u ON u.id=m.user_id
    WHERE m.workspace_id=w AND m.user_id=(a->>'replacement_id')::uuid AND m.role='admin' AND u.is_active AND m.user_id<>t)
  THEN RAISE EXCEPTION 'active replacement admin required'; END IF;
  PERFORM 1 FROM public.user_account WHERE id=t FOR UPDATE;
  UPDATE public.project SET owner_id=(a->>'replacement_id')::uuid,version=version+1,updated_at=stamp WHERE workspace_id=w AND owner_id=t;
  UPDATE public.item SET assignee_id=NULL,version=version+1,updated_at=stamp WHERE workspace_id=w AND assignee_id=t;
  DELETE FROM public.membership WHERE workspace_id=w AND user_id=t;
  DELETE FROM public.session WHERE user_id=t;
 WHEN 'anonymize-account' THEN
  IF EXISTS(SELECT 1 FROM public.membership WHERE user_id=t AND (workspace_id<>w OR role='admin'))
  OR EXISTS(SELECT 1 FROM public.project WHERE owner_id=t) THEN RAISE EXCEPTION 'membership/ownership prerequisite not satisfied'; END IF;
  IF EXISTS(SELECT 1 FROM public.operator_lifecycle_hold h WHERE h.released_at IS NULL AND (
   EXISTS(SELECT 1 FROM public.comment c JOIN public.item i ON i.id=c.item_id WHERE c.author_id=t AND i.workspace_id=h.workspace_id)
   OR EXISTS(SELECT 1 FROM public.saved_view v WHERE v.owner_id=t AND v.workspace_id=h.workspace_id)
   OR EXISTS(SELECT 1 FROM public.change_event e WHERE e.actor_id=t AND e.workspace_id=h.workspace_id))) THEN
    RAISE EXCEPTION 'account has held records'; END IF;
  UPDATE public.user_account SET is_active=false,email=('erased+'||id::text||'@invalid'),display_name='[redacted]',password_hash=NULL,totp_secret=NULL,theme='system',reduced_motion=NULL WHERE id=t;
  INSERT INTO public.operator_content_restriction(kind,target_id,workspace_id,permanent,case_ref,restriction_ref) VALUES('account',t,w,true,c,t) ON CONFLICT DO NOTHING;
  DELETE FROM public.session WHERE user_id=t;
  UPDATE public.change_event SET old_value='{"redacted":true}',new_value='{"redacted":true}' WHERE actor_id=t;
 WHEN 'redact-history' THEN
  UPDATE public.change_event SET old_value='{"redacted":true}',new_value='{"redacted":true}' WHERE workspace_id=w AND item_id=t;
 WHEN 'correct-history' THEN
  IF (a->>'correction') IS NULL OR char_length(a->>'correction') NOT BETWEEN 1 AND 4096 THEN RAISE EXCEPTION 'bounded correction required'; END IF;
  UPDATE public.change_event SET old_value='{"redacted":true}',new_value=jsonb_build_object('operator_correction',a->>'correction','case_ref',c)
  WHERE workspace_id=w AND item_id=t AND seq=(a->>'event_seq')::bigint;
 WHEN 'redact-item','redact-comment','redact-view','retention','cleanup' THEN NULL;
 ELSE RAISE EXCEPTION 'unsupported action';
 END CASE;
 IF k IN ('redact-item','retention') THEN
  IF k='retention' AND EXISTS(SELECT 1 FROM public.item WHERE id=ANY(ids) AND (deleted_at IS NULL OR deleted_at>=(a->>'cutoff')::timestamptz))
  THEN RAISE EXCEPTION 'retention target no longer qualifies'; END IF;
  UPDATE public.item SET title='[redacted]',body=NULL,fields='{}',assignee_id=NULL,points=NULL,start_date=NULL,due_date=NULL,
   deleted_at=coalesce(deleted_at,stamp),version=version+1,updated_at=stamp WHERE id=ANY(ids);
  INSERT INTO public.operator_content_restriction(kind,target_id,workspace_id,root_path,permanent,case_ref,restriction_ref)
  SELECT 'item',id,workspace_id,CASE WHEN k='redact-item' AND id=t THEN path ELSE NULL END,true,c,coalesce(t,id) FROM public.item WHERE id=ANY(ids)
  ON CONFLICT DO NOTHING;
  UPDATE public.change_event SET old_value='{"redacted":true}',new_value='{"redacted":true}'
   WHERE workspace_id=w AND (item_id=ANY(ids) OR EXISTS(SELECT 1 FROM unnest(ids) i WHERE
   position(i::text IN coalesce(old_value::text,''))>0 OR position(i::text IN coalesce(new_value::text,''))>0));
  -- Derived aggregates are recomputed once for affected ancestors, including
  -- strict ancestors outside the redacted subtree; no stale points/dates remain.
  UPDATE public.item_rollup r SET descendant_count=d.n,done_count=d.done,points_total=d.points,points_done=d.done_points,
   earliest_start=d.starts,latest_due=d.ends,computed_at=stamp
  FROM public.item ancestor CROSS JOIN LATERAL(
   SELECT count(*)::int n,count(*) FILTER(WHERE st.category='done')::int done,sum(child.points) points,
   sum(child.points) FILTER(WHERE st.category='done') done_points,min(child.start_date) starts,max(child.due_date) ends
   FROM public.item child JOIN public.status st ON st.id=child.status_id
   WHERE child.path <@ ancestor.path AND child.id<>ancestor.id AND child.deleted_at IS NULL
  ) d WHERE r.item_id=ancestor.id AND EXISTS(SELECT 1 FROM public.item changed WHERE changed.id=ANY(ids) AND changed.path <@ ancestor.path);
 END IF;
 IF cardinality(comments)>0 THEN
  UPDATE public.comment SET body='[redacted]',deleted_at=coalesce(deleted_at,stamp),edited_at=stamp WHERE id=ANY(comments);
  INSERT INTO public.operator_content_restriction(kind,target_id,workspace_id,permanent,case_ref,restriction_ref)
  SELECT 'comment',cmt.id,i.workspace_id,true,c,cmt.id FROM public.comment cmt JOIN public.item i ON i.id=cmt.item_id WHERE cmt.id=ANY(comments) ON CONFLICT DO NOTHING;
  -- Comment bodies occur in item events. Wipe the affected items' values;
  -- the operator action is an explicit metadata-only historical tombstone.
  UPDATE public.change_event SET old_value='{"redacted":true}',new_value='{"redacted":true}'
  WHERE item_id IN (SELECT item_id FROM public.comment WHERE id=ANY(comments));
 END IF;
 IF cardinality(views)>0 THEN
  UPDATE public.saved_view SET name='[redacted]',query='',shared=false WHERE id=ANY(views);
  INSERT INTO public.operator_content_restriction(kind,target_id,workspace_id,permanent,case_ref,restriction_ref)
  SELECT 'view',id,workspace_id,true,c,id FROM public.saved_view WHERE id=ANY(views) ON CONFLICT DO NOTHING;
 END IF;
 -- Revoke earlier artifacts whenever access/content changes. Held copies remain
 -- restricted evidence; every other server copy is erased on revocation.
 IF k IN ('takedown','redact-item','redact-comment','redact-view','redact-history','correct-history','remove-member','anonymize-account','retention') THEN
  UPDATE public.operator_data_export SET revoked_at=stamp WHERE payload IS NOT NULL AND revoked_at IS NULL;
 END IF;
 UPDATE public.operator_data_export e SET payload=NULL WHERE payload IS NOT NULL
 AND (revoked_at IS NOT NULL OR expires_at<=stamp)
 AND NOT EXISTS(SELECT 1 FROM public.operator_lifecycle_hold h WHERE h.released_at IS NULL);
 IF k='cleanup' THEN
  DELETE FROM public.session sess WHERE expires_at<=stamp AND NOT EXISTS(
   SELECT 1 FROM public.membership m JOIN public.operator_lifecycle_hold h ON h.workspace_id=m.workspace_id
   WHERE m.user_id=sess.user_id AND h.released_at IS NULL);
 END IF;
 INSERT INTO public.operator_lifecycle_event(operator_role,case_ref,outcome,sequence,decision)
 VALUES(session_user,c,'applied',p_sequence,a-'correction');
 UPDATE public.operator_lifecycle_state SET sequence=p_sequence,head=p_head WHERE singleton;
END $_$;


--
-- Name: sierx_lifecycle_blocked(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_lifecycle_blocked(a jsonb) RETURNS void
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
 INSERT INTO public.operator_lifecycle_event(operator_role,case_ref,outcome,decision)
 VALUES(session_user,(a->>'case_ref')::uuid,'blocked',a-'correction') $$;


--
-- Name: sierx_lifecycle_event_visible(uuid, uuid, jsonb, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_lifecycle_event_visible(p_workspace uuid, p_item uuid, p_old jsonb, p_new jsonb) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$ SELECT (p_item IS NULL OR EXISTS(
 SELECT 1 FROM public.item i WHERE i.id=p_item AND i.workspace_id=p_workspace
 AND public.sierx_lifecycle_visible('item',i.id,i.workspace_id,i.path)))
 AND NOT EXISTS(
 SELECT 1 FROM public.operator_content_restriction r
 WHERE r.workspace_id=p_workspace AND
 (position(r.target_id::text IN coalesce(p_old::text,''))>0 OR position(r.target_id::text IN coalesce(p_new::text,''))>0)
 ) $$;


--
-- Name: sierx_lifecycle_has_hold(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_lifecycle_has_hold() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$ SELECT EXISTS(SELECT 1 FROM public.operator_lifecycle_hold WHERE released_at IS NULL) $$;


--
-- Name: sierx_lifecycle_lock(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_lifecycle_lock() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(761492314);
 LOCK TABLE public.workspace,public.user_account,public.membership,public.project,
 public.item,public.comment,public.saved_view,public.change_event,public.session,
 public.operator_data_export IN SHARE ROW EXCLUSIVE MODE;
 PERFORM 1 FROM public.operator_lifecycle_state WHERE singleton FOR UPDATE;
END $$;


--
-- Name: sierx_lifecycle_plan(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_lifecycle_plan(a jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
 k text:=a->>'kind'; w uuid:=NULLIF(a->>'workspace_id','')::uuid;
 t uuid:=NULLIF(a->>'target_id','')::uuid; c uuid:=(a->>'case_ref')::uuid;
 replacement uuid:=NULLIF(a->>'replacement_id','')::uuid;
 stamp timestamptz:=(a->>'at')::timestamptz;
 origin uuid; inst uuid; ids jsonb:='[]'; comments jsonb:='[]'; views jsonb:='[]'; root ltree;
BEGIN
 IF c IS NULL OR stamp IS NULL OR stamp>now()+interval '1 minute' OR stamp<now()-interval '1 day' THEN
  RAISE EXCEPTION 'case UUID and current decision timestamp required' USING ERRCODE='22023';
 END IF;
 SELECT instance_id INTO inst FROM public.operator_lifecycle_state WHERE singleton;
 IF w IS NOT NULL THEN
  SELECT origin_id INTO origin FROM public.workspace WHERE id=w;
  IF NOT FOUND THEN RAISE EXCEPTION 'workspace not found' USING ERRCODE='P0002'; END IF;
 ELSIF k<>'cleanup' THEN RAISE EXCEPTION 'workspace required' USING ERRCODE='22023'; END IF;
 IF k IN ('redact-item','redact-comment','redact-view','redact-history','correct-history','retention','remove-member','anonymize-account')
 AND EXISTS(SELECT 1 FROM public.operator_lifecycle_hold WHERE workspace_id=w AND released_at IS NULL) THEN
  RAISE EXCEPTION 'workspace hold blocks the operation' USING ERRCODE='55000';
 END IF;
 CASE k
 WHEN 'hold-create' THEN
  IF t IS NULL OR (a->>'authority_ref')::uuid IS NULL OR (a->>'review_at') IS NULL OR (a->>'review_at')::timestamptz<=stamp THEN
   RAISE EXCEPTION 'hold ID, authority reference and future review required' USING ERRCODE='22023'; END IF;
  IF EXISTS(SELECT 1 FROM public.operator_lifecycle_hold WHERE id=t) THEN RAISE EXCEPTION 'hold ID already exists'; END IF;
 WHEN 'hold-release' THEN
  IF NOT EXISTS(SELECT 1 FROM public.operator_lifecycle_hold WHERE id=t AND workspace_id=w AND released_at IS NULL)
  THEN RAISE EXCEPTION 'active hold not found' USING ERRCODE='P0002'; END IF;
 WHEN 'takedown','restore-content','redact-item' THEN
  SELECT path INTO root FROM public.item WHERE id=t AND workspace_id=w;
  IF NOT FOUND THEN RAISE EXCEPTION 'item not found in workspace' USING ERRCODE='P0002'; END IF;
  SELECT coalesce(jsonb_agg(id ORDER BY id),'[]') INTO ids FROM public.item WHERE workspace_id=w AND path <@ root;
  IF k='redact-item' THEN
   SELECT coalesce(jsonb_agg(c.id ORDER BY c.id),'[]') INTO comments FROM public.comment c
   WHERE c.item_id IN (SELECT value::uuid FROM jsonb_array_elements_text(ids));
  END IF;
 WHEN 'redact-comment' THEN
  IF NOT EXISTS(SELECT 1 FROM public.comment c JOIN public.item i ON i.id=c.item_id WHERE c.id=t AND i.workspace_id=w)
  THEN RAISE EXCEPTION 'comment not found in workspace' USING ERRCODE='P0002'; END IF;
  comments:=jsonb_build_array(t);
 WHEN 'redact-view' THEN
  IF NOT EXISTS(SELECT 1 FROM public.saved_view WHERE id=t AND workspace_id=w)
  THEN RAISE EXCEPTION 'view not found in workspace' USING ERRCODE='P0002'; END IF;
  views:=jsonb_build_array(t);
 WHEN 'redact-history' THEN
  IF NOT EXISTS(SELECT 1 FROM public.item WHERE id=t AND workspace_id=w)
  THEN RAISE EXCEPTION 'item not found in workspace' USING ERRCODE='P0002'; END IF;
 WHEN 'correct-history' THEN
  IF (a->>'correction') IS NULL OR char_length(a->>'correction') NOT BETWEEN 1 AND 4096 OR NOT EXISTS(
   SELECT 1 FROM public.change_event WHERE workspace_id=w AND seq=(a->>'event_seq')::bigint AND item_id=t)
  THEN RAISE EXCEPTION 'event and bounded correction required' USING ERRCODE='22023'; END IF;
 WHEN 'remove-member' THEN
  IF replacement IS NULL OR replacement=t OR NOT EXISTS(SELECT 1 FROM public.membership m JOIN public.user_account u ON u.id=m.user_id
   WHERE m.workspace_id=w AND m.user_id=replacement AND m.role='admin' AND u.is_active)
  THEN RAISE EXCEPTION 'different active workspace admin replacement required' USING ERRCODE='22023'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.membership WHERE workspace_id=w AND user_id=t)
  THEN RAISE EXCEPTION 'membership not found' USING ERRCODE='P0002'; END IF;
 WHEN 'anonymize-account' THEN
  IF NOT EXISTS(SELECT 1 FROM public.user_account WHERE id=t) THEN RAISE EXCEPTION 'account not found' USING ERRCODE='P0002'; END IF;
  -- Preserve an active administrator and refuse cross-workspace anonymization.
  IF EXISTS(SELECT 1 FROM public.membership WHERE user_id=t AND workspace_id<>w)
  OR EXISTS(SELECT 1 FROM public.project WHERE owner_id=t)
  OR EXISTS(SELECT 1 FROM public.membership WHERE user_id=t AND workspace_id=w AND role='admin') THEN
   RAISE EXCEPTION 'remove memberships and reassign ownership before anonymization' USING ERRCODE='55000'; END IF;
  IF EXISTS(SELECT 1 FROM public.operator_lifecycle_hold h WHERE h.released_at IS NULL AND (
    EXISTS(SELECT 1 FROM public.comment c JOIN public.item i ON i.id=c.item_id WHERE c.author_id=t AND i.workspace_id=h.workspace_id)
    OR EXISTS(SELECT 1 FROM public.saved_view v WHERE v.owner_id=t AND v.workspace_id=h.workspace_id)
    OR EXISTS(SELECT 1 FROM public.change_event e WHERE e.actor_id=t AND e.workspace_id=h.workspace_id))) THEN
   RAISE EXCEPTION 'account has records in a held workspace' USING ERRCODE='55000'; END IF;
  SELECT coalesce(jsonb_agg(id ORDER BY id),'[]') INTO comments FROM public.comment WHERE author_id=t;
  SELECT coalesce(jsonb_agg(id ORDER BY id),'[]') INTO views FROM public.saved_view WHERE owner_id=t;
 WHEN 'retention' THEN
  IF (a->>'cutoff')::timestamptz IS NULL OR (a->>'cutoff')::timestamptz>=stamp THEN RAISE EXCEPTION 'explicit past cutoff required' USING ERRCODE='22023'; END IF;
  SELECT coalesce(jsonb_agg(id ORDER BY id),'[]') INTO ids FROM (
   SELECT id FROM public.item WHERE workspace_id=w AND deleted_at<(a->>'cutoff')::timestamptz
   AND NOT EXISTS(SELECT 1 FROM public.operator_content_restriction r WHERE r.kind='item' AND r.target_id=item.id AND r.permanent)
   ORDER BY id LIMIT 512) batch;
  SELECT coalesce(jsonb_agg(id ORDER BY id),'[]') INTO comments FROM (
   SELECT c.id FROM public.comment c JOIN public.item i ON i.id=c.item_id
   WHERE i.workspace_id=w AND c.deleted_at<(a->>'cutoff')::timestamptz
   AND NOT EXISTS(SELECT 1 FROM public.operator_content_restriction r WHERE r.kind='comment' AND r.target_id=c.id AND r.permanent)
   ORDER BY c.id LIMIT 512) batch;
 WHEN 'cleanup' THEN NULL;
 ELSE RAISE EXCEPTION 'unsupported lifecycle action' USING ERRCODE='22023';
 END CASE;
 IF jsonb_array_length(ids)>512 OR jsonb_array_length(comments)>10000 OR jsonb_array_length(views)>512 THEN
  RAISE EXCEPTION 'case exceeds 512 items/views or 10000 comments; split into smaller targets' USING ERRCODE='54000'; END IF;
 RETURN a || jsonb_build_object('instance_id',inst,'workspace_origin',origin,'item_ids',ids,'comment_ids',comments,'view_ids',views);
END $$;


--
-- Name: sierx_lifecycle_status(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_lifecycle_status() RETURNS TABLE(instance_id uuid, sequence bigint, head text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$ SELECT instance_id,sequence,head FROM public.operator_lifecycle_state WHERE singleton $$;


--
-- Name: sierx_lifecycle_visible(text, uuid, uuid, public.ltree); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_lifecycle_visible(p_kind text, p_id uuid, p_workspace uuid, p_path public.ltree DEFAULT NULL::public.ltree) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$ SELECT NOT EXISTS(
 SELECT 1 FROM public.operator_content_restriction r
 WHERE r.kind=p_kind AND (r.target_id=p_id OR
  (p_kind='item' AND r.workspace_id=p_workspace AND p_path <@ r.root_path))
) $$;


--
-- Name: sierx_project_rank_scope(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_project_rank_scope(p_project uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
 SELECT EXISTS(SELECT 1 FROM public.project p WHERE p.id=p_project AND (
  (coalesce(current_setting('role',true),'none') IN ('none','') AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=session_user AND rolsuper))
  OR (p.workspace_id=public.sierx_current_workspace_id() AND EXISTS(
   SELECT 1 FROM public.membership m JOIN public.user_account u ON u.id=m.user_id
   WHERE m.workspace_id=p.workspace_id AND m.user_id=public.sierx_current_user_id() AND u.is_active))))
$$;


--
-- Name: sierx_project_workspace_id(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_project_workspace_id(p_project_id uuid) RETURNS uuid
    LANGUAGE sql STABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$ SELECT workspace_id FROM public.project WHERE id = p_project_id $$;


--
-- Name: sierx_read_data_export(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_read_data_export(p_export_id uuid, p_case_ref uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  result jsonb;
BEGIN
  SELECT e.payload INTO result
    FROM public.operator_data_export e
   WHERE e.id=p_export_id AND e.case_ref=p_case_ref AND e.expires_at>now() AND e.revoked_at IS NULL
   FOR UPDATE;
  IF NOT FOUND OR result IS NULL THEN
    RAISE EXCEPTION 'export not found or expired' USING ERRCODE = 'P0002';
  END IF;
  INSERT INTO public.operator_data_export_event(export_id,operator_role,case_ref,event)
  VALUES (p_export_id,session_user,p_case_ref,'downloaded');
  RETURN result;
END
$$;


--
-- Name: sierx_restricted_subtree_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_restricted_subtree_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
 IF NEW.path IS DISTINCT FROM OLD.path AND EXISTS(
  SELECT 1 FROM public.item i JOIN public.operator_content_restriction r ON r.kind='item' AND r.target_id=i.id
  WHERE i.workspace_id=OLD.workspace_id AND i.path <@ OLD.path) THEN
  RAISE EXCEPTION 'restricted descendants prevent hierarchy movement' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;


--
-- Name: sierx_set_account_active(uuid, boolean, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_set_account_active(p_user_id uuid, p_active boolean, p_case_ref uuid) RETURNS TABLE(account_id uuid, active_before boolean, active_after boolean, sessions_revoked integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
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


--
-- Name: sierx_set_project_ranks(uuid, text[], text[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sierx_set_project_ranks(p_project uuid, p_old text[], p_new text[]) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $_$
BEGIN
 IF NOT public.sierx_project_rank_scope(p_project) THEN RAISE EXCEPTION 'project rank access denied' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.project WHERE id=p_project FOR UPDATE;
 IF p_old IS NULL OR p_new IS NULL OR cardinality(p_old)<>cardinality(p_new)
 OR cardinality(p_old)<>(SELECT count(*) FROM public.item WHERE project_id=p_project)
 OR cardinality(p_old)<>(SELECT count(DISTINCT x) FROM unnest(p_old) x)
 OR cardinality(p_new)<>(SELECT count(DISTINCT x) FROM unnest(p_new) x)
 OR EXISTS(SELECT 1 FROM unnest(p_new) x WHERE x IS NULL OR x !~ '^[0-9a-z]{1,40}$')
 OR EXISTS(SELECT 1 FROM public.item WHERE project_id=p_project AND NOT(rank=ANY(p_old))) THEN
  RAISE EXCEPTION 'complete unique bounded project rank map required'; END IF;
 SET CONSTRAINTS item_project_rank_uniq DEFERRED;
 UPDATE public.item i SET rank=m.new,version=i.version+1,updated_at=now()
 FROM unnest(p_old,p_new) AS m(old,new) WHERE i.project_id=p_project AND i.rank=m.old;
 SET CONSTRAINTS item_project_rank_uniq IMMEDIATE;
END $_$;


--
-- Name: status_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.status_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.key      IS DISTINCT FROM OLD.key
  OR NEW.name     IS DISTINCT FROM OLD.name
  OR NEW.category IS DISTINCT FROM OLD.category THEN
    RAISE EXCEPTION 'status % is immutable: key, name, category cannot change (SPEC §5.6); insert a new row and a new config version',
      OLD.id USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;


--
-- Name: workspace_create_seq_counter(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.workspace_create_seq_counter() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO seq_counter (workspace_id) VALUES (NEW.id);
  RETURN NEW;
END $$;


SET default_tablespace = '';

--
-- Name: change_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.change_event (
    workspace_id uuid NOT NULL,
    seq bigint NOT NULL,
    at timestamp with time zone DEFAULT now() NOT NULL,
    item_id uuid,
    actor_id uuid,
    kind text NOT NULL,
    field text,
    old_value jsonb,
    new_value jsonb
)
PARTITION BY RANGE (at);

ALTER TABLE ONLY public.change_event FORCE ROW LEVEL SECURITY;


SET default_table_access_method = heap;

--
-- Name: change_event_2026_09; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.change_event_2026_09 (
    workspace_id uuid CONSTRAINT change_event_workspace_id_not_null NOT NULL,
    seq bigint CONSTRAINT change_event_seq_not_null NOT NULL,
    at timestamp with time zone DEFAULT now() CONSTRAINT change_event_at_not_null NOT NULL,
    item_id uuid,
    actor_id uuid,
    kind text CONSTRAINT change_event_kind_not_null NOT NULL,
    field text,
    old_value jsonb,
    new_value jsonb
);

ALTER TABLE ONLY public.change_event_2026_09 FORCE ROW LEVEL SECURITY;


--
-- Name: change_event_2026_10; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.change_event_2026_10 (
    workspace_id uuid CONSTRAINT change_event_workspace_id_not_null NOT NULL,
    seq bigint CONSTRAINT change_event_seq_not_null NOT NULL,
    at timestamp with time zone DEFAULT now() CONSTRAINT change_event_at_not_null NOT NULL,
    item_id uuid,
    actor_id uuid,
    kind text CONSTRAINT change_event_kind_not_null NOT NULL,
    field text,
    old_value jsonb,
    new_value jsonb
);

ALTER TABLE ONLY public.change_event_2026_10 FORCE ROW LEVEL SECURITY;


--
-- Name: change_event_2026_11; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.change_event_2026_11 (
    workspace_id uuid CONSTRAINT change_event_workspace_id_not_null NOT NULL,
    seq bigint CONSTRAINT change_event_seq_not_null NOT NULL,
    at timestamp with time zone DEFAULT now() CONSTRAINT change_event_at_not_null NOT NULL,
    item_id uuid,
    actor_id uuid,
    kind text CONSTRAINT change_event_kind_not_null NOT NULL,
    field text,
    old_value jsonb,
    new_value jsonb
);

ALTER TABLE ONLY public.change_event_2026_11 FORCE ROW LEVEL SECURITY;


--
-- Name: comment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.comment (
    id uuid DEFAULT uuidv7() NOT NULL,
    item_id uuid NOT NULL,
    author_id uuid NOT NULL,
    body text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    edited_at timestamp with time zone,
    deleted_at timestamp with time zone
);

ALTER TABLE ONLY public.comment FORCE ROW LEVEL SECURITY;


--
-- Name: config_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_status (
    project_id uuid NOT NULL,
    version integer NOT NULL,
    status_id uuid NOT NULL,
    display_order integer NOT NULL
);

ALTER TABLE ONLY public.config_status FORCE ROW LEVEL SECURITY;


--
-- Name: config_transition; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_transition (
    project_id uuid NOT NULL,
    version integer NOT NULL,
    from_status_id uuid NOT NULL,
    to_status_id uuid NOT NULL,
    requires jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE ONLY public.config_transition FORCE ROW LEVEL SECURITY;


--
-- Name: config_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_type (
    project_id uuid NOT NULL,
    version integer NOT NULL,
    item_type_id uuid NOT NULL,
    initial_status_id uuid NOT NULL
);

ALTER TABLE ONLY public.config_type FORCE ROW LEVEL SECURITY;


--
-- Name: field_def; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.field_def (
    id uuid DEFAULT uuidv7() NOT NULL,
    project_id uuid NOT NULL,
    key text NOT NULL,
    name text NOT NULL,
    data_type text NOT NULL,
    options jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT field_def_data_type_check CHECK ((data_type = ANY (ARRAY['text'::text, 'number'::text, 'date'::text, 'select'::text, 'multiselect'::text, 'user'::text, 'url'::text, 'bool'::text])))
);

ALTER TABLE ONLY public.field_def FORCE ROW LEVEL SECURITY;


--
-- Name: item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item (
    id uuid DEFAULT uuidv7() NOT NULL,
    workspace_id uuid NOT NULL,
    project_id uuid NOT NULL,
    key text NOT NULL,
    item_type_id uuid NOT NULL,
    status_id uuid NOT NULL,
    config_version integer NOT NULL,
    parent_id uuid,
    path public.ltree NOT NULL,
    title text NOT NULL,
    body text,
    assignee_id uuid,
    points numeric(6,2),
    start_date date,
    due_date date,
    rank text NOT NULL,
    fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    change_seq bigint NOT NULL,
    origin_id uuid NOT NULL,
    origin_seq bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, ((title || ' '::text) || COALESCE(body, ''::text)))) STORED,
    CONSTRAINT item_title_check CHECK (((length(title) >= 1) AND (length(title) <= 500)))
);

ALTER TABLE ONLY public.item FORCE ROW LEVEL SECURITY;


--
-- Name: item_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_link (
    id uuid DEFAULT uuidv7() NOT NULL,
    from_item_id uuid NOT NULL,
    to_item_id uuid NOT NULL,
    kind text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid,
    CONSTRAINT item_link_check CHECK ((from_item_id <> to_item_id)),
    CONSTRAINT item_link_kind_check CHECK ((kind = ANY (ARRAY['blocks'::text, 'duplicates'::text, 'relates'::text, 'implements'::text, 'discovered_from'::text])))
);

ALTER TABLE ONLY public.item_link FORCE ROW LEVEL SECURITY;


--
-- Name: item_rollup; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_rollup (
    item_id uuid NOT NULL,
    descendant_count integer DEFAULT 0 NOT NULL,
    done_count integer DEFAULT 0 NOT NULL,
    points_total numeric(10,2),
    points_done numeric(10,2),
    earliest_start date,
    latest_due date,
    computed_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.item_rollup FORCE ROW LEVEL SECURITY;


--
-- Name: item_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_type (
    id uuid DEFAULT uuidv7() NOT NULL,
    project_id uuid NOT NULL,
    key text NOT NULL,
    name text NOT NULL,
    level integer NOT NULL,
    is_idea boolean DEFAULT false NOT NULL
);

ALTER TABLE ONLY public.item_type FORCE ROW LEVEL SECURITY;


--
-- Name: membership; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.membership (
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role text NOT NULL,
    CONSTRAINT membership_role_check CHECK ((role = ANY (ARRAY['member'::text, 'admin'::text])))
);

ALTER TABLE ONLY public.membership FORCE ROW LEVEL SECURITY;


--
-- Name: operator_account_action; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_account_action (
    id uuid DEFAULT uuidv7() NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    operator_role text NOT NULL,
    case_ref uuid NOT NULL,
    user_id uuid NOT NULL,
    active_before boolean NOT NULL,
    active_after boolean NOT NULL,
    sessions_revoked integer NOT NULL,
    CONSTRAINT operator_account_action_sessions_revoked_check CHECK ((sessions_revoked >= 0))
);

ALTER TABLE ONLY public.operator_account_action FORCE ROW LEVEL SECURITY;


--
-- Name: operator_content_restriction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_content_restriction (
    kind text NOT NULL,
    target_id uuid NOT NULL,
    workspace_id uuid,
    root_path public.ltree,
    permanent boolean NOT NULL,
    case_ref uuid NOT NULL,
    restriction_ref uuid NOT NULL,
    CONSTRAINT operator_content_restriction_kind_check CHECK ((kind = ANY (ARRAY['item'::text, 'comment'::text, 'view'::text, 'account'::text])))
);

ALTER TABLE ONLY public.operator_content_restriction FORCE ROW LEVEL SECURITY;


--
-- Name: operator_data_export; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_data_export (
    id uuid DEFAULT uuidv7() NOT NULL,
    user_id uuid NOT NULL,
    case_ref uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    payload jsonb,
    workspace_id uuid,
    revoked_at timestamp with time zone,
    CONSTRAINT operator_data_export_check CHECK ((expires_at > created_at))
);

ALTER TABLE ONLY public.operator_data_export FORCE ROW LEVEL SECURITY;


--
-- Name: operator_data_export_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_data_export_event (
    id uuid DEFAULT uuidv7() NOT NULL,
    export_id uuid NOT NULL,
    operator_role text NOT NULL,
    case_ref uuid NOT NULL,
    event text NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT operator_data_export_event_event_check CHECK ((event = ANY (ARRAY['created'::text, 'downloaded'::text, 'expired'::text])))
);

ALTER TABLE ONLY public.operator_data_export_event FORCE ROW LEVEL SECURITY;


--
-- Name: operator_lifecycle_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_lifecycle_event (
    id uuid DEFAULT uuidv7() NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    operator_role text NOT NULL,
    case_ref uuid NOT NULL,
    outcome text NOT NULL,
    sequence bigint,
    decision jsonb NOT NULL,
    CONSTRAINT operator_lifecycle_event_outcome_check CHECK ((outcome = ANY (ARRAY['applied'::text, 'blocked'::text])))
);

ALTER TABLE ONLY public.operator_lifecycle_event FORCE ROW LEVEL SECURITY;


--
-- Name: operator_lifecycle_hold; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_lifecycle_hold (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    case_ref uuid NOT NULL,
    authority_ref uuid NOT NULL,
    started_at timestamp with time zone NOT NULL,
    review_at timestamp with time zone NOT NULL,
    released_at timestamp with time zone,
    release_case uuid,
    CONSTRAINT operator_lifecycle_hold_check CHECK ((review_at > started_at))
);

ALTER TABLE ONLY public.operator_lifecycle_hold FORCE ROW LEVEL SECURITY;


--
-- Name: operator_lifecycle_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_lifecycle_state (
    singleton boolean DEFAULT true NOT NULL,
    instance_id uuid DEFAULT uuidv7() NOT NULL,
    sequence bigint DEFAULT 0 NOT NULL,
    head text DEFAULT ''::text NOT NULL,
    CONSTRAINT operator_lifecycle_state_sequence_check CHECK ((sequence >= 0)),
    CONSTRAINT operator_lifecycle_state_singleton_check CHECK (singleton)
);

ALTER TABLE ONLY public.operator_lifecycle_state FORCE ROW LEVEL SECURITY;


--
-- Name: project; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project (
    id uuid DEFAULT uuidv7() NOT NULL,
    workspace_id uuid NOT NULL,
    key_prefix text NOT NULL,
    name text NOT NULL,
    kind text NOT NULL,
    next_key_num integer DEFAULT 1 NOT NULL,
    archived_at timestamp with time zone,
    owner_id uuid,
    version integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT project_key_prefix_check CHECK ((key_prefix ~ '^[A-Z][A-Z0-9]{1,9}$'::text)),
    CONSTRAINT project_kind_check CHECK ((kind = ANY (ARRAY['delivery'::text, 'discovery'::text, 'portfolio'::text]))),
    CONSTRAINT project_version_check CHECK ((version > 0))
);

ALTER TABLE ONLY public.project FORCE ROW LEVEL SECURITY;


--
-- Name: project_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_config (
    project_id uuid NOT NULL,
    version integer NOT NULL,
    source_yaml text,
    applied_at timestamp with time zone DEFAULT now() NOT NULL,
    applied_by uuid
);

ALTER TABLE ONLY public.project_config FORCE ROW LEVEL SECURITY;


--
-- Name: saved_view; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.saved_view (
    id uuid DEFAULT uuidv7() NOT NULL,
    workspace_id uuid NOT NULL,
    owner_id uuid,
    name text NOT NULL,
    query text NOT NULL,
    layout text NOT NULL,
    shared boolean DEFAULT false NOT NULL,
    CONSTRAINT saved_view_layout_check CHECK ((layout = ANY (ARRAY['list'::text, 'board'::text, 'timeline'::text, 'grid'::text])))
);

ALTER TABLE ONLY public.saved_view FORCE ROW LEVEL SECURITY;


--
-- Name: seq_counter; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.seq_counter (
    workspace_id uuid NOT NULL,
    value bigint DEFAULT 0 NOT NULL
);

ALTER TABLE ONLY public.seq_counter FORCE ROW LEVEL SECURITY;


--
-- Name: session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session (
    id_hash bytea NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone
);

ALTER TABLE ONLY public.session FORCE ROW LEVEL SECURITY;


--
-- Name: user_account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_account (
    id uuid DEFAULT uuidv7() NOT NULL,
    email public.citext NOT NULL,
    display_name text NOT NULL,
    password_hash text,
    totp_secret bytea,
    theme text DEFAULT 'system'::text NOT NULL,
    reduced_motion boolean,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.user_account FORCE ROW LEVEL SECURITY;


--
-- Name: sierx_project_reserved_ranks; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.sierx_project_reserved_ranks WITH (security_barrier='true') AS
 SELECT
        CASE
            WHEN (NOT (EXISTS ( SELECT 1
               FROM public.operator_content_restriction r
              WHERE ((r.kind = 'item'::text) AND ((r.target_id = i.id) OR ((r.workspace_id = i.workspace_id) AND (i.path OPERATOR(public.<@) r.root_path))))))) THEN id
            ELSE NULL::uuid
        END AS id,
    rank,
    project_id
   FROM public.item i
  WHERE (((COALESCE(current_setting('role'::text, true), 'none'::text) = ANY (ARRAY['none'::text, ''::text])) AND ( SELECT pg_roles.rolsuper
           FROM pg_roles
          WHERE (pg_roles.rolname = SESSION_USER))) OR ((workspace_id = public.sierx_current_workspace_id()) AND (EXISTS ( SELECT 1
           FROM (public.membership m
             JOIN public.user_account u ON ((u.id = m.user_id)))
          WHERE ((m.workspace_id = public.sierx_current_workspace_id()) AND (m.user_id = public.sierx_current_user_id()) AND u.is_active)))));


--
-- Name: sprint; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sprint (
    id uuid DEFAULT uuidv7() NOT NULL,
    project_id uuid NOT NULL,
    name text NOT NULL,
    goal text,
    starts_on date NOT NULL,
    ends_on date NOT NULL,
    state text NOT NULL,
    CONSTRAINT sprint_check CHECK ((ends_on > starts_on)),
    CONSTRAINT sprint_state_check CHECK ((state = ANY (ARRAY['planned'::text, 'active'::text, 'closed'::text])))
);

ALTER TABLE ONLY public.sprint FORCE ROW LEVEL SECURITY;


--
-- Name: sprint_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sprint_item (
    sprint_id uuid NOT NULL,
    item_id uuid NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    removed_at timestamp with time zone
);

ALTER TABLE ONLY public.sprint_item FORCE ROW LEVEL SECURITY;


--
-- Name: status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.status (
    id uuid DEFAULT uuidv7() NOT NULL,
    project_id uuid NOT NULL,
    key text NOT NULL,
    name text NOT NULL,
    category text NOT NULL,
    CONSTRAINT status_category_check CHECK ((category = ANY (ARRAY['open'::text, 'active'::text, 'done'::text, 'cancelled'::text])))
);

ALTER TABLE ONLY public.status FORCE ROW LEVEL SECURITY;


--
-- Name: workspace; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace (
    id uuid DEFAULT uuidv7() NOT NULL,
    slug text NOT NULL,
    name text NOT NULL,
    origin_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.workspace FORCE ROW LEVEL SECURITY;


--
-- Name: change_event_2026_09; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event ATTACH PARTITION public.change_event_2026_09 FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');


--
-- Name: change_event_2026_10; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event ATTACH PARTITION public.change_event_2026_10 FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');


--
-- Name: change_event_2026_11; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event ATTACH PARTITION public.change_event_2026_11 FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');


--
-- Name: change_event change_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event
    ADD CONSTRAINT change_event_pkey PRIMARY KEY (workspace_id, seq, at);


--
-- Name: change_event_2026_09 change_event_2026_09_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event_2026_09
    ADD CONSTRAINT change_event_2026_09_pkey PRIMARY KEY (workspace_id, seq, at);


--
-- Name: change_event_2026_10 change_event_2026_10_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event_2026_10
    ADD CONSTRAINT change_event_2026_10_pkey PRIMARY KEY (workspace_id, seq, at);


--
-- Name: change_event_2026_11 change_event_2026_11_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event_2026_11
    ADD CONSTRAINT change_event_2026_11_pkey PRIMARY KEY (workspace_id, seq, at);


--
-- Name: comment comment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_pkey PRIMARY KEY (id);


--
-- Name: config_status config_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_status
    ADD CONSTRAINT config_status_pkey PRIMARY KEY (project_id, version, status_id);


--
-- Name: config_transition config_transition_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_transition
    ADD CONSTRAINT config_transition_pkey PRIMARY KEY (project_id, version, from_status_id, to_status_id);


--
-- Name: config_type config_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_type
    ADD CONSTRAINT config_type_pkey PRIMARY KEY (project_id, version, item_type_id);


--
-- Name: field_def field_def_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_def
    ADD CONSTRAINT field_def_pkey PRIMARY KEY (id);


--
-- Name: field_def field_def_project_id_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_def
    ADD CONSTRAINT field_def_project_id_key_key UNIQUE (project_id, key);


--
-- Name: item_link item_link_from_item_id_to_item_id_kind_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_from_item_id_to_item_id_kind_key UNIQUE (from_item_id, to_item_id, kind);


--
-- Name: item_link item_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_pkey PRIMARY KEY (id);


--
-- Name: item item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_pkey PRIMARY KEY (id);


--
-- Name: item item_project_rank_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_project_rank_uniq UNIQUE (project_id, rank) DEFERRABLE;


--
-- Name: item_rollup item_rollup_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_rollup
    ADD CONSTRAINT item_rollup_pkey PRIMARY KEY (item_id);


--
-- Name: item_type item_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_type
    ADD CONSTRAINT item_type_pkey PRIMARY KEY (id);


--
-- Name: item_type item_type_project_id_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_type
    ADD CONSTRAINT item_type_project_id_uniq UNIQUE (project_id, id);


--
-- Name: item item_workspace_id_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_workspace_id_key_key UNIQUE (workspace_id, key);


--
-- Name: membership membership_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_pkey PRIMARY KEY (workspace_id, user_id);


--
-- Name: operator_account_action operator_account_action_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_account_action
    ADD CONSTRAINT operator_account_action_pkey PRIMARY KEY (id);


--
-- Name: operator_content_restriction operator_content_restriction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_content_restriction
    ADD CONSTRAINT operator_content_restriction_pkey PRIMARY KEY (kind, target_id, permanent, restriction_ref);


--
-- Name: operator_data_export_event operator_data_export_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_data_export_event
    ADD CONSTRAINT operator_data_export_event_pkey PRIMARY KEY (id);


--
-- Name: operator_data_export operator_data_export_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_data_export
    ADD CONSTRAINT operator_data_export_pkey PRIMARY KEY (id);


--
-- Name: operator_lifecycle_event operator_lifecycle_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_lifecycle_event
    ADD CONSTRAINT operator_lifecycle_event_pkey PRIMARY KEY (id);


--
-- Name: operator_lifecycle_hold operator_lifecycle_hold_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_lifecycle_hold
    ADD CONSTRAINT operator_lifecycle_hold_pkey PRIMARY KEY (id);


--
-- Name: operator_lifecycle_state operator_lifecycle_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_lifecycle_state
    ADD CONSTRAINT operator_lifecycle_state_pkey PRIMARY KEY (singleton);


--
-- Name: project_config project_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_config
    ADD CONSTRAINT project_config_pkey PRIMARY KEY (project_id, version);


--
-- Name: project project_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_pkey PRIMARY KEY (id);


--
-- Name: project project_workspace_id_key_prefix_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_workspace_id_key_prefix_key UNIQUE (workspace_id, key_prefix);


--
-- Name: saved_view saved_view_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_pkey PRIMARY KEY (id);


--
-- Name: seq_counter seq_counter_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seq_counter
    ADD CONSTRAINT seq_counter_pkey PRIMARY KEY (workspace_id);


--
-- Name: session session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session
    ADD CONSTRAINT session_pkey PRIMARY KEY (id_hash);


--
-- Name: sprint_item sprint_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint_item
    ADD CONSTRAINT sprint_item_pkey PRIMARY KEY (sprint_id, item_id);


--
-- Name: sprint sprint_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint
    ADD CONSTRAINT sprint_pkey PRIMARY KEY (id);


--
-- Name: status status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status
    ADD CONSTRAINT status_pkey PRIMARY KEY (id);


--
-- Name: status status_project_id_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status
    ADD CONSTRAINT status_project_id_uniq UNIQUE (project_id, id);


--
-- Name: user_account user_account_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_account
    ADD CONSTRAINT user_account_email_key UNIQUE (email);


--
-- Name: user_account user_account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_account
    ADD CONSTRAINT user_account_pkey PRIMARY KEY (id);


--
-- Name: workspace workspace_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace
    ADD CONSTRAINT workspace_pkey PRIMARY KEY (id);


--
-- Name: workspace workspace_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace
    ADD CONSTRAINT workspace_slug_key UNIQUE (slug);


--
-- Name: change_event_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_item ON ONLY public.change_event USING btree (item_id, at DESC);


--
-- Name: change_event_2026_09_item_id_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_09_item_id_at_idx ON public.change_event_2026_09 USING btree (item_id, at DESC);


--
-- Name: change_event_ws_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_ws_seq ON ONLY public.change_event USING btree (workspace_id, seq);


--
-- Name: change_event_2026_09_workspace_id_seq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_09_workspace_id_seq_idx ON public.change_event_2026_09 USING btree (workspace_id, seq);


--
-- Name: change_event_2026_10_item_id_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_10_item_id_at_idx ON public.change_event_2026_10 USING btree (item_id, at DESC);


--
-- Name: change_event_2026_10_workspace_id_seq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_10_workspace_id_seq_idx ON public.change_event_2026_10 USING btree (workspace_id, seq);


--
-- Name: change_event_2026_11_item_id_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_11_item_id_at_idx ON public.change_event_2026_11 USING btree (item_id, at DESC);


--
-- Name: change_event_2026_11_workspace_id_seq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_11_workspace_id_seq_idx ON public.change_event_2026_11 USING btree (workspace_id, seq);


--
-- Name: comment_item_rls; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comment_item_rls ON public.comment USING btree (item_id);


--
-- Name: item_assignee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_assignee ON public.item USING btree (assignee_id) WHERE (deleted_at IS NULL);


--
-- Name: item_fields_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_fields_gin ON public.item USING gin (fields jsonb_path_ops);


--
-- Name: item_link_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_link_to ON public.item_link USING btree (to_item_id, kind);


--
-- Name: item_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_parent ON public.item USING btree (parent_id);


--
-- Name: item_path_gist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_path_gist ON public.item USING gist (path);


--
-- Name: item_proj_stat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_proj_stat ON public.item USING btree (project_id, status_id) WHERE (deleted_at IS NULL);


--
-- Name: item_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_search ON public.item USING gin (search_tsv);


--
-- Name: item_ws_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_ws_seq ON public.item USING btree (workspace_id, change_seq);


--
-- Name: operator_content_restriction_workspace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX operator_content_restriction_workspace ON public.operator_content_restriction USING btree (workspace_id, kind);


--
-- Name: operator_data_export_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX operator_data_export_expiry ON public.operator_data_export USING btree (expires_at) WHERE (payload IS NOT NULL);


--
-- Name: operator_lifecycle_hold_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX operator_lifecycle_hold_active ON public.operator_lifecycle_hold USING btree (workspace_id) WHERE (released_at IS NULL);


--
-- Name: project_owner_membership_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX project_owner_membership_idx ON public.project USING btree (workspace_id, owner_id) WHERE (owner_id IS NOT NULL);


--
-- Name: saved_view_workspace_owner_rls; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX saved_view_workspace_owner_rls ON public.saved_view USING btree (workspace_id, owner_id);


--
-- Name: session_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX session_expires_at ON public.session USING btree (expires_at);


--
-- Name: sprint_project_rls; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sprint_project_rls ON public.sprint USING btree (project_id);


--
-- Name: change_event_2026_09_item_id_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_item ATTACH PARTITION public.change_event_2026_09_item_id_at_idx;


--
-- Name: change_event_2026_09_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_pkey ATTACH PARTITION public.change_event_2026_09_pkey;


--
-- Name: change_event_2026_09_workspace_id_seq_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_ws_seq ATTACH PARTITION public.change_event_2026_09_workspace_id_seq_idx;


--
-- Name: change_event_2026_10_item_id_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_item ATTACH PARTITION public.change_event_2026_10_item_id_at_idx;


--
-- Name: change_event_2026_10_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_pkey ATTACH PARTITION public.change_event_2026_10_pkey;


--
-- Name: change_event_2026_10_workspace_id_seq_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_ws_seq ATTACH PARTITION public.change_event_2026_10_workspace_id_seq_idx;


--
-- Name: change_event_2026_11_item_id_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_item ATTACH PARTITION public.change_event_2026_11_item_id_at_idx;


--
-- Name: change_event_2026_11_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_pkey ATTACH PARTITION public.change_event_2026_11_pkey;


--
-- Name: change_event_2026_11_workspace_id_seq_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_ws_seq ATTACH PARTITION public.change_event_2026_11_workspace_id_seq_idx;


--
-- Name: user_account erased_account_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER erased_account_guard BEFORE UPDATE ON public.user_account FOR EACH ROW EXECUTE FUNCTION public.sierx_erased_account_guard();


--
-- Name: item item_path_check_trg; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER item_path_check_trg BEFORE INSERT OR UPDATE OF parent_id, path ON public.item FOR EACH ROW EXECUTE FUNCTION public.item_path_check();


--
-- Name: item_type item_type_immutable_trg; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER item_type_immutable_trg BEFORE UPDATE ON public.item_type FOR EACH ROW EXECUTE FUNCTION public.item_type_immutable();


--
-- Name: project project_runtime_update_guard_trg; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER project_runtime_update_guard_trg BEFORE UPDATE ON public.project FOR EACH ROW EXECUTE FUNCTION public.project_runtime_update_guard();


--
-- Name: item restricted_subtree_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER restricted_subtree_guard BEFORE UPDATE OF path ON public.item FOR EACH ROW EXECUTE FUNCTION public.sierx_restricted_subtree_guard();


--
-- Name: status status_immutable_trg; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER status_immutable_trg BEFORE UPDATE ON public.status FOR EACH ROW EXECUTE FUNCTION public.status_immutable();


--
-- Name: workspace workspace_create_seq_counter_trg; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER workspace_create_seq_counter_trg AFTER INSERT ON public.workspace FOR EACH ROW EXECUTE FUNCTION public.workspace_create_seq_counter();


--
-- Name: comment comment_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.user_account(id);


--
-- Name: comment comment_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(id);


--
-- Name: config_status config_status_project_id_version_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_status
    ADD CONSTRAINT config_status_project_id_version_fkey FOREIGN KEY (project_id, version) REFERENCES public.project_config(project_id, version);


--
-- Name: config_status config_status_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_status
    ADD CONSTRAINT config_status_status_id_fkey FOREIGN KEY (status_id) REFERENCES public.status(id);


--
-- Name: config_transition config_transition_from_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_transition
    ADD CONSTRAINT config_transition_from_status_id_fkey FOREIGN KEY (from_status_id) REFERENCES public.status(id);


--
-- Name: config_transition config_transition_project_id_version_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_transition
    ADD CONSTRAINT config_transition_project_id_version_fkey FOREIGN KEY (project_id, version) REFERENCES public.project_config(project_id, version);


--
-- Name: config_transition config_transition_to_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_transition
    ADD CONSTRAINT config_transition_to_status_id_fkey FOREIGN KEY (to_status_id) REFERENCES public.status(id);


--
-- Name: config_type config_type_initial_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_type
    ADD CONSTRAINT config_type_initial_status_id_fkey FOREIGN KEY (initial_status_id) REFERENCES public.status(id);


--
-- Name: config_type config_type_item_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_type
    ADD CONSTRAINT config_type_item_type_id_fkey FOREIGN KEY (item_type_id) REFERENCES public.item_type(id);


--
-- Name: config_type config_type_project_id_version_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_type
    ADD CONSTRAINT config_type_project_id_version_fkey FOREIGN KEY (project_id, version) REFERENCES public.project_config(project_id, version);


--
-- Name: field_def field_def_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_def
    ADD CONSTRAINT field_def_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: item item_assignee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_assignee_id_fkey FOREIGN KEY (assignee_id) REFERENCES public.user_account(id);


--
-- Name: item item_config_version_exists; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_config_version_exists FOREIGN KEY (project_id, config_version) REFERENCES public.project_config(project_id, version);


--
-- Name: item item_item_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_item_type_id_fkey FOREIGN KEY (item_type_id) REFERENCES public.item_type(id);


--
-- Name: item_link item_link_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.user_account(id);


--
-- Name: item_link item_link_from_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_from_item_id_fkey FOREIGN KEY (from_item_id) REFERENCES public.item(id);


--
-- Name: item_link item_link_to_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_to_item_id_fkey FOREIGN KEY (to_item_id) REFERENCES public.item(id);


--
-- Name: item item_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.item(id);


--
-- Name: item item_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: item_rollup item_rollup_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_rollup
    ADD CONSTRAINT item_rollup_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(id) ON DELETE CASCADE;


--
-- Name: item item_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_status_id_fkey FOREIGN KEY (status_id) REFERENCES public.status(id);


--
-- Name: item item_status_same_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_status_same_project FOREIGN KEY (project_id, status_id) REFERENCES public.status(project_id, id);


--
-- Name: item_type item_type_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_type
    ADD CONSTRAINT item_type_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: item item_type_same_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_type_same_project FOREIGN KEY (project_id, item_type_id) REFERENCES public.item_type(project_id, id);


--
-- Name: item item_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: membership membership_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_account(id);


--
-- Name: membership membership_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: operator_account_action operator_account_action_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_account_action
    ADD CONSTRAINT operator_account_action_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_account(id) ON DELETE RESTRICT;


--
-- Name: operator_content_restriction operator_content_restriction_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_content_restriction
    ADD CONSTRAINT operator_content_restriction_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: operator_data_export_event operator_data_export_event_export_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_data_export_event
    ADD CONSTRAINT operator_data_export_event_export_id_fkey FOREIGN KEY (export_id) REFERENCES public.operator_data_export(id) ON DELETE RESTRICT;


--
-- Name: operator_data_export operator_data_export_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_data_export
    ADD CONSTRAINT operator_data_export_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_account(id) ON DELETE RESTRICT;


--
-- Name: operator_data_export operator_data_export_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_data_export
    ADD CONSTRAINT operator_data_export_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: operator_lifecycle_hold operator_lifecycle_hold_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_lifecycle_hold
    ADD CONSTRAINT operator_lifecycle_hold_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: project_config project_config_applied_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_config
    ADD CONSTRAINT project_config_applied_by_fkey FOREIGN KEY (applied_by) REFERENCES public.user_account(id);


--
-- Name: project_config project_config_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_config
    ADD CONSTRAINT project_config_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: project project_owner_membership_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_owner_membership_fk FOREIGN KEY (workspace_id, owner_id) REFERENCES public.membership(workspace_id, user_id) ON DELETE RESTRICT;


--
-- Name: project project_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: saved_view saved_view_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.user_account(id);


--
-- Name: saved_view saved_view_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: seq_counter seq_counter_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seq_counter
    ADD CONSTRAINT seq_counter_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: session session_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session
    ADD CONSTRAINT session_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_account(id) ON DELETE CASCADE;


--
-- Name: sprint_item sprint_item_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint_item
    ADD CONSTRAINT sprint_item_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(id);


--
-- Name: sprint_item sprint_item_sprint_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint_item
    ADD CONSTRAINT sprint_item_sprint_id_fkey FOREIGN KEY (sprint_id) REFERENCES public.sprint(id);


--
-- Name: sprint sprint_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint
    ADD CONSTRAINT sprint_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: status status_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status
    ADD CONSTRAINT status_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: change_event; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.change_event ENABLE ROW LEVEL SECURITY;

--
-- Name: change_event_2026_09; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.change_event_2026_09 ENABLE ROW LEVEL SECURITY;

--
-- Name: change_event_2026_10; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.change_event_2026_10 ENABLE ROW LEVEL SECURITY;

--
-- Name: change_event_2026_11; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.change_event_2026_11 ENABLE ROW LEVEL SECURITY;

--
-- Name: change_event_2026_09 change_event_partition_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY change_event_partition_runtime ON public.change_event_2026_09 TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id())) WITH CHECK ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: change_event_2026_10 change_event_partition_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY change_event_partition_runtime ON public.change_event_2026_10 TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id())) WITH CHECK ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: change_event_2026_11 change_event_partition_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY change_event_partition_runtime ON public.change_event_2026_11 TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id())) WITH CHECK ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: change_event change_event_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY change_event_runtime ON public.change_event TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id())) WITH CHECK ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: comment; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.comment ENABLE ROW LEVEL SECURITY;

--
-- Name: comment comment_lifecycle; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY comment_lifecycle ON public.comment AS RESTRICTIVE TO sierx_runtime USING (public.sierx_lifecycle_visible('comment'::text, id, NULL::uuid)) WITH CHECK (public.sierx_lifecycle_visible('comment'::text, id, NULL::uuid));


--
-- Name: comment comment_maintenance; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY comment_maintenance ON public.comment FOR SELECT TO sierx_maintenance USING (true);


--
-- Name: comment comment_runtime_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY comment_runtime_insert ON public.comment FOR INSERT TO sierx_runtime WITH CHECK (((author_id = public.sierx_current_user_id()) AND (EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = comment.item_id)))));


--
-- Name: comment comment_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY comment_runtime_read ON public.comment FOR SELECT TO sierx_runtime USING ((EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = comment.item_id))));


--
-- Name: comment comment_runtime_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY comment_runtime_update ON public.comment FOR UPDATE TO sierx_runtime USING (((EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = comment.item_id))) AND ((author_id = public.sierx_current_user_id()) OR (public.sierx_current_role() = 'admin'::text)))) WITH CHECK (((EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = comment.item_id))) AND ((author_id = public.sierx_current_user_id()) OR (public.sierx_current_role() = 'admin'::text))));


--
-- Name: config_status; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.config_status ENABLE ROW LEVEL SECURITY;

--
-- Name: config_status config_status_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY config_status_runtime_read ON public.config_status FOR SELECT TO sierx_runtime USING ((project_id IN ( SELECT project.id
   FROM public.project
  WHERE (project.workspace_id = public.sierx_current_workspace_id()))));


--
-- Name: config_status config_status_runtime_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY config_status_runtime_write ON public.config_status FOR INSERT TO sierx_runtime WITH CHECK (((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: config_transition; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.config_transition ENABLE ROW LEVEL SECURITY;

--
-- Name: config_transition config_transition_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY config_transition_runtime_read ON public.config_transition FOR SELECT TO sierx_runtime USING ((project_id IN ( SELECT project.id
   FROM public.project
  WHERE (project.workspace_id = public.sierx_current_workspace_id()))));


--
-- Name: config_transition config_transition_runtime_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY config_transition_runtime_write ON public.config_transition FOR INSERT TO sierx_runtime WITH CHECK (((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: config_type; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.config_type ENABLE ROW LEVEL SECURITY;

--
-- Name: config_type config_type_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY config_type_runtime_read ON public.config_type FOR SELECT TO sierx_runtime USING ((project_id IN ( SELECT project.id
   FROM public.project
  WHERE (project.workspace_id = public.sierx_current_workspace_id()))));


--
-- Name: config_type config_type_runtime_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY config_type_runtime_write ON public.config_type FOR INSERT TO sierx_runtime WITH CHECK (((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: change_event event_lifecycle; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY event_lifecycle ON public.change_event AS RESTRICTIVE TO sierx_runtime USING (public.sierx_lifecycle_event_visible(workspace_id, item_id, old_value, new_value)) WITH CHECK (public.sierx_lifecycle_event_visible(workspace_id, item_id, old_value, new_value));


--
-- Name: change_event_2026_09 event_lifecycle; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY event_lifecycle ON public.change_event_2026_09 AS RESTRICTIVE TO sierx_runtime USING (public.sierx_lifecycle_event_visible(workspace_id, item_id, old_value, new_value)) WITH CHECK (public.sierx_lifecycle_event_visible(workspace_id, item_id, old_value, new_value));


--
-- Name: change_event_2026_10 event_lifecycle; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY event_lifecycle ON public.change_event_2026_10 AS RESTRICTIVE TO sierx_runtime USING (public.sierx_lifecycle_event_visible(workspace_id, item_id, old_value, new_value)) WITH CHECK (public.sierx_lifecycle_event_visible(workspace_id, item_id, old_value, new_value));


--
-- Name: change_event_2026_11 event_lifecycle; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY event_lifecycle ON public.change_event_2026_11 AS RESTRICTIVE TO sierx_runtime USING (public.sierx_lifecycle_event_visible(workspace_id, item_id, old_value, new_value)) WITH CHECK (public.sierx_lifecycle_event_visible(workspace_id, item_id, old_value, new_value));


--
-- Name: field_def; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.field_def ENABLE ROW LEVEL SECURITY;

--
-- Name: field_def field_def_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY field_def_runtime_read ON public.field_def FOR SELECT TO sierx_runtime USING ((project_id IN ( SELECT project.id
   FROM public.project
  WHERE (project.workspace_id = public.sierx_current_workspace_id()))));


--
-- Name: field_def field_def_runtime_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY field_def_runtime_write ON public.field_def FOR INSERT TO sierx_runtime WITH CHECK (((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: item; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.item ENABLE ROW LEVEL SECURITY;

--
-- Name: item item_lifecycle; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY item_lifecycle ON public.item AS RESTRICTIVE TO sierx_runtime USING (public.sierx_lifecycle_visible('item'::text, id, workspace_id, path)) WITH CHECK (public.sierx_lifecycle_visible('item'::text, id, workspace_id, path));


--
-- Name: item_link; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.item_link ENABLE ROW LEVEL SECURITY;

--
-- Name: item_link item_link_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY item_link_runtime ON public.item_link TO sierx_runtime USING (((EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = item_link.from_item_id))) AND (EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = item_link.to_item_id))))) WITH CHECK (((EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = item_link.from_item_id))) AND (EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = item_link.to_item_id)))));


--
-- Name: item item_maintenance_lifecycle; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY item_maintenance_lifecycle ON public.item FOR SELECT TO sierx_maintenance USING (true);


--
-- Name: item_rollup; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.item_rollup ENABLE ROW LEVEL SECURITY;

--
-- Name: item_rollup item_rollup_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY item_rollup_runtime ON public.item_rollup TO sierx_runtime USING ((EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = item_rollup.item_id)))) WITH CHECK ((EXISTS ( SELECT 1
   FROM public.item i
  WHERE (i.id = item_rollup.item_id))));


--
-- Name: item item_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY item_runtime ON public.item TO sierx_runtime USING (((workspace_id = public.sierx_current_workspace_id()) AND (project_id IN ( SELECT project.id
   FROM public.project
  WHERE (project.workspace_id = public.sierx_current_workspace_id()))))) WITH CHECK (((workspace_id = public.sierx_current_workspace_id()) AND (public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id())));


--
-- Name: item_type; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.item_type ENABLE ROW LEVEL SECURITY;

--
-- Name: item_type item_type_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY item_type_runtime_read ON public.item_type FOR SELECT TO sierx_runtime USING ((project_id IN ( SELECT project.id
   FROM public.project
  WHERE (project.workspace_id = public.sierx_current_workspace_id()))));


--
-- Name: item_type item_type_runtime_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY item_type_runtime_write ON public.item_type FOR INSERT TO sierx_runtime WITH CHECK (((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: operator_content_restriction lifecycle_runtime_deny; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY lifecycle_runtime_deny ON public.operator_content_restriction TO sierx_runtime USING (false) WITH CHECK (false);


--
-- Name: operator_lifecycle_event lifecycle_runtime_deny; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY lifecycle_runtime_deny ON public.operator_lifecycle_event TO sierx_runtime USING (false) WITH CHECK (false);


--
-- Name: operator_lifecycle_hold lifecycle_runtime_deny; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY lifecycle_runtime_deny ON public.operator_lifecycle_hold TO sierx_runtime USING (false) WITH CHECK (false);


--
-- Name: operator_lifecycle_state lifecycle_runtime_deny; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY lifecycle_runtime_deny ON public.operator_lifecycle_state TO sierx_runtime USING (false) WITH CHECK (false);


--
-- Name: membership; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.membership ENABLE ROW LEVEL SECURITY;

--
-- Name: membership membership_auth; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY membership_auth ON public.membership FOR SELECT TO sierx_auth USING (true);


--
-- Name: membership membership_maintenance; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY membership_maintenance ON public.membership FOR SELECT TO sierx_maintenance USING (true);


--
-- Name: membership membership_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY membership_runtime ON public.membership FOR SELECT TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: operator_account_action; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.operator_account_action ENABLE ROW LEVEL SECURITY;

--
-- Name: operator_account_action operator_account_action_maintenance; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY operator_account_action_maintenance ON public.operator_account_action TO sierx_maintenance USING (true) WITH CHECK (true);


--
-- Name: operator_account_action operator_account_action_runtime_deny; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY operator_account_action_runtime_deny ON public.operator_account_action TO sierx_runtime USING (false) WITH CHECK (false);


--
-- Name: operator_content_restriction; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.operator_content_restriction ENABLE ROW LEVEL SECURITY;

--
-- Name: operator_data_export; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.operator_data_export ENABLE ROW LEVEL SECURITY;

--
-- Name: operator_data_export_event; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.operator_data_export_event ENABLE ROW LEVEL SECURITY;

--
-- Name: operator_data_export_event operator_data_export_event_maintenance; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY operator_data_export_event_maintenance ON public.operator_data_export_event TO sierx_maintenance USING (true) WITH CHECK (true);


--
-- Name: operator_data_export_event operator_data_export_event_runtime_deny; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY operator_data_export_event_runtime_deny ON public.operator_data_export_event TO sierx_runtime USING (false) WITH CHECK (false);


--
-- Name: operator_data_export operator_data_export_maintenance; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY operator_data_export_maintenance ON public.operator_data_export TO sierx_maintenance USING (true) WITH CHECK (true);


--
-- Name: operator_data_export operator_data_export_runtime_deny; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY operator_data_export_runtime_deny ON public.operator_data_export TO sierx_runtime USING (false) WITH CHECK (false);


--
-- Name: operator_lifecycle_event; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.operator_lifecycle_event ENABLE ROW LEVEL SECURITY;

--
-- Name: operator_lifecycle_hold; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.operator_lifecycle_hold ENABLE ROW LEVEL SECURITY;

--
-- Name: operator_lifecycle_state; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.operator_lifecycle_state ENABLE ROW LEVEL SECURITY;

--
-- Name: project; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.project ENABLE ROW LEVEL SECURITY;

--
-- Name: project_config; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.project_config ENABLE ROW LEVEL SECURITY;

--
-- Name: project_config project_config_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY project_config_runtime_read ON public.project_config FOR SELECT TO sierx_runtime USING ((project_id IN ( SELECT project.id
   FROM public.project
  WHERE (project.workspace_id = public.sierx_current_workspace_id()))));


--
-- Name: project_config project_config_runtime_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY project_config_runtime_write ON public.project_config FOR INSERT TO sierx_runtime WITH CHECK (((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: project project_runtime_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY project_runtime_insert ON public.project FOR INSERT TO sierx_runtime WITH CHECK (((workspace_id = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: project project_runtime_key_counter; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY project_runtime_key_counter ON public.project FOR UPDATE TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id())) WITH CHECK ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: project project_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY project_runtime_read ON public.project FOR SELECT TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: project project_runtime_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY project_runtime_update ON public.project FOR UPDATE TO sierx_runtime USING (((workspace_id = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text))) WITH CHECK (((workspace_id = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: saved_view; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.saved_view ENABLE ROW LEVEL SECURITY;

--
-- Name: saved_view saved_view_maintenance; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY saved_view_maintenance ON public.saved_view FOR SELECT TO sierx_maintenance USING (true);


--
-- Name: saved_view saved_view_runtime_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY saved_view_runtime_insert ON public.saved_view FOR INSERT TO sierx_runtime WITH CHECK (((workspace_id = public.sierx_current_workspace_id()) AND (owner_id = public.sierx_current_user_id())));


--
-- Name: saved_view saved_view_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY saved_view_runtime_read ON public.saved_view FOR SELECT TO sierx_runtime USING (((workspace_id = public.sierx_current_workspace_id()) AND (shared OR (owner_id = public.sierx_current_user_id()))));


--
-- Name: saved_view saved_view_runtime_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY saved_view_runtime_update ON public.saved_view FOR UPDATE TO sierx_runtime USING (((workspace_id = public.sierx_current_workspace_id()) AND (owner_id = public.sierx_current_user_id()))) WITH CHECK (((workspace_id = public.sierx_current_workspace_id()) AND (owner_id = public.sierx_current_user_id())));


--
-- Name: seq_counter; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.seq_counter ENABLE ROW LEVEL SECURITY;

--
-- Name: seq_counter seq_counter_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY seq_counter_runtime ON public.seq_counter FOR SELECT TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: seq_counter seq_counter_runtime_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY seq_counter_runtime_update ON public.seq_counter FOR UPDATE TO sierx_runtime USING ((workspace_id = public.sierx_current_workspace_id())) WITH CHECK ((workspace_id = public.sierx_current_workspace_id()));


--
-- Name: session; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.session ENABLE ROW LEVEL SECURITY;

--
-- Name: session session_auth; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY session_auth ON public.session TO sierx_auth USING (true) WITH CHECK (true);


--
-- Name: session session_maintenance_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY session_maintenance_delete ON public.session FOR DELETE TO sierx_maintenance USING (true);


--
-- Name: session session_maintenance_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY session_maintenance_insert ON public.session FOR INSERT TO sierx_maintenance WITH CHECK (true);


--
-- Name: session session_maintenance_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY session_maintenance_select ON public.session FOR SELECT TO sierx_maintenance USING (true);


--
-- Name: sprint; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.sprint ENABLE ROW LEVEL SECURITY;

--
-- Name: sprint_item; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.sprint_item ENABLE ROW LEVEL SECURITY;

--
-- Name: sprint_item sprint_item_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY sprint_item_runtime ON public.sprint_item TO sierx_runtime USING ((EXISTS ( SELECT 1
   FROM (public.item i
     JOIN public.sprint s ON ((s.project_id = i.project_id)))
  WHERE ((i.id = sprint_item.item_id) AND (s.id = sprint_item.sprint_id))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (public.item i
     JOIN public.sprint s ON ((s.project_id = i.project_id)))
  WHERE ((i.id = sprint_item.item_id) AND (s.id = sprint_item.sprint_id)))));


--
-- Name: sprint sprint_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY sprint_runtime ON public.sprint TO sierx_runtime USING ((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id())) WITH CHECK ((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()));


--
-- Name: status; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.status ENABLE ROW LEVEL SECURITY;

--
-- Name: status status_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY status_runtime_read ON public.status FOR SELECT TO sierx_runtime USING ((project_id IN ( SELECT project.id
   FROM public.project
  WHERE (project.workspace_id = public.sierx_current_workspace_id()))));


--
-- Name: status status_runtime_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY status_runtime_write ON public.status FOR INSERT TO sierx_runtime WITH CHECK (((public.sierx_project_workspace_id(project_id) = public.sierx_current_workspace_id()) AND (public.sierx_current_role() = 'admin'::text)));


--
-- Name: user_account; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_account ENABLE ROW LEVEL SECURITY;

--
-- Name: user_account user_account_auth; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_account_auth ON public.user_account TO sierx_auth USING (true) WITH CHECK (true);


--
-- Name: user_account user_account_maintenance; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_account_maintenance ON public.user_account TO sierx_maintenance USING (true) WITH CHECK (true);


--
-- Name: user_account user_account_runtime_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_account_runtime_read ON public.user_account FOR SELECT TO sierx_runtime USING (((id = public.sierx_current_user_id()) OR (EXISTS ( SELECT 1
   FROM public.membership m
  WHERE ((m.workspace_id = public.sierx_current_workspace_id()) AND (m.user_id = user_account.id))))));


--
-- Name: user_account user_account_runtime_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_account_runtime_update ON public.user_account FOR UPDATE TO sierx_runtime USING ((id = public.sierx_current_user_id())) WITH CHECK ((id = public.sierx_current_user_id()));


--
-- Name: saved_view view_lifecycle; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY view_lifecycle ON public.saved_view AS RESTRICTIVE TO sierx_runtime USING (public.sierx_lifecycle_visible('view'::text, id, workspace_id)) WITH CHECK (public.sierx_lifecycle_visible('view'::text, id, workspace_id));


--
-- Name: workspace; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workspace ENABLE ROW LEVEL SECURITY;

--
-- Name: workspace workspace_maintenance; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY workspace_maintenance ON public.workspace FOR SELECT TO sierx_maintenance USING (true);


--
-- Name: workspace workspace_runtime; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY workspace_runtime ON public.workspace FOR SELECT TO sierx_runtime USING ((id = public.sierx_current_workspace_id()));


--
-- PostgreSQL database dump complete
--


