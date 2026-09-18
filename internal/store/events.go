package store

import (
	"encoding/json"
	"fmt"
	"uuid"
)

// Event kinds (SPEC §4.7).
const (
	EventCreated       = "created"
	EventFieldChanged  = "field_changed"
	EventStatusChanged = "status_changed"
	EventMoved         = "moved"
	EventLinked        = "linked"
	EventUnlinked      = "unlinked"
	EventPromoted      = "promoted"
	EventDeleted       = "deleted"
)

// event is a pending change_event row. seq is assigned at flush, never by the
// caller (§5.1).
type event struct {
	itemID   uuid.UUID
	hasItem  bool
	actorID  uuid.UUID
	hasActor bool
	kind     string
	field    *string
	oldValue []byte
	newValue []byte
	seq      int64
}

// change is a pending row change. Every change carries the events that
// describe it: the only way to register one is through a method that takes its
// events, so "a row change with no event" is not a value this package can
// construct. That is ADR-001 as a type property rather than a review comment.
type change struct {
	kind    changeKind
	itemID  uuid.UUID
	events  []event
	insert  *ItemInsert
	update  *ItemUpdate
	reparen *ItemReparent
	link    *LinkChange
	comment *CommentChange
	hard    bool
}

type changeKind int

const (
	changeInsert changeKind = iota
	changeUpdate
	changeReparent
	changeSoftDelete
	changeHardDelete
	changeLink
	changeUnlink
	changeComment
)

// Mutation accumulates row changes and their events inside one Mutate call.
// It is not safe for concurrent use; one Mutation belongs to one transaction.
type Mutation struct {
	expected    map[uuid.UUID]int32
	workspaceID uuid.UUID
	actorID     uuid.UUID
	hasActor    bool
	changes     []change
	// touched paths drive the dirty ancestor set (§5.2, ADR-005).
	touchedPaths []string
	err          error
}

// WorkspaceID is the workspace every change in this mutation belongs to.
func (m *Mutation) WorkspaceID() uuid.UUID { return m.workspaceID }

// Actor returns the acting user, if the caller supplied one.
func (m *Mutation) Actor() (uuid.UUID, bool) { return m.actorID, m.hasActor }

// ItemInsert is a create. Rank, path and key are computed by the store, not
// by callers: path must end in the item's own id (§5.3) and keys come from the
// project's monotonic counter (§A.1).
type ItemInsert struct {
	ID            uuid.UUID
	ProjectID     uuid.UUID
	ItemTypeID    uuid.UUID
	StatusID      uuid.UUID
	ParentID      *uuid.UUID
	Title         string
	Body          *string
	AssigneeID    *uuid.UUID
	Points        *float64
	StartDate     *string // date, not timestamptz (§A.3)
	DueDate       *string
	Fields        map[string]any
	OriginID      uuid.UUID
	OriginSeq     *int64
	ConfigVersion *int32

	// resolved during flush
	key  string
	path string
	rank string
}

// ItemUpdate is a field change. A nil pointer means "leave alone"; the Set*
// flags distinguish "leave alone" from "set to NULL" for nullable columns.
type ItemUpdate struct {
	ID            uuid.UUID
	Title         *string
	Body          *string
	SetBody       bool
	StatusID      *uuid.UUID
	ConfigVersion *int32
	AssigneeID    *uuid.UUID
	SetAssignee   bool
	Points        *float64
	SetPoints     bool
	StartDate     *string
	SetStartDate  bool
	DueDate       *string
	SetDueDate    bool
	Rank          *string
	Fields        map[string]any
}

// ItemReparent moves an item and its whole subtree. NewParentID nil means
// "move to the root".
type ItemReparent struct {
	ID          uuid.UUID
	NewParentID *uuid.UUID
	SetRank     bool
	RankAfter   *uuid.UUID
}

// LinkChange is a link create or delete (§4.6).
type LinkChange struct {
	ID         uuid.UUID
	FromItemID uuid.UUID
	ToItemID   uuid.UUID
	Kind       string
}

type CommentChange struct {
	ID      uuid.UUID
	ItemID  uuid.UUID
	Action  string
	Body    string
	OldBody *string
}

// Comment changes share the owning item's version and sequence ordering.
func (m *Mutation) Comment(c CommentChange) *Mutation {
	if c.Action != "create" && c.Action != "edit" && c.Action != "delete" {
		m.fail(fmt.Errorf("store: invalid comment action"))
		return m
	}
	if !m.hasActor {
		m.fail(fmt.Errorf("store: comment requires an actor"))
		return m
	}
	if c.ID == (uuid.UUID{}) {
		c.ID = uuid.NewV7()
	}
	var old any
	if c.OldBody != nil {
		old = map[string]any{"id": c.ID.String(), "body": *c.OldBody}
	}
	newValue := map[string]any{"id": c.ID.String(), "body": c.Body, "deleted": c.Action == "delete"}
	if c.Action == "delete" {
		newValue["body"] = nil
	}
	ev, err := m.fieldEvent(c.ItemID, FieldChange{Field: "comment", Old: old, New: newValue})
	if err != nil {
		m.fail(err)
		return m
	}
	m.changes = append(m.changes, change{kind: changeComment, itemID: c.ItemID, comment: &c, events: []event{ev}})
	return m
}

func (m *Mutation) fail(err error) {
	if m.err == nil {
		m.err = err
	}
}

