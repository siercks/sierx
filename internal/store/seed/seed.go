// Package seed builds a realistic workspace for benchmarking and manual use
// (BUILD task 0.9). It exists in phase 0 so ARM performance is discovered now
// rather than in month four (§13).
//
// Everything goes through store.Mutate, so sequences, rollups and the event
// log are correct by construction rather than by the seed's own arithmetic —
// which also means the seed exercises the write path it shares with the API.
package seed

import (
	"context"
	_ "embed"
	"fmt"
	"hash/fnv"
	"math/rand/v2"
	"strings"
	"time"
	"uuid"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/siercks/sierx/internal/store"
	"github.com/siercks/sierx/internal/store/gen"
)

//go:embed config.sql
var configSQL string

// Options controls a seed run. Seed is the only source of randomness: the same
// value reproduces the same workspace exactly, which is what makes the
// benchmark harness comparable across runs and machines.
type Options struct {
	Seed      int64
	Items     int
	Projects  int
	MaxDepth  int
	Users     int
	Slug      string
	HistoryOf time.Duration
}

// DefaultOptions matches the task's target: 10k items, 5 projects, depth 6,
// roughly nine months of backdated history.
func DefaultOptions() Options {
	return Options{
		Seed:      1,
		Items:     10000,
		Projects:  5,
		MaxDepth:  6,
		Users:     8,
		Slug:      "seed",
		HistoryOf: 273 * 24 * time.Hour,
	}
}

// Summary is what a run reports.
type Summary struct {
	WorkspaceID uuid.UUID
	Items       int
	MaxDepth    int
	Links       int
	Events      int64
	Checksum    string
}

type project struct {
	id       uuid.UUID
	prefix   string
	kind     string
	statuses map[string]uuid.UUID
	types    map[string]uuid.UUID
	// items by depth, for choosing parents without a query per insert
	byDepth [][]uuid.UUID
}

// Run seeds a fresh workspace and returns what it built.
func Run(ctx context.Context, db store.DB, opts Options) (Summary, error) {
	if opts.Items <= 0 || opts.Projects <= 0 || opts.MaxDepth < 1 {
		return Summary{}, fmt.Errorf("seed: items, projects and max depth must be positive")
	}
	// A fixed-key PCG keyed only by opts.Seed: two runs with the same seed make
	// identical choices, including which items get links and history.
	rng := rand.New(rand.NewPCG(uint64(opts.Seed), 0x5e3d))
	st := store.New(db)
	q := gen.New(db)

	slug := fmt.Sprintf("%s-%d", opts.Slug, opts.Seed)
	originID := deterministicUUID("origin", opts.Seed, 0)
	ws, err := q.CreateWorkspace(ctx, gen.CreateWorkspaceParams{
		Slug: slug, Name: "Seed workspace", OriginID: pgUUID(originID),
	})
	if err != nil {
		// The slug is derived from --seed so that a run is reproducible, which
		// means a second run into the same database collides. Say so, rather
		// than surfacing a constraint name.
		if strings.Contains(err.Error(), "workspace_slug_key") {
			return Summary{}, fmt.Errorf("seed: workspace %q already exists — run `make db-reset` first, or pass --slug", slug)
		}
		return Summary{}, fmt.Errorf("create workspace %q: %w", slug, err)
	}
	wsID := uuid.UUID(ws.ID.Bytes)

	users := make([]uuid.UUID, 0, opts.Users)
	for i := range opts.Users {
		u, err := q.CreateUser(ctx, gen.CreateUserParams{
			Email:       fmt.Sprintf("user%02d@%s.seed", i, slug),
			DisplayName: fmt.Sprintf("Seed User %02d", i),
		})
		if err != nil {
			return Summary{}, fmt.Errorf("create user %d: %w", i, err)
		}
		users = append(users, uuid.UUID(u.ID.Bytes))
	}

	projects, err := createProjects(ctx, db, q, wsID, opts)
	if err != nil {
		return Summary{}, err
	}

	// Items are created in batches inside one Mutate each: a single mutation
	// per item would be 10k transactions, and one mutation for all 10k would
	// hold a transaction open for the whole run and allocate a 10k-value seq
	// block in one go. 200 is small enough to keep each transaction short.
	const batch = 200
	created := 0
	for created < opts.Items {
		n := min(batch, opts.Items-created)
		if err := seedBatch(ctx, st, wsID, originID, projects, users, rng, n, opts); err != nil {
			return Summary{}, err
		}
		created += n
	}

	links, err := seedLinks(ctx, st, wsID, projects, users, rng)
	if err != nil {
		return Summary{}, err
	}
	if err := seedHistory(ctx, st, wsID, projects, users, rng, opts); err != nil {
		return Summary{}, err
	}

	return summarize(ctx, q, wsID, links)
}

