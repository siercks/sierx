package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
)

type workflowStatus struct {
	Key      string `json:"key"`
	Name     string `json:"name"`
	Category string `json:"category"`
}
type workflowArc struct {
	To       string   `json:"to_key"`
	Requires []string `json:"requires"`
}
type workflowDraft struct {
	Statuses    []workflowStatus         `json:"statuses"`
	Transitions map[string][]workflowArc `json:"transitions"`
	Initial     map[string]string        `json:"initial_statuses"`
}
type workflowConfig struct {
	Version     int32                    `json:"version"`
	Statuses    []workflowStatus         `json:"statuses"`
	Transitions map[string][]workflowArc `json:"transitions"`
	Types       []struct {
		Key     string `json:"key"`
		Initial string `json:"initial_status"`
	} `json:"types"`
	Fields []struct {
		Key string `json:"key"`
	} `json:"fields"`
}

// A bounded additive editor: existing immutable status definitions are retained.
// New snapshots change order/arcs/initial states without rewriting item history.
func (s *Server) updateWorkflow(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	who := Identity(r)
	if who.Role != "admin" {
		WriteProblem(w, Forbidden())
		return
	}
	expected, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	var draft workflowDraft
	if !decodeJSON(w, r, &draft) {
		return
	}
	if len(draft.Statuses) < 1 || len(draft.Statuses) > 50 {
		requestProblem(w, "Provide 1–50 statuses.")
		return
	}
	keys := map[string]workflowStatus{}
	names := map[string]bool{}
	for _, status := range draft.Statuses {
		if !regexp.MustCompile(`^[a-z][a-z0-9_-]{0,39}$`).MatchString(status.Key) || strings.TrimSpace(status.Name) == "" || utf8.RuneCountInString(status.Name) > 80 {
			requestProblem(w, "Statuses need a unique lowercase key and a name of 1–80 characters.")
			return
		}
		if _, exists := keys[status.Key]; exists {
			requestProblem(w, "Status keys must be unique.")
			return
		}
		name := strings.ToLower(strings.TrimSpace(status.Name))
		if names[name] {
			requestProblem(w, "Status names must be unique.")
			return
		}
		names[name] = true
		switch status.Category {
		case "open", "active", "done", "cancelled":
		default:
			requestProblem(w, "Choose an open, active, done or cancelled category.")
			return
		}
		keys[status.Key] = status
	}
	tx, err := s.DB.Begin(r.Context())
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer tx.Rollback(r.Context())
	projectKey := chi.URLParam(r, "key")
	var projectID string
	if err = tx.QueryRow(r.Context(), `SELECT id::text FROM project WHERE workspace_id=$1 AND key_prefix=$2 AND archived_at IS NULL FOR UPDATE`, who.WorkspaceID, projectKey).Scan(&projectID); err != nil {
		databaseProblem(w, err)
		return
	}
	var raw []byte
	if err = tx.QueryRow(r.Context(), resolvedConfigSQL, who.WorkspaceID, projectKey).Scan(&raw); err != nil {
		databaseProblem(w, err)
		return
	}
	var current workflowConfig
	if json.Unmarshal(raw, &current) != nil {
		WriteProblem(w, InternalError())
		return
	}
	if current.Version != expected {
		p := problem(409, "Conflict", "This workflow changed. Compare the latest configuration before applying your draft.")
		w.Header().Set("Content-Type", "application/problem+json")
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(409)
		_ = json.NewEncoder(w).Encode(struct {
			Problem
			Current json.RawMessage `json:"current_config"`
		}{p, raw})
		return
	}
	for _, old := range current.Statuses {
		next, exists := keys[old.Key]
		if !exists || next != old {
			requestProblem(w, "Existing status keys, names and categories are retained to preserve item history. Add a new status instead.")
			return
		}
	}
	validRequired := map[string]bool{"assignee": true, "points": true, "start_date": true, "due_date": true, "title": true, "body": true}
	for _, field := range current.Fields {
		validRequired["fields."+field.Key] = true
	}
	arcs := 0
	for from, targets := range draft.Transitions {
		if _, exists := keys[from]; !exists {
			requestProblem(w, "Every transition must start at a configured status.")
			return
		}
		seen := map[string]bool{}
		for _, target := range targets {
			if _, exists := keys[target.To]; !exists || target.To == from || seen[target.To] {
				requestProblem(w, "Transitions need distinct configured start and destination statuses, without duplicates.")
				return
			}
			seen[target.To] = true
			arcs++
			requirements := map[string]bool{}
			for _, field := range target.Requires {
				if !validRequired[field] || requirements[field] {
					requestProblem(w, "Transition requirements must be unique known item fields.")
					return
				}
				requirements[field] = true
			}
		}
	}
	if arcs > 200 {
		requestProblem(w, "A workflow supports at most 200 transitions.")
		return
	}
	if len(draft.Initial) != len(current.Types) {
		requestProblem(w, "Choose one initial status for every item type.")
		return
	}
	for _, kind := range current.Types {
		if _, exists := keys[draft.Initial[kind.Key]]; !exists {
			requestProblem(w, "Choose a configured initial status for every item type.")
			return
		}
	}
	ids := map[string]string{}
	rows, err := tx.Query(r.Context(), `SELECT s.key,s.id::text FROM config_status cs JOIN status s ON s.id=cs.status_id WHERE cs.project_id=$1 AND cs.version=$2`, projectID, current.Version)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	for rows.Next() {
		var key, id string
		if err = rows.Scan(&key, &id); err != nil {
			rows.Close()
			databaseProblem(w, err)
			return
		}
		ids[key] = id
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		databaseProblem(w, err)
		return
	}
	nextVersion := current.Version + 1
	if _, err = tx.Exec(r.Context(), `INSERT INTO project_config(project_id,version,applied_by) VALUES($1,$2,$3)`, projectID, nextVersion, who.ID); err != nil {
		databaseProblem(w, err)
		return
	}
	for index, status := range draft.Statuses {
		if ids[status.Key] == "" {
			var id string
			if err = tx.QueryRow(r.Context(), `INSERT INTO status(project_id,key,name,category) VALUES($1,$2,$3,$4) RETURNING id::text`, projectID, status.Key, status.Name, status.Category).Scan(&id); err != nil {
				databaseProblem(w, err)
				return
			}
			ids[status.Key] = id
		}
		if _, err = tx.Exec(r.Context(), `INSERT INTO config_status(project_id,version,status_id,display_order) VALUES($1,$2,$3,$4)`, projectID, nextVersion, ids[status.Key], index); err != nil {
			databaseProblem(w, err)
			return
		}
	}
	for _, kind := range current.Types {
		if _, err = tx.Exec(r.Context(), `INSERT INTO config_type(project_id,version,item_type_id,initial_status_id) SELECT ct.project_id,$3,ct.item_type_id,$4::uuid FROM config_type ct JOIN item_type t ON t.id=ct.item_type_id WHERE ct.project_id=$1 AND ct.version=$2 AND t.key=$5`, projectID, current.Version, nextVersion, ids[draft.Initial[kind.Key]], kind.Key); err != nil {
			databaseProblem(w, err)
			return
		}
	}
	for from, targets := range draft.Transitions {
		for _, target := range targets {
			required := target.Requires
			if required == nil {
				required = []string{}
			}
			encoded, _ := json.Marshal(required)
			if _, err = tx.Exec(r.Context(), `INSERT INTO config_transition(project_id,version,from_status_id,to_status_id,requires) VALUES($1,$2,$3,$4,$5)`, projectID, nextVersion, ids[from], ids[target.To], encoded); err != nil {
				databaseProblem(w, err)
				return
			}
		}
	}
	if err = tx.QueryRow(r.Context(), resolvedConfigSQL, who.WorkspaceID, projectKey).Scan(&raw); err != nil {
		databaseProblem(w, err)
		return
	}
	if err = tx.Commit(r.Context()); err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("ETag", fmt.Sprintf(`"%d"`, nextVersion))
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(append(raw, '\n'))
}
