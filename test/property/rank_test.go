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

// §5.5 and ADR-003. Two properties plus one non-random assertion the ADR
// asks for by name: a 5,000-item rebalance must commit.

func TestPropertyRankIsStrictTotalOrder(t *testing.T) {
	params := gopter.DefaultTestParameters()
	params.MinSuccessfulTests = 10
	properties := gopter.NewProperties(params)

	properties.Property("per-project ranks are a strict total order matching insertion order",
		prop.ForAll(func(n int) string {
			e := newEnv(t)
			n = 2 + n%25
			ids := make([]uuid.UUID, 0, n)
			for range n {
				ids = append(ids, e.create(t, nil, "todo", nil))
			}
			ranks, err := e.q.ListProjectRanks(context.Background(), pg(e.projectID))
			if err != nil {
				return fmt.Sprintf("list ranks: %v", err)
			}
			if len(ranks) != n {
				return fmt.Sprintf("got %d ranks for %d items", len(ranks), n)
			}
			seen := make(map[string]bool, n)
			for i, r := range ranks {
				if r.Rank == "" {
					return fmt.Sprintf("item %d has an empty rank", i)
				}
				if seen[r.Rank] {
					return fmt.Sprintf("duplicate rank %q", r.Rank)
				}
				seen[r.Rank] = true
				if i > 0 && ranks[i-1].Rank >= r.Rank {
					return fmt.Sprintf("not strictly ascending at %d: %q >= %q", i, ranks[i-1].Rank, r.Rank)
				}
				if uuid.UUID(r.ID.Bytes) != ids[i] {
					return fmt.Sprintf("rank order diverges from insertion order at %d", i)
				}
			}
			return ""
		}, gen.IntRange(0, 60)))

	properties.TestingRun(t)
}

func TestPropertyRankBetweenAlwaysStrictlyBetween(t *testing.T) {
	// The generator itself, without a database: whatever bounds it is given,
	// the result must sort strictly between them, and repeated insertion at
	// the same point must keep working.
	params := gopter.DefaultTestParameters()
	params.MinSuccessfulTests = 200
	properties := gopter.NewProperties(params)

	properties.Property("RankBetween lands strictly between its bounds",
		prop.ForAll(func(steps int) string {
			lo, hi := "", ""
			first, err := store.RankBetween(lo, hi)
			if err != nil {
				return fmt.Sprintf("initial: %v", err)
			}
			last, err := store.RankBetween(first, "")
			if err != nil {
				return fmt.Sprintf("append: %v", err)
			}
			lo, hi = first, last
			// Insert repeatedly into the same gap: the hard case for a
			// LexoRank implementation, and where an off-by-one produces a rank
			// equal to one of its bounds.
			for i := range 1 + steps%60 {
				mid, err := store.RankBetween(lo, hi)
				if err != nil {
					return fmt.Sprintf("step %d: %v", i, err)
				}
				if !(lo < mid && mid < hi) {
					return fmt.Sprintf("step %d: %q is not strictly between %q and %q", i, mid, lo, hi)
				}
				hi = mid
			}
			return ""
		}, gen.IntRange(0, 200)))

	properties.Property("RankBetween rejects inverted bounds",
		prop.ForAll(func(a, b int) string {
			lo := fmt.Sprintf("m%03d", a%1000)
			hi := fmt.Sprintf("m%03d", b%1000)
			if lo <= hi {
				return ""
			}
			if _, err := store.RankBetween(lo, hi); err == nil {
				return fmt.Sprintf("accepted inverted bounds %q > %q", lo, hi)
			}
			return ""
		}, gen.IntRange(0, 2000), gen.IntRange(0, 2000)))

	properties.TestingRun(t)
}

// TestRankRebalance5000 is the assertion ADR-003 names: a 5,000-item
// rebalance commits. Not randomized — the size is the point.
func TestRankRebalance5000(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping the 5,000-item rebalance in -short mode")
	}
	e := newEnv(t)
	ctx := context.Background()
	const n = 5000

	// Seeding 5,000 items one Mutate at a time would be 5,000 transactions;
	// batch them, which is also how the seed generator does it.
	const batch = 250
	ids := make([]uuid.UUID, 0, n)
	for created := 0; created < n; created += batch {
		size := min(batch, n-created)
		planned := make([]uuid.UUID, 0, size)
		if _, err := e.st.Mutate(ctx, e.wsID, func(m *store.Mutation) error {
			for range size {
				id := uuid.NewV7()
				planned = append(planned, id)
				m.Create(store.ItemInsert{
					ID: id, ProjectID: e.projectID, ItemTypeID: e.typeID,
					StatusID: e.statuses["todo"], Title: "r-" + id.String()[:8],
					OriginID: e.originID,
				})
			}
			return nil
		}); err != nil {
			t.Fatalf("seeding at %d: %v", created, err)
		}
		ids = append(ids, planned...)
	}

	got, err := e.st.RebalanceProject(ctx, e.wsID, e.projectID)
	if err != nil {
		t.Fatalf("rebalance of %d items failed: %v", n, err)
	}
	if got != n {
		t.Fatalf("rebalanced %d items, want %d", got, n)
	}

	ranks, err := e.q.ListProjectRanks(ctx, pg(e.projectID))
	if err != nil {
		t.Fatal(err)
	}
	if len(ranks) != n {
		t.Fatalf("after rebalance %d ranks, want %d", len(ranks), n)
	}
	for i := 1; i < len(ranks); i++ {
		if ranks[i-1].Rank >= ranks[i].Rank {
			t.Fatalf("rebalance broke the order at %d: %q >= %q", i, ranks[i-1].Rank, ranks[i].Rank)
		}
	}
	// Relative order must survive the respread, or a board would reshuffle
	// itself the first time a rank grew too long.
	for i, r := range ranks {
		if uuid.UUID(r.ID.Bytes) != ids[i] {
			t.Fatalf("rebalance changed relative order at %d", i)
		}
	}
	// And a fresh insert after a rebalance still lands at the end.
	last := ranks[len(ranks)-1].Rank
	next := e.create(t, nil, "todo", nil)
	after, err := e.q.ListProjectRanks(ctx, pg(e.projectID))
	if err != nil {
		t.Fatal(err)
	}
	tail := after[len(after)-1]
	if uuid.UUID(tail.ID.Bytes) != next {
		t.Fatalf("an item created after a rebalance did not land last")
	}
	if tail.Rank <= last {
		t.Fatalf("new rank %q does not sort after the previous last %q", tail.Rank, last)
	}
}
