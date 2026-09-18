package property

import (
	"context"
	"fmt"
	"testing"
	"uuid"

	"github.com/leanovate/gopter"
	"github.com/leanovate/gopter/gen"
	"github.com/leanovate/gopter/prop"

	"github.com/siercks/sierx/internal/store"
)

// A randomized sequence of create / move / delete / reparent / transition is
// applied, and after each sequence the invariants of §13, A.5, ADR-013 and
// task 0.5 are checked. gopter generates the operation sequences and shrinks a
// failing one, so a counterexample arrives minimal rather than as a 40-step
// transcript.

type opKind int

const (
	opCreateRoot opKind = iota
	opCreateChild
	opTransition
	opReparent
	opSoftDelete
)

type op struct {
	kind opKind
	// indices into the live item list, taken modulo its length at apply time
	// so a generated index is always usable and shrinking stays meaningful
	a, b int
	// status index for a transition
	status int
}

func genOps(maxOps int) gopter.Gen {
	return gen.SliceOfN(maxOps, gopter.CombineGens(
		gen.IntRange(0, 4),
		gen.IntRange(0, 1<<20),
		gen.IntRange(0, 1<<20),
		gen.IntRange(0, 3),
	).Map(func(v []any) op {
		return op{
			kind:   opKind(v[0].(int)),
			a:      v[1].(int),
			b:      v[2].(int),
			status: v[3].(int),
		}
	}))
}

var statusKeys = []string{"todo", "doing", "done", "dropped"}

// apply runs one operation sequence against a fresh project and returns the
// ids it created. Operations that cannot apply (no items yet, a move that
// would create a cycle) are skipped rather than failed: the invariants must
// hold over whatever the sequence actually did.
func (e *env) apply(t *testing.T, ops []op) {
	t.Helper()
	ctx := context.Background()
	var live []uuid.UUID
	pts := 3.0

	for _, o := range ops {
		switch o.kind {
		case opCreateRoot:
			live = append(live, e.create(t, nil, statusKeys[o.status], &pts))

		case opCreateChild:
			if len(live) == 0 {
				live = append(live, e.create(t, nil, statusKeys[o.status], &pts))
				continue
			}
			parent := live[o.a%len(live)]
			// Depth is capped at 8 (§5.3); skip if the parent is already there.
			if e.depthOf(t, parent) >= 8 {
				continue
			}
			live = append(live, e.create(t, &parent, statusKeys[o.status], &pts))

		case opTransition:
			if len(live) == 0 {
				continue
			}
			id := live[o.a%len(live)]
			key := statusKeys[o.status]
			sid := e.statuses[key]
			if _, err := e.st.Mutate(ctx, e.wsID, func(m *store.Mutation) error {
				m.Update(store.ItemUpdate{ID: id, StatusID: &sid},
					store.FieldChange{Kind: store.EventStatusChanged, Field: "status_id", New: key})
				return nil
			}, store.WithActor(e.users[o.b%len(e.users)])); err != nil {
				t.Fatalf("transition %s -> %s: %v", id, key, err)
			}

		case opReparent:
			if len(live) < 2 {
				continue
			}
			child := live[o.a%len(live)]
			parent := live[o.b%len(live)]
			if child == parent {
				continue
			}
			// A move that would create a cycle or exceed the depth cap is
			// rejected by design; the property is about the moves that succeed.
			if e.wouldCycle(t, child, parent) || e.depthOf(t, parent)+e.subtreeHeight(t, child) > 8 {
				continue
			}
			if _, err := e.st.Mutate(ctx, e.wsID, func(m *store.Mutation) error {
				m.Reparent(store.ItemReparent{ID: child, NewParentID: &parent})
				return nil
			}); err != nil {
				t.Fatalf("reparent %s under %s: %v", child, parent, err)
			}

		case opSoftDelete:
			if len(live) == 0 {
				continue
			}
			idx := o.a % len(live)
			id := live[idx]
			if e.isDeleted(t, id) {
				continue
			}
			if _, err := e.st.Mutate(ctx, e.wsID, func(m *store.Mutation) error {
				m.SoftDelete(id)
				return nil
			}); err != nil {
				t.Fatalf("soft delete %s: %v", id, err)
			}
		}
	}
}

