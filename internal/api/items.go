package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"uuid"

	"github.com/go-chi/chi/v5"
	"github.com/siercks/sierx/internal/api/projection"
	"github.com/siercks/sierx/internal/store"
)

const itemJoins = ` FROM item i JOIN project p ON p.id=i.project_id JOIN status s ON s.id=i.status_id JOIN item_type t ON t.id=i.item_type_id LEFT JOIN item par ON par.id=i.parent_id LEFT JOIN user_account u ON u.id=i.assignee_id JOIN item_rollup r ON r.item_id=i.id `

func (s *Server) customFields(ctx context.Context, workspace string) (map[string]string, error) {
	rows, err := s.Pool.Query(ctx, `SELECT f.key,f.data_type FROM field_def f JOIN project p ON p.id=f.project_id WHERE p.workspace_id=$1`, workspace)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var key, kind string
		if err := rows.Scan(&key, &kind); err != nil {
			return nil, err
		}
		out[key] = kind
	}
	return out, rows.Err()
}
func (s *Server) selectedFields(w http.ResponseWriter, r *http.Request, policy projection.Policy) ([]string, bool) {
	custom, err := s.customFields(r.Context(), Identity(r).WorkspaceID)
	if err != nil {
		databaseProblem(w, err)
		return nil, false
	}
	q := r.URL.Query()
	fields, err := projection.Parse(q.Get("fields"), q.Has("fields"), policy, custom)
	if err != nil {
		requestProblem(w, err.Error())
		return nil, false
	}
	return fields, true
}
func (s *Server) readItem(ctx context.Context, workspace, key string, fields []string) (map[string]any, int32, error) {
	if fields == nil {
		fields, _ = projection.Parse("", false, projection.Optional, nil)
	}
	expression, args := projection.SQL(fields, 3)
	params := append([]any{workspace, key}, args...)
	var raw []byte
	var version int32
	err := s.Pool.QueryRow(ctx, "SELECT "+expression+",i.version"+itemJoins+"WHERE i.workspace_id=$1 AND i.key=$2", params...).Scan(&raw, &version)
	if err != nil {
		return nil, 0, err
	}
	var doc map[string]any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err = decoder.Decode(&doc); err != nil {
		return nil, 0, err
	}
	return projection.Apply(doc, fields), version, nil
}
func (s *Server) getItem(w http.ResponseWriter, r *http.Request) {
	fields, ok := s.selectedFields(w, r, projection.Optional)
	if !ok {
		return
	}
	doc, _, err := s.readItem(r.Context(), Identity(r).WorkspaceID, chi.URLParam(r, "key"), fields)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	writeCachedJSON(w, r, doc)
}

type itemInput struct {
	Project   string         `json:"project"`
	Type      string         `json:"type"`
	Title     string         `json:"title"`
	Body      *string        `json:"body"`
	Parent    *string        `json:"parent"`
	Assignee  *string        `json:"assignee"`
	Points    *float64       `json:"points"`
	StartDate *string        `json:"start_date"`
	DueDate   *string        `json:"due_date"`
	Fields    map[string]any `json:"fields"`
}

func (s *Server) createItem(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	var in itemInput
	if !decodeJSON(w, r, &in) {
		return
	}
	who := Identity(r)
	var projectID, typeID, statusID, origin string
	var version int32
	err := s.Pool.QueryRow(r.Context(), `SELECT p.id::text,t.id::text,ct.initial_status_id::text,pc.version,w.origin_id::text FROM project p JOIN workspace w ON w.id=p.workspace_id JOIN project_config pc ON pc.project_id=p.id JOIN config_type ct ON ct.project_id=p.id AND ct.version=pc.version JOIN item_type t ON t.id=ct.item_type_id WHERE p.workspace_id=$1 AND p.key_prefix=$2 AND p.archived_at IS NULL AND t.key=$3 AND pc.version=(SELECT max(version) FROM project_config WHERE project_id=p.id)`, who.WorkspaceID, in.Project, in.Type).Scan(&projectID, &typeID, &statusID, &version, &origin)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	if err := s.validateInput(r.Context(), who.WorkspaceID, projectID, in, true); err != nil {
		requestProblem(w, err.Error())
		return
	}
	id := uuid.NewV7()
	pid, _ := uuid.Parse(projectID)
	tid, _ := uuid.Parse(typeID)
	sid, _ := uuid.Parse(statusID)
	oid, _ := uuid.Parse(origin)
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	var parent, assignee *uuid.UUID
	if in.Parent != nil {
		var idString string
		err = s.Pool.QueryRow(r.Context(), `SELECT id::text FROM item WHERE workspace_id=$1 AND project_id=$2 AND key=$3 AND deleted_at IS NULL`, who.WorkspaceID, projectID, *in.Parent).Scan(&idString)
		if err != nil {
			databaseProblem(w, err)
			return
		}
		v, _ := uuid.Parse(idString)
		parent = &v
	}
	if in.Assignee != nil {
		v, _ := uuid.Parse(*in.Assignee)
		assignee = &v
	}
	_, err = store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error {
		m.Create(store.ItemInsert{ID: id, ProjectID: pid, ItemTypeID: tid, StatusID: sid, ParentID: parent, Title: in.Title, Body: in.Body, AssigneeID: assignee, Points: in.Points, StartDate: in.StartDate, DueDate: in.DueDate, Fields: in.Fields, OriginID: oid, ConfigVersion: &version})
		return nil
	}, store.WithActor(actor))
	if err != nil {
		databaseProblem(w, err)
		return
	}
	var key string
	if err = s.Pool.QueryRow(r.Context(), `SELECT key FROM item WHERE id=$1`, id.String()).Scan(&key); err != nil {
		databaseProblem(w, err)
		return
	}
	doc, v, err := s.readItem(r.Context(), who.WorkspaceID, key, nil)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("Location", "/api/v1/items/"+key)
	w.Header().Set("ETag", fmt.Sprintf(`"%d"`, v))
	writeJSON(w, 201, doc)
}

