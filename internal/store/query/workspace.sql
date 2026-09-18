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
