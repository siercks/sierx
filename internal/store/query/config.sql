-- Project and config reads the unit of work and the seed need. status and
-- item_type are append-only (§5.6) — there is deliberately no UPDATE here.

-- name: CreateProject :one
INSERT INTO project (workspace_id, key_prefix, name, kind)
VALUES ($1, $2, $3, $4)
RETURNING *;

-- name: NextItemKey :one
-- §A.1: monotonic, never reset, never reused. Row-locked like the sequence
-- counter so two concurrent creates cannot take the same number.
UPDATE project SET next_key_num = next_key_num + 1
WHERE id = sqlc.arg(project_id)
RETURNING (key_prefix || '-' || (next_key_num - 1)::text)::text AS key,
          (next_key_num - 1)::int AS num;

-- name: GetProject :one
SELECT * FROM project WHERE id = $1;

-- name: InsertProjectConfig :one
INSERT INTO project_config (project_id, version, source_yaml, applied_by)
VALUES ($1, $2, $3, $4)
RETURNING *;

-- name: LatestConfigVersion :one
SELECT coalesce(max(version), 0)::int FROM project_config WHERE project_id = $1;

-- name: InsertStatus :one
INSERT INTO status (project_id, key, name, category)
VALUES ($1, $2, $3, $4)
RETURNING *;

-- name: InsertItemType :one
INSERT INTO item_type (project_id, key, name, level, is_idea)
VALUES ($1, $2, $3, $4, $5)
RETURNING *;

-- name: InsertConfigStatus :exec
INSERT INTO config_status (project_id, version, status_id, display_order)
VALUES ($1, $2, $3, $4);

-- name: InsertConfigType :exec
INSERT INTO config_type (project_id, version, item_type_id, initial_status_id)
VALUES ($1, $2, $3, $4);

-- name: InsertConfigTransition :exec
INSERT INTO config_transition (project_id, version, from_status_id, to_status_id, requires)
VALUES ($1, $2, $3, $4, $5);

-- name: ListStatuses :many
SELECT * FROM status WHERE project_id = $1 ORDER BY key;

-- name: ListItemTypes :many
SELECT * FROM item_type WHERE project_id = $1 ORDER BY level, key;

-- name: InsertLink :one
INSERT INTO item_link (from_item_id, to_item_id, kind, created_by)
VALUES ($1, $2, $3, $4)
RETURNING *;

-- name: DeleteLink :exec
DELETE FROM item_link WHERE id = $1;

-- name: CreateUser :one
INSERT INTO user_account (email, display_name) VALUES ($1, $2) RETURNING *;
