package api

import (
	"encoding/json"
	"fmt"
	"github.com/go-chi/chi/v5"
	"net/http"
	"strconv"
)

const historySQL = `SELECT e.seq,jsonb_build_object('seq',e.seq,'kind',e.kind,'at',e.at,'actor',CASE WHEN u.id IS NULL THEN NULL ELSE jsonb_build_object('id',u.id,'display_name',u.display_name) END,'field',e.field,'old_value',e.old_value,'new_value',e.new_value) FROM change_event e LEFT JOIN user_account u ON u.id=e.actor_id WHERE e.workspace_id=$1 AND e.item_id=$2 AND e.seq<=$3 AND e.seq<$4 ORDER BY e.seq DESC LIMIT $5`

func (s *Server) itemHistory(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	limit, err := PageLimit(r)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	// History remains accessible after soft deletion.
	var id string
	err = s.Pool.QueryRow(r.Context(), `SELECT id::text FROM item WHERE workspace_id=$1 AND key=$2`, Identity(r).WorkspaceID, chi.URLParam(r, "key")).Scan(&id)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	c := Cursor{After: "9223372036854775807", Upper: "0", Scope: cursorScope(r)}
	if token := r.URL.Query().Get("cursor"); token != "" {
		c, err = DecodeCursor(token, s.auth.cfg.SessionKey, c.Scope)
		if err != nil {
			requestProblem(w, err.Error())
			return
		}
	} else {
		err = s.Pool.QueryRow(r.Context(), `SELECT coalesce(max(seq),0)::text FROM change_event WHERE workspace_id=$1 AND item_id=$2`, Identity(r).WorkspaceID, id).Scan(&c.Upper)
		if err != nil {
			databaseProblem(w, err)
			return
		}
	}
	upper, err := strconv.ParseInt(c.Upper, 10, 64)
	if err != nil {
		requestProblem(w, "Invalid history cursor.")
		return
	}
	after, err := strconv.ParseInt(c.After, 10, 64)
	if err != nil {
		requestProblem(w, "Invalid history cursor.")
		return
	}
	rows, err := s.Pool.Query(r.Context(), historySQL, Identity(r).WorkspaceID, id, upper, after, limit+1)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer rows.Close()
	page := Page{Data: []any{}}
	for rows.Next() {
		var seq int64
		var raw []byte
		if err = rows.Scan(&seq, &raw); err != nil {
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
		page.Data = append(page.Data, json.RawMessage(raw))
		c.After = fmt.Sprint(seq)
	}
	if rows.Err() != nil {
		databaseProblem(w, rows.Err())
		return
	}
	writeJSON(w, 200, page)
}