func (e *env) depthOf(t *testing.T, id uuid.UUID) int {
	t.Helper()
	var n int
	if err := e.pool.QueryRow(context.Background(),
		`SELECT nlevel(path) FROM item WHERE id = $1`, pg(id)).Scan(&n); err != nil {
		t.Fatalf("depth of %s: %v", id, err)
	}
	return n
}

func (e *env) subtreeHeight(t *testing.T, id uuid.UUID) int {
	t.Helper()
	var n int
	if err := e.pool.QueryRow(context.Background(), `
		SELECT coalesce(max(nlevel(d.path)) - nlevel(i.path), 0) + 1
		  FROM item i LEFT JOIN item d ON d.path <@ i.path
		 WHERE i.id = $1 GROUP BY i.path`, pg(id)).Scan(&n); err != nil {
		t.Fatalf("subtree height of %s: %v", id, err)
	}
	return n
}

func (e *env) wouldCycle(t *testing.T, child, parent uuid.UUID) bool {
	t.Helper()
	var yes bool
	if err := e.pool.QueryRow(context.Background(), `
		SELECT (SELECT path FROM item WHERE id = $2) <@ (SELECT path FROM item WHERE id = $1)`,
		pg(child), pg(parent)).Scan(&yes); err != nil {
		t.Fatalf("cycle check: %v", err)
	}
	return yes
}

func (e *env) isDeleted(t *testing.T, id uuid.UUID) bool {
	t.Helper()
	var yes bool
	if err := e.pool.QueryRow(context.Background(),
		`SELECT deleted_at IS NOT NULL FROM item WHERE id = $1`, pg(id)).Scan(&yes); err != nil {
		t.Fatalf("deleted check: %v", err)
	}
	return yes
}

// --- properties -----------------------------------------------------------

func TestPropertyRollupsMatchAggregate(t *testing.T) {
	// §13, A.5, ADR-013: every non-leaf's rollup equals a fresh aggregate over
	// its ltree descendants, every leaf's is all-zero, and there is exactly one
	// rollup row per item.
	params := gopter.DefaultTestParameters()
	params.MinSuccessfulTests = 12
	params.MaxSize = 14
	properties := gopter.NewProperties(params)

	properties.Property("rollups equal a fresh aggregate over descendants",
		prop.ForAll(func(ops []op) string {
			e := newEnv(t)
			e.apply(t, ops)

			// The store's own SQL recomputation must find nothing wrong.
			// Scoped to this test's project: the unscoped query costs the whole
			// database, so an unrelated seed would dominate the run time.
			bad, err := e.st.VerifyRollupsForProject(context.Background(), e.projectID)
			if err != nil {
				return fmt.Sprintf("VerifyRollups: %v", err)
			}
			if len(bad) > 0 {
				return fmt.Sprintf("%d rollup row(s) disagree, first: %+v", len(bad), bad[0])
			}

			// And an independent aggregate computed in Go must agree, so the
			// property is not merely asserting that one SQL query matches
			// itself.
			items := e.snapshot(t)
			stored := e.rollups(t)
			for _, parent := range items {
				var descendants, done int
				var pointsTotal float64
				for _, d := range items {
					if d.deleted || !isStrictDescendant(d.path, parent.path) {
						continue
					}
					descendants++
					if d.category == "done" {
						done++
					}
					if d.points != nil {
						pointsTotal += *d.points
					}
				}
				r, ok := stored[parent.id]
				if !ok {
					return fmt.Sprintf("rollup missing for %s", parent.id)
				}
				if int(r.DescendantCount) != descendants {
					return fmt.Sprintf("%s descendant_count=%d, aggregate=%d",
						parent.id, r.DescendantCount, descendants)
				}
				if int(r.DoneCount) != done {
					return fmt.Sprintf("%s done_count=%d, aggregate=%d", parent.id, r.DoneCount, done)
				}
				if descendants == 0 && (r.DescendantCount != 0 || r.DoneCount != 0) {
					return fmt.Sprintf("leaf %s has a non-zero rollup (ADR-013)", parent.id)
				}
			}
			return ""
		}, genOps(14)))

	properties.TestingRun(t)
}

