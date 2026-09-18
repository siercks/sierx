-- SPEC §4: the three extensions the schema depends on. uuidv7() is built into
-- PostgreSQL 18, so pgcrypto is deliberately absent.
-- +goose Up
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- +goose Down
DROP EXTENSION IF EXISTS pg_trgm;
DROP EXTENSION IF EXISTS citext;
DROP EXTENSION IF EXISTS ltree;