// Create registers an item insert. The `created` event is generated here, so
// there is no path to a create without one.
func (m *Mutation) Create(in ItemInsert) *Mutation {
	if in.ID == (uuid.UUID{}) {
		in.ID = uuid.NewV7()
	}
	if in.Title == "" {
		m.fail(fmt.Errorf("store: create %s: title is required", in.ID))
		return m
	}
	if in.OriginID == (uuid.UUID{}) {
		m.fail(fmt.Errorf("store: create %s: origin_id is required (§5.7)", in.ID))
		return m
	}
	payload, err := json.Marshal(map[string]any{"title": in.Title, "project_id": in.ProjectID.String()})
	if err != nil {
		m.fail(err)
		return m
	}
	ins := in
	m.changes = append(m.changes, change{
		kind:   changeInsert,
		itemID: in.ID,
		insert: &ins,
		events: []event{m.newEvent(in.ID, EventCreated, nil, nil, payload)},
	})
	return m
}

// Update registers a field change. Callers pass the events describing what
// changed; passing none is an error rather than a silent audit gap.
func (m *Mutation) Update(up ItemUpdate, evs ...FieldChange) *Mutation {
	if len(evs) == 0 {
		m.fail(fmt.Errorf("store: update %s: at least one field change must be described (ADR-001)", up.ID))
		return m
	}
	events := make([]event, 0, len(evs))
	for _, fc := range evs {
		ev, err := m.fieldEvent(up.ID, fc)
		if err != nil {
			m.fail(err)
			return m
		}
		events = append(events, ev)
	}
	u := up
	m.changes = append(m.changes, change{kind: changeUpdate, itemID: up.ID, update: &u, events: events})
	return m
}

// FieldChange describes one field's before and after for the event log.
// Kind defaults to field_changed; a status move must say so explicitly, since
// §6 and the activity feed distinguish them.
type FieldChange struct {
	Kind  string
	Field string
	Old   any
	New   any
}

func (m *Mutation) fieldEvent(itemID uuid.UUID, fc FieldChange) (event, error) {
	if fc.Field == "" {
		return event{}, fmt.Errorf("store: field change on %s has no field name", itemID)
	}
	kind := fc.Kind
	if kind == "" {
		kind = EventFieldChanged
	}
	oldJSON, err := marshalValue(fc.Old)
	if err != nil {
		return event{}, err
	}
	newJSON, err := marshalValue(fc.New)
	if err != nil {
		return event{}, err
	}
	field := fc.Field
	return m.newEvent(itemID, kind, &field, oldJSON, newJSON), nil
}

// Reparent registers a subtree move and its `moved` event.
func (m *Mutation) Reparent(r ItemReparent) *Mutation {
	newParent := "null"
	if r.NewParentID != nil {
		newParent = r.NewParentID.String()
	}
	payload, err := json.Marshal(map[string]any{"new_parent_id": newParent})
	if err != nil {
		m.fail(err)
		return m
	}
	field := "parent_id"
	rp := r
	m.changes = append(m.changes, change{
		kind:    changeReparent,
		itemID:  r.ID,
		reparen: &rp,
		events:  []event{m.newEvent(r.ID, EventMoved, &field, nil, payload)},
	})
	return m
}

// SoftDelete registers the soft delete of an item (§5.8).
func (m *Mutation) SoftDelete(id uuid.UUID) *Mutation {
	m.changes = append(m.changes, change{
		kind:   changeSoftDelete,
		itemID: id,
		events: []event{m.newEvent(id, EventDeleted, nil, nil, nil)},
	})
	return m
}

// hardDelete is unexported: §5.8 allows hard deletion only from an admin CLI
// path, which reaches it through HardDeleteItem in this package. The terminal
// event is written first, in the same transaction, by construction.
func (m *Mutation) hardDelete(id uuid.UUID) *Mutation {
	payload, _ := json.Marshal(map[string]any{"hard": true})
	m.changes = append(m.changes, change{
		kind:   changeHardDelete,
		itemID: id,
		hard:   true,
		events: []event{m.newEvent(id, EventDeleted, nil, nil, payload)},
	})
	return m
}

// Link and Unlink register link changes and their events.
func (m *Mutation) Link(l LinkChange) *Mutation {
	if l.ID == (uuid.UUID{}) {
		l.ID = uuid.NewV7()
	}
	payload, err := json.Marshal(map[string]any{"to": l.ToItemID.String(), "kind": l.Kind})
	if err != nil {
		m.fail(err)
		return m
	}
	lc := l
	m.changes = append(m.changes, change{
		kind:   changeLink,
		itemID: l.FromItemID,
		link:   &lc,
		events: []event{m.newEvent(l.FromItemID, EventLinked, nil, nil, payload)},
	})
	return m
}

func (m *Mutation) Unlink(l LinkChange) *Mutation {
	payload, err := json.Marshal(map[string]any{"to": l.ToItemID.String(), "kind": l.Kind})
	if err != nil {
		m.fail(err)
		return m
	}
	lc := l
	m.changes = append(m.changes, change{
		kind:   changeUnlink,
		itemID: l.FromItemID,
		link:   &lc,
		events: []event{m.newEvent(l.FromItemID, EventUnlinked, nil, nil, payload)},
	})
	return m
}

func (m *Mutation) newEvent(itemID uuid.UUID, kind string, field *string, oldV, newV []byte) event {
	return event{
		itemID:   itemID,
		hasItem:  itemID != uuid.UUID{},
		actorID:  m.actorID,
		hasActor: m.hasActor,
		kind:     kind,
		field:    field,
		oldValue: oldV,
		newValue: newV,
	}
}

// eventCount is what the seq block is sized from (ADR-002): one sequence value
// per event row, allocated in a single statement.
func (m *Mutation) eventCount() int {
	n := 0
	for _, c := range m.changes {
		n += len(c.events)
	}
	return n
}

func marshalValue(v any) ([]byte, error) {
	if v == nil {
		return nil, nil
	}
	return json.Marshal(v)
}