func TestPropertyRollupCountEqualsItemCount(t *testing.T) {
	// ADR-013 stated as its own property: one rollup row per item, always.
	params := gopter.DefaultTestParameters()
	params.MinSuccessfulTests = 12
	params.MaxSize = 12
	properties := gopter.NewProperties(params)

	properties.Property("count(item_rollup) == count(item)",
		prop.ForAll(func(ops []op) string {
			e := newEnv(t)
			e.apply(t, ops)
			var items, rollups int
			if err := e.pool.QueryRow(context.Background(), `
				SELECT (SELECT count(*) FROM item  WHERE project_id = $1),
				       (SELECT count(*) FROM item_rollup r JOIN item i ON i.id = r.item_id
				         WHERE i.project_id = $1)`, pg(e.projectID)).Scan(&items, &rollups); err != nil {
				return fmt.Sprintf("count: %v", err)
			}
			if items != rollups {
				return fmt.Sprintf("count(item)=%d but count(item_rollup)=%d (ADR-013)", items, rollups)
			}
			return ""
		}, genOps(12)))

	properties.TestingRun(t)
}

func TestPropertyPathsStayConsistent(t *testing.T) {
	// §13 and task 0.5: every path ends with its own id, every prefix matches
	// an ancestor, the penultimate label equals parent_id, and there are no
	// cycles.
	params := gopter.DefaultTestParameters()
	params.MinSuccessfulTests = 12
	params.MaxSize = 14
	properties := gopter.NewProperties(params)

	properties.Property("paths agree with parent_id and contain no cycles",
		prop.ForAll(func(ops []op) string {
			e := newEnv(t)
			e.apply(t, ops)
			items := e.snapshot(t)
			byID := make(map[uuid.UUID]itemRow, len(items))
			for _, it := range items {
				byID[it.id] = it
			}

			for _, it := range items {
				ls := labels(it.path)
				if ls[len(ls)-1] != it.id.String() {
					return fmt.Sprintf("%s path %q does not end with its own id", it.id, it.path)
				}
				if it.parentID == nil {
					if len(ls) != 1 {
						return fmt.Sprintf("%s has no parent but path %q has %d labels", it.id, it.path, len(ls))
					}
				} else {
					if len(ls) < 2 || ls[len(ls)-2] != it.parentID.String() {
						return fmt.Sprintf("%s path %q disagrees with parent_id %s", it.id, it.path, it.parentID)
					}
				}
				// Every prefix label must name an item that exists, and the
				// ancestor's own path must be that prefix.
				for i := range ls[:len(ls)-1] {
					ancID, err := uuid.Parse(ls[i])
					if err != nil {
						return fmt.Sprintf("%s path label %q is not a uuid", it.id, ls[i])
					}
					anc, ok := byID[ancID]
					if !ok {
						return fmt.Sprintf("%s path references missing ancestor %s", it.id, ancID)
					}
					want := joinLabels(ls[:i+1])
					if anc.path != want {
						return fmt.Sprintf("ancestor %s has path %q, but %s's path implies %q",
							ancID, anc.path, it.id, want)
					}
				}
				// No cycles: an item cannot appear twice in its own path.
				seen := map[string]bool{}
				for _, l := range ls {
					if seen[l] {
						return fmt.Sprintf("%s path %q contains %s twice", it.id, it.path, l)
					}
					seen[l] = true
				}
				if len(ls) > 8 {
					return fmt.Sprintf("%s is at depth %d, over the §5.3 cap of 8", it.id, len(ls))
				}
			}
			return ""
		}, genOps(14)))

	properties.TestingRun(t)
}

func joinLabels(ls []string) string {
	out := ls[0]
	for _, l := range ls[1:] {
		out += "." + l
	}
	return out
}
