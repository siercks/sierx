package api

import (
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/siercks/sierx/internal/store/seed"
)

const zeroID = "00000000-0000-0000-0000-000000000000"

type Project struct {
	ID         string     `json:"id"`
	KeyPrefix  string     `json:"key_prefix"`
	Name       string     `json:"name"`
	Kind       string     `json:"kind"`
	ArchivedAt *time.Time `json:"archived_at"`
}

func rejectFields(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Query().Has("fields") {
		p := BadRequest()
		p.Detail = "fields is not supported for this endpoint; remove it."
		WriteProblem(w, p)
		return false
	}
	return true
}
func requestProblem(w http.ResponseWriter, detail string) {
	p := BadRequest()
	p.Detail = detail
	WriteProblem(w, p)
}
func databaseProblem(w http.ResponseWriter, err error) {
	if errors.Is(err, pgx.ErrNoRows) {
		WriteProblem(w, NotFound())
		return
	}
	var pg *pgconn.PgError
	if errors.As(err, &pg) {
		switch pg.Code {
		case "23505":
			p := problem(409, "Conflict", "This identifier already exists. Choose a different identifier.")
			WriteProblem(w, p)
			return
		case "22P02", "22007", "22008", "23514", "23503":
			WriteProblem(w, Unprocessable())
			return
		}
	}
	WriteProblem(w, Unavailable())
}

func (s *Server) createProject(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	who := Identity(r)
	if who.Role != "admin" {
		WriteProblem(w, Forbidden())
		return
	}
	var in struct {
		KeyPrefix string `json:"key_prefix"`
		Name      string `json:"name"`
		Kind      string `json:"kind"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	if !regexp.MustCompile(`^[A-Z][A-Z0-9]{1,9}$`).MatchString(in.KeyPrefix) {
		requestProblem(w, "key_prefix must match ^[A-Z][A-Z0-9]{1,9}$. Choose an uppercase prefix.")
		return
	}
	for _, prefix := range ReservedPrefixes {
		if in.KeyPrefix == prefix {
			requestProblem(w, "key_prefix is reserved. Avoid: "+strings.Join(ReservedPrefixes, ", ")+".")
			return
		}
	}
	if strings.TrimSpace(in.Name) == "" || utf8.RuneCountInString(in.Name) > 200 || (in.Kind != "delivery" && in.Kind != "discovery" && in.Kind != "portfolio") {
		requestProblem(w, "Provide a name of 1–200 characters and kind delivery, discovery or portfolio.")
		return
	}
	tx, err := s.Pool.Begin(r.Context())
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer tx.Rollback(r.Context())
	var p Project
	err = tx.QueryRow(r.Context(), `INSERT INTO project(workspace_id,key_prefix,name,kind) VALUES($1,$2,$3,$4) RETURNING id::text,key_prefix,name,kind,archived_at`, who.WorkspaceID, in.KeyPrefix, in.Name, in.Kind).Scan(&p.ID, &p.KeyPrefix, &p.Name, &p.Kind, &p.ArchivedAt)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	if err = seed.InstallConfig(r.Context(), tx, p.ID); err != nil {
		databaseProblem(w, err)
		return
	}
	if err = tx.Commit(r.Context()); err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("Location", "/api/v1/projects/"+p.KeyPrefix)
	writeJSON(w, 201, p)
}

func (s *Server) getProject(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	var p Project
	err := s.Pool.QueryRow(r.Context(), `SELECT id::text,key_prefix,name,kind,archived_at FROM project WHERE workspace_id=$1 AND key_prefix=$2`, Identity(r).WorkspaceID, chi.URLParam(r, "key")).Scan(&p.ID, &p.KeyPrefix, &p.Name, &p.Kind, &p.ArchivedAt)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	writeJSON(w, 200, p)
}

func (s *Server) listProjects(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	limit, err := PageLimit(r)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	q := r.URL.Query()
	archived := q.Get("archived")
	if q.Has("archived") && archived != "true" && archived != "false" {
		requestProblem(w, "archived must be true or false.")
		return
	}
	who := Identity(r)
	c := Cursor{After: zeroID, Upper: zeroID, Scope: cursorScope(r)}
	if token := q.Get("cursor"); token != "" {
		c, err = DecodeCursor(token, s.auth.cfg.SessionKey, c.Scope)
		if err != nil {
			requestProblem(w, err.Error())
			return
		}
	} else {
		err = s.Pool.QueryRow(r.Context(), `SELECT id::text FROM project WHERE workspace_id=$1 ORDER BY id DESC LIMIT 1`, who.WorkspaceID).Scan(&c.Upper)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			databaseProblem(w, err)
			return
		}
	}
	rows, err := s.Pool.Query(r.Context(), `SELECT id::text,key_prefix,name,kind,archived_at FROM project WHERE workspace_id=$1 AND id>$2::uuid AND id<=$3::uuid AND ($4 OR archived_at IS NULL) ORDER BY id LIMIT $5`, who.WorkspaceID, c.After, c.Upper, archived == "true", limit+1)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer rows.Close()
	page := Page{Data: []any{}}
	for rows.Next() {
		var p Project
		if err := rows.Scan(&p.ID, &p.KeyPrefix, &p.Name, &p.Kind, &p.ArchivedAt); err != nil {
			databaseProblem(w, err)
			return
		}
		if len(page.Data) == limit {
			token, err := EncodeCursor(c, s.auth.cfg.SessionKey)
			if err != nil {
				WriteProblem(w, InternalError())
				return
			}
			page.NextCursor = &token
			break
		}
		page.Data = append(page.Data, p)
		c.After = p.ID
	}
	if rows.Err() != nil {
		databaseProblem(w, rows.Err())
		return
	}
	writeJSON(w, 200, page)
}
