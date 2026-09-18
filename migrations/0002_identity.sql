-- SPEC §4.1 Tenancy and identity. Transcribed verbatim; one addition from
-- BUILD task 0.4's table: an index on session(expires_at) for expiry sweeps.
-- +goose Up
CREATE TABLE workspace (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  slug       text NOT NULL UNIQUE,
  name       text NOT NULL,
  origin_id  uuid NOT NULL,                      -- §5.7
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_account (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  email         citext NOT NULL UNIQUE,
  display_name  text NOT NULL,
  password_hash text,                            -- NULL under proxy auth (§11.2)
  totp_secret   bytea,
  theme         text NOT NULL DEFAULT 'system',  -- §10.2
  reduced_motion boolean,                        -- NULL = follow OS preference
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE membership (
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  user_id      uuid NOT NULL REFERENCES user_account(id),
  role         text NOT NULL CHECK (role IN ('member','admin')),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE session (
  id_hash      bytea PRIMARY KEY,                -- SHA-256 of the cookie token
  user_id      uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  last_seen_at timestamptz
);

CREATE INDEX session_expires_at ON session (expires_at);   -- BUILD task 0.4, mechanical

-- +goose Down
DROP TABLE session;
DROP TABLE membership;
DROP TABLE user_account;
DROP TABLE workspace;
