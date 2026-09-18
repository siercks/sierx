package api

import (
	"crypto/sha256"
	"fmt"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
)

const resolvedConfigSQL = `SELECT jsonb_build_object(
 'version',pc.version,
 'statuses',(SELECT coalesce(jsonb_agg(jsonb_build_object('key',s.key,'name',s.name,'category',s.category) ORDER BY cs.display_order),'[]') FROM config_status cs JOIN status s ON s.id=cs.status_id WHERE cs.project_id=p.id AND cs.version=pc.version),
 'types',(SELECT coalesce(jsonb_agg(jsonb_build_object('key',t.key,'name',t.name,'level',t.level,'is_idea',t.is_idea,'initial_status',s.key) ORDER BY t.level DESC,t.key),'[]') FROM config_type ct JOIN item_type t ON t.id=ct.item_type_id JOIN status s ON s.id=ct.initial_status_id WHERE ct.project_id=p.id AND ct.version=pc.version),
 'transitions',(SELECT coalesce(jsonb_object_agg(arcs.from_key,arcs.targets),'{}') FROM (SELECT f.key AS from_key,jsonb_agg(jsonb_build_object('to_key',s.key,'requires',ct.requires) ORDER BY s.key) AS targets FROM config_transition ct JOIN status f ON f.id=ct.from_status_id JOIN status s ON s.id=ct.to_status_id WHERE ct.project_id=p.id AND ct.version=pc.version GROUP BY f.key) arcs),
 'fields',(SELECT coalesce(jsonb_agg(jsonb_build_object('key',f.key,'name',f.name,'data_type',f.data_type,'options',f.options) ORDER BY f.key),'[]') FROM field_def f WHERE f.project_id=p.id)
) FROM project p JOIN project_config pc ON pc.project_id=p.id
WHERE p.workspace_id=$1 AND p.key_prefix=$2 ORDER BY pc.version DESC LIMIT 1`

func etagMatches(header, etag string) bool {
	for _, value := range strings.Split(header, ",") {
		value = strings.TrimSpace(value)
		if value == "*" || strings.TrimPrefix(value, "W/") == etag {
			return true
		}
	}
	return false
}

func (s *Server) projectConfig(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	var body []byte
	if err := s.Pool.QueryRow(r.Context(), resolvedConfigSQL, Identity(r).WorkspaceID, chi.URLParam(r, "key")).Scan(&body); err != nil {
		databaseProblem(w, err)
		return
	}
	sum := sha256.Sum256(body)
	etag := fmt.Sprintf(`"%x"`, sum)
	w.Header().Set("ETag", etag)
	w.Header().Set("Cache-Control", "private, no-cache")
	w.Header().Set("Content-Type", "application/json")
	if etagMatches(r.Header.Get("If-None-Match"), etag) {
		w.WriteHeader(http.StatusNotModified)
		return
	}
	_, _ = w.Write(append(body, '\n'))
}
