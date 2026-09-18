package store

import (
	"context"
	"fmt"
	"strings"
	"uuid"

	"github.com/jackc/pgx/v5/pgtype"

	"github.com/siercks/sierx/internal/store/gen"
)

// Rollup maintenance (SPEC §5.2, ADR-005). State is truth; rollups are
// derived, written, and never computed on read (A.5).
//
// §5.2 describes a row trigger collecting dirty ancestors plus a deferred
// constraint trigger recomputing them at commit. ADR-005 moved that into this
// layer: the effect is the same — each dirty ancestor recomputed exactly once
// per transaction, not once per touched descendant — and it stays debuggable
// and testable in Go. The naive alternative, recomputing ancestors on every row
// change, is O(depth × changes) and recomputes the same ancestor dozens of
// times in one bulk operation.

// dirtyAncestors turns the set of touched paths into the set of item ids whose
// rollups must be recomputed: every strict ancestor of every touched path.
// Deduplicated, so an ancestor touched by fifty descendants is recomputed once.
func dirtyAncestors(paths []string) []uuid.UUID {
	seen := make(map[string]struct{})
	var out []uuid.UUID
	for _, p := range paths {
		labels := strings.Split(p, ".")
		// Drop the last label: an item is not its own ancestor, and its own
		// rollup covers its descendants, which this path's change does not
		// alter unless the item itself moved — handled by the caller adding
		// both the old and the new path.
		for _, label := range labels[:max(len(labels)-1, 0)] {
			if _, dup := seen[label]; dup {
				continue
			}
			seen[label] = struct{}{}
			id, err := uuid.Parse(label)
			if err != nil {
				// A non-UUID label cannot exist: paths are built from ids
				// (§4.4) and the database trigger rejects anything else.
				continue
			}
			out = append(out, id)
		}
	}
	return out
}

// recomputeRollups recomputes each dirty ancestor's rollup row once.
func recomputeRollups(ctx context.Context, q *gen.Queries, ids []uuid.UUID) error {
	for _, id := range ids {
		if err := q.RecomputeRollup(ctx, toPgUUID(id)); err != nil {
			return fmt.Errorf("recompute rollup %s: %w", id, err)
		}
	}
	return nil
}

// RollupMismatch is one row where the stored rollup disagrees with a fresh
// aggregate over the item's ltree descendants.
type RollupMismatch struct {
	ItemID            uuid.UUID
	StoredDescendants int32
	ActualDescendants int32
	StoredDone        int32
	ActualDone        int32
}

// VerifyRollups recomputes every rollup in SQL and reports the rows that
// disagree with what is stored — ADR-005's control 2. Used by
// `sierxctl rollup --verify` and by the backup conformance check against a
// restored copy, where a silently wrong rollup would otherwise be invisible.
func (s *Store) VerifyRollups(ctx context.Context) ([]RollupMismatch, error) {
	rows, err := s.q.VerifyRollups(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]RollupMismatch, 0, len(rows))
	for _, r := range rows {
		out = append(out, RollupMismatch{
			ItemID:            fromPgUUID(r.ID),
			StoredDescendants: r.StoredDescendants,
			ActualDescendants: r.ActualDescendants,
			StoredDone:        r.StoredDone,
			ActualDone:        r.ActualDone,
		})
	}
	return out, nil
}

// CountItemsAndRollups returns both counts. ADR-013 requires they be equal:
// every item gets a rollup row at creation, so a leaf has an all-zero row
// rather than no row, and a query can join instead of coalescing.
func (s *Store) CountItemsAndRollups(ctx context.Context) (items, rollups int64, err error) {
	row, err := s.q.CountItemsAndRollups(ctx)
	if err != nil {
		return 0, 0, err
	}
	return row.Items, row.Rollups, nil
}

func toPgUUID(id uuid.UUID) pgtype.UUID {
	return pgtype.UUID{Bytes: id, Valid: true}
}

func toPgUUIDPtr(id *uuid.UUID) pgtype.UUID {
	if id == nil {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: *id, Valid: true}
}

func fromPgUUID(p pgtype.UUID) uuid.UUID {
	if !p.Valid {
		return uuid.UUID{}
	}
	return uuid.UUID(p.Bytes)
}
