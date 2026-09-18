package api

import (
	"encoding/json"
	"net/http"
	"strconv"
)

// Change summaries intentionally omit unbounded before/after content. Clients
// fetch the affected projected items; full values remain in item history.
func (s *Server) changes(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	q := r.URL.Query()
	if q.Has("cursor") || len(q["since_seq"]) > 1 {
		requestProblem(w, "Send one since_seq value; cursor is not supported on changes.")
		return
	}
	limit, err := PageLimit(r)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	var since int64
	if q.Has("since_seq") {
		since, err = strconv.ParseInt(q.Get("since_seq"), 10, 64)
		if err != nil || since < 0 {
			requestProblem(w, "since_seq must be a nonnegative sequence number returned by this workspace.")
			return
		}
	}
	rows, err := s.Pool.Query(r.Context(), `SELECT seq,jsonb_build_object('seq',seq,'at',at,'item_id',item_id,'actor_id',actor_id,'kind',kind,'field',field) FROM change_event WHERE workspace_id=$1 AND seq>$2 ORDER BY seq LIMIT $3`, Identity(r).WorkspaceID, since, limit)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer rows.Close()
	data := []json.RawMessage{}
	for rows.Next() {
		var raw []byte
		if err = rows.Scan(&since, &raw); err != nil {
			databaseProblem(w, err)
			return
		}
		data = append(data, json.RawMessage(raw))
	}
	if rows.Err() != nil {
		databaseProblem(w, rows.Err())
		return
	}
	writeJSON(w, 200, struct {
		Data    []json.RawMessage `json:"data"`
		NextSeq int64             `json:"next_seq"`
	}{data, since})
}
