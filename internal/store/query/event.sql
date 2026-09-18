-- change_event writes (§4.7, A.4). A derived append-only log written in the same
-- transaction as the state change — not event sourcing: no projections, no
-- replay, no versioned event schemas.

-- name: InsertEvent :exec
INSERT INTO change_event (
  workspace_id, seq, item_id, actor_id, kind, field, old_value, new_value
) VALUES (
  sqlc.arg(workspace_id), sqlc.arg(seq), sqlc.narg(item_id), sqlc.narg(actor_id),
  sqlc.arg(kind), sqlc.narg(field), sqlc.narg(old_value), sqlc.narg(new_value)
);

-- name: ListEventsSince :many
-- The sync cursor read (§5.1). Gap-free because seq comes from seq_counter.
SELECT * FROM change_event
WHERE workspace_id = sqlc.arg(workspace_id) AND seq > sqlc.arg(since_seq)
ORDER BY seq
LIMIT sqlc.arg(lim);

-- name: MaxEventSeq :one
SELECT coalesce(max(seq), 0)::bigint FROM change_event WHERE workspace_id = $1;
