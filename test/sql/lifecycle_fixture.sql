CREATE FUNCTION test_mark_expired_item(p_id uuid) RETURNS void LANGUAGE sql AS $$ UPDATE item SET deleted_at=now()-interval '30 days' WHERE id=p_id $$;
CREATE FUNCTION test_expire_export(p_id uuid) RETURNS void LANGUAGE sql AS $$ UPDATE operator_data_export SET created_at=now()-interval '30 minutes',expires_at=now()-interval '1 second' WHERE id=p_id $$;
CREATE FUNCTION test_move_restricted_item(p_id uuid,p_parent uuid) RETURNS void LANGUAGE sql AS $$ UPDATE item SET parent_id=p_parent,path=(SELECT path FROM item WHERE id=p_parent)||id::text::ltree WHERE id=p_id $$;
