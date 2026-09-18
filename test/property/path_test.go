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

// A reparent must rewrite the moved item and every descendant in one
// statement (§5.3). This property builds a chain, moves a middle node, and
// asserts every descendant's path follows — the failure mode being a move that
// updates the item and leaves its subtree pointing at the old ancestry.
func TestPropertySubtreeMovesWholesale(t *testing.T) {
	params := gopter.DefaultTestParameters()
	params.MinSuccessfulTests = 10
	properties := gopter.NewProperties(params)

	properties.Property("moving a node moves its whole subtree",
		prop.ForAll(func(chainLen, moveAt int) string {
			e := newEnv(t)
			ctx := context.Background()
			// Build a chain within the depth cap, plus a separate root to move under.
			chainLen = 2 + chainLen%5
			ids := make([]uuid.UUID, 0, chainLen)
			var parent *uuid.UUID
			for range chainLen {
				id := e.create(t, parent, "todo", nil)
				ids = append(ids, id)
				p := id
				parent = &p
			}
			target := e.create(t, nil, "todo", nil)

			idx := 1 + moveAt%(chainLen-1) // never the root of the chain
			moved := ids[idx]
			before := e.snapshot(t)
			var descendantsBefore int
			for _, it := range before {
				if isStrictDescendant(it.path, pathOf(before, moved)) {
					descendantsBefore++
				}
			}

			if _, err := e.st.Mutate(ctx, e.wsID, func(m *store.Mutation) error {
				m.Reparent(store.ItemReparent{ID: moved, NewParentID: &target})
				return nil
			}); err != nil {
				return fmt.Sprintf("reparent: %v", err)
			}

			after := e.snapshot(t)
			movedPath := pathOf(after, moved)
			want := pathOf(after, target) + "." + moved.String()
			if movedPath != want {
				return fmt.Sprintf("moved item path %q, want %q", movedPath, want)
			}
			var descendantsAfter int
			for _, it := range after {
				if isStrictDescendant(it.path, movedPath) {
					descendantsAfter++
				}
			}
			if descendantsAfter != descendantsBefore {
				return fmt.Sprintf("subtree lost members: %d descendants before, %d after",
					descendantsBefore, descendantsAfter)
			}
			// No item may still sit under the old ancestry.
			for _, it := range after {
				ls := labels(it.path)
				for _, l := range ls[:len(ls)-1] {
					if l == moved.String() && !isStrictDescendant(it.path, movedPath) {
						return fmt.Sprintf("%s still references the moved node's old path: %q", it.id, it.path)
					}
				}
			}
			return ""
		}, gen.IntRange(0, 40), gen.IntRange(0, 40)))

	properties.TestingRun(t)
}

// pathOf returns the path of id in a snapshot.
func pathOf(items []itemRow, id uuid.UUID) string {
	for _, it := range items {
		if it.id == id {
			return it.path
		}
	}
	return ""
}
