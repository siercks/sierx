package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"uuid"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/siercks/sierx/internal/store"
)

func invalidChange(w http.ResponseWriter, detail string) {
	p := Unprocessable()
	p.Detail = detail
	WriteProblem(w, p)
}

// fields is an optional patch of the same editable properties as PATCH /items.
// It is validated together with the transition and committed in one mutation.
func (s *Server) transitionItem(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	version, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	var in struct {
		ToStatus string                     `json:"to_status"`
		Fields   map[string]json.RawMessage `json:"fields"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	who := Identity(r)
	key := chi.URLParam(r, "key")
	current, v, err := s.readItem(r.Context(), who.WorkspaceID, key, nil)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	if v != version {
		s.mutationError(w, r, store.ErrVersionConflict, in)
		return
	}
	var projectID, statusID string
	var configVersion int32
	var required []byte
	err = s.Pool.QueryRow(r.Context(), `SELECT i.project_id::text,t.id::text,ct.version,ct.requires FROM item i JOIN status t ON t.project_id=i.project_id AND t.key=$3 JOIN config_transition ct ON ct.project_id=i.project_id AND ct.from_status_id=i.status_id AND ct.to_status_id=t.id WHERE i.workspace_id=$1 AND i.key=$2 AND i.deleted_at IS NULL AND ct.version=(SELECT max(version) FROM project_config WHERE project_id=i.project_id)`, who.WorkspaceID, key, in.ToStatus).Scan(&projectID, &statusID, &configVersion, &required)
	if errors.Is(err, pgx.ErrNoRows) {
		invalidChange(w, "to_status is not an allowed transition from the current status.")
		return
	}
	if err != nil {
		databaseProblem(w, err)
		return
	}
	up, events, merged, err := s.itemPatch(r, projectID, current, in.Fields)
	if err != nil {
		invalidChange(w, err.Error())
		return
	}
	var requires []string
	if json.Unmarshal(required, &requires) != nil {
		WriteProblem(w, InternalError())
		return
	}
	var missing []string
	for _, field := range requires {
		value := merged[field]
		if strings.HasPrefix(field, "fields.") {
			value = merged["fields"].(map[string]any)[strings.TrimPrefix(field, "fields.")]
		}
		if value == nil || value == "" {
			missing = append(missing, field)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		invalidChange(w, "Required fields are missing: "+strings.Join(missing, ", ")+".")
		return
	}
	sid, _ := uuid.Parse(statusID)
	up.StatusID = &sid
	up.ConfigVersion = &configVersion
	events = append(events, store.FieldChange{Kind: store.EventStatusChanged, Field: "status", Old: current["status"].(map[string]any)["key"], New: in.ToStatus})
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	_, err = store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error { m.Update(up, events...); return nil }, store.WithActor(actor), store.WithExpectedVersion(up.ID, version))
	if err != nil {
		s.mutationError(w, r, err, in)
		return
	}
	doc, v, err := s.readItem(r.Context(), who.WorkspaceID, key, nil)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("ETag", fmt.Sprintf(`"%d"`, v))
	writeJSON(w, 200, doc)
}

func (s *Server) itemPatch(r *http.Request, projectID string, current map[string]any, raw map[string]json.RawMessage) (store.ItemUpdate, []store.FieldChange, map[string]any, error) {
	id, _ := uuid.Parse(current["id"].(string))
	up := store.ItemUpdate{ID: id}
	merged := map[string]any{}
	for k, v := range current {
		merged[k] = v
	}
	var in itemInput
	encoded, _ := json.Marshal(raw)
	if err := json.Unmarshal(encoded, &in); err != nil {
		return up, nil, nil, fmt.Errorf("fields must contain valid editable item properties")
	}
	_, titleSet := raw["title"]
	if err := s.validateInput(r.Context(), Identity(r).WorkspaceID, projectID, in, titleSet); err != nil {
		return up, nil, nil, err
	}
	keys := make([]string, 0, len(raw))
	for k := range raw {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var events []store.FieldChange
	for _, field := range keys {
		var value any
		_ = json.Unmarshal(raw[field], &value)
		old := current[field]
		merged[field] = value
		switch field {
		case "title":
			up.Title = &in.Title
		case "body":
			up.SetBody = true
			up.Body = in.Body
		case "assignee":
			up.SetAssignee = true
			if in.Assignee != nil {
				v, _ := uuid.Parse(*in.Assignee)
				up.AssigneeID = &v
			}
			if object, ok := old.(map[string]any); ok {
				old = object["id"]
			}
		case "points":
			up.SetPoints = true
			up.Points = in.Points
		case "start_date":
			up.SetStartDate = true
			up.StartDate = in.StartDate
		case "due_date":
			up.SetDueDate = true
			up.DueDate = in.DueDate
		case "fields":
			if in.Fields == nil {
				return up, nil, nil, fmt.Errorf("fields must be an object")
			}
			fields := map[string]any{}
			oldFields := current["fields"].(map[string]any)
			for k, v := range oldFields {
				fields[k] = v
			}
			customKeys := make([]string, 0, len(in.Fields))
			for k := range in.Fields {
				customKeys = append(customKeys, k)
			}
			sort.Strings(customKeys)
			for _, k := range customKeys {
				fields[k] = in.Fields[k]
				events = append(events, store.FieldChange{Field: "fields." + k, Old: oldFields[k], New: in.Fields[k]})
			}
			up.Fields = fields
			merged[field] = fields
			continue
		default:
			return up, nil, nil, fmt.Errorf("field %s cannot be edited here; use its dedicated action", field)
		}
		events = append(events, store.FieldChange{Field: field, Old: old, New: value})
	}
	return up, events, merged, nil
}
