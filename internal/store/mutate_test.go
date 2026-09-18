package store_test

import (
	"context"
	"errors"
	"fmt"
	"os"
	"sync"
	"testing"
	"uuid"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/siercks/sierx/internal/store"
	"github.com/siercks/sierx/internal/store/gen"
)

// These tests run against a real PostgreSQL: the behaviour under test is
// transactional and mostly lives in SQL, so a fake would test the fake. They
// skip rather than fail when DATABASE_URL is unset, so `go test ./...` still
// works on a machine with no database (make test-store sets it).

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL unset; skipping store tests (run: make test-store)")
	}
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

// fixture is one workspace, one project, a config version, statuses and a type.
// Every test gets its own, so tests are order-independent and can run against
// a database that already has data in it.
type fixture struct {
	st        *store.Store
	q         *gen.Queries
	pool      *pgxpool.Pool
	wsID      uuid.UUID
	projectID uuid.UUID
	typeID    uuid.UUID
	todo      uuid.UUID
	doing     uuid.UUID
	done      uuid.UUID
	userID    uuid.UUID
	originID  uuid.UUID
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	ctx := context.Background()
	pool := testPool(t)
	q := gen.New(pool)
	f := &fixture{st: store.New(pool), q: q, pool: pool}

	slug := "t-" + uuid.NewV4().String()[:8]
	f.originID = uuid.NewV7()
	ws, err := q.CreateWorkspace(ctx, gen.CreateWorkspaceParams{
		Slug: slug, Name: "test", OriginID: pgUUID(f.originID),
	})
	if err != nil {
		t.Fatalf("create workspace: %v", err)
	}
	f.wsID = uuid.UUID(ws.ID.Bytes)

	user, err := q.CreateUser(ctx, gen.CreateUserParams{
		Email: slug + "@example.test", DisplayName: "Test User",
	})
	if err != nil {
		t.Fatalf("create user: %v", err)
	}
	f.userID = uuid.UUID(user.ID.Bytes)

	// key_prefix is ^[A-Z][A-Z0-9]{1,9}$ and unique per workspace.
	proj, err := q.CreateProject(ctx, gen.CreateProjectParams{
		WorkspaceID: pgUUID(f.wsID), KeyPrefix: "T" + randPrefix(), Name: "Test", Kind: "delivery",
	})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}
	f.projectID = uuid.UUID(proj.ID.Bytes)

	if _, err := q.InsertProjectConfig(ctx, gen.InsertProjectConfigParams{
		ProjectID: pgUUID(f.projectID), Version: 1,
	}); err != nil {
		t.Fatalf("insert config: %v", err)
	}
	for _, s := range []struct {
		key, name, category string
		dst                 *uuid.UUID
	}{
		{"todo", "To do", "open", &f.todo},
		{"doing", "Doing", "active", &f.doing},
		{"done", "Done", "done", &f.done},
	} {
		row, err := q.InsertStatus(ctx, gen.InsertStatusParams{
			ProjectID: pgUUID(f.projectID), Key: s.key, Name: s.name, Category: s.category,
		})
		if err != nil {
			t.Fatalf("insert status %s: %v", s.key, err)
		}
		*s.dst = uuid.UUID(row.ID.Bytes)
	}
	it, err := q.InsertItemType(ctx, gen.InsertItemTypeParams{
		ProjectID: pgUUID(f.projectID), Key: "task", Name: "Task", Level: 0,
	})
	if err != nil {
		t.Fatalf("insert item type: %v", err)
	}
	f.typeID = uuid.UUID(it.ID.Bytes)
	return f
}

func randPrefix() string {
	const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	id := uuid.NewV4()
	out := make([]byte, 6)
	for i := range out {
		out[i] = alpha[int(id[i])%len(alpha)]
	}
	return string(out)
}