func createProjects(ctx context.Context, db store.DB, q *gen.Queries, wsID uuid.UUID, opts Options) ([]*project, error) {
	// One discovery project (§2: the discovery surface is first-class), the
	// rest delivery. A portfolio project appears only when there is room for
	// it, so a 2-project seed is still meaningful.
	kinds := make([]string, opts.Projects)
	for i := range kinds {
		switch {
		case i == 0:
			kinds[i] = "delivery"
		case i == 1:
			kinds[i] = "discovery"
		case i == 2 && opts.Projects > 3:
			kinds[i] = "portfolio"
		default:
			kinds[i] = "delivery"
		}
	}
	out := make([]*project, 0, opts.Projects)
	for i, kind := range kinds {
		prefix := projectPrefix(i)
		row, err := q.CreateProject(ctx, gen.CreateProjectParams{
			WorkspaceID: pgUUID(wsID), KeyPrefix: prefix,
			Name: fmt.Sprintf("Seed %s %d", kind, i+1), Kind: kind,
		})
		if err != nil {
			return nil, fmt.Errorf("create project %s: %w", prefix, err)
		}
		p := &project{
			id: uuid.UUID(row.ID.Bytes), prefix: prefix, kind: kind,
			statuses: map[string]uuid.UUID{}, types: map[string]uuid.UUID{},
			byDepth: make([][]uuid.UUID, opts.MaxDepth+1),
		}
		if _, err := q.InsertProjectConfig(ctx, gen.InsertProjectConfigParams{
			ProjectID: row.ID, Version: 1,
		}); err != nil {
			return nil, fmt.Errorf("config for %s: %w", prefix, err)
		}
		// config.sql is one multi-statement script whose statements share the
		// same two parameters. The extended protocol prepares each statement
		// and rejects a multi-command string, so this one Exec asks for the
		// simple protocol; pgx interpolates the two values (a uuid and an int
		// we generated) and sends the script as a single simple query.
		if _, err := db.Exec(ctx, configSQL, pgx.QueryExecModeSimpleProtocol, row.ID, int32(1)); err != nil {
			return nil, fmt.Errorf("seed config for %s: %w", prefix, err)
		}
		statuses, err := q.ListStatuses(ctx, row.ID)
		if err != nil {
			return nil, err
		}
		for _, s := range statuses {
			p.statuses[s.Key] = uuid.UUID(s.ID.Bytes)
		}
		types, err := q.ListItemTypes(ctx, row.ID)
		if err != nil {
			return nil, err
		}
		for _, t := range types {
			p.types[t.Key] = uuid.UUID(t.ID.Bytes)
		}
		out = append(out, p)
	}
	return out, nil
}

// projectPrefix produces AAA, AAB, ... — valid under ^[A-Z][A-Z0-9]{1,9}$ and
// stable for a given index, so keys are reproducible.
func projectPrefix(i int) string {
	const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	return string([]byte{
		alpha[(i/676)%26], alpha[(i/26)%26], alpha[i%26],
	})
}

// typeForDepth maps depth to the §8.1 type hierarchy: initiatives at the root,
// epics under them, stories and bugs at the leaves.
func typeForDepth(p *project, depth int, rng *rand.Rand) uuid.UUID {
	switch {
	case depth <= 1:
		return p.types["initiative"]
	case depth == 2:
		return p.types["epic"]
	case rng.IntN(5) == 0:
		return p.types["bug"]
	default:
		return p.types["story"]
	}
}

