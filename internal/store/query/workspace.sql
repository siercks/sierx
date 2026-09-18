-- Queries the unit of work needs for tenancy and sequence allocation (§5.1).

-- name: GetWorkspaceBySlug :one
SELECT * FROM workspace WHERE slug = $1;

-- name: CreateWorkspace :one
-- seq_counter is created by trigger (migration 0009).
INSERT INTO workspace (slug, name, origin_id)
VALUES ($1, $2, $3)
RETURNING *;

-- name: AllocateSeq :one
-- §5.1: allocate n values from the row-locked counter in the same transaction
-- as the write. Returns the HIGHEST value allocated; the block is
-- (value-n+1 .. value). Never a sequence: sequence values are handed out before
-- commit and commit out of order, which silently loses cursor updates.
UPDATE seq_counter
   SET value = value + sqlc.arg(n)::bigint
 WHERE workspace_id = sqlc.arg(workspace_id)
RETURNING value;

-- name: SeedChecksum :one
-- The determinism check for the seed generator (task 0.9). Hashes the content
-- that must be identical between two runs with the same --seed, in a stable
-- order. Ids and timestamps are excluded on purpose: uuidv7 embeds the clock,
-- so they differ between runs by design, and `at`/`created_at` likewise.
SELECT count(*)::int AS items,
       coalesce(max(nlevel(path)), 0)::int AS max_depth,
       md5(string_agg(sig, '|' ORDER BY sig))::text AS checksum
  FROM (
    SELECT i.title || ':' || s.key || ':' || t.key || ':' ||
           coalesce(i.points::text, '-') || ':' ||
           coalesce(i.start_date::text, '-') || ':' ||
           coalesce(i.due_date::text, '-') || ':' ||
           coalesce(i.body, '-') || ':' || i.fields::text || ':' ||
           nlevel(i.path)::text AS sig,
           i.path
      FROM item i
      JOIN status s ON s.id = i.status_id
      JOIN item_type t ON t.id = i.item_type_id
     WHERE i.workspace_id = $1
  ) x;