// create makes one item, optionally under parent, and returns its id.
func (f *fixture) create(t *testing.T, title string, parent *uuid.UUID, status uuid.UUID, points *float64) uuid.UUID {
	t.Helper()
	id := uuid.NewV7()
	_, err := f.st.Mutate(context.Background(), f.wsID, func(m *store.Mutation) error {
		m.Create(store.ItemInsert{
			ID: id, ProjectID: f.projectID, ItemTypeID: f.typeID, StatusID: status,
			ParentID: parent, Title: title, Points: points, OriginID: f.originID,
		})
		return nil
	}, store.WithActor(f.userID))
	if err != nil {
		t.Fatalf("create %q: %v", title, err)
	}
	return id
}

func (f *fixture) item(t *testing.T, id uuid.UUID) gen.GetItemRow {
	t.Helper()
	row, err := f.q.GetItem(context.Background(), pgUUID(id))
	if err != nil {
		t.Fatalf("get item %s: %v", id, err)
	}
	return row
}

func (f *fixture) rollup(t *testing.T, id uuid.UUID) gen.ItemRollup {
	t.Helper()
	row, err := f.q.GetRollup(context.Background(), pgUUID(id))
	if err != nil {
		t.Fatalf("get rollup %s: %v", id, err)
	}
	return row
}

func pgUUID(id uuid.UUID) pgtype.UUID {
	return pgtype.UUID{Bytes: id, Valid: true}
}

// --- the tests ------------------------------------------------------------

func TestMutateAllocatesOneSeqPerEvent(t *testing.T) {
	// ADR-002: one sequence value per event row, allocated in one statement.
	f := newFixture(t)
	ctx := context.Background()
	id := uuid.NewV7()

	res, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Create(store.ItemInsert{
			ID: id, ProjectID: f.projectID, ItemTypeID: f.typeID, StatusID: f.todo,
			Title: "one", OriginID: f.originID,
		})
		return nil
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if res.EventCount != 1 || res.HighestSeq != res.LowestSeq {
		t.Fatalf("one event should take one seq value, got count=%d lowest=%d highest=%d",
			res.EventCount, res.LowestSeq, res.HighestSeq)
	}

	// Three events in one mutation take three consecutive values.
	title := "renamed"
	res2, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Update(store.ItemUpdate{ID: id, Title: &title, StatusID: &f.doing},
			store.FieldChange{Field: "title", Old: "one", New: title},
			store.FieldChange{Kind: store.EventStatusChanged, Field: "status_id", Old: "todo", New: "doing"},
			store.FieldChange{Field: "points", Old: nil, New: 3},
		)
		return nil
	})
	if err != nil {
		t.Fatalf("update: %v", err)
	}
	if res2.EventCount != 3 {
		t.Fatalf("expected 3 events, got %d", res2.EventCount)
	}
	if got := res2.HighestSeq - res2.LowestSeq + 1; got != 3 {
		t.Fatalf("3 events should span 3 seq values, spans %d", got)
	}
	if res2.LowestSeq != res.HighestSeq+1 {
		t.Fatalf("sequence must be gap-free: previous highest %d, next lowest %d", res.HighestSeq, res2.LowestSeq)
	}

	// item.change_seq is the highest value assigned to that item's events.
	if got := f.item(t, id).ChangeSeq; got != res2.HighestSeq {
		t.Fatalf("item.change_seq = %d, want the highest event seq %d", got, res2.HighestSeq)
	}

	// The event log carries exactly those values, in order, with no gaps.
	events, err := f.q.ListEventsSince(ctx, gen.ListEventsSinceParams{
		WorkspaceID: pgUUID(f.wsID), SinceSeq: 0, Lim: 100,
	})
	if err != nil {
		t.Fatalf("list events: %v", err)
	}
	if len(events) != 4 {
		t.Fatalf("expected 4 events in the log, got %d", len(events))
	}
	for i, ev := range events {
		if want := int64(i + 1); ev.Seq != want {
			t.Fatalf("event %d has seq %d, want %d (sequence must be gap-free)", i, ev.Seq, want)
		}
	}
}

