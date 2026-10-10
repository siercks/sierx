package bench

import (
	"context"
	"os"
	"testing"
	"time"
	"uuid"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/siercks/sierx/internal/sxq"
)

// One benchmark per §12 scenario. Scenarios whose endpoints do not exist yet
// are skipped EXPLICITLY BY NAME (task 0.14) — never silently — so the gap
// between what §12 promises and what is measurable today is visible in the
// output rather than inferred from a short list.
//
// These benchmarks measure database/store costs. scripts/bench-http.py adds
// authenticated HTTP p95 and response-byte evidence on an explicit target.

const (
	reasonNoProcess = "not measured by this database-only benchmark; record as a separate process/hardware acceptance"
)

func pool(tb testing.TB) *pgxpool.Pool {
	tb.Helper()
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		tb.Skip("DATABASE_URL unset; skipping benchmarks (run: make bench-smoke)")
	}
	p, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		tb.Fatalf("connect: %v", err)
	}
	tb.Cleanup(p.Close)
	return p
}

// seededWorkspace finds the largest workspace in the database — the one the
// seed generator built. §12's numbers are only meaningful against a 10k-item
// workspace, so a benchmark run against an empty database says so rather than
// reporting a fast, meaningless number.
func seededWorkspace(tb testing.TB, p *pgxpool.Pool) (uuid.UUID, uuid.UUID, int) {
	tb.Helper()
	var ws, project pgtype.UUID
	var n int
	err := p.QueryRow(context.Background(), `
		SELECT workspace_id, project_id, count(*)::int
		  FROM item
		 GROUP BY workspace_id, project_id
		 ORDER BY count(*) DESC
		 LIMIT 1`).Scan(&ws, &project, &n)
	if err != nil {
		tb.Skipf("no seeded items found (run: make seed): %v", err)
	}
	if n < 500 {
		tb.Skipf("largest project has %d items; §12's scenarios assume a 10k-item workspace (run: make seed)", n)
	}
	return uuid.UUID(ws.Bytes), uuid.UUID(project.Bytes), n
}

func pg(id uuid.UUID) pgtype.UUID { return pgtype.UUID{Bytes: id, Valid: true} }

// --- measurable today -----------------------------------------------------

func BenchmarkBoardView500(b *testing.B) {
	// "board view, 500 items, projected fields" — the query the board renders
	// from: one project, grouped by status, projecting only what a card shows.
	p := pool(b)
	_, project, _ := seededWorkspace(b, p)
	ctx := context.Background()
	b.ResetTimer()
	for b.Loop() {
		rows, err := p.Query(ctx, `
			SELECT i.id, i.key, i.title, i.status_id, i.assignee_id, i.points, i.rank,
			       r.descendant_count, r.done_count
			  FROM item i
			  LEFT JOIN item_rollup r ON r.item_id = i.id
			 WHERE i.project_id = $1 AND i.deleted_at IS NULL
			 ORDER BY i.rank
			 LIMIT 500`, pg(project))
		if err != nil {
			b.Fatalf("board query: %v", err)
		}
		n := 0
		for rows.Next() {
			n++
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			b.Fatalf("board rows: %v", err)
		}
		if n == 0 {
			b.Fatal("board query returned no rows")
		}
	}
}

func BenchmarkItemDetail(b *testing.B) {
	// "item detail with rollup and history" — the item, its rollup, and the
	// most recent events for it.
	p := pool(b)
	_, project, _ := seededWorkspace(b, p)
	ctx := context.Background()
	var id pgtype.UUID
	// Prefer an item with a parent (a detail view with real ancestry), but do
	// not skip the scenario if the largest project happens to be flat: a
	// skipped scenario should mean "not measurable yet", not "today's data
	// looked wrong".
	if err := p.QueryRow(ctx, `
		SELECT i.id FROM item i
		 JOIN item_rollup r ON r.item_id = i.id
		 WHERE i.project_id = $1
		 ORDER BY (i.parent_id IS NOT NULL) DESC, i.change_seq DESC
		 LIMIT 1`, pg(project)).Scan(&id); err != nil {
		b.Skipf("%s: no item with a rollup row: %v",
			ThresholdFor("item detail with rollup and history").Name, err)
	}
	b.ResetTimer()
	for b.Loop() {
		var key, title string
		var descendants, done int32
		if err := p.QueryRow(ctx, `
			SELECT i.key, i.title, r.descendant_count, r.done_count
			  FROM item i JOIN item_rollup r ON r.item_id = i.id
			 WHERE i.id = $1`, id).Scan(&key, &title, &descendants, &done); err != nil {
			b.Fatalf("detail query: %v", err)
		}
		rows, err := p.Query(ctx, `
			SELECT kind, field, at FROM change_event
			 WHERE item_id = $1 ORDER BY at DESC LIMIT 50`, id)
		if err != nil {
			b.Fatalf("history query: %v", err)
		}
		for rows.Next() {
		}
		rows.Close()
	}
}

