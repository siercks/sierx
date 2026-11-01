package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"unicode/utf8"
)

type WorkspaceSettings struct {
	ID      string `json:"id"`
	Slug    string `json:"slug"`
	Name    string `json:"name"`
	Version int32  `json:"version"`
}

func (s *Server) workspaceSettings(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	var current WorkspaceSettings
	if err := s.DB.QueryRow(r.Context(), `SELECT id::text,slug,name,version FROM workspace WHERE id=$1`, Identity(r).WorkspaceID).Scan(&current.ID, &current.Slug, &current.Name, &current.Version); err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("ETag", fmt.Sprintf(`"%d"`, current.Version))
	writeJSON(w, 200, current)
}

func (s *Server) updateWorkspaceSettings(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	who := Identity(r)
	if who.Role != "admin" {
		WriteProblem(w, Forbidden())
		return
	}
	version, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	var in struct {
		Name string `json:"name"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	in.Name = strings.TrimSpace(in.Name)
	if in.Name == "" || utf8.RuneCountInString(in.Name) > 200 {
		requestProblem(w, "Workspace name must contain 1–200 characters.")
		return
	}
	tx, err := s.DB.Begin(r.Context())
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer tx.Rollback(r.Context())
	var current WorkspaceSettings
	if err = tx.QueryRow(r.Context(), `SELECT id::text,slug,name,version FROM workspace WHERE id=$1 FOR UPDATE`, who.WorkspaceID).Scan(&current.ID, &current.Slug, &current.Name, &current.Version); err != nil {
		databaseProblem(w, err)
		return
	}
	if current.Version != version {
		p := problem(409, "Conflict", "Workspace settings changed. Compare the latest name before applying your draft.")
		w.Header().Set("Content-Type", "application/problem+json")
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(409)
		_ = json.NewEncoder(w).Encode(struct {
			Problem
			Current WorkspaceSettings `json:"current_workspace"`
		}{p, current})
		return
	}
	if err = tx.QueryRow(r.Context(), `UPDATE workspace SET name=$2,version=version+1 WHERE id=$1 RETURNING version`, who.WorkspaceID, in.Name).Scan(&current.Version); err != nil {
		databaseProblem(w, err)
		return
	}
	if err = tx.Commit(r.Context()); err != nil {
		databaseProblem(w, err)
		return
	}
	current.Name = in.Name
	w.Header().Set("ETag", fmt.Sprintf(`"%d"`, current.Version))
	writeJSON(w, 200, current)
}
