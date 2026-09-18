// Package store is the only package that writes item, item_link, sprint_item
// and comment. Everything goes through Mutate, which allocates the change
// sequence, applies row changes, maintains rollups and writes the event log in
// one transaction. gate-nodirect enforces the boundary; this file is why the
// boundary is worth having.
package store

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"uuid"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/siercks/sierx/internal/store/gen"
)

// Store owns a pgx connection pool's worth of behaviour. The concrete pool
// type is left to the caller (task 1.1 supplies it) — all this package needs is
// the ability to begin a transaction and run queries.
type Store struct {
	db DB
	q  *gen.Queries
}

// DB is the subset of pgx a Store needs, so tests can pass a single connection
// and the server can pass a pool.
type DB interface {
	gen.DBTX
	Begin(ctx context.Context) (pgx.Tx, error)
}

// New returns a Store over db.
func New(db DB) *Store {
	return &Store{db: db, q: gen.New(db)}
}

// WithExpectedVersion checks the caller's version after sequence allocation
// has serialized workspace writers, before any governed row is changed.
func WithExpectedVersion(id uuid.UUID, version int32) MutateOption {
	return func(m *Mutation) {
		if m.expected == nil {
			m.expected = map[uuid.UUID]int32{}
		}
		m.expected[id] = version
	}
}

// Queries exposes read-only generated queries for callers outside this package.
// Writes are not reachable this way: the generated writers take parameters this
// package builds during flush, and gate-nodirect fails any package outside
// internal/store that mentions a governed table.
func (s *Store) Queries() *gen.Queries { return s.q }

var (
	// ErrNoEvents is returned when a mutation would change rows without
	// describing the change (ADR-001).
	ErrNoEvents = errors.New("store: mutation has row changes but no events")
	// ErrEmpty is returned for a mutation that registered nothing.
	ErrEmpty = errors.New("store: mutation is empty")
	// ErrVersionConflict maps to 409 (§5.4).
	ErrVersionConflict = errors.New("store: item version conflict")
	ErrInvalidMove     = errors.New("store: invalid hierarchy move")
)

// Result reports what a mutation did. HighestSeq is the value a client can use
// as its next `since_seq` cursor.
type Result struct {
	HighestSeq int64
	LowestSeq  int64
	EventCount int
	ItemIDs    []uuid.UUID
}

// MutateOption configures a mutation before the callback runs.
type MutateOption func(*Mutation)

// WithActor records who is making the change.
func WithActor(id uuid.UUID) MutateOption {
	return func(m *Mutation) { m.actorID, m.hasActor = id, true }
}

