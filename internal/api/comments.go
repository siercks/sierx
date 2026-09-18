package api

import (
	"encoding/json"
	"github.com/go-chi/chi/v5"
	"github.com/siercks/sierx/internal/store"
	"net/http"
	"strings"
	"uuid"
)

const commentSelect = `SELECT c.id,jsonb_build_object('id',c.id,'item',i.key,'author',jsonb_build_object('id',u.id,'display_name',u.display_name),'body',CASE WHEN c.deleted_at IS NULL THEN c.body ELSE NULL END,'created_at',c.created_at,'edited_at',c.edited_at,'deleted_at',c.deleted_at) AS doc FROM comment c JOIN item i ON i.id=c.item_id JOIN user_account u ON u.id=c.author_id WHERE i.workspace_id=$1 `

func (s *Server) listComments(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	id, ok := s.itemID(w, r, r.URL.Query().Get("item"))
	if !ok {
		return
	}
	s.jsonPage(w, r, commentSelect+`AND c.item_id=$2`, Identity(r).WorkspaceID, id.String())
}
func (s *Server) commentResponse(w http.ResponseWriter, r *http.Request, id uuid.UUID, status int) {
	var raw []byte
	err := s.Pool.QueryRow(r.Context(), "SELECT doc FROM ("+commentSelect+" AND c.id=$2) result", Identity(r).WorkspaceID, id.String()).Scan(&raw)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	writeJSON(w, status, json.RawMessage(raw))
}
func commentBodyValid(w http.ResponseWriter, body string) bool {
	if strings.TrimSpace(body) == "" || len(body) > 100000 {
		invalidChange(w, "body must contain Markdown text and must not exceed 100000 bytes.")
		return false
	}
	return true
}
func (s *Server) createComment(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	version, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	var in struct {
		Item string `json:"item"`
		Body string `json:"body"`
	}
	if !decodeJSON(w, r, &in) || !commentBodyValid(w, in.Body) {
		return
	}
	item, ok := s.itemID(w, r, in.Item)
	if !ok {
		return
	}
	who := Identity(r)
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	id := uuid.NewV7()
	_, err := store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error {
		m.Comment(store.CommentChange{ID: id, ItemID: item, Action: "create", Body: in.Body})
		return nil
	}, store.WithActor(actor), store.WithExpectedVersion(item, version))
	if err != nil {
		chi.RouteContext(r.Context()).URLParams.Add("key", in.Item)
		s.mutationError(w, r, err, in)
		return
	}
	s.commentResponse(w, r, id, 201)
}
func (s *Server) changeComment(w http.ResponseWriter, r *http.Request) {
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
	var itemID, authorID, key, oldBody string
	err = s.Pool.QueryRow(r.Context(), `SELECT c.item_id::text,c.author_id::text,i.key,c.body FROM comment c JOIN item i ON i.id=c.item_id WHERE c.id=$1 AND i.workspace_id=$2 AND c.deleted_at IS NULL`, id.String(), who.WorkspaceID).Scan(&itemID, &authorID, &key, &oldBody)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	if authorID != who.ID && !(r.Method == "DELETE" && who.Role == "admin") {
		WriteProblem(w, Forbidden())
		return
	}
	var in struct {
		Body string `json:"body"`
	}
	action := "delete"
	if r.Method == "PATCH" {
		action = "edit"
		if !decodeJSON(w, r, &in) || !commentBodyValid(w, in.Body) {
			return
		}
	}
	item, _ := uuid.Parse(itemID)
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	_, err = store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error {
		m.Comment(store.CommentChange{ID: id, ItemID: item, Action: action, Body: in.Body, OldBody: &oldBody})
		return nil
	}, store.WithActor(actor), store.WithExpectedVersion(item, version))
	if err != nil {
		chi.RouteContext(r.Context()).URLParams.Add("key", key)
		s.mutationError(w, r, err, in)
		return
	}
	s.commentResponse(w, r, id, 200)
}