func TestMutateRejectsChangeWithoutEvents(t *testing.T) {
	// ADR-001: no row change without an event describing it.
	f := newFixture(t)
	title := "x"
	_, err := f.st.Mutate(context.Background(), f.wsID, func(m *store.Mutation) error {
		m.Update(store.ItemUpdate{ID: uuid.NewV7(), Title: &title})
		return nil
	})
	if err == nil {
		t.Fatal("an update with no described field change must be rejected")
	}
}

func TestMutateEmptyIsAnError(t *testing.T) {
	f := newFixture(t)
	_, err := f.st.Mutate(context.Background(), f.wsID, func(m *store.Mutation) error { return nil })
	if !errors.Is(err, store.ErrEmpty) {
		t.Fatalf("empty mutation: got %v, want ErrEmpty", err)
	}
}

func TestMutateCallbackErrorRollsBack(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	before, _, err := f.st.CountItemsAndRollups(ctx)
	if err != nil {
		t.Fatal(err)
	}
	sentinel := errors.New("caller changed its mind")
	id := uuid.NewV7()
	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Create(store.ItemInsert{
			ID: id, ProjectID: f.projectID, ItemTypeID: f.typeID, StatusID: f.todo,
			Title: "doomed", OriginID: f.originID,
		})
		return sentinel
	}); !errors.Is(err, sentinel) {
		t.Fatalf("got %v, want the callback's error", err)
	}
	after, _, err := f.st.CountItemsAndRollups(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if after != before {
		t.Fatalf("item count moved from %d to %d after a failed mutation", before, after)
	}
}

func TestMutatePathAndKey(t *testing.T) {
	// §5.3 path contains the item's own id last; §A.1 keys are monotonic.
	f := newFixture(t)
	root := f.create(t, "root", nil, f.todo, nil)
	child := f.create(t, "child", &root, f.todo, nil)
	grand := f.create(t, "grandchild", &child, f.todo, nil)

	if got, want := f.item(t, root).Path, root.String(); got != want {
		t.Fatalf("root path = %q, want %q", got, want)
	}
	if got, want := f.item(t, grand).Path, fmt.Sprintf("%s.%s.%s", root, child, grand); got != want {
		t.Fatalf("grandchild path = %q, want %q", got, want)
	}
	k1, k2 := f.item(t, root).Key, f.item(t, child).Key
	if k1 == k2 {
		t.Fatalf("two items share key %q", k1)
	}
}

