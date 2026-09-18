package api

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5"
	"github.com/siercks/sierx/internal/api/projection"
	"github.com/siercks/sierx/internal/sxq"
	"net/http"
	"time"
)

func (s *Server) queryOptions(r *http.Request, q *sxq.Query, at time.Time, start int) (sxq.Options, error) {
	options := sxq.Options{UserID: Identity(r).ID, Now: at, Start: start, Custom: map[string][]sxq.CustomField{}}
	projects := q.ProjectKeys()
	if project := r.URL.Query().Get("project"); project != "" && r.URL.Path != "/api/v1/views" {
		projects = []string{project}
	}
	rows, err := s.Pool.Query(r.Context(), `SELECT f.key,f.data_type,p.id::text FROM field_def f JOIN project p ON p.id=f.project_id WHERE p.workspace_id=$1 AND ($2::text[] IS NULL OR p.key_prefix=ANY($2)) ORDER BY p.id,f.key`, Identity(r).WorkspaceID, projects)
	if err != nil {
		return options, err
	}
	defer rows.Close()
	for rows.Next() {
		var key, kind, id string
		if err = rows.Scan(&key, &kind, &id); err != nil {
			return options, err
		}
		options.Custom[key] = append(options.Custom[key], sxq.CustomField{ProjectID: id, Kind: kind})
	}
	return options, rows.Err()
}
func (s *Server) completeSXQ(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	options, err := s.queryOptions(r, &sxq.Query{}, time.Now(), 1)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	suggestions, err := sxq.Complete(r.URL.Query().Get("partial"), options.Custom)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	if suggestions == nil {
		suggestions = []string{}
	}
	writeJSON(w, 200, map[string]any{"suggestions": suggestions})
}
func (s *Server) listItems(w http.ResponseWriter, r *http.Request) {
	fields, ok := s.selectedFields(w, r, projection.Required)
	if !ok {
		return
	}
	limit, err := PageLimit(r)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	q, err := sxq.Parse(r.URL.Query().Get("q"))
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	c := Cursor{After: zeroID, Upper: zeroID, Scope: cursorScope(r), At: time.Now().UTC().Format(time.RFC3339Nano)}
	if token := r.URL.Query().Get("cursor"); token != "" {
		c, err = DecodeCursor(token, s.auth.cfg.SessionKey, c.Scope)
		if err != nil {
			requestProblem(w, err.Error())
			return
		}
	} else {
		err = s.Pool.QueryRow(r.Context(), `SELECT id::text FROM item WHERE workspace_id=$1 ORDER BY id DESC LIMIT 1`, Identity(r).WorkspaceID).Scan(&c.Upper)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			databaseProblem(w, err)
			return
		}
	}
	at, err := time.Parse(time.RFC3339Nano, c.At)
	if err != nil {
		requestProblem(w, "Invalid query cursor; restart from the first page.")
		return
	}
	options, err := s.queryOptions(r, q, at, 6)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	plan, err := sxq.Compile(q, options)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	args := append([]any{Identity(r).WorkspaceID, c.After, c.Upper, r.URL.Query().Get("project"), limit + 1}, plan.Args...)
	expression, params := projection.SQL(fields, len(args)+1)
	args = append(args, params...)
	predicate := "TRUE"
	if c.After != zeroID {
		if len(c.Sort) != 1 {
			requestProblem(w, "Invalid sort cursor; restart from the first page.")
			return
		}
		if c.Sort[0] == nil {
			predicate = "(" + plan.OrderExpr + " IS NULL AND i.id>$2::uuid)"
		} else {
			value := c.Sort[0]
			if n, ok := value.(json.Number); ok {
				value = n.String()
			}
			args = append(args, value)
			placeholder := fmt.Sprintf("$%d", len(args))
			switch plan.OrderKind {
			case "number":
				placeholder += "::text::numeric"
			case "uuid":
				placeholder += "::text::uuid"
			case "date":
				placeholder += "::text::date"
			case "timestamp":
				placeholder += "::text::timestamptz"
			case "text":
				placeholder += "::text"
			case "bool":
				placeholder += "::boolean"
			}
			op := ">"
			if plan.Desc {
				op = "<"
			}
			predicate = "(" + plan.OrderExpr + " " + op + " " + placeholder + " OR (" + plan.OrderExpr + "=" + placeholder + " AND i.id>$2::uuid) OR " + plan.OrderExpr + " IS NULL)"
		}
	}
	direction := " ASC"
	if plan.Desc {
		direction = " DESC"
	}
	query := "SELECT " + expression + ",i.id::text,to_jsonb(" + plan.OrderExpr + ")" + itemJoins + `WHERE i.workspace_id=$1 AND $2::uuid IS NOT NULL AND i.id<=$3::uuid AND ($4='' OR p.key_prefix=$4) AND i.deleted_at IS NULL AND ` + plan.Where + " AND " + predicate + " ORDER BY " + plan.OrderExpr + direction + " NULLS LAST,i.id ASC LIMIT $5"
	rows, err := s.Pool.Query(r.Context(), query, args...)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer rows.Close()
	page := Page{Data: []any{}}
	for rows.Next() {
		var raw, sortRaw []byte
		var id string
		if err = rows.Scan(&raw, &id, &sortRaw); err != nil {
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
		var doc map[string]any
		d := json.NewDecoder(bytes.NewReader(raw))
		d.UseNumber()
		if err = d.Decode(&doc); err != nil {
			WriteProblem(w, InternalError())
			return
		}
		var sortValue any
		if len(sortRaw) > 0 {
			d = json.NewDecoder(bytes.NewReader(sortRaw))
			d.UseNumber()
			if err = d.Decode(&sortValue); err != nil {
				WriteProblem(w, InternalError())
				return
			}
		}
		page.Data = append(page.Data, projection.Apply(doc, fields))
		c.After = id
		c.Sort = []any{sortValue}
	}
	if rows.Err() != nil {
		databaseProblem(w, rows.Err())
		return
	}
	writeJSON(w, 200, page)
}