func BenchmarkDescendantRollupDepth6(b *testing.B) {
	// "descendant rollup read, depth 6" — the read that must never recompute
	// (A.5): a stored rollup fetched for a deep item.
	p := pool(b)
	_, project, _ := seededWorkspace(b, p)
	ctx := context.Background()
	var id pgtype.UUID
	if err := p.QueryRow(ctx, `
		SELECT id FROM item
		 WHERE project_id = $1 AND nlevel(path) = (
		   SELECT max(nlevel(path)) FROM item WHERE project_id = $1)
		 LIMIT 1`, pg(project)).Scan(&id); err != nil {
		b.Skipf("no deep item: %v", err)
	}
	b.ResetTimer()
	for b.Loop() {
		var descendants, done int32
		if err := p.QueryRow(ctx, `
			SELECT descendant_count, done_count FROM item_rollup WHERE item_id = $1`,
			id).Scan(&descendants, &done); err != nil {
			b.Fatalf("rollup read: %v", err)
		}
	}
}

func BenchmarkDeltaSync50(b *testing.B) {
	// "delta sync, 50 changes" — the ?since_seq cursor read, plus the response
	// size the threshold also caps.
	p := pool(b)
	ws, _, _ := seededWorkspace(b, p)
	ctx := context.Background()
	var maxSeq int64
	if err := p.QueryRow(ctx,
		`SELECT coalesce(max(seq),0) FROM change_event WHERE workspace_id = $1`,
		pg(ws)).Scan(&maxSeq); err != nil {
		b.Fatalf("max seq: %v", err)
	}
	since := max(maxSeq-50, 0)
	var bytesOut int
	b.ResetTimer()
	for b.Loop() {
		rows, err := p.Query(ctx, `
			SELECT seq, item_id, kind, field, old_value, new_value, at
			  FROM change_event
			 WHERE workspace_id = $1 AND seq > $2
			 ORDER BY seq LIMIT 50`, pg(ws), since)
		if err != nil {
			b.Fatalf("delta query: %v", err)
		}
		size := 0
		for rows.Next() {
			var (
				seq        int64
				item       pgtype.UUID
				kind       string
				field      *string
				oldV, newV []byte
				at         pgtype.Timestamptz
			)
			if err := rows.Scan(&seq, &item, &kind, &field, &oldV, &newV, &at); err != nil {
				rows.Close()
				b.Fatalf("delta scan: %v", err)
			}
			// An approximation of the JSON the API will emit, for the 20KB cap.
			size += 80 + len(kind) + len(oldV) + len(newV)
			if field != nil {
				size += len(*field)
			}
		}
		rows.Close()
		bytesOut = size
	}
	b.ReportMetric(float64(bytesOut), "resp_bytes")
}

func BenchmarkFullTextSearch(b *testing.B) {
	// "full-text search over 10k items" — the GIN index on search_tsv.
	p := pool(b)
	ws, _, _ := seededWorkspace(b, p)
	ctx := context.Background()
	b.ResetTimer()
	for b.Loop() {
		rows, err := p.Query(ctx, `
			SELECT id, key, title FROM item
			 WHERE workspace_id = $1
			   AND search_tsv @@ websearch_to_tsquery('english', 'rollup OR cursor')
			 LIMIT 100`, pg(ws))
		if err != nil {
			b.Fatalf("search query: %v", err)
		}
		for rows.Next() {
		}
		rows.Close()
	}
}

func BenchmarkRollupRecompute200(b *testing.B) {
	// "rollup recompute after a 200-item bulk transition" — a whole-operation
	// budget (2s), not a p95. Measured through the store so it is the real
	// path, including the dirty-ancestor derivation.
	p := pool(b)
	benchBulkTransition(b, p, 200)
}

// --- explicitly skipped, by name ------------------------------------------

func BenchmarkSXQQuery10k(b *testing.B) {
	p := pool(b)
	ws, _, _ := seededWorkspace(b, p)
	parsed, err := sxq.Parse(`text ~ "rollup cursor"`)
	if err != nil {
		b.Fatalf("parse benchmark query: %v", err)
	}
	plan, err := sxq.Compile(parsed, sxq.Options{Start: 2, Now: time.Now().UTC(), Custom: map[string][]sxq.CustomField{}})
	if err != nil {
		b.Fatalf("compile benchmark query: %v", err)
	}
	args := append([]any{pg(ws)}, plan.Args...)
	b.ResetTimer()
	for b.Loop() {
		rows, queryErr := p.Query(context.Background(), `
			SELECT i.id, i.key, i.title
			  FROM item i JOIN project p ON p.id=i.project_id
			 WHERE i.workspace_id=$1 AND i.deleted_at IS NULL AND `+plan.Where+`
			 LIMIT 100`, args...)
		if queryErr != nil {
			b.Fatalf("SXQ query: %v", queryErr)
		}
		for rows.Next() {
		}
		rows.Close()
		if queryErr = rows.Err(); queryErr != nil {
			b.Fatalf("SXQ rows: %v", queryErr)
		}
	}
}

func BenchmarkSteadyStateRSS(b *testing.B) {
	b.Skipf("%s: %s", ThresholdFor("steady-state RSS, sierx process").Name, reasonNoProcess)
}

func BenchmarkColdStart(b *testing.B) {
	b.Skipf("%s: %s", ThresholdFor("cold start to serving").Name, reasonNoProcess)
}