func TestMutateRollupsAreMaintained(t *testing.T) {
	// §5.2 / A.5 / ADR-013.
	f := newFixture(t)
	three, five := 3.0, 5.0
	root := f.create(t, "root", nil, f.todo, nil)
	a := f.create(t, "a", &root, f.todo, &three)
	b := f.create(t, "b", &root, f.done, &five)

	r := f.rollup(t, root)
	if r.DescendantCount != 2 {
		t.Fatalf("root descendant_count = %d, want 2", r.DescendantCount)
	}
	if r.DoneCount != 1 {
		t.Fatalf("root done_count = %d, want 1", r.DoneCount)
	}
	// A leaf has an all-zero row, not a missing row (ADR-013).
	if la := f.rollup(t, a); la.DescendantCount != 0 || la.DoneCount != 0 {
		t.Fatalf("leaf rollup should be all-zero, got %+v", la)
	}

	// A status change on a descendant updates the ancestor's done_count.
	if _, err := f.st.Mutate(context.Background(), f.wsID, func(m *store.Mutation) error {
		m.Update(store.ItemUpdate{ID: a, StatusID: &f.done},
			store.FieldChange{Kind: store.EventStatusChanged, Field: "status_id", Old: "todo", New: "done"})
		return nil
	}); err != nil {
		t.Fatalf("transition: %v", err)
	}
	if got := f.rollup(t, root).DoneCount; got != 2 {
		t.Fatalf("after transition root done_count = %d, want 2", got)
	}
	_ = b

	// ADR-013: counts stay equal.
	items, rollups, err := f.st.CountItemsAndRollups(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if items != rollups {
		t.Fatalf("count(item)=%d but count(item_rollup)=%d (ADR-013)", items, rollups)
	}

	// ADR-005 control 2: nothing disagrees with a fresh aggregate.
	bad, err := f.st.VerifyRollups(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(bad) != 0 {
		t.Fatalf("%d rollup rows disagree with a fresh aggregate: %+v", len(bad), bad[0])
	}
}

func TestMutateReparentRewritesSubtreeAndRollups(t *testing.T) {
	// §5.3: one statement for the item and all descendants.
	f := newFixture(t)
	ctx := context.Background()
	r1 := f.create(t, "r1", nil, f.todo, nil)
	r2 := f.create(t, "r2", nil, f.todo, nil)
	mid := f.create(t, "mid", &r1, f.todo, nil)
	leaf := f.create(t, "leaf", &mid, f.todo, nil)

	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Reparent(store.ItemReparent{ID: mid, NewParentID: &r2})
		return nil
	}); err != nil {
		t.Fatalf("reparent: %v", err)
	}
	if got, want := f.item(t, mid).Path, fmt.Sprintf("%s.%s", r2, mid); got != want {
		t.Fatalf("moved item path = %q, want %q", got, want)
	}
	if got, want := f.item(t, leaf).Path, fmt.Sprintf("%s.%s.%s", r2, mid, leaf); got != want {
		t.Fatalf("descendant path = %q, want %q (subtree must be rewritten)", got, want)
	}
	if got := f.rollup(t, r1).DescendantCount; got != 0 {
		t.Fatalf("old parent descendant_count = %d, want 0", got)
	}
	if got := f.rollup(t, r2).DescendantCount; got != 2 {
		t.Fatalf("new parent descendant_count = %d, want 2", got)
	}

	// Move to the root.
	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Reparent(store.ItemReparent{ID: mid, NewParentID: nil})
		return nil
	}); err != nil {
		t.Fatalf("reparent to root: %v", err)
	}
	if got, want := f.item(t, mid).Path, mid.String(); got != want {
		t.Fatalf("after move to root path = %q, want %q", got, want)
	}
	if got, want := f.item(t, leaf).Path, fmt.Sprintf("%s.%s", mid, leaf); got != want {
		t.Fatalf("descendant after move to root = %q, want %q", got, want)
	}
	if bad, err := f.st.VerifyRollups(ctx); err != nil || len(bad) != 0 {
		t.Fatalf("rollups disagree after reparent: %v %+v", err, bad)
	}
}

func TestMutateRejectsSelfAncestryAndCrossProject(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	root := f.create(t, "root", nil, f.todo, nil)
	child := f.create(t, "child", &root, f.todo, nil)

	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Reparent(store.ItemReparent{ID: root, NewParentID: &child})
		return nil
	}); err == nil {
		t.Fatal("reparenting an item under its own descendant must be rejected (§5.3)")
	}
	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Reparent(store.ItemReparent{ID: root, NewParentID: &root})
		return nil
	}); err == nil {
		t.Fatal("reparenting an item under itself must be rejected (§5.3)")
	}

	// ADR-012: hierarchy stays inside a project.
	other, err := f.q.CreateProject(ctx, gen.CreateProjectParams{
		WorkspaceID: pgUUID(f.wsID), KeyPrefix: "O" + randPrefix(), Name: "Other", Kind: "delivery",
	})
	if err != nil {
		t.Fatal(err)
	}
	otherID := uuid.UUID(other.ID.Bytes)
	if _, err := f.q.InsertProjectConfig(ctx, gen.InsertProjectConfigParams{
		ProjectID: other.ID, Version: 1,
	}); err != nil {
		t.Fatal(err)
	}
	os2, err := f.q.InsertStatus(ctx, gen.InsertStatusParams{
		ProjectID: other.ID, Key: "todo", Name: "To do", Category: "open",
	})
	if err != nil {
		t.Fatal(err)
	}
	ot, err := f.q.InsertItemType(ctx, gen.InsertItemTypeParams{
		ProjectID: other.ID, Key: "task", Name: "Task", Level: 0,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Create(store.ItemInsert{
			ProjectID: otherID, ItemTypeID: uuid.UUID(ot.ID.Bytes), StatusID: uuid.UUID(os2.ID.Bytes),
			ParentID: &root, Title: "cross-project child", OriginID: f.originID,
		})
		return nil
	}); err == nil {
		t.Fatal("a child in a different project from its parent must be rejected (ADR-012)")
	}
}

