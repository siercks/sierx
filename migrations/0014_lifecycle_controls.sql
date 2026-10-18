-- Explicit operator lifecycle controls; ordinary API roles cannot perform them.
-- Metadata, stable keys and counters survive redaction. No default content expiry.
-- +goose Up
CREATE TABLE operator_lifecycle_state (
 singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
 instance_id uuid NOT NULL DEFAULT uuidv7(),
 sequence bigint NOT NULL DEFAULT 0 CHECK (sequence >= 0),
 head text NOT NULL DEFAULT ''
);
INSERT INTO operator_lifecycle_state DEFAULT VALUES;
CREATE TABLE operator_lifecycle_hold (
 id uuid PRIMARY KEY,
 workspace_id uuid NOT NULL REFERENCES workspace(id),
 case_ref uuid NOT NULL,
 authority_ref uuid NOT NULL,
 started_at timestamptz NOT NULL,
 review_at timestamptz NOT NULL,
 released_at timestamptz,
 release_case uuid,
 CHECK (review_at > started_at)
);
CREATE INDEX operator_lifecycle_hold_active ON operator_lifecycle_hold(workspace_id) WHERE released_at IS NULL;
CREATE TABLE operator_content_restriction (
 kind text NOT NULL CHECK (kind IN ('item','comment','view','account')),
 target_id uuid NOT NULL,
 workspace_id uuid REFERENCES workspace(id),
 root_path ltree,
 permanent boolean NOT NULL,
 case_ref uuid NOT NULL,
 restriction_ref uuid NOT NULL,
 PRIMARY KEY(kind,target_id,permanent,restriction_ref)
);
CREATE INDEX operator_content_restriction_workspace ON operator_content_restriction(workspace_id,kind);
CREATE TABLE operator_lifecycle_event (
 id uuid PRIMARY KEY DEFAULT uuidv7(),
 occurred_at timestamptz NOT NULL DEFAULT now(),
 operator_role text NOT NULL,
 case_ref uuid NOT NULL,
 outcome text NOT NULL CHECK (outcome IN ('applied','blocked')),
 sequence bigint,
 decision jsonb NOT NULL
);
ALTER TABLE operator_data_export ADD COLUMN workspace_id uuid REFERENCES workspace(id);
ALTER TABLE operator_data_export ADD COLUMN revoked_at timestamptz;
-- +goose StatementBegin
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['operator_lifecycle_state','operator_lifecycle_hold','operator_content_restriction','operator_lifecycle_event'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY lifecycle_runtime_deny ON public.%I FOR ALL TO sierx_runtime USING(false) WITH CHECK(false)',t);
 END LOOP;
END $$;
-- +goose StatementEnd

CREATE FUNCTION sierx_lifecycle_status() RETURNS TABLE(instance_id uuid,sequence bigint,head text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public
AS $$ SELECT instance_id,sequence,head FROM public.operator_lifecycle_state WHERE singleton $$;
REVOKE ALL ON FUNCTION sierx_lifecycle_status() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_lifecycle_status() TO sierx_runtime,sierx_auth,sierx_maintenance;

CREATE FUNCTION sierx_lifecycle_visible(p_kind text,p_id uuid,p_workspace uuid,p_path ltree DEFAULT NULL)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public
AS $$ SELECT NOT EXISTS(
 SELECT 1 FROM public.operator_content_restriction r
 WHERE r.kind=p_kind AND (r.target_id=p_id OR
  (p_kind='item' AND r.workspace_id=p_workspace AND p_path <@ r.root_path))
) $$;
REVOKE ALL ON FUNCTION sierx_lifecycle_visible(text,uuid,uuid,ltree) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_lifecycle_visible(text,uuid,uuid,ltree) TO sierx_runtime,sierx_maintenance;

CREATE FUNCTION sierx_lifecycle_event_visible(p_workspace uuid,p_item uuid,p_old jsonb,p_new jsonb)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public
AS $$ SELECT (p_item IS NULL OR EXISTS(
 SELECT 1 FROM public.item i WHERE i.id=p_item AND i.workspace_id=p_workspace
 AND public.sierx_lifecycle_visible('item',i.id,i.workspace_id,i.path)))
 AND NOT EXISTS(
 SELECT 1 FROM public.operator_content_restriction r
 WHERE r.workspace_id=p_workspace AND
 (position(r.target_id::text IN coalesce(p_old::text,''))>0 OR position(r.target_id::text IN coalesce(p_new::text,''))>0)
 ) $$;
REVOKE ALL ON FUNCTION sierx_lifecycle_event_visible(uuid,uuid,jsonb,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_lifecycle_event_visible(uuid,uuid,jsonb,jsonb) TO sierx_runtime;

-- Set-based project visibility gives the planner realistic join cardinality
-- without relaxing tenant read/write controls. RLS still applies to project.
ALTER POLICY item_runtime ON item USING(
 workspace_id=public.sierx_current_workspace_id() AND project_id IN (
  SELECT id FROM public.project WHERE workspace_id=public.sierx_current_workspace_id()));
ALTER POLICY project_config_runtime_read ON project_config USING(project_id IN (SELECT id FROM public.project WHERE workspace_id=public.sierx_current_workspace_id()));
ALTER POLICY status_runtime_read ON status USING(project_id IN (SELECT id FROM public.project WHERE workspace_id=public.sierx_current_workspace_id()));
ALTER POLICY item_type_runtime_read ON item_type USING(project_id IN (SELECT id FROM public.project WHERE workspace_id=public.sierx_current_workspace_id()));
ALTER POLICY config_status_runtime_read ON config_status USING(project_id IN (SELECT id FROM public.project WHERE workspace_id=public.sierx_current_workspace_id()));
ALTER POLICY config_type_runtime_read ON config_type USING(project_id IN (SELECT id FROM public.project WHERE workspace_id=public.sierx_current_workspace_id()));
ALTER POLICY config_transition_runtime_read ON config_transition USING(project_id IN (SELECT id FROM public.project WHERE workspace_id=public.sierx_current_workspace_id()));
ALTER POLICY field_def_runtime_read ON field_def USING(project_id IN (SELECT id FROM public.project WHERE workspace_id=public.sierx_current_workspace_id()));

CREATE POLICY item_lifecycle ON item AS RESTRICTIVE FOR ALL TO sierx_runtime
 USING(public.sierx_lifecycle_visible('item',id,workspace_id,path))
 WITH CHECK(public.sierx_lifecycle_visible('item',id,workspace_id,path));
CREATE POLICY comment_lifecycle ON comment AS RESTRICTIVE FOR ALL TO sierx_runtime
 USING(public.sierx_lifecycle_visible('comment',id,NULL))
 WITH CHECK(public.sierx_lifecycle_visible('comment',id,NULL));
CREATE POLICY view_lifecycle ON saved_view AS RESTRICTIVE FOR ALL TO sierx_runtime
 USING(public.sierx_lifecycle_visible('view',id,workspace_id))
 WITH CHECK(public.sierx_lifecycle_visible('view',id,workspace_id));
CREATE POLICY event_lifecycle ON change_event AS RESTRICTIVE FOR ALL TO sierx_runtime
 USING(public.sierx_lifecycle_event_visible(workspace_id,item_id,old_value,new_value))
 WITH CHECK(public.sierx_lifecycle_event_visible(workspace_id,item_id,old_value,new_value));

-- A permanently anonymized identity cannot be reactivated or repopulated.
-- +goose StatementBegin
CREATE FUNCTION sierx_erased_account_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.operator_content_restriction WHERE kind='account' AND target_id=OLD.id AND permanent)
 AND (NEW.email IS DISTINCT FROM OLD.email OR NEW.display_name IS DISTINCT FROM OLD.display_name
 OR NEW.password_hash IS NOT NULL OR NEW.totp_secret IS NOT NULL OR NEW.is_active) THEN
  RAISE EXCEPTION 'anonymized account cannot be reactivated or repopulated';
 END IF;
 RETURN NEW;
END $$;
-- +goose StatementEnd
REVOKE ALL ON FUNCTION sierx_erased_account_guard() FROM PUBLIC;
CREATE TRIGGER erased_account_guard BEFORE UPDATE ON user_account FOR EACH ROW EXECUTE FUNCTION sierx_erased_account_guard();

-- Serializes operator cases with ordinary writers while a bounded intent is
-- journaled. Reads remain available until the durable checkpoint advances.
-- +goose StatementBegin
CREATE FUNCTION sierx_lifecycle_lock() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(761492314);
 LOCK TABLE public.workspace,public.user_account,public.membership,public.project,
 public.item,public.comment,public.saved_view,public.change_event,public.session,
 public.operator_data_export IN SHARE ROW EXCLUSIVE MODE;
 PERFORM 1 FROM public.operator_lifecycle_state WHERE singleton FOR UPDATE;
END $$;
-- +goose StatementEnd
REVOKE ALL ON FUNCTION sierx_lifecycle_lock() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_lifecycle_lock() TO sierx_maintenance;

-- Validation and exact target enumeration happen before journal persistence.
-- +goose StatementBegin
CREATE FUNCTION sierx_lifecycle_plan(a jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
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
-- +goose StatementEnd
REVOKE ALL ON FUNCTION sierx_lifecycle_plan(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_lifecycle_plan(jsonb) TO sierx_maintenance;

-- Append-only metadata audit, including attempts refused by holds.
CREATE FUNCTION sierx_lifecycle_blocked(a jsonb) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 INSERT INTO public.operator_lifecycle_event(operator_role,case_ref,outcome,decision)
 VALUES(session_user,(a->>'case_ref')::uuid,'blocked',a-'correction') $$;
REVOKE ALL ON FUNCTION sierx_lifecycle_blocked(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_lifecycle_blocked(jsonb) TO sierx_maintenance;

-- +goose StatementBegin
CREATE FUNCTION sierx_lifecycle_apply(a jsonb,p_sequence bigint,p_previous text,p_head text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
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
END $$;
-- +goose StatementEnd
REVOKE ALL ON FUNCTION sierx_lifecycle_apply(jsonb,bigint,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_lifecycle_apply(jsonb,bigint,text,text) TO sierx_maintenance;

-- Protect direct reads of existing and subsequently generated partitions.
-- +goose StatementBegin
DO $$
DECLARE child regclass;
BEGIN
 FOR child IN SELECT inhrelid FROM pg_inherits WHERE inhparent='public.change_event'::regclass LOOP
  EXECUTE format('CREATE POLICY event_lifecycle ON %s AS RESTRICTIVE FOR ALL TO sierx_runtime USING(public.sierx_lifecycle_event_visible(workspace_id,item_id,old_value,new_value)) WITH CHECK(public.sierx_lifecycle_event_visible(workspace_id,item_id,old_value,new_value))',child);
 END LOOP;
END $$;
-- +goose StatementEnd
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
      EXECUTE format('CREATE POLICY event_lifecycle ON public.%I AS RESTRICTIVE FOR ALL TO sierx_runtime USING(public.sierx_lifecycle_event_visible(workspace_id,item_id,old_value,new_value)) WITH CHECK(public.sierx_lifecycle_event_visible(workspace_id,item_id,old_value,new_value))', pname);
      EXECUTE format('GRANT SELECT, INSERT ON public.%I TO sierx_runtime', pname);
      RETURN NEXT pname;
    END IF;
  END LOOP;
  RETURN;
END $$;
-- +goose StatementEnd

CREATE FUNCTION sierx_lifecycle_has_hold() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public
AS $$ SELECT EXISTS(SELECT 1 FROM public.operator_lifecycle_hold WHERE released_at IS NULL) $$;
REVOKE ALL ON FUNCTION sierx_lifecycle_has_hold() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_lifecycle_has_hold() TO sierx_maintenance;
CREATE POLICY item_maintenance_lifecycle ON item FOR SELECT TO sierx_maintenance USING(true);
GRANT SELECT (id, workspace_id, path) ON item TO sierx_maintenance;
GRANT SELECT (workspace_id, revoked_at) ON operator_data_export TO sierx_maintenance;
-- +goose StatementBegin
CREATE OR REPLACE FUNCTION sierx_create_data_export(p_user_id uuid, p_case_ref uuid)
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
-- +goose StatementEnd
-- +goose StatementBegin
CREATE OR REPLACE FUNCTION sierx_read_data_export(p_export_id uuid, p_case_ref uuid)
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
-- +goose StatementEnd

-- An explicitly authorized workspace export, with strict size/row limits and
-- no credentials. This is shared workspace content, not a personal-data export.
-- +goose StatementBegin
CREATE FUNCTION sierx_create_workspace_export(p_workspace uuid,p_user uuid,p_case uuid)
RETURNS TABLE(export_id uuid,expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
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
-- +goose StatementEnd
REVOKE ALL ON FUNCTION sierx_create_workspace_export(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_create_workspace_export(uuid,uuid,uuid) TO sierx_maintenance;

-- Ordering metadata includes reserved hidden ranks without revealing hidden IDs
-- or content. Only the store calls the remap inside its event transaction.
-- +goose StatementBegin
CREATE FUNCTION sierx_project_rank_scope(p_project uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT EXISTS(SELECT 1 FROM public.project p WHERE p.id=p_project AND (
  (coalesce(current_setting('role',true),'none') IN ('none','') AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=session_user AND rolsuper))
  OR (p.workspace_id=public.sierx_current_workspace_id() AND EXISTS(
   SELECT 1 FROM public.membership m JOIN public.user_account u ON u.id=m.user_id
   WHERE m.workspace_id=p.workspace_id AND m.user_id=public.sierx_current_user_id() AND u.is_active))))
$$;
-- +goose StatementEnd
REVOKE ALL ON FUNCTION sierx_project_rank_scope(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_project_rank_scope(uuid) TO sierx_runtime;

CREATE VIEW sierx_project_reserved_ranks WITH (security_barrier=true) AS
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM public.operator_content_restriction r
  WHERE r.kind='item' AND (r.target_id=i.id OR (r.workspace_id=i.workspace_id AND i.path <@ r.root_path))) THEN i.id END AS id,
 i.rank,i.project_id FROM public.item i WHERE
 (coalesce(current_setting('role',true),'none') IN ('none','') AND (SELECT rolsuper FROM pg_roles WHERE rolname=session_user))
 OR (i.workspace_id=public.sierx_current_workspace_id() AND EXISTS(
  SELECT 1 FROM public.membership m JOIN public.user_account u ON u.id=m.user_id
  WHERE m.workspace_id=public.sierx_current_workspace_id() AND m.user_id=public.sierx_current_user_id() AND u.is_active));
REVOKE ALL ON sierx_project_reserved_ranks FROM PUBLIC;
GRANT SELECT ON sierx_project_reserved_ranks TO sierx_runtime;

-- +goose StatementBegin
CREATE FUNCTION sierx_set_project_ranks(p_project uuid,p_old text[],p_new text[]) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
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
END $$;
-- +goose StatementEnd
REVOKE ALL ON FUNCTION sierx_set_project_ranks(uuid,text[],text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sierx_set_project_ranks(uuid,text[],text[]) TO sierx_runtime;

-- +goose StatementBegin
CREATE FUNCTION sierx_restricted_subtree_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.path IS DISTINCT FROM OLD.path AND EXISTS(
  SELECT 1 FROM public.item i JOIN public.operator_content_restriction r ON r.kind='item' AND r.target_id=i.id
  WHERE i.workspace_id=OLD.workspace_id AND i.path <@ OLD.path) THEN
  RAISE EXCEPTION 'restricted descendants prevent hierarchy movement' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
-- +goose StatementEnd
REVOKE ALL ON FUNCTION sierx_restricted_subtree_guard() FROM PUBLIC;
CREATE TRIGGER restricted_subtree_guard BEFORE UPDATE OF path ON item FOR EACH ROW EXECUTE FUNCTION sierx_restricted_subtree_guard();

-- +goose Down
ALTER POLICY item_runtime ON item USING(workspace_id=public.sierx_current_workspace_id()
 AND public.sierx_project_workspace_id(project_id)=public.sierx_current_workspace_id());
ALTER POLICY project_config_runtime_read ON project_config USING(public.sierx_project_workspace_id(project_id)=public.sierx_current_workspace_id());
ALTER POLICY status_runtime_read ON status USING(public.sierx_project_workspace_id(project_id)=public.sierx_current_workspace_id());
ALTER POLICY item_type_runtime_read ON item_type USING(public.sierx_project_workspace_id(project_id)=public.sierx_current_workspace_id());
ALTER POLICY config_status_runtime_read ON config_status USING(public.sierx_project_workspace_id(project_id)=public.sierx_current_workspace_id());
ALTER POLICY config_type_runtime_read ON config_type USING(public.sierx_project_workspace_id(project_id)=public.sierx_current_workspace_id());
ALTER POLICY config_transition_runtime_read ON config_transition USING(public.sierx_project_workspace_id(project_id)=public.sierx_current_workspace_id());
ALTER POLICY field_def_runtime_read ON field_def USING(public.sierx_project_workspace_id(project_id)=public.sierx_current_workspace_id());

DROP TRIGGER IF EXISTS restricted_subtree_guard ON item;
DROP FUNCTION IF EXISTS sierx_restricted_subtree_guard();
DROP VIEW IF EXISTS sierx_project_reserved_ranks;
DROP FUNCTION IF EXISTS sierx_set_project_ranks(uuid,text[],text[]);
DROP FUNCTION IF EXISTS sierx_project_ranks(uuid);
DROP FUNCTION IF EXISTS sierx_project_rank_scope(uuid);
DROP FUNCTION sierx_create_workspace_export(uuid,uuid,uuid);
-- +goose StatementBegin
CREATE OR REPLACE FUNCTION sierx_create_data_export(p_user_id uuid, p_case_ref uuid)
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
-- +goose StatementBegin
CREATE OR REPLACE FUNCTION sierx_read_data_export(p_export_id uuid, p_case_ref uuid)
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
DROP FUNCTION sierx_lifecycle_has_hold();
DROP POLICY item_maintenance_lifecycle ON item;
REVOKE SELECT (id,workspace_id,path) ON item FROM sierx_maintenance;
DROP TRIGGER erased_account_guard ON user_account;
DROP FUNCTION sierx_erased_account_guard();
DROP POLICY item_lifecycle ON item;
DROP POLICY comment_lifecycle ON comment;
DROP POLICY view_lifecycle ON saved_view;
DROP POLICY event_lifecycle ON change_event;
-- +goose StatementBegin
DO $$ DECLARE child regclass; BEGIN
 FOR child IN SELECT inhrelid FROM pg_inherits WHERE inhparent='public.change_event'::regclass LOOP
  EXECUTE format('DROP POLICY event_lifecycle ON %s',child);
 END LOOP;
END $$;
-- +goose StatementEnd
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
DROP FUNCTION sierx_lifecycle_apply(jsonb,bigint,text,text);
DROP FUNCTION sierx_lifecycle_plan(jsonb);
DROP FUNCTION sierx_lifecycle_lock();
DROP FUNCTION sierx_lifecycle_blocked(jsonb);
DROP FUNCTION sierx_lifecycle_event_visible(uuid,uuid,jsonb,jsonb);
DROP FUNCTION sierx_lifecycle_visible(text,uuid,uuid,ltree);
DROP FUNCTION sierx_lifecycle_status();
ALTER TABLE operator_data_export DROP COLUMN workspace_id;
ALTER TABLE operator_data_export DROP COLUMN revoked_at;
DROP TABLE operator_lifecycle_event;
DROP TABLE operator_content_restriction;
DROP TABLE operator_lifecycle_hold;
DROP TABLE operator_lifecycle_state;
