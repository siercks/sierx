package api

import (
	"encoding/json"
	"github.com/siercks/sierx/internal/sxq"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"
	"uuid"
)

const viewSelect = `SELECT id,jsonb_build_object('id',id,'name',name,'query',query,'layout',layout,'shared',shared,'owner_id',owner_id) AS doc FROM saved_view WHERE workspace_id=$1 AND (shared OR owner_id=$2)`

func (s *Server) listViews(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	who := Identity(r)
	s.jsonPage(w, r, viewSelect, who.WorkspaceID, who.ID)
}
func (s *Server) createView(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	var in struct {
		Name   string `json:"name"`
		Query  string `json:"query"`
		Layout string `json:"layout"`
		Shared bool   `json:"shared"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	if strings.TrimSpace(in.Name) == "" || utf8.RuneCountInString(in.Name) > 200 {
		requestProblem(w, "name must contain 1-200 characters.")
		return
	}
	switch in.Layout {
	case "list", "board", "timeline", "grid":
	default:
		requestProblem(w, "layout must be list, board, timeline or grid.")
		return
	}
	q, err := sxq.Parse(in.Query)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	options, err := s.queryOptions(r, q, time.Now(), 1)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	if _, err = sxq.Compile(q, options); err != nil {
		requestProblem(w, err.Error())
		return
	}
	id := uuid.NewV7().String()
	who := Identity(r)
	_, err = s.Pool.Exec(r.Context(), `INSERT INTO saved_view(id,workspace_id,owner_id,name,query,layout,shared) VALUES($1,$2,$3,$4,$5,$6,$7)`, id, who.WorkspaceID, who.ID, in.Name, in.Query, in.Layout, in.Shared)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	var raw []byte
	err = s.Pool.QueryRow(r.Context(), "SELECT doc FROM ("+viewSelect+" AND id=$3) result", who.WorkspaceID, who.ID, id).Scan(&raw)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	writeJSON(w, 201, json.RawMessage(raw))
}