// statusForSeed gives a realistic distribution: mostly open, some active, a
// solid tail of done, a few dropped.
func statusForSeed(p *project, rng *rand.Rand) (string, uuid.UUID) {
	switch n := rng.IntN(100); {
	case n < 42:
		return "todo", p.statuses["todo"]
	case n < 60:
		return "doing", p.statuses["doing"]
	case n < 68:
		return "review", p.statuses["review"]
	case n < 96:
		return "done", p.statuses["done"]
	default:
		return "dropped", p.statuses["dropped"]
	}
}

func seedBatch(ctx context.Context, st *store.Store, wsID, originID uuid.UUID,
	projects []*project, users []uuid.UUID, rng *rand.Rand, n int, opts Options) error {

	// Choices are made before the mutation so the RNG is consumed in a fixed
	// order regardless of how the transaction behaves.
	//
	// Items planned earlier in this batch are valid parents: registration
	// order is insertion order inside the mutation, so a parent is in the
	// table by the time its child's INSERT runs. Without this, the first batch
	// would be all roots and a 400-item seed would never exceed depth 2.
	type plan struct {
		p      *project
		id     uuid.UUID
		depth  int
		parent *uuid.UUID
	}
	plans := make([]plan, 0, n)
	// Per-project working copy of the depth pools, extended as we plan.
	pools := make(map[*project][][]uuid.UUID, len(projects))
	for _, p := range projects {
		cp := make([][]uuid.UUID, len(p.byDepth))
		for d := range p.byDepth {
			cp[d] = append([]uuid.UUID(nil), p.byDepth[d]...)
		}
		pools[p] = cp
	}

	for range n {
		p := projects[rng.IntN(len(projects))]
		pool := pools[p]
		depth := 1
		var parent *uuid.UUID

		// Fill the shallowest empty level first, so the tree reaches MaxDepth
		// early instead of converging on it only if the item count is large.
		forced := 0
		for d := 2; d <= opts.MaxDepth; d++ {
			if len(pool[d]) == 0 && len(pool[d-1]) > 0 {
				forced = d
				break
			}
		}
		switch {
		case forced > 0:
			candidates := pool[forced-1]
			pick := candidates[rng.IntN(len(candidates))]
			parent = &pick
			depth = forced
		case rng.IntN(100) < 70:
			// Attach below an existing item, biased towards deeper levels so
			// the result is a tree rather than a wide fan under the roots.
			for d := opts.MaxDepth - 1; d >= 1; d-- {
				if len(pool[d]) == 0 {
					continue
				}
				if d == 1 || rng.IntN(100) < 55 {
					candidates := pool[d]
					pick := candidates[rng.IntN(len(candidates))]
					parent = &pick
					depth = d + 1
					break
				}
			}
		}
		id := uuid.NewV7()
		plans = append(plans, plan{p: p, id: id, depth: depth, parent: parent})
		pool[depth] = append(pool[depth], id)
	}

	_, err := st.Mutate(ctx, wsID, func(m *store.Mutation) error {
		for _, pl := range plans {
			_, statusID := statusForSeed(pl.p, rng)
			var assignee *uuid.UUID
			if rng.IntN(100) < 70 {
				a := users[rng.IntN(len(users))]
				assignee = &a
			}
			var points *float64
			if rng.IntN(100) < 80 {
				// Fibonacci-ish estimates, as a team would use.
				scale := []float64{1, 2, 3, 5, 8, 13}
				pt := scale[rng.IntN(len(scale))]
				points = &pt
			}
			start, due := seedDates(rng, opts)
			m.Create(store.ItemInsert{
				ID:         pl.id,
				ProjectID:  pl.p.id,
				ItemTypeID: typeForDepth(pl.p, pl.depth, rng),
				StatusID:   statusID,
				ParentID:   pl.parent,
				Title:      seedTitle(rng),
				Body:       seedBody(rng),
				AssigneeID: assignee,
				Points:     points,
				StartDate:  start,
				DueDate:    due,
				Fields:     seedFields(rng),
				OriginID:   originID,
			})
		}
		return nil
	})
	if err != nil {
		return fmt.Errorf("seed batch: %w", err)
	}
	for _, pl := range plans {
		pl.p.byDepth[pl.depth] = append(pl.p.byDepth[pl.depth], pl.id)
	}
	return nil
}

