-- item's column list is written out rather than `*` in every read and
-- RETURNING clause for two reasons: `search_tsv` is a generated tsvector that
-- pgx cannot scan, and `path` is ltree, which needs an explicit ::text so it
-- lands in the Go string the sqlc override declares. Adding a column to the
-- table means adding it here.

-- Item reads and writes for the unit of work (task 0.8) and the seed (0.9).
-- Every write here is called only from internal/store — gate-nodirect enforces
-- that no other package writes these tables.

-- name: GetItem :one
SELECT id, workspace_id, project_id, key, item_type_id, status_id, config_version,
  parent_id, path::text AS path, title, body, assignee_id, points, start_date, due_date,
  rank, fields, version, change_seq, origin_id, origin_seq, created_at, updated_at,
  deleted_at
FROM item WHERE id = $1;

-- name: GetItemForUpdate :one
SELECT id, workspace_id, project_id, key, item_type_id, status_id, config_version,
  parent_id, path::text AS path, title, body, assignee_id, points, start_date, due_date,
  rank, fields, version, change_seq, origin_id, origin_seq, created_at, updated_at,
  deleted_at
FROM item WHERE id = $1 FOR UPDATE;

-- name: InsertItem :one
INSERT INTO item (
  id, workspace_id, project_id, key, item_type_id, status_id, config_version,
  parent_id, path, title, body, assignee_id, points, start_date, due_date,
  rank, fields, change_seq, origin_id, origin_seq
) VALUES (
  sqlc.arg(id), sqlc.arg(workspace_id), sqlc.arg(project_id), sqlc.arg(key),
  sqlc.arg(item_type_id), sqlc.arg(status_id), sqlc.arg(config_version),
  sqlc.narg(parent_id), sqlc.arg(path)::ltree, sqlc.arg(title), sqlc.narg(body),
  sqlc.narg(assignee_id), sqlc.narg(points), sqlc.narg(start_date),
  sqlc.narg(due_date), sqlc.arg(rank), sqlc.arg(fields), sqlc.arg(change_seq),
  sqlc.arg(origin_id), sqlc.narg(origin_seq)
)
RETURNING id, workspace_id, project_id, key, item_type_id, status_id, config_version,
  parent_id, path::text AS path, title, body, assignee_id, points, start_date, due_date,
  rank, fields, version, change_seq, origin_id, origin_seq, created_at, updated_at,
  deleted_at;

-- name: UpdateItemFields :one
-- The generic field update. version is bumped here and nowhere else (§5.4);
-- config_version moves only on create/transition/promote (ADR-006), so it is
-- passed through unchanged unless the caller supplies a new one.
UPDATE item SET
  title          = coalesce(sqlc.narg(title), title),
  body           = CASE WHEN sqlc.arg(set_body)::boolean THEN sqlc.narg(body) ELSE body END,
  status_id      = coalesce(sqlc.narg(status_id), status_id),
  config_version = coalesce(sqlc.narg(config_version), config_version),
  assignee_id    = CASE WHEN sqlc.arg(set_assignee)::boolean THEN sqlc.narg(assignee_id) ELSE assignee_id END,
  points         = CASE WHEN sqlc.arg(set_points)::boolean THEN sqlc.narg(points) ELSE points END,
  start_date     = CASE WHEN sqlc.arg(set_start_date)::boolean THEN sqlc.narg(start_date) ELSE start_date END,
  due_date       = CASE WHEN sqlc.arg(set_due_date)::boolean THEN sqlc.narg(due_date) ELSE due_date END,
  rank           = coalesce(sqlc.narg(rank), rank),
  fields         = coalesce(sqlc.narg(fields), fields),
  change_seq     = sqlc.arg(change_seq),
  version        = version + 1,
  updated_at     = now()
WHERE id = sqlc.arg(id)
RETURNING id, workspace_id, project_id, key, item_type_id, status_id, config_version,
  parent_id, path::text AS path, title, body, assignee_id, points, start_date, due_date,
  rank, fields, version, change_seq, origin_id, origin_seq, created_at, updated_at,
  deleted_at;

-- name: SoftDeleteItem :one
UPDATE item SET deleted_at = now(), change_seq = sqlc.arg(change_seq),
                version = version + 1, updated_at = now()
WHERE id = sqlc.arg(id) AND deleted_at IS NULL
RETURNING id, workspace_id, project_id, key, item_type_id, status_id, config_version,
  parent_id, path::text AS path, title, body, assignee_id, points, start_date, due_date,
  rank, fields, version, change_seq, origin_id, origin_seq, created_at, updated_at,
  deleted_at;

-- name: HardDeleteItem :exec
-- §5.8: reachable only from the admin CLI path, and only after a terminal
-- change_event has been written in the same transaction.
DELETE FROM item WHERE id = $1;

-- name: ReparentSubtree :many
-- §5.3: rewrite path for the item and all its descendants in ONE statement.
-- new_parent_path is '' for a move to the root.
UPDATE item SET
  parent_id = CASE WHEN id = sqlc.arg(item_id) THEN sqlc.narg(new_parent_id) ELSE parent_id END,
  path = CASE
           WHEN sqlc.arg(new_parent_path)::text = ''
             THEN subpath(path, nlevel(sqlc.arg(old_path)::ltree) - 1)
           ELSE sqlc.arg(new_parent_path)::ltree
                || subpath(path, nlevel(sqlc.arg(old_path)::ltree) - 1)
         END,
  change_seq = sqlc.arg(change_seq),
  version = version + 1,
  updated_at = now()
WHERE path <@ sqlc.arg(old_path)::ltree
RETURNING id, path::text AS path, parent_id;

-- name: SetItemChangeSeq :exec
UPDATE item SET change_seq = sqlc.arg(change_seq) WHERE id = sqlc.arg(id);

-- name: ListProjectRanks :many
SELECT id, rank FROM item
WHERE project_id = $1 AND deleted_at IS NULL
ORDER BY rank;

-- name: UpdateItemRank :exec
UPDATE item SET rank = sqlc.arg(rank), version = version + 1, updated_at = now()
WHERE id = sqlc.arg(id);

-- name: GetItemsByPaths :many
-- The dirty ancestor set: every item whose path is a prefix of any touched path.
SELECT id, path::text AS path, parent_id FROM item
WHERE path @> ANY (sqlc.arg(paths)::ltree[]);

