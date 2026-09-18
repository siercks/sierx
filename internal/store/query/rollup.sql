-- Rollup maintenance (§5.2, ADR-005, ADR-013). Written, never computed on read.

-- name: InsertRollupRow :exec
-- ADR-013: every created item gets a row immediately, so count(item_rollup)
-- always equals count(item).
INSERT INTO item_rollup (item_id) VALUES ($1)
ON CONFLICT (item_id) DO NOTHING;

-- name: RecomputeRollup :exec
-- One item's rollup from its ltree descendants, excluding itself. Leaves end up
-- all-zero, which is what the property tests assert.
WITH d AS (
  SELECT i.points, i.start_date, i.due_date, s.category
    FROM item i
    JOIN status s ON s.id = i.status_id
   WHERE i.path <@ (SELECT path FROM item WHERE id = sqlc.arg(item_id))
     AND i.id <> sqlc.arg(item_id)
     AND i.deleted_at IS NULL
)
INSERT INTO item_rollup AS r (
  item_id, descendant_count, done_count, points_total, points_done,
  earliest_start, latest_due, computed_at
)
SELECT sqlc.arg(item_id),
       (SELECT count(*) FROM d),
       (SELECT count(*) FROM d WHERE category = 'done'),
       (SELECT sum(points) FROM d),
       (SELECT sum(points) FROM d WHERE category = 'done'),
       (SELECT min(start_date) FROM d),
       (SELECT max(due_date) FROM d),
       now()
ON CONFLICT (item_id) DO UPDATE SET
  descendant_count = excluded.descendant_count,
  done_count       = excluded.done_count,
  points_total     = excluded.points_total,
  points_done      = excluded.points_done,
  earliest_start   = excluded.earliest_start,
  latest_due       = excluded.latest_due,
  computed_at      = excluded.computed_at;

-- name: GetRollup :one
SELECT * FROM item_rollup WHERE item_id = $1;

-- name: CountItemsAndRollups :one
SELECT (SELECT count(*) FROM item) AS items,
       (SELECT count(*) FROM item_rollup) AS rollups;

-- name: VerifyRollups :many
-- ADR-005 control 2: recompute every rollup in SQL and return the rows that
-- disagree with the stored value. Used by `sierxctl rollup --verify` and by the
-- backup conformance check on a restored copy.
SELECT i.id,
       r.descendant_count AS stored_descendants,
       coalesce(a.descendants, 0)::int AS actual_descendants,
       r.done_count AS stored_done,
       coalesce(a.done, 0)::int AS actual_done,
       r.points_total AS stored_points,
       a.points AS actual_points
  FROM item i
  JOIN item_rollup r ON r.item_id = i.id
  LEFT JOIN LATERAL (
    SELECT count(*) AS descendants,
           count(*) FILTER (WHERE s.category = 'done') AS done,
           sum(d.points) AS points
      FROM item d JOIN status s ON s.id = d.status_id
     WHERE d.path <@ i.path AND d.id <> i.id AND d.deleted_at IS NULL
  ) a ON true
 WHERE r.descendant_count <> coalesce(a.descendants, 0)
    OR r.done_count       <> coalesce(a.done, 0)
    OR coalesce(r.points_total, 0) <> coalesce(a.points, 0);

-- name: VerifyRollupsForProject :many
-- The same check as VerifyRollups, scoped to one project. The unscoped version
-- is what `sierxctl rollup --verify` wants — an operator asking "is anything
-- wrong" means anything. A test that created 14 items should not pay to
-- re-verify a 10k-item seed on every sequence, which is what made the property
-- suite quadratic in unrelated data.
SELECT i.id,
       r.descendant_count AS stored_descendants,
       coalesce(a.descendants, 0)::int AS actual_descendants,
       r.done_count AS stored_done,
       coalesce(a.done, 0)::int AS actual_done,
       r.points_total AS stored_points,
       a.points AS actual_points
  FROM item i
  JOIN item_rollup r ON r.item_id = i.id
  LEFT JOIN LATERAL (
    SELECT count(*) AS descendants,
           count(*) FILTER (WHERE s.category = 'done') AS done,
           sum(d.points) AS points
      FROM item d JOIN status s ON s.id = d.status_id
     WHERE d.path <@ i.path AND d.id <> i.id AND d.deleted_at IS NULL
  ) a ON true
 WHERE i.project_id = sqlc.arg(project_id)
   AND (r.descendant_count <> coalesce(a.descendants, 0)
     OR r.done_count       <> coalesce(a.done, 0)
     OR coalesce(r.points_total, 0) <> coalesce(a.points, 0));

-- name: ListRollupsForProject :many
-- Every rollup in one project, so a caller comparing many items against its
-- own aggregate makes one round trip instead of one per item.
SELECT r.item_id, r.descendant_count, r.done_count, r.points_total
  FROM item_rollup r JOIN item i ON i.id = r.item_id
 WHERE i.project_id = sqlc.arg(project_id);