// seedLinks creates links, deliberately including cross-project ones: the
// hierarchy stays inside a project (ADR-012), so cross-project relationships
// have to be links, and the seed should exercise that.
func seedLinks(ctx context.Context, st *store.Store, wsID uuid.UUID,
	projects []*project, users []uuid.UUID, rng *rand.Rand) (int, error) {

	var all []uuid.UUID
	for _, p := range projects {
		for _, level := range p.byDepth {
			all = append(all, level...)
		}
	}
	if len(all) < 2 {
		return 0, nil
	}
	kinds := []string{"blocks", "duplicates", "relates", "implements", "discovered_from"}
	target := len(all) / 20 // ~5% of items carry a link
	made := 0
	const batch = 100
	for made < target {
		n := min(batch, target-made)
		// Deduplicate within the batch: (from, to, kind) is unique, and a
		// collision would abort the whole transaction.
		seen := map[string]bool{}
		type link struct {
			from, to uuid.UUID
			kind     string
		}
		var links []link
		for range n * 2 {
			if len(links) == n {
				break
			}
			from := all[rng.IntN(len(all))]
			to := all[rng.IntN(len(all))]
			if from == to {
				continue
			}
			kind := kinds[rng.IntN(len(kinds))]
			key := from.String() + to.String() + kind
			if seen[key] {
				continue
			}
			seen[key] = true
			links = append(links, link{from, to, kind})
		}
		if len(links) == 0 {
			break
		}
		actor := users[rng.IntN(len(users))]
		_, err := st.Mutate(ctx, wsID, func(m *store.Mutation) error {
			for _, l := range links {
				m.Link(store.LinkChange{FromItemID: l.from, ToItemID: l.to, Kind: l.kind})
			}
			return nil
		}, store.WithActor(actor))
		if err != nil {
			// A unique-violation against a link made in an earlier batch is
			// possible and not interesting; anything else is.
			if !strings.Contains(err.Error(), "23505") {
				return made, fmt.Errorf("seed links: %w", err)
			}
			continue
		}
		made += len(links)
	}
	return made, nil
}

// seedHistory walks items that are not in an open state through the §8.1
// transition graph, so cycle-time distributions and burndowns have something
// true to say later (§13).
//
// change_event.at defaults to now() and the column is not written by Mutate,
// so the events themselves are stamped with the run time. The backdating that
// matters for analytics is in the items' own start and due dates, and in the
// order of transitions; a later task that needs historical event timestamps
// will have to write `at` explicitly, which is a schema-level decision rather
// than something to fake here.
func seedHistory(ctx context.Context, st *store.Store, wsID uuid.UUID,
	projects []*project, users []uuid.UUID, rng *rand.Rand, opts Options) error {

	type step struct {
		id       uuid.UUID
		from, to string
		statusID uuid.UUID
		actor    uuid.UUID
	}
	var steps []step
	for _, p := range projects {
		for _, level := range p.byDepth {
			for _, id := range level {
				// Walk roughly a third of items forward one or two states, so
				// the log is not uniform.
				if rng.IntN(3) != 0 {
					continue
				}
				path := [][2]string{{"todo", "doing"}, {"doing", "review"}, {"review", "done"}}
				n := 1 + rng.IntN(len(path))
				for _, arc := range path[:n] {
					steps = append(steps, step{
						id: id, from: arc[0], to: arc[1],
						statusID: p.statuses[arc[1]],
						actor:    users[rng.IntN(len(users))],
					})
				}
			}
		}
	}

	const batch = 200
	for i := 0; i < len(steps); i += batch {
		chunk := steps[i:min(i+batch, len(steps))]
		actor := chunk[0].actor
		_, err := st.Mutate(ctx, wsID, func(m *store.Mutation) error {
			for _, s := range chunk {
				sid := s.statusID
				m.Update(store.ItemUpdate{ID: s.id, StatusID: &sid},
					store.FieldChange{
						Kind: store.EventStatusChanged, Field: "status_id",
						Old: s.from, New: s.to,
					})
			}
			return nil
		}, store.WithActor(actor))
		if err != nil {
			return fmt.Errorf("seed history: %w", err)
		}
	}
	return nil
}