// Mutate is the single write path. It opens a transaction, runs fn to
// accumulate changes, then flushes them in the order ADR-002 and §5.2 require.
//
// There is deliberately no event-count parameter (ADR-002) and no
// WithoutEvents escape hatch: the sequence block is sized from the accumulated
// events, so a caller cannot get the arithmetic wrong.
func (s *Store) Mutate(ctx context.Context, workspaceID uuid.UUID, fn func(*Mutation) error, opts ...MutateOption) (Result, error) {
	m := &Mutation{workspaceID: workspaceID}
	for _, o := range opts {
		o(m)
	}
	if err := fn(m); err != nil {
		return Result{}, err
	}
	if m.err != nil {
		return Result{}, m.err
	}
	if len(m.changes) == 0 {
		return Result{}, ErrEmpty
	}
	for _, c := range m.changes {
		if len(c.events) == 0 {
			return Result{}, fmt.Errorf("%w: %s", ErrNoEvents, c.itemID)
		}
	}

	tx, err := s.db.Begin(ctx)
	if err != nil {
		return Result{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	res, err := s.flush(ctx, tx, m)
	if err != nil {
		return Result{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Result{}, err
	}
	return res, nil
}

// flush applies the mutation inside tx, in the order BUILD task 0.8 step 2
// prescribes.
func (s *Store) flush(ctx context.Context, tx pgx.Tx, m *Mutation) (Result, error) {
	q := gen.New(tx)
	n := m.eventCount()

	// (a) One statement bumps the counter by the number of events and returns
	// the highest value allocated (ADR-002, §5.1). Row-locked, so the sequence
	// is gap-free and commit-ordered — which a bigserial is not.
	highest, err := q.AllocateSeq(ctx, gen.AllocateSeqParams{
		N:           int64(n),
		WorkspaceID: toPgUUID(m.workspaceID),
	})
	if err != nil {
		return Result{}, fmt.Errorf("allocate %d seq values: %w", n, err)
	}
	lowest := highest - int64(n) + 1
	for id, expected := range m.expected {
		var actual int32
		err := tx.QueryRow(ctx, `SELECT version FROM item WHERE id=$1 AND workspace_id=$2 AND deleted_at IS NULL FOR UPDATE`, id.String(), m.workspaceID.String()).Scan(&actual)
		if errors.Is(err, pgx.ErrNoRows) || err == nil && actual != expected {
			return Result{}, ErrVersionConflict
		}
		if err != nil {
			return Result{}, err
		}
	}

	// (b) Assign seq to each event in registration order; each item's
	// change_seq becomes the highest value assigned to any of its events.
	next := lowest
	itemSeq := make(map[uuid.UUID]int64, len(m.changes))
	for ci := range m.changes {
		c := &m.changes[ci]
		for ei := range c.events {
			c.events[ei].seq = next
			if id := c.events[ei].itemID; id != (uuid.UUID{}) {
				if next > itemSeq[id] {
					itemSeq[id] = next
				}
			}
			next++
		}
	}

	// (c)–(e) Apply row changes.
	var (
		itemIDs   []uuid.UUID
		created   []uuid.UUID
		hardDeled = map[uuid.UUID]bool{}
	)
	for ci := range m.changes {
		c := &m.changes[ci]
		seq := itemSeq[c.itemID]
		switch c.kind {
		case changeInsert:
			if err := s.applyInsert(ctx, tx, q, m, c.insert, seq); err != nil {
				return Result{}, err
			}
			created = append(created, c.insert.ID)
			m.touchedPaths = append(m.touchedPaths, c.insert.path)

		case changeUpdate:
			if err := s.applyUpdate(ctx, q, m, c.update, seq); err != nil {
				return Result{}, err
			}

		case changeReparent:
			if err := s.applyReparent(ctx, tx, q, m, c.reparen, seq); err != nil {
				return Result{}, err
			}

		case changeSoftDelete:
			row, err := q.SoftDeleteItem(ctx, gen.SoftDeleteItemParams{
				ID: toPgUUID(c.itemID), ChangeSeq: seq,
			})
			if err != nil {
				return Result{}, fmt.Errorf("soft delete %s: %w", c.itemID, err)
			}
			m.touchedPaths = append(m.touchedPaths, row.Path)

		case changeHardDelete:
			// §5.8: the terminal event is inserted below, in the same
			// transaction, after the row is gone. Order within the transaction
			// does not matter for durability; that the event exists does.
			row, err := q.GetItem(ctx, toPgUUID(c.itemID))
			if err != nil {
				return Result{}, fmt.Errorf("hard delete %s: %w", c.itemID, err)
			}
			m.touchedPaths = append(m.touchedPaths, row.Path)
			if err := q.HardDeleteItem(ctx, toPgUUID(c.itemID)); err != nil {
				return Result{}, fmt.Errorf("hard delete %s: %w", c.itemID, err)
			}
			hardDeled[c.itemID] = true

		case changeLink:
			if _, err := q.InsertLink(ctx, gen.InsertLinkParams{
				ID:         toPgUUID(c.link.ID),
				FromItemID: toPgUUID(c.link.FromItemID),
				ToItemID:   toPgUUID(c.link.ToItemID),
				Kind:       c.link.Kind,
				CreatedBy:  toPgUUIDPtr(actorPtr(m)),
			}); err != nil {
				return Result{}, fmt.Errorf("link %s -> %s: %w", c.link.FromItemID, c.link.ToItemID, err)
			}

		case changeUnlink:
			if err := q.DeleteLink(ctx, toPgUUID(c.link.ID)); err != nil {
				return Result{}, fmt.Errorf("unlink %s: %w", c.link.ID, err)
			}
		}
		if c.kind == changeLink || c.kind == changeUnlink {
			if _, err := tx.Exec(ctx, `UPDATE item SET version=version+1,change_seq=$2,updated_at=now() WHERE id=$1`, c.itemID.String(), seq); err != nil {
				return Result{}, err
			}
		}
		if c.itemID != (uuid.UUID{}) {
			itemIDs = append(itemIDs, c.itemID)
		}
	}

	// (e) ADR-013: a rollup row for every created item, so
	// count(item_rollup) == count(item) always holds and leaves are all-zero
	// rows rather than missing rows.
	for _, id := range created {
		if err := q.InsertRollupRow(ctx, toPgUUID(id)); err != nil {
			return Result{}, fmt.Errorf("rollup row for %s: %w", id, err)
		}
	}

	// (f) Recompute each dirty ancestor exactly once (ADR-005, §5.2).
	dirty := dirtyAncestors(m.touchedPaths)
	live := make([]uuid.UUID, 0, len(dirty))
	for _, id := range dirty {
		if !hardDeled[id] {
			live = append(live, id)
		}
	}
	if err := recomputeRollups(ctx, q, live); err != nil {
		return Result{}, err
	}

	// (g) Insert the events.
	for _, c := range m.changes {
		for _, ev := range c.events {
			if err := q.InsertEvent(ctx, gen.InsertEventParams{
				WorkspaceID: toPgUUID(m.workspaceID),
				Seq:         ev.seq,
				ItemID:      eventItemUUID(ev),
				ActorID:     eventActorUUID(ev),
				Kind:        ev.kind,
				Field:       ev.field,
				OldValue:    ev.oldValue,
				NewValue:    ev.newValue,
			}); err != nil {
				return Result{}, fmt.Errorf("insert event %s seq %d: %w", ev.kind, ev.seq, err)
			}
		}
	}

	// (h) item.version is bumped by the UPDATE statements themselves (§5.4);
	// inserts start at 1. Nothing to do here, which is the point of doing it in
	// SQL: there is no path that writes an item without bumping it.
	return Result{
		HighestSeq: highest,
		LowestSeq:  lowest,
		EventCount: n,
		ItemIDs:    itemIDs,
	}, nil
}

func (s *Store) applyInsert(ctx context.Context, db gen.DBTX, q *gen.Queries, m *Mutation, in *ItemInsert, seq int64) error {
	if in.OriginSeq == nil {
		in.OriginSeq = &seq
	}
	// Key from the project's monotonic counter (§A.1), never reused or reset.
	keyRow, err := q.NextItemKey(ctx, toPgUUID(in.ProjectID))
	if err != nil {
		return fmt.Errorf("next key for project %s: %w", in.ProjectID, err)
	}
	in.key = keyRow.Key

	// Path includes the item's own id as the final label (§5.3). The database
	// also enforces this, plus agreement with parent_id.
	if in.ParentID == nil {
		in.path = in.ID.String()
	} else {
		parent, err := q.GetItem(ctx, toPgUUID(*in.ParentID))
		if err != nil {
			return fmt.Errorf("parent %s: %w", *in.ParentID, err)
		}
		if parent.ProjectID != toPgUUID(in.ProjectID) {
			// ADR-012: hierarchy stays within a project; cross-project
			// relationships are links.
			return fmt.Errorf("store: parent %s is in another project (ADR-012)", *in.ParentID)
		}
		in.path = parent.Path + "." + in.ID.String()
	}

	// config_version is set on create (ADR-006).
	cfg := in.ConfigVersion
	if cfg == nil {
		v, err := q.LatestConfigVersion(ctx, toPgUUID(in.ProjectID))
		if err != nil {
			return fmt.Errorf("latest config version for %s: %w", in.ProjectID, err)
		}
		cfg = &v
	}

	if in.rank == "" {
		rank, err := s.rankForNewItem(ctx, db, q, in.ProjectID)
		if err != nil {
			return err
		}
		in.rank = rank
	}

	fields, err := marshalFields(in.Fields)
	if err != nil {
		return err
	}
	_, err = q.InsertItem(ctx, gen.InsertItemParams{
		ID:            toPgUUID(in.ID),
		WorkspaceID:   toPgUUID(m.workspaceID),
		ProjectID:     toPgUUID(in.ProjectID),
		Key:           in.key,
		ItemTypeID:    toPgUUID(in.ItemTypeID),
		StatusID:      toPgUUID(in.StatusID),
		ConfigVersion: *cfg,
		ParentID:      toPgUUIDPtr(in.ParentID),
		Path:          in.path,
		Title:         in.Title,
		Body:          in.Body,
		AssigneeID:    toPgUUIDPtr(in.AssigneeID),
		Points:        toPgNumeric(in.Points),
		StartDate:     toPgDate(in.StartDate),
		DueDate:       toPgDate(in.DueDate),
		Rank:          in.rank,
		Fields:        fields,
		ChangeSeq:     seq,
		OriginID:      toPgUUID(in.OriginID),
		OriginSeq:     in.OriginSeq,
	})
	if err != nil {
		return fmt.Errorf("insert item %s: %w", in.ID, err)
	}
	return nil
}

func (s *Store) applyUpdate(ctx context.Context, q *gen.Queries, m *Mutation, up *ItemUpdate, seq int64) error {
	fields, err := marshalFieldsPatch(up.Fields)
	if err != nil {
		return err
	}
	row, err := q.UpdateItemFields(ctx, gen.UpdateItemFieldsParams{
		ID:            toPgUUID(up.ID),
		Title:         up.Title,
		Body:          up.Body,
		SetBody:       up.SetBody,
		StatusID:      toPgUUIDPtr(up.StatusID),
		ConfigVersion: up.ConfigVersion,
		AssigneeID:    toPgUUIDPtr(up.AssigneeID),
		SetAssignee:   up.SetAssignee,
		Points:        toPgNumeric(up.Points),
		SetPoints:     up.SetPoints,
		StartDate:     toPgDate(up.StartDate),
		SetStartDate:  up.SetStartDate,
		DueDate:       toPgDate(up.DueDate),
		SetDueDate:    up.SetDueDate,
		Rank:          up.Rank,
		Fields:        fields,
		ChangeSeq:     seq,
	})
	if err != nil {
		return fmt.Errorf("update item %s: %w", up.ID, err)
	}
	// A status change alters the ancestors' done_count and points_done, so the
	// item's own path is dirty even though its position did not move.
	m.touchedPaths = append(m.touchedPaths, row.Path)
	return nil
}

func (s *Store) applyReparent(ctx context.Context, db gen.DBTX, q *gen.Queries, m *Mutation, r *ItemReparent, seq int64) error {
	item, err := q.GetItem(ctx, toPgUUID(r.ID))
	if err != nil {
		return fmt.Errorf("reparent %s: %w", r.ID, err)
	}
	newParentPath := ""
	if r.NewParentID != nil {
		parent, err := q.GetItem(ctx, toPgUUID(*r.NewParentID))
		if err != nil {
			return fmt.Errorf("reparent %s: new parent %s: %w", r.ID, *r.NewParentID, err)
		}
		if parent.ProjectID != item.ProjectID || parent.DeletedAt.Valid {
			return ErrInvalidMove
		}
		// §5.3: reject a move that would make the item its own ancestor. The
		// database trigger rejects it too; this produces a usable error instead
		// of a constraint violation.
		if isDescendantOrSelf(parent.Path, item.Path) {
			return ErrInvalidMove
		}
		newParentPath = parent.Path
	}
	var height int
	if err := db.QueryRow(ctx, `SELECT max(nlevel(path))-nlevel($1::ltree)+1 FROM item WHERE path <@ $1::ltree`, item.Path).Scan(&height); err != nil {
		return err
	}
	depth := 0
	if newParentPath != "" {
		depth = strings.Count(newParentPath, ".") + 1
	}
	if depth+height > 8 {
		return ErrInvalidMove
	}
	// The old path is dirty (its former ancestors lose descendants) and so is
	// the new one (its new ancestors gain them).
	m.touchedPaths = append(m.touchedPaths, item.Path)

	// One statement rewrites the item and every descendant (§5.3).
	rows, err := q.ReparentSubtree(ctx, gen.ReparentSubtreeParams{
		ItemID:        toPgUUID(r.ID),
		NewParentID:   toPgUUIDPtr(r.NewParentID),
		NewParentPath: newParentPath,
		OldPath:       item.Path,
		ChangeSeq:     seq,
	})
	if err != nil {
		return fmt.Errorf("reparent subtree %s: %w", r.ID, err)
	}
	for _, row := range rows {
		m.touchedPaths = append(m.touchedPaths, row.Path)
	}
	if r.SetRank {
		for attempt := 0; attempt < 2; attempt++ {
			ranks, err := q.ListProjectRanks(ctx, item.ProjectID)
			if err != nil {
				return err
			}
			lo, hi := "", ""
			found := r.RankAfter == nil
			for _, candidate := range ranks {
				if candidate.ID == item.ID {
					continue
				}
				if found {
					hi = candidate.Rank
					break
				}
				if fromPgUUID(candidate.ID) == *r.RankAfter {
					lo = candidate.Rank
					found = true
				}
			}
			if !found {
				return ErrInvalidMove
			}
			rank, err := RankBetween(lo, hi)
			if err != nil {
				return err
			}
			if RankNeedsRebalance(rank) {
				if err := rebalanceProjectRanks(ctx, db, q, fromPgUUID(item.ProjectID), ranks); err != nil {
					return err
				}
				continue
			}
			_, err = db.Exec(ctx, `UPDATE item SET rank=$2 WHERE id=$1`, r.ID.String(), rank)
			return err
		}
		return ErrRankOrder
	}
	return nil
}

// rankForNewItem appends after the project's current last rank, rebalancing
// first if the generated key would exceed the §5.5 threshold.
func (s *Store) rankForNewItem(ctx context.Context, db gen.DBTX, q *gen.Queries, projectID uuid.UUID) (string, error) {
	ranks, err := q.ListProjectRanks(ctx, toPgUUID(projectID))
	if err != nil {
		return "", err
	}
	last := ""
	if len(ranks) > 0 {
		last = ranks[len(ranks)-1].Rank
	}
	rank, err := RankBetween(last, "")
	if err != nil {
		return "", err
	}
	if RankNeedsRebalance(rank) {
		if err := rebalanceProjectRanks(ctx, db, q, projectID, ranks); err != nil {
			return "", err
		}
		ranks, err = q.ListProjectRanks(ctx, toPgUUID(projectID))
		if err != nil {
			return "", err
		}
		last = ""
		if len(ranks) > 0 {
			last = ranks[len(ranks)-1].Rank
		}
		return RankBetween(last, "")
	}
	return rank, nil
}

// rebalanceProjectRanks respreads a project's ranks evenly (§5.5, ADR-003).
// The caller is already inside a transaction; the unique constraint on
// (project_id, rank) is deferred for the duration so intermediate collisions
// during the respread cannot abort it. (Task 0.5 established that a DEFERRABLE
// constraint is checked at end of statement even while immediate, so this
// matters only because the respread is one UPDATE per row.)
func rebalanceProjectRanks(ctx context.Context, db gen.DBTX, q *gen.Queries, projectID uuid.UUID, ranks []gen.ListProjectRanksRow) error {
	// SET CONSTRAINTS is a transaction-control statement, not a query sqlc can
	// model, so it goes through the connection directly.
	if _, err := db.Exec(ctx, "SET CONSTRAINTS item_project_rank_uniq DEFERRED"); err != nil {
		return fmt.Errorf("defer rank constraint: %w", err)
	}
	fresh := RankSequence(len(ranks))
	for i, r := range ranks {
		if err := q.UpdateItemRank(ctx, gen.UpdateItemRankParams{ID: r.ID, Rank: fresh[i]}); err != nil {
			return fmt.Errorf("rebalance %s: %w", fromPgUUID(r.ID), err)
		}
	}
	if _, err := db.Exec(ctx, "SET CONSTRAINTS item_project_rank_uniq IMMEDIATE"); err != nil {
		return fmt.Errorf("restore rank constraint: %w", err)
	}
	return nil
}

// RebalanceProject respreads one project's ranks. Exposed for the property
// tests (ADR-003 requires a 5,000-item rebalance to commit) and for an
// operator path; it goes through Mutate like everything else, carrying a
// field_changed event per item would be 5,000 events for a mechanical
// respread, so it is its own transaction with a single summarising event.
func (s *Store) RebalanceProject(ctx context.Context, workspaceID, projectID uuid.UUID) (int, error) {
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	q := gen.New(tx)

	ranks, err := q.ListProjectRanks(ctx, toPgUUID(projectID))
	if err != nil {
		return 0, err
	}
	seq, err := q.AllocateSeq(ctx, gen.AllocateSeqParams{N: 1, WorkspaceID: toPgUUID(workspaceID)})
	if err != nil {
		return 0, err
	}
	if err := rebalanceProjectRanks(ctx, tx, q, projectID, ranks); err != nil {
		return 0, err
	}
	field := "rank"
	payload := fmt.Appendf(nil, `{"rebalanced":%d,"project_id":%q}`, len(ranks), projectID.String())
	if err := q.InsertEvent(ctx, gen.InsertEventParams{
		WorkspaceID: toPgUUID(workspaceID),
		Seq:         seq,
		Kind:        EventFieldChanged,
		Field:       &field,
		NewValue:    payload,
	}); err != nil {
		return 0, err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, err
	}
	return len(ranks), nil
}

// HardDeleteItem is the only hard-delete path (§5.8). It is a method rather
// than a Mutation verb so that the CLI is the only caller that can reach it,
// and it writes the terminal event in the same transaction by construction.
func (s *Store) HardDeleteItem(ctx context.Context, workspaceID, itemID uuid.UUID, opts ...MutateOption) (Result, error) {
	return s.Mutate(ctx, workspaceID, func(m *Mutation) error {
		m.hardDelete(itemID)
		return nil
	}, opts...)
}

// isDescendantOrSelf reports whether candidate is at or below ancestor in the
// ltree sense, comparing whole labels so a shared prefix within a label cannot
// produce a false positive.
func isDescendantOrSelf(candidate, ancestor string) bool {
	if candidate == ancestor {
		return true
	}
	return strings.HasPrefix(candidate, ancestor+".")
}

func actorPtr(m *Mutation) *uuid.UUID {
	if !m.hasActor {
		return nil
	}
	id := m.actorID
	return &id
}

func eventItemUUID(ev event) pgtype.UUID {
	if !ev.hasItem {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: ev.itemID, Valid: true}
}

func eventActorUUID(ev event) pgtype.UUID {
	if !ev.hasActor {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: ev.actorID, Valid: true}
}
