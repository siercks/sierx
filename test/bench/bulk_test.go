package bench

import (
	"context"
	"testing"
	"uuid"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/siercks/sierx/internal/store"
)

// benchBulkTransition measures the §12 scenario "rollup recompute after a
// 200-item bulk transition" through store.Mutate, so what is timed is the real
// write path: the seq allocation, the 200 updates, the dirty-ancestor
// derivation and the rollup recomputation, in one transaction.
//
// Each iteration flips the same items between two statuses in the same
// category-changing direction, so the work is comparable run to run.
func benchBulkTransition(b *testing.B, p *pgxpool.Pool, n int) {
	ctx := context.Background()
	ws, project, _ := seededWorkspace(b, p)
	st := store.New(p)

	// Pick n leaf items in the seeded project and learn the two status ids.
	rows, err := p.Query(ctx, `
		SELECT i.id FROM item i
		 WHERE i.project_id = $1 AND i.deleted_at IS NULL
		 ORDER BY i.rank LIMIT $2`, pg(project), n)
	if err != nil {
		b.Fatalf("select items: %v", err)
	}
	var ids []uuid.UUID
	for rows.Next() {
		var id pgtype.UUID
		if err := rows.Scan(&id); err != nil {
			b.Fatalf("scan: %v", err)
		}
		ids = append(ids, uuid.UUID(id.Bytes))
	}
	rows.Close()
	if len(ids) < n {
		b.Skipf("only %d items available, need %d (run: make seed)", len(ids), n)
	}

	var doing, done pgtype.UUID
	if err := p.QueryRow(ctx,
		`SELECT id FROM status WHERE project_id = $1 AND category = 'active' LIMIT 1`,
		pg(project)).Scan(&doing); err != nil {
		b.Skipf("no active status: %v", err)
	}
	if err := p.QueryRow(ctx,
		`SELECT id FROM status WHERE project_id = $1 AND category = 'done' LIMIT 1`,
		pg(project)).Scan(&done); err != nil {
		b.Skipf("no done status: %v", err)
	}

	targets := []uuid.UUID{uuid.UUID(done.Bytes), uuid.UUID(doing.Bytes)}
	i := 0
	b.ResetTimer()
	for b.Loop() {
		target := targets[i%2]
		i++
		if _, err := st.Mutate(ctx, ws, func(m *store.Mutation) error {
			for _, id := range ids {
				sid := target
				m.Update(store.ItemUpdate{ID: id, StatusID: &sid},
					store.FieldChange{
						Kind: store.EventStatusChanged, Field: "status_id", New: sid.String(),
					})
			}
			return nil
		}); err != nil {
			b.Fatalf("bulk transition: %v", err)
		}
	}
}