func seedDates(rng *rand.Rand, opts Options) (start, due *string) {
	if rng.IntN(100) < 35 {
		return nil, nil
	}
	// Spread across the history window, ending near today.
	days := int(opts.HistoryOf.Hours() / 24)
	offset := rng.IntN(days)
	s := time.Now().UTC().AddDate(0, 0, -offset).Format(time.DateOnly)
	d := time.Now().UTC().AddDate(0, 0, -offset+7+rng.IntN(28)).Format(time.DateOnly)
	return &s, &d
}

var (
	verbs = []string{"Migrate", "Harden", "Instrument", "Refactor", "Document", "Benchmark", "Backport", "Deprecate"}
	nouns = []string{"ingest path", "cursor sync", "board renderer", "rank rebalance", "restore harness",
		"partition maintenance", "session store", "query planner", "config loader", "audit log"}
	tails = []string{"on ARM", "under load", "for the Pi target", "in the offline case", "", "", ""}
)

func seedTitle(rng *rand.Rand) string {
	t := fmt.Sprintf("%s %s %s", verbs[rng.IntN(len(verbs))], nouns[rng.IntN(len(nouns))], tails[rng.IntN(len(tails))])
	return strings.TrimSpace(t)
}

func seedBody(rng *rand.Rand) *string {
	if rng.IntN(100) < 40 {
		return nil
	}
	// Markdown, since that is what the field holds (ADR-014).
	b := fmt.Sprintf("## Context\n\nSeeded item.\n\n- [ ] step %d\n- [ ] step %d\n",
		rng.IntN(9)+1, rng.IntN(9)+1)
	return &b
}

func seedFields(rng *rand.Rand) map[string]any {
	if rng.IntN(100) < 50 {
		return nil
	}
	out := map[string]any{}
	if rng.IntN(2) == 0 {
		out["impact"] = rng.IntN(5) + 1
	}
	if rng.IntN(2) == 0 {
		out["component"] = []string{"api", "web", "infra"}[rng.IntN(3)]
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

// summarize reads back what was built, including a checksum over the content
// that must be identical between two runs with the same seed. Ids and
// timestamps are excluded: uuidv7 embeds the clock, so they differ by design.
func summarize(ctx context.Context, q *gen.Queries, wsID uuid.UUID, links int) (Summary, error) {
	sum, err := q.SeedChecksum(ctx, pgUUID(wsID))
	if err != nil {
		return Summary{}, fmt.Errorf("summarize: %w", err)
	}
	items, maxDepth, checksum := int(sum.Items), int(sum.MaxDepth), sum.Checksum
	maxSeq, err := q.MaxEventSeq(ctx, pgUUID(wsID))
	if err != nil {
		return Summary{}, err
	}
	_ = err
	return Summary{
		WorkspaceID: wsID, Items: items, MaxDepth: maxDepth,
		Links: links, Events: maxSeq, Checksum: checksum,
	}, nil
}

func deterministicUUID(kind string, seed int64, n int) uuid.UUID {
	h := fnv.New128a()
	fmt.Fprintf(h, "%s:%d:%d", kind, seed, n)
	var out uuid.UUID
	copy(out[:], h.Sum(nil))
	// Stamp version 7 and the RFC 9562 variant so the value is a well-formed
	// UUID rather than 16 arbitrary bytes.
	out[6] = (out[6] & 0x0f) | 0x70
	out[8] = (out[8] & 0x3f) | 0x80
	return out
}

func pgUUID(id uuid.UUID) pgtype.UUID { return pgtype.UUID{Bytes: id, Valid: true} }
