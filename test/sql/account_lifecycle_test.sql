-- Reversible operator suspension must revoke sessions atomically, preserve the
-- account and workspace data, and remain inaccessible to runtime roles.
\set ON_ERROR_STOP on
BEGIN;

DO $$
BEGIN
  IF (SELECT pg_get_userbyid(p.proowner) FROM pg_proc p
      WHERE p.oid='public.sierx_set_account_active(uuid,boolean,uuid)'::regprocedure) <> 'sierx_maintenance' THEN
    RAISE EXCEPTION 'account lifecycle function owner is not sierx_maintenance';
  END IF;
  IF (SELECT pg_get_userbyid(p.proowner) FROM pg_proc p
      WHERE p.oid='public.sierx_create_session(bytea,uuid)'::regprocedure) <> 'sierx_maintenance' THEN
    RAISE EXCEPTION 'session creation function owner is not sierx_maintenance';
  END IF;
  IF NOT has_table_privilege('sierx_maintenance','public.session','DELETE')
     OR NOT has_column_privilege('sierx_maintenance','public.user_account','is_active','UPDATE')
     OR NOT has_column_privilege('sierx_maintenance','public.session','id_hash','INSERT')
     OR NOT has_table_privilege('sierx_maintenance','public.operator_account_action','INSERT') THEN
    RAISE EXCEPTION 'maintenance account lifecycle grants are incomplete';
  END IF;
  IF has_table_privilege('sierx_auth','public.session','INSERT')
     OR has_column_privilege('sierx_auth','public.session','id_hash','INSERT')
     OR NOT has_function_privilege('sierx_auth','public.sierx_create_session(bytea,uuid)','EXECUTE')
     OR has_function_privilege('sierx_runtime','public.sierx_create_session(bytea,uuid)','EXECUTE') THEN
    RAISE EXCEPTION 'session creation is not restricted to the auth function';
  END IF;
END $$;

INSERT INTO user_account (id,email,display_name,is_active)
VALUES ('13000000-0000-7000-8000-000000000001','lifecycle@example.test','Lifecycle User',true);
INSERT INTO session (id_hash,user_id,expires_at)
VALUES (decode(repeat('13',32),'hex'),'13000000-0000-7000-8000-000000000001',now()+interval '1 hour');

SET ROLE sierx_maintenance;
DO $$
DECLARE
  was_active boolean;
  is_active boolean;
  revoked integer;
BEGIN
  SELECT r.active_before,r.active_after,r.sessions_revoked
    INTO was_active,is_active,revoked
    FROM public.sierx_set_account_active(
      '13000000-0000-7000-8000-000000000001',false,'13000000-0000-7000-8000-000000000002'
    ) r;
  IF NOT was_active OR is_active OR revoked <> 1 THEN
    RAISE EXCEPTION 'suspend did not disable the account and revoke its session atomically';
  END IF;
  IF has_column_privilege(current_user,'public.user_account','password_hash','SELECT')
     OR has_column_privilege(current_user,'public.user_account','totp_secret','SELECT')
     OR has_column_privilege(current_user,'public.session','id_hash','SELECT') THEN
    RAISE EXCEPTION 'maintenance role can read authentication secrets';
  END IF;

  SELECT r.active_before,r.active_after,r.sessions_revoked
    INTO was_active,is_active,revoked
    FROM public.sierx_set_account_active(
      '13000000-0000-7000-8000-000000000001',true,'13000000-0000-7000-8000-000000000003'
    ) r;
  IF was_active OR NOT is_active OR revoked <> 0 THEN
    RAISE EXCEPTION 'reactivation state is incorrect';
  END IF;
END $$;
RESET ROLE;

DO $$
BEGIN
  IF (SELECT is_active FROM user_account WHERE id='13000000-0000-7000-8000-000000000001') IS NOT TRUE THEN
    RAISE EXCEPTION 'account did not reactivate';
  END IF;
  IF EXISTS (SELECT 1 FROM session WHERE user_id='13000000-0000-7000-8000-000000000001') THEN
    RAISE EXCEPTION 'reactivation unexpectedly restored an old session';
  END IF;
  IF (SELECT count(*) FROM operator_account_action WHERE user_id='13000000-0000-7000-8000-000000000001') <> 2 THEN
    RAISE EXCEPTION 'operator action audit rows were not retained';
  END IF;
END $$;

SET ROLE sierx_auth;
DO $$
BEGIN
  IF NOT public.sierx_create_session(
    decode(repeat('14',32),'hex'),'13000000-0000-7000-8000-000000000001'
  ) THEN
    RAISE EXCEPTION 'active account could not create a session through auth function';
  END IF;
END $$;
RESET ROLE;

SET ROLE sierx_maintenance;
SELECT * FROM public.sierx_set_account_active(
  '13000000-0000-7000-8000-000000000001',false,'13000000-0000-7000-8000-000000000004'
);
RESET ROLE;

SET ROLE sierx_auth;
DO $$
BEGIN
  IF public.sierx_create_session(
    decode(repeat('15',32),'hex'),'13000000-0000-7000-8000-000000000001'
  ) THEN
    RAISE EXCEPTION 'inactive account created a session';
  END IF;
END $$;
RESET ROLE;

SET ROLE sierx_maintenance;
SELECT * FROM public.sierx_set_account_active(
  '13000000-0000-7000-8000-000000000001',true,'13000000-0000-7000-8000-000000000005'
);
RESET ROLE;

SET ROLE sierx_runtime;
DO $$
BEGIN
  IF has_function_privilege(current_user,'public.sierx_set_account_active(uuid,boolean,uuid)','EXECUTE')
     OR has_function_privilege(current_user,'public.sierx_create_session(bytea,uuid)','EXECUTE') THEN
    RAISE EXCEPTION 'runtime role can invoke account lifecycle function';
  END IF;
  IF has_table_privilege(current_user,'public.operator_account_action','SELECT')
     OR has_table_privilege(current_user,'public.operator_account_action','INSERT') THEN
    RAISE EXCEPTION 'runtime role can inspect or alter operator lifecycle records';
  END IF;
END $$;
RESET ROLE;

DO $$
BEGIN
  IF (SELECT is_active FROM user_account WHERE id='13000000-0000-7000-8000-000000000001') IS NOT TRUE THEN
    RAISE EXCEPTION 'final reactivation did not restore account access';
  END IF;
  IF EXISTS (SELECT 1 FROM session WHERE user_id='13000000-0000-7000-8000-000000000001') THEN
    RAISE EXCEPTION 'a session survived suspension or was restored during reactivation';
  END IF;
  IF (SELECT count(*) FROM operator_account_action WHERE user_id='13000000-0000-7000-8000-000000000001') <> 4 THEN
    RAISE EXCEPTION 'operator action audit rows were not retained';
  END IF;
END $$;
ROLLBACK;

\echo 'account-lifecycle: suspension, session issue/revoke serialization, reactivation and restricted audit passed'
