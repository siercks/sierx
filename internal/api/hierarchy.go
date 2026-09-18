package api

import (
	"github.com/go-chi/chi/v5"
	"github.com/siercks/sierx/internal/api/projection"
	"net/http"
	"strconv"
)

func (s *Server) children(w http.ResponseWriter, r *http.Request)    { s.hierarchy(w, r, true) }
func (s *Server) descendants(w http.ResponseWriter, r *http.Request) { s.hierarchy(w, r, false) }
func (s *Server) hierarchy(w http.ResponseWriter, r *http.Request, children bool) {
	fields, ok := s.selectedFields(w, r, projection.Required)
	if !ok {
		return
	}
	depth := 8
	if r.URL.Query().Has("depth") {
		var err error
		depth, err = strconv.Atoi(r.URL.Query().Get("depth"))
		if children || err != nil || depth < 1 || depth > 8 {
			requestProblem(w, "depth must be between 1 and 8 and is supported only on descendants.")
			return
		}
	}
	if children {
		depth = 1
	}
	var path string
	err := s.Pool.QueryRow(r.Context(), `SELECT path::text FROM item WHERE workspace_id=$1 AND key=$2 AND deleted_at IS NULL`, Identity(r).WorkspaceID, chi.URLParam(r, "key")).Scan(&path)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	expression, params := projection.SQL(fields, 4)
	args := append([]any{Identity(r).WorkspaceID, path, depth}, params...)
	base := "SELECT i.id," + expression + " AS doc" + itemJoins + `WHERE i.workspace_id=$1 AND i.path <@ $2::ltree AND i.path<>$2::ltree AND nlevel(i.path)<=nlevel($2::ltree)+$3 AND i.deleted_at IS NULL`
	s.projectedPage(w, r, base, fields, args...)
}
func (s *Server) itemRollup(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	doc, _, err := s.readItem(r.Context(), Identity(r).WorkspaceID, chi.URLParam(r, "key"), []string{"rollup"})
	if err != nil {
		databaseProblem(w, err)
		return
	}
	writeJSON(w, 200, doc["rollup"])
}
