package api

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5"
	"github.com/siercks/sierx/internal/api/projection"
	"net/http"
)

// jsonPage applies bounded ID keyset pagination to an authored SELECT returning
// id (uuid) and doc (jsonb). The base query must enforce visibility itself.
func (s *Server) jsonPage(w http.ResponseWriter, r *http.Request, base string, args ...any) {
	s.projectedPage(w, r, base, nil, args...)
}

func (s *Server) projectedPage(w http.ResponseWriter, r *http.Request, base string, fields []string, args ...any) {
	limit, err := PageLimit(r)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	c := Cursor{After: zeroID, Upper: zeroID, Scope: cursorScope(r)}
	if token := r.URL.Query().Get("cursor"); token != "" {
		c, err = DecodeCursor(token, s.auth.cfg.SessionKey, c.Scope)
	} else {
		err = s.Pool.QueryRow(r.Context(), "SELECT id::text FROM ("+base+") page ORDER BY id DESC LIMIT 1", args...).Scan(&c.Upper)
		if errors.Is(err, pgx.ErrNoRows) {
			err = nil
		}
	}
	if err != nil {
		if r.URL.Query().Get("cursor") != "" {
			requestProblem(w, err.Error())
		} else {
			databaseProblem(w, err)
		}
		return
	}
	n := len(args) + 1
	query := fmt.Sprintf("SELECT id::text,doc FROM (%s) page WHERE id>$%d::uuid AND id<=$%d::uuid ORDER BY id LIMIT $%d", base, n, n+1, n+2)
	rows, err := s.Pool.Query(r.Context(), query, append(args, c.After, c.Upper, limit+1)...)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer rows.Close()
	page := Page{Data: []any{}}
	for rows.Next() {
		var id string
		var raw []byte
		if err = rows.Scan(&id, &raw); err != nil {
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
		if fields == nil {
			page.Data = append(page.Data, json.RawMessage(raw))
		} else {
			var doc map[string]any
			d := json.NewDecoder(bytes.NewReader(raw))
			d.UseNumber()
			if err := d.Decode(&doc); err != nil {
				WriteProblem(w, InternalError())
				return
			}
			page.Data = append(page.Data, projection.Apply(doc, fields))
		}
		c.After = id
	}
	if rows.Err() != nil {
		databaseProblem(w, rows.Err())
		return
	}
	writeJSON(w, 200, page)
}
