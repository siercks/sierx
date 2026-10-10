-- Catalog acceptance for runtime/auth/maintenance database separation.
\set ON_ERROR_STOP on
DO $$
DECLARE bad text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sierx_runtime' AND rolcanlogin AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication) THEN
    RAISE EXCEPTION 'runtime role attributes are not least-privileged';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sierx_auth' AND rolcanlogin AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication) THEN
    RAISE EXCEPTION 'auth role attributes are not least-privileged';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sierx_maintenance' AND rolcanlogin AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication) THEN
    RAISE EXCEPTION 'maintenance role attributes are not least-privileged';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members m
    JOIN pg_roles member ON member.oid=m.member
    JOIN pg_roles granted ON granted.oid=m.roleid
    WHERE member.rolname IN ('sierx_runtime','sierx_auth','sierx_maintenance')
       OR granted.rolname IN ('sierx_runtime','sierx_auth','sierx_maintenance')
  ) THEN RAISE EXCEPTION 'application roles have or grant role membership'; END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relname <> 'goose_db_version'
      AND (pg_get_userbyid(c.relowner) IN ('sierx_runtime','sierx_auth','sierx_maintenance')
        OR NOT c.relrowsecurity OR NOT c.relforcerowsecurity
        OR NOT EXISTS (
          SELECT 1 FROM pg_policy p
          WHERE p.polrelid=c.oid
            AND p.polroles && ARRAY[(SELECT oid FROM pg_roles WHERE rolname='sierx_runtime'),
                                    (SELECT oid FROM pg_roles WHERE rolname='sierx_auth')]::oid[]
        ))
  ) THEN RAISE EXCEPTION 'an application table/partition is owned by an app role or lacks effective RLS policy'; END IF;
  SELECT c.relname INTO bad FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relname <> 'goose_db_version'
     AND has_table_privilege('sierx_runtime',c.oid,'TRUNCATE') LIMIT 1;
  IF bad IS NOT NULL THEN RAISE EXCEPTION 'runtime can TRUNCATE %', bad; END IF;
  IF has_database_privilege('sierx_runtime',current_database(),'CREATE')
     OR has_database_privilege('sierx_runtime',current_database(),'TEMP')
     OR has_schema_privilege('sierx_runtime','public','CREATE') THEN
    RAISE EXCEPTION 'runtime has database CREATE/TEMP or schema CREATE privilege';
  END IF;
  IF has_column_privilege('sierx_runtime','user_account','password_hash','SELECT')
     OR has_column_privilege('sierx_runtime','user_account','totp_secret','SELECT') THEN
    RAISE EXCEPTION 'runtime can read authentication secrets';
  END IF;
  IF NOT has_column_privilege('sierx_auth','user_account','password_hash','SELECT')
     OR NOT has_column_privilege('sierx_auth','user_account','totp_secret','SELECT') THEN
    RAISE EXCEPTION 'auth role lacks its narrowly scoped credential columns';
  END IF;
  IF has_function_privilege('sierx_runtime','change_event_ensure_partitions(integer)','EXECUTE')
     OR has_function_privilege('sierx_auth','change_event_ensure_partitions(integer)','EXECUTE')
     OR NOT has_function_privilege('sierx_maintenance','change_event_ensure_partitions(integer)','EXECUTE') THEN
    RAISE EXCEPTION 'partition maintenance function grants are incorrect';
  END IF;
END $$;
\echo 'gate-db-privileges: application role attributes, ownership, DDL, secret columns and RLS catalog passed'
