// Package property holds the randomized invariant tests (BUILD task 0.10).
//
// Property-testing library: github.com/leanovate/gopter v0.2.9, MIT, no
// runtime dependencies of its own — cleared through `make gate-license`
// before adoption, as the task requires. pgregory.net/rapid was the first
// choice and was rejected: it is MPL-2.0, which SPEC §15.1 blocks.
//
// The properties run against a real database: what they assert is
// transactional and largely enforced in SQL, so a fake would test the fake.
// Each test builds its own workspace and project, so a failure is reproducible
// in isolation and tests can run in any order against a long-lived database.
package property

import (
	"context"
	"os"
	"strings"
	"testing"
	"uuid"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/siercks/sierx/internal/store"
	"github.com/siercks/sierx/internal/store/gen"
)

type env struct {
	st        *store.Store
	q         *gen.Queries
	pool      *pgxpool.Pool
	wsID      uuid.UUID
	projectID uuid.UUID
	typeID    uuid.UUID
	statuses  map[string]uuid.UUID
	users     []uuid.UUID
	originID  uuid.UUID
}

func newEnv(t *testing.T) *env {
	t.Helper()
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL unset; skipping property tests (run: make test-property)")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	t.Cleanup(pool.Close)

	e := &env{st: store.New(pool), q: gen.New(pool), pool: pool, statuses: map[string]uuid.UUID{}}
	e.originID = uuid.NewV7()
	slug := "prop-" + uuid.NewV4().String()[:12]
	ws, err := e.q.CreateWorkspace(ctx, gen.CreateWorkspaceParams{
		Slug: slug, Name: "property", OriginID: pg(e.originID),
	})
	if err != nil {
		t.Fatalf("create workspace: %v", err)
	}
	e.wsID = uuid.UUID(ws.ID.Bytes)

	for i := range 3 {
		u, err := e.q.CreateUser(ctx, gen.CreateUserParams{
			Email:       slug + "-" + string(rune('a'+i)) + "@example.test",
			DisplayName: "Property User",
		})
		if err != nil {
			t.Fatalf("create user: %v", err)
		}
		e.users = append(e.users, uuid.UUID(u.ID.Bytes))
	}

	proj, err := e.q.CreateProject(ctx, gen.CreateProjectParams{
		WorkspaceID: ws.ID, KeyPrefix: prefixFor(slug), Name: "Property", Kind: "delivery",
	})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}
	e.projectID = uuid.UUID(proj.ID.Bytes)
	if _, err := e.q.InsertProjectConfig(ctx, gen.InsertProjectConfigParams{
		ProjectID: proj.ID, Version: 1,
	}); err != nil {
		t.Fatalf("insert config: %v", err)
	}
	for _, s := range [][3]string{
		{"todo", "To do", "open"},
		{"doing", "Doing", "active"},
		{"done", "Done", "done"},
		{"dropped", "Dropped", "cancelled"},
	} {
		row, err := e.q.InsertStatus(ctx, gen.InsertStatusParams{
			ProjectID: proj.ID, Key: s[0], Name: s[1], Category: s[2],
		})
		if err != nil {
			t.Fatalf("insert status %s: %v", s[0], err)
		}
		e.statuses[s[0]] = uuid.UUID(row.ID.Bytes)
	}
	it, err := e.q.InsertItemType(ctx, gen.InsertItemTypeParams{
		ProjectID: proj.ID, Key: "task", Name: "Task", Level: 0,
	})
	if err != nil {
		t.Fatalf("insert item type: %v", err)
	}
	e.typeID = uuid.UUID(it.ID.Bytes)
	return e
}

// prefixFor derives a valid, unique-per-workspace key prefix
// (^[A-Z][A-Z0-9]{1,9}$) from the slug.
func prefixFor(slug string) string {
	const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	out := make([]byte, 8)
	for i := range out {
		out[i] = alpha[int(slug[(i+5)%len(slug)])%len(alpha)]
	}
	return "P" + string(out)
}

func pg(id uuid.UUID) pgtype.UUID { return pgtype.UUID{Bytes: id, Valid: true} }

func (e *env) create(t *testing.T, parent *uuid.UUID, statusKey string, points *float64) uuid.UUID {
	t.Helper()
	id := uuid.NewV7()
	_, err := e.st.Mutate(context.Background(), e.wsID, func(m *store.Mutation) error {
		m.Create(store.ItemInsert{
			ID: id, ProjectID: e.projectID, ItemTypeID: e.typeID,
			StatusID: e.statuses[statusKey], ParentID: parent,
			Title: "p-" + id.String()[:8], Points: points, OriginID: e.originID,
		})
		return nil
	}, store.WithActor(e.users[0]))
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	return id
}

// itemRow is the subset of item the properties inspect.
type itemRow struct {
	id       uuid.UUID
	path     string
	parentID *uuid.UUID
	deleted  bool
	category string
	points   *float64
}

// snapshot reads every item in this test's project, ordered by path.
func (e *env) snapshot(t *testing.T) []itemRow {
	t.Helper()
	rows, err := e.pool.Query(context.Background(), `
		SELECT i.id, i.path::text, i.parent_id, i.deleted_at IS NOT NULL, s.category, i.points
		  FROM item i JOIN status s ON s.id = i.status_id
		 WHERE i.project_id = $1
		 ORDER BY i.path`, pg(e.projectID))
	if err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	defer rows.Close()

	var out []itemRow
	for rows.Next() {
		var (
			id     pgtype.UUID
			path   string
			parent pgtype.UUID
			del    bool
			cat    string
			pts    pgtype.Numeric
		)
		if err := rows.Scan(&id, &path, &parent, &del, &cat, &pts); err != nil {
			t.Fatalf("scan: %v", err)
		}
		r := itemRow{id: uuid.UUID(id.Bytes), path: path, deleted: del, category: cat}
		if parent.Valid {
			p := uuid.UUID(parent.Bytes)
			r.parentID = &p
		}
		if pts.Valid {
			if f, err := pts.Float64Value(); err == nil && f.Valid {
				v := f.Float64
				r.points = &v
			}
		}
		out = append(out, r)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("snapshot rows: %v", err)
	}
	return out
}

// storedRollup is the subset of item_rollup the properties compare.
type storedRollup struct {
	DescendantCount int32
	DoneCount       int32
}

// rollups fetches every rollup in this test's project in one round trip. The
// per-item alternative turns the comparison loop into one query per item.
func (e *env) rollups(t *testing.T) map[uuid.UUID]storedRollup {
	t.Helper()
	rows, err := e.q.ListRollupsForProject(context.Background(), pg(e.projectID))
	if err != nil {
		t.Fatalf("list rollups: %v", err)
	}
	out := make(map[uuid.UUID]storedRollup, len(rows))
	for _, r := range rows {
		out[uuid.UUID(r.ItemID.Bytes)] = storedRollup{
			DescendantCount: r.DescendantCount,
			DoneCount:       r.DoneCount,
		}
	}
	return out
}

func labels(path string) []string { return strings.Split(path, ".") }

// isStrictDescendant reports whether child's path is strictly below parent's,
// comparing whole labels so a shared prefix inside a label cannot match.
func isStrictDescendant(childPath, parentPath string) bool {
	return strings.HasPrefix(childPath, parentPath+".")
}
