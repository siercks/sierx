package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
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
	ID         string        `json:"id"`
	KeyPrefix  string        `json:"key_prefix"`
	Name       string        `json:"name"`
	Kind       string        `json:"kind"`
	ArchivedAt *time.Time    `json:"archived_at"`
	Owner      *ProjectOwner `json:"owner"`
	Version    int           `json:"version"`
	UpdatedAt  time.Time     `json:"updated_at"`
}

type ProjectOwner struct {
	ID          string `json:"id"`
	DisplayName string `json:"display_name"`
}

const projectSelect = `SELECT p.id::text,p.key_prefix,p.name,p.kind,p.archived_at,
 p.version,p.updated_at,u.id::text,u.display_name
 FROM project p LEFT JOIN user_account u ON u.id=p.owner_id`

func scanProject(row interface{ Scan(...any) error }) (Project, error) {
	var p Project
	var ownerID, ownerName *string
	err := row.Scan(&p.ID, &p.KeyPrefix, &p.Name, &p.Kind, &p.ArchivedAt, &p.Version, &p.UpdatedAt, &ownerID, &ownerName)
	if err == nil && ownerID != nil && ownerName != nil {
		p.Owner = &ProjectOwner{ID: *ownerID, DisplayName: *ownerName}
	}
	return p, err
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
		KeyPrefix string  `json:"key_prefix"`
		Name      string  `json:"name"`
		Kind      string  `json:"kind"`
		OwnerID   *string `json:"owner_id"`
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
	if in.OwnerID != nil {
		var active bool
		err = tx.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM membership m JOIN user_account u ON u.id=m.user_id WHERE m.workspace_id=$1 AND m.user_id=$2 AND u.is_active)`, who.WorkspaceID, *in.OwnerID).Scan(&active)
		if err != nil {
			databaseProblem(w, err)
			return
		}
		if !active {
			requestProblem(w, "owner_id must identify an active member of this workspace.")
			return
		}
	}
	var p Project
	row := tx.QueryRow(r.Context(), `INSERT INTO project(workspace_id,key_prefix,name,kind,owner_id) VALUES($1,$2,$3,$4,$5) RETURNING id::text,key_prefix,name,kind,archived_at,version,updated_at`, who.WorkspaceID, in.KeyPrefix, in.Name, in.Kind, in.OwnerID)
	var ownerID *string
	err = row.Scan(&p.ID, &p.KeyPrefix, &p.Name, &p.Kind, &p.ArchivedAt, &p.Version, &p.UpdatedAt)
	if err == nil && in.OwnerID != nil {
		var display string
		err = tx.QueryRow(r.Context(), `SELECT display_name FROM user_account WHERE id=$1`, *in.OwnerID).Scan(&display)
		if err == nil {
			ownerID = in.OwnerID
			p.Owner = &ProjectOwner{ID: *ownerID, DisplayName: display}
		}
	}
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
	p, err := scanProject(s.Pool.QueryRow(r.Context(), projectSelect+` WHERE p.workspace_id=$1 AND p.key_prefix=$2`, Identity(r).WorkspaceID, chi.URLParam(r, "key")))
	if err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("ETag", fmt.Sprintf("\"%d\"", p.Version))
	writeJSON(w, 200, p)
}

func (s *Server) updateProject(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	who := Identity(r)
	if who.Role != "admin" {
		WriteProblem(w, Forbidden())
		return
	}
	match := r.Header.Get("If-Match")
	if match == "" {
		WriteProblem(w, PreconditionRequired())
		return
	}
	if len(match) < 3 || match[0] != '"' || match[len(match)-1] != '"' {
		requestProblem(w, "If-Match must contain the quoted current project version.")
		return
	}
	expected, err := strconv.Atoi(match[1:len(match)-1])
	if err != nil || expected < 1 {
		requestProblem(w, "If-Match must contain the quoted current project version.")
		return
	}
	var in map[string]json.RawMessage
	if !decodeJSON(w, r, &in) {
		return
	}
	if len(in) == 0 {
		requestProblem(w, "Provide name or owner_id to update.")
		return
	}
	for key := range in {
		if key != "name" && key != "owner_id" {
			requestProblem(w, "Only name and owner_id can be updated.")
			return
		}
	}
	var name *string
	if raw, ok := in["name"]; ok {
		var value string
		if err := json.Unmarshal(raw, &value); err != nil || strings.TrimSpace(value) == "" || utf8.RuneCountInString(value) > 200 {
			requestProblem(w, "name must contain 1–200 characters.")
			return
		}
		name = &value
	}
	ownerPresent := false
	var ownerID *string
	if raw, ok := in["owner_id"]; ok {
		ownerPresent = true
		if string(raw) != "null" {
			var value string
			if err := json.Unmarshal(raw, &value); err != nil || value == "" {
				requestProblem(w, "owner_id must be a member ID or null.")
				return
			}
			ownerID = &value
		}
	}
	tx, err := s.Pool.Begin(r.Context())
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer tx.Rollback(r.Context())
	key := chi.URLParam(r, "key")
	var current Project
	var currentOwnerID, currentOwnerName *string
	err = tx.QueryRow(r.Context(), `SELECT p.id::text,p.key_prefix,p.name,p.kind,p.archived_at,p.version,p.updated_at,u.id::text,u.display_name FROM project p LEFT JOIN user_account u ON u.id=p.owner_id WHERE p.workspace_id=$1 AND p.key_prefix=$2 FOR UPDATE OF p`, who.WorkspaceID, key).Scan(&current.ID, &current.KeyPrefix, &current.Name, &current.Kind, &current.ArchivedAt, &current.Version, &current.UpdatedAt, &currentOwnerID, &currentOwnerName)
	if errors.Is(err, pgx.ErrNoRows) {
		WriteProblem(w, NotFound())
		return
	}
	if err != nil {
		databaseProblem(w, err)
		return
	}
	// Scan nullable owner display separately because the public shape intentionally omits email and auth data.
	if currentOwnerID != nil && currentOwnerName != nil {
		current.Owner = &ProjectOwner{ID: *currentOwnerID, DisplayName: *currentOwnerName}
	}
	submitted := map[string]any{}
	if name != nil { submitted["name"] = *name }
	if ownerPresent { submitted["owner_id"] = ownerID }
	if current.Version != expected {
		p := problem(409,"Conflict","This project changed. Compare the current metadata with your edits and retry using its version.")
		p.Type = "urn:sierx:project-conflict"
		w.Header().Set("Content-Type", "application/problem+json")
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(p.Status)
		_ = json.NewEncoder(w).Encode(struct {
			Problem
			CurrentProject Project `json:"current_project"`
			SubmittedProject map[string]any `json:"submitted_project"`
		}{Problem: p, CurrentProject: current, SubmittedProject: submitted})
		return
	}
	if ownerPresent && ownerID != nil {
		var active bool
		if err = tx.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM membership m JOIN user_account u ON u.id=m.user_id WHERE m.workspace_id=$1 AND m.user_id=$2 AND u.is_active)`, who.WorkspaceID, *ownerID).Scan(&active); err != nil {
			databaseProblem(w, err)
			return
		}
		if !active {
			requestProblem(w, "owner_id must identify an active member of this workspace.")
			return
		}
	}
	var updated Project
	row := tx.QueryRow(r.Context(), `UPDATE project SET name=COALESCE($3,name), owner_id=CASE WHEN $4 THEN $5::uuid ELSE owner_id END, version=version+1, updated_at=now() WHERE workspace_id=$1 AND key_prefix=$2 RETURNING id::text,key_prefix,name,kind,archived_at,version,updated_at`, who.WorkspaceID, key, name, ownerPresent, ownerID)
	if err = row.Scan(&updated.ID, &updated.KeyPrefix, &updated.Name, &updated.Kind, &updated.ArchivedAt, &updated.Version, &updated.UpdatedAt); err != nil {
		databaseProblem(w, err)
		return
	}
	if ownerPresent && ownerID != nil {
		var display string
		if err = tx.QueryRow(r.Context(), `SELECT display_name FROM user_account WHERE id=$1`, *ownerID).Scan(&display); err != nil {
			databaseProblem(w, err)
			return
		}
		updated.Owner = &ProjectOwner{ID: *ownerID, DisplayName: display}
	} else if !ownerPresent {
		updated.Owner = current.Owner
	}
	if err = tx.Commit(r.Context()); err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("ETag", fmt.Sprintf("\"%d\"", updated.Version))
	writeJSON(w, 200, updated)
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
	search := strings.TrimSpace(q.Get("search"))
	if len(search) > 100 { requestProblem(w, "search must be at most 100 characters."); return }
	who := Identity(r)
	c := Cursor{After: zeroID, Upper: zeroID, Scope: cursorScope(r)}
	if token := q.Get("cursor"); token != "" {
		c, err = DecodeCursor(token, s.auth.cfg.SessionKey, c.Scope)
		if err != nil {
			requestProblem(w, err.Error())
			return
		}
	} else {
		err = s.Pool.QueryRow(r.Context(), `SELECT id::text FROM project WHERE workspace_id=$1 AND ($2='' OR key_prefix ILIKE '%'||$2||'%' OR name ILIKE '%'||$2||'%') ORDER BY id DESC LIMIT 1`, who.WorkspaceID, search).Scan(&c.Upper)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			databaseProblem(w, err)
			return
		}
	}
	rows, err := s.Pool.Query(r.Context(), `SELECT p.id::text,p.key_prefix,p.name,p.kind,p.archived_at,p.version,p.updated_at,u.id::text,u.display_name FROM project p LEFT JOIN user_account u ON u.id=p.owner_id WHERE p.workspace_id=$1 AND p.id>$2::uuid AND p.id<=$3::uuid AND ($4 OR p.archived_at IS NULL) AND ($5='' OR p.key_prefix ILIKE '%'||$5||'%' OR p.name ILIKE '%'||$5||'%') ORDER BY p.id LIMIT $6`, who.WorkspaceID, c.After, c.Upper, archived == "true", search, limit+1)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer rows.Close()
	page := Page{Data: []any{}}
	for rows.Next() {
		p, err := scanProject(rows)
		if err != nil {
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

func (s *Server) listMembers(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	if Identity(r).Role != "admin" {
		WriteProblem(w, Forbidden())
		return
	}
	limit, err := PageLimit(r)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	q := r.URL.Query()
	search := strings.TrimSpace(q.Get("q"))
	if len(search) > 100 {
		requestProblem(w, "q must be at most 100 characters.")
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
		err = s.Pool.QueryRow(r.Context(), `SELECT m.user_id::text FROM membership m JOIN user_account u ON u.id=m.user_id WHERE m.workspace_id=$1 AND u.is_active AND u.display_name ILIKE $2 ORDER BY m.user_id DESC LIMIT 1`, who.WorkspaceID, "%"+search+"%").Scan(&c.Upper)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			databaseProblem(w, err)
			return
		}
	}
	rows, err := s.Pool.Query(r.Context(), `SELECT m.user_id::text,u.display_name FROM membership m JOIN user_account u ON u.id=m.user_id WHERE m.workspace_id=$1 AND m.user_id>$2::uuid AND m.user_id<=$3::uuid AND u.is_active AND u.display_name ILIKE $4 ORDER BY m.user_id LIMIT $5`, who.WorkspaceID, c.After, c.Upper, "%"+search+"%", limit+1)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer rows.Close()
	page := Page{Data: []any{}}
	for rows.Next() {
		var member ProjectOwner
		if err = rows.Scan(&member.ID, &member.DisplayName); err != nil {
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
		page.Data = append(page.Data, member)
		c.After = member.ID
	}
	if rows.Err() != nil {
		databaseProblem(w, rows.Err())
		return
	}
	writeJSON(w, 200, page)
}