func expectedVersion(w http.ResponseWriter, r *http.Request) (int32, bool) {
	header := r.Header.Get("If-Match")
	if header == "" {
		WriteProblem(w, PreconditionRequired())
		return 0, false
	}
	if len(header) < 3 || header[0] != '"' || header[len(header)-1] != '"' {
		requestProblem(w, "If-Match must contain one quoted item version.")
		return 0, false
	}
	n, err := strconv.ParseInt(header[1:len(header)-1], 10, 32)
	if err != nil || n < 1 {
		requestProblem(w, "If-Match must contain one positive quoted item version.")
		return 0, false
	}
	return int32(n), true
}

func (s *Server) mutationError(w http.ResponseWriter, r *http.Request, err error, submitted any) {
	if errors.Is(err, store.ErrVersionConflict) {
		current, _, readErr := s.readItem(r.Context(), Identity(r).WorkspaceID, chi.URLParam(r, "key"), nil)
		if readErr != nil {
			databaseProblem(w, readErr)
			return
		}
		p := Conflict(current)
		p.Submitted = submitted
		WriteProblem(w, p)
		return
	}
	databaseProblem(w, err)
}

func (s *Server) updateItem(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	version, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	var raw map[string]json.RawMessage
	if !decodeJSON(w, r, &raw) {
		return
	}
	if len(raw) == 0 {
		requestProblem(w, "Provide at least one editable field.")
		return
	}
	for field := range raw {
		switch field {
		case "title", "body", "assignee", "points", "start_date", "due_date", "fields":
		default:
			requestProblem(w, "Field "+field+" cannot be edited here. Use its dedicated action.")
			return
		}
	}
	encoded, _ := json.Marshal(raw)
	var in itemInput
	if err := json.Unmarshal(encoded, &in); err != nil {
		WriteProblem(w, BadRequest())
		return
	}
	who := Identity(r)
	current, _, err := s.readItem(r.Context(), who.WorkspaceID, chi.URLParam(r, "key"), nil)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	var projectID string
	err = s.Pool.QueryRow(r.Context(), `SELECT project_id::text FROM item WHERE workspace_id=$1 AND key=$2`, who.WorkspaceID, chi.URLParam(r, "key")).Scan(&projectID)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	_, titleSet := raw["title"]
	if err = s.validateInput(r.Context(), who.WorkspaceID, projectID, in, titleSet); err != nil {
		requestProblem(w, err.Error())
		return
	}
	id, _ := uuid.Parse(current["id"].(string))
	up := store.ItemUpdate{ID: id}
	var events []store.FieldChange
	keys := make([]string, 0, len(raw))
	for field := range raw {
		keys = append(keys, field)
	}
	sort.Strings(keys)
	for _, field := range keys {
		var value any
		_ = json.Unmarshal(raw[field], &value)
		old := current[field]
		switch field {
		case "title":
			up.Title = &in.Title
		case "body":
			up.SetBody = true
			up.Body = in.Body
		case "points":
			up.SetPoints = true
			up.Points = in.Points
		case "start_date":
			up.SetStartDate = true
			up.StartDate = in.StartDate
		case "due_date":
			up.SetDueDate = true
			up.DueDate = in.DueDate
		case "assignee":
			up.SetAssignee = true
			if in.Assignee != nil {
				v, _ := uuid.Parse(*in.Assignee)
				up.AssigneeID = &v
			}
			if object, ok := old.(map[string]any); ok {
				old = object["id"]
			}
		case "fields":
			if in.Fields == nil {
				requestProblem(w, "fields must be an object.")
				return
			}
			merged := map[string]any{}
			oldFields, _ := current["fields"].(map[string]any)
			for k, v := range oldFields {
				merged[k] = v
			}
			fieldKeys := make([]string, 0, len(in.Fields))
			for k := range in.Fields {
				fieldKeys = append(fieldKeys, k)
			}
			sort.Strings(fieldKeys)
			for _, k := range fieldKeys {
				v := in.Fields[k]
				merged[k] = v
				events = append(events, store.FieldChange{Field: "fields." + k, Old: oldFields[k], New: v})
			}
			up.Fields = merged
			continue
		}
		events = append(events, store.FieldChange{Field: field, Old: old, New: value})
	}
	if len(events) == 0 {
		requestProblem(w, "Provide at least one editable field.")
		return
	}
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	_, err = store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error { m.Update(up, events...); return nil }, store.WithActor(actor), store.WithExpectedVersion(id, version))
	if err != nil {
		s.mutationError(w, r, err, raw)
		return
	}
	doc, v, err := s.readItem(r.Context(), who.WorkspaceID, chi.URLParam(r, "key"), nil)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("ETag", fmt.Sprintf(`"%d"`, v))
	writeJSON(w, 200, doc)
}

func (s *Server) deleteItem(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	version, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	who := Identity(r)
	var idString string
	err := s.Pool.QueryRow(r.Context(), `SELECT id::text FROM item WHERE workspace_id=$1 AND key=$2`, who.WorkspaceID, chi.URLParam(r, "key")).Scan(&idString)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	id, _ := uuid.Parse(idString)
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	_, err = store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error { m.SoftDelete(id); return nil }, store.WithActor(actor), store.WithExpectedVersion(id, version))
	if err != nil {
		s.mutationError(w, r, err, map[string]any{"deleted": true})
		return
	}
	writeJSON(w, 200, map[string]any{"key": chi.URLParam(r, "key"), "deleted": true})
}
