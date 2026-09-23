package api

import (
	"encoding/json"
	"github.com/go-chi/chi/v5"
	"github.com/siercks/sierx/internal/store"
	"net/http"
	"uuid"
)

// Endpoint summaries are nested so later visibility policy can reduce their
// shape without changing the relationship envelope.
const linkSelect = `SELECT l.id,jsonb_build_object('id',l.id,'kind',l.kind,'from',jsonb_build_object('key',f.key,'title',f.title),'to',jsonb_build_object('key',t.key,'title',t.title),'created_at',l.created_at) AS doc FROM item_link l JOIN item f ON f.id=l.from_item_id JOIN item t ON t.id=l.to_item_id WHERE f.workspace_id=$1 AND t.workspace_id=$1 `

func (s *Server) itemID(w http.ResponseWriter, r *http.Request, key string) (uuid.UUID, bool) {
	var id string
	err := s.Pool.QueryRow(r.Context(), `SELECT id::text FROM item WHERE workspace_id=$1 AND key=$2 AND deleted_at IS NULL`, Identity(r).WorkspaceID, key).Scan(&id)
	if err != nil {
		databaseProblem(w, err)
		return uuid.UUID{}, false
	}
	v, _ := uuid.Parse(id)
	return v, true
}
func (s *Server) listLinks(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	id, ok := s.itemID(w, r, chi.URLParam(r, "key"))
	if !ok {
		return
	}
	s.jsonPage(w, r, linkSelect+`AND (l.from_item_id=$2 OR l.to_item_id=$2)`, Identity(r).WorkspaceID, id.String())
}
func (s *Server) createLink(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	version, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	var in struct {
		To   string `json:"to"`
		Kind string `json:"kind"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	switch in.Kind {
	case "blocks", "duplicates", "relates", "implements", "discovered_from":
	default:
		invalidChange(w, "kind must be blocks, duplicates, relates, implements or discovered_from.")
		return
	}
	from, ok := s.itemID(w, r, chi.URLParam(r, "key"))
	if !ok {
		return
	}
	to, ok := s.itemID(w, r, in.To)
	if !ok {
		return
	}
	if from == to {
		invalidChange(w, "to must identify a different item; self-links are not allowed.")
		return
	}
	id := uuid.NewV7()
	who := Identity(r)
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	_, err := store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error {
		m.Link(store.LinkChange{ID: id, FromItemID: from, ToItemID: to, Kind: in.Kind})
		return nil
	}, store.WithActor(actor), store.WithExpectedVersion(from, version))
	if err != nil {
		s.mutationError(w, r, err, in)
		return
	}
	var raw []byte
	err = s.Pool.QueryRow(r.Context(), "SELECT doc FROM ("+linkSelect+" AND l.id=$2) link", who.WorkspaceID, id.String()).Scan(&raw)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	writeJSON(w, 201, json.RawMessage(raw))
}
func (s *Server) deleteLink(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	version, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		WriteProblem(w, NotFound())
		return
	}
	who := Identity(r)
	var fromID, toID, fromKey, toKey, kind string
	err = s.Pool.QueryRow(r.Context(), `SELECT l.from_item_id::text,l.to_item_id::text,f.key,t.key,l.kind FROM item_link l JOIN item f ON f.id=l.from_item_id JOIN item t ON t.id=l.to_item_id WHERE l.id=$1 AND f.workspace_id=$2 AND t.workspace_id=$2`, id.String(), who.WorkspaceID).Scan(&fromID, &toID, &fromKey, &toKey, &kind)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	from, _ := uuid.Parse(fromID)
	to, _ := uuid.Parse(toID)
	acting, key := from, fromKey
	if requested := r.URL.Query().Get("item"); requested != "" {
		switch requested {
		case fromKey:
		case toKey:
			acting, key = to, toKey
		default:
			invalidChange(w, "item must identify one of the linked items.")
			return
		}
	}
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	_, err = store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error {
		m.Unlink(store.LinkChange{ID: id, FromItemID: from, ToItemID: to, ActingItemID: acting, Kind: kind})
		return nil
	}, store.WithActor(actor), store.WithExpectedVersion(acting, version))
	if err != nil {
		chi.RouteContext(r.Context()).URLParams.Add("key", key)
		s.mutationError(w, r, err, map[string]any{"deleted": true, "id": id.String()})
		return
	}
	writeJSON(w, 200, map[string]any{"id": id.String(), "deleted": true})
}