func TestMutateSoftAndHardDelete(t *testing.T) {
	// §5.8: soft delete by default; hard delete writes a terminal event first.
	f := newFixture(t)
	ctx := context.Background()
	root := f.create(t, "root", nil, f.todo, nil)
	child := f.create(t, "child", &root, f.todo, nil)

	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.SoftDelete(child)
		return nil
	}); err != nil {
		t.Fatalf("soft delete: %v", err)
	}
	if row := f.item(t, child); !row.DeletedAt.Valid {
		t.Fatal("soft delete must set deleted_at")
	}
	if got := f.rollup(t, root).DescendantCount; got != 0 {
		t.Fatalf("soft-deleted child still counted: descendant_count = %d", got)
	}

	res, err := f.st.HardDeleteItem(ctx, f.wsID, child, store.WithActor(f.userID))
	if err != nil {
		t.Fatalf("hard delete: %v", err)
	}
	if _, err := f.q.GetItem(ctx, pgUUID(child)); err == nil {
		t.Fatal("hard delete must remove the row")
	}
	events, err := f.q.ListEventsSince(ctx, gen.ListEventsSinceParams{
		WorkspaceID: pgUUID(f.wsID), SinceSeq: res.LowestSeq - 1, Lim: 10,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(events) == 0 || events[0].Kind != store.EventDeleted {
		t.Fatalf("hard delete must write a terminal deleted event, got %+v", events)
	}
}

func TestMutateVersionIncrements(t *testing.T) {
	// §5.4: version moves on every successful mutation.
	f := newFixture(t)
	id := f.create(t, "v", nil, f.todo, nil)
	if got := f.item(t, id).Version; got != 1 {
		t.Fatalf("new item version = %d, want 1", got)
	}
	title := "v2"
	if _, err := f.st.Mutate(context.Background(), f.wsID, func(m *store.Mutation) error {
		m.Update(store.ItemUpdate{ID: id, Title: &title},
			store.FieldChange{Field: "title", Old: "v", New: title})
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if got := f.item(t, id).Version; got != 2 {
		t.Fatalf("after one update version = %d, want 2", got)
	}
}

func TestMutateConfigVersionOnlyOnCreateAndTransition(t *testing.T) {
	// ADR-006.
	f := newFixture(t)
	ctx := context.Background()
	id := f.create(t, "cfg", nil, f.todo, nil)
	if got := f.item(t, id).ConfigVersion; got != 1 {
		t.Fatalf("create should stamp the latest config version, got %d", got)
	}
	if _, err := f.q.InsertProjectConfig(ctx, gen.InsertProjectConfigParams{
		ProjectID: pgUUID(f.projectID), Version: 2,
	}); err != nil {
		t.Fatal(err)
	}
	title := "renamed"
	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Update(store.ItemUpdate{ID: id, Title: &title},
			store.FieldChange{Field: "title", Old: "cfg", New: title})
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if got := f.item(t, id).ConfigVersion; got != 1 {
		t.Fatalf("a plain field change must not move config_version, got %d (ADR-006)", got)
	}
	v2 := int32(2)
	if _, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
		m.Update(store.ItemUpdate{ID: id, StatusID: &f.doing, ConfigVersion: &v2},
			store.FieldChange{Kind: store.EventStatusChanged, Field: "status_id", Old: "todo", New: "doing"})
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if got := f.item(t, id).ConfigVersion; got != 2 {
		t.Fatalf("a transition may move config_version, got %d (ADR-006)", got)
	}
}

func TestMutateSeqGapFreeUnderConcurrency(t *testing.T) {
	// §5.1's test requirement: N parallel writers, a cursor polled throughout,
	// every committed change observed exactly once.
	f := newFixture(t)
	ctx := context.Background()
	const writers, each = 8, 6

	var wg sync.WaitGroup
	errs := make(chan error, writers*each)
	for w := range writers {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			for i := range each {
				_, err := f.st.Mutate(ctx, f.wsID, func(m *store.Mutation) error {
					m.Create(store.ItemInsert{
						ProjectID: f.projectID, ItemTypeID: f.typeID, StatusID: f.todo,
						Title:    fmt.Sprintf("w%d-i%d", w, i),
						OriginID: f.originID,
					})
					return nil
				})
				if err != nil {
					errs <- err
					return
				}
			}
		}(w)
	}

	// Poll with a cursor while the writers run, exactly as a client would.
	seen := map[int64]int{}
	done := make(chan struct{})
	var pollErr error
	go func() {
		defer close(done)
		var cursor int64
		for {
			evs, err := f.q.ListEventsSince(ctx, gen.ListEventsSinceParams{
				WorkspaceID: pgUUID(f.wsID), SinceSeq: cursor, Lim: 500,
			})
			if err != nil {
				pollErr = err
				return
			}
			for _, ev := range evs {
				seen[ev.Seq]++
				if ev.Seq > cursor {
					cursor = ev.Seq
				}
			}
			if cursor >= int64(writers*each) {
				return
			}
		}
	}()

	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatalf("writer failed: %v", err)
	}
	<-done
	if pollErr != nil {
		t.Fatalf("poller failed: %v", pollErr)
	}

	if len(seen) != writers*each {
		t.Fatalf("cursor observed %d distinct events, want %d — a value was lost", len(seen), writers*each)
	}
	for seq := int64(1); seq <= int64(writers*each); seq++ {
		switch n := seen[seq]; {
		case n == 0:
			t.Fatalf("seq %d was never observed by the cursor (§5.1: this is the bigserial failure mode)", seq)
		case n > 1:
			t.Fatalf("seq %d observed %d times, want exactly once", seq, n)
		}
	}
}

func TestMutateRankOrderAndRebalance(t *testing.T) {
	// §5.5 / ADR-003.
	f := newFixture(t)
	ctx := context.Background()
	var ids []uuid.UUID
	for i := range 20 {
		ids = append(ids, f.create(t, fmt.Sprintf("r%02d", i), nil, f.todo, nil))
	}
	ranks, err := f.q.ListProjectRanks(ctx, pgUUID(f.projectID))
	if err != nil {
		t.Fatal(err)
	}
	if len(ranks) != len(ids) {
		t.Fatalf("got %d ranks, want %d", len(ranks), len(ids))
	}
	for i := 1; i < len(ranks); i++ {
		if ranks[i-1].Rank >= ranks[i].Rank {
			t.Fatalf("ranks are not a strict total order at %d: %q >= %q", i, ranks[i-1].Rank, ranks[i].Rank)
		}
	}
	// Insertion order must match rank order for append-only creation.
	for i, r := range ranks {
		if uuid.UUID(r.ID.Bytes) != ids[i] {
			t.Fatalf("rank order diverges from creation order at %d", i)
		}
	}

	n, err := f.st.RebalanceProject(ctx, f.wsID, f.projectID)
	if err != nil {
		t.Fatalf("rebalance: %v", err)
	}
	if n != len(ids) {
		t.Fatalf("rebalanced %d items, want %d", n, len(ids))
	}
	after, err := f.q.ListProjectRanks(ctx, pgUUID(f.projectID))
	if err != nil {
		t.Fatal(err)
	}
	for i := 1; i < len(after); i++ {
		if after[i-1].Rank >= after[i].Rank {
			t.Fatalf("rebalance broke the order at %d: %q >= %q", i, after[i-1].Rank, after[i].Rank)
		}
	}
	for i, r := range after {
		if uuid.UUID(r.ID.Bytes) != ids[i] {
			t.Fatalf("rebalance changed the relative order at %d", i)
		}
	}
}
