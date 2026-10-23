package api

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"uuid"
)

func TestWorkspaceSettingsAuthorizationConflictAndRoster(t *testing.T) {
	s, email, uid, wid := authFixture(t)
	cookie := fixtureSession(t, s, email)
	w := apiCall(s, "GET", "/api/v1/workspace", "", cookie)
	var initial WorkspaceSettings
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &initial) != nil {
		t.Fatal(w.Code, w.Body)
	}
	if initial.ID != wid || initial.Version != 1 {
		t.Fatal(initial)
	}
	assertGolden(t, "workspace-settings", w.Body.Bytes(), map[string]string{wid: "workspace-1"})
	if w = apiCall(s, "PATCH", "/api/v1/workspace", `{"name":"New name"}`, cookie); w.Code != 428 {
		t.Fatal(w.Code)
	}
	w = versionCall(s, "PATCH", "/api/v1/workspace", `{"name":"New name"}`, cookie, 1)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"version":2`) {
		t.Fatal(w.Code, w.Body)
	}
	assertGolden(t, "workspace-update", w.Body.Bytes(), map[string]string{wid: "workspace-1"})
	w = versionCall(s, "PATCH", "/api/v1/workspace", `{"name":"Stale"}`, cookie, 1)
	if w.Code != 409 || !strings.Contains(w.Body.String(), "current_workspace") {
		t.Fatal(w.Code, w.Body)
	}
	if w = versionCall(s, "PATCH", "/api/v1/workspace", `{"name":"   "}`, cookie, 2); w.Code != 400 {
		t.Fatal(w.Code)
	}
	if w = versionCall(s, "PATCH", "/api/v1/workspace", `{"name":"X","slug":"changed"}`, cookie, 2); w.Code != 400 {
		t.Fatal(w.Code)
	}
	ctx := context.Background()
	foreign := uuid.NewV7().String()
	for _, query := range []string{`INSERT INTO workspace(id,slug,name,origin_id) VALUES($1::uuid,$1::text,'Other workspace',$1::uuid)`, `INSERT INTO user_account(id,email,display_name) VALUES($1,'foreign@example.test','Foreign person')`, `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$1,'admin')`} {
		if _, err := s.Pool.Exec(ctx, query, foreign); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := s.Pool.Exec(ctx, `UPDATE membership SET role='member' WHERE workspace_id=$1 AND user_id=$2`, wid, uid); err != nil {
		t.Fatal(err)
	}
	if w = versionCall(s, "PATCH", "/api/v1/workspace", `{"name":"Member write"}`, cookie, 2); w.Code != 403 {
		t.Fatal(w.Code)
	}
	w = apiCall(s, "GET", "/api/v1/members", "", cookie)
	if w.Code != 200 || !strings.Contains(w.Body.String(), "Test user") || strings.Contains(w.Body.String(), "Foreign person") || strings.Contains(w.Body.String(), "email") {
		t.Fatal(w.Code, w.Body)
	}
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SET LOCAL ROLE sierx_runtime`); err != nil {
		t.Fatal(err)
	}
	if _, err = tx.Exec(ctx, `SELECT set_config('sierx.workspace_id',$1,true),set_config('sierx.user_id',$2,true),set_config('sierx.role','member',true)`, wid, uid); err != nil {
		t.Fatal(err)
	}
	tag, err := tx.Exec(ctx, `UPDATE workspace SET name='Forbidden',version=version+1 WHERE id=$1`, wid)
	if err != nil || tag.RowsAffected() != 0 {
		t.Fatal("member database policy", tag, err)
	}
	if _, err = tx.Exec(ctx, `SELECT set_config('sierx.role','admin',true)`); err != nil {
		t.Fatal(err)
	}
	tag, err = tx.Exec(ctx, `UPDATE workspace SET name='Forbidden',version=version+1 WHERE id=$1`, foreign)
	if err != nil || tag.RowsAffected() != 0 {
		t.Fatal("tenant database policy", tag, err)
	}
	tag, err = tx.Exec(ctx, `UPDATE workspace SET name='Allowed',version=version+1 WHERE id=$1`, wid)
	if err != nil || tag.RowsAffected() != 1 {
		t.Fatal("admin database policy", tag, err)
	}
}

func TestWorkflowSnapshotsValidationAndTransitions(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	var current workflowConfig
	w := apiCall(s, "GET", "/api/v1/projects/SRX/config", "", cookie)
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &current) != nil {
		t.Fatal(w.Code, w.Body)
	}
	draft := workflowDraft{Statuses: append(current.Statuses, workflowStatus{"planned", "Planned", "open"}, workflowStatus{"blocked", "Blocked", "active"}, workflowStatus{"completed", "Completed", "done"}), Transitions: current.Transitions, Initial: map[string]string{}}
	for _, kind := range current.Types {
		draft.Initial[kind.Key] = kind.Initial
	}
	draft.Initial["story"] = "planned"
	draft.Transitions["todo"] = append(draft.Transitions["todo"], workflowArc{"blocked", []string{"assignee"}})
	draft.Transitions["blocked"] = []workflowArc{{"completed", []string{}}}
	encoded, _ := json.Marshal(draft)
	w = versionCall(s, "PUT", "/api/v1/projects/SRX/config", string(encoded), cookie, 1)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"version": 2`) && !strings.Contains(w.Body.String(), `"version":2`) {
		t.Fatal(w.Code, w.Body)
	}
	assertGolden(t, "workflow-update", w.Body.Bytes(), nil)
	var originalStatus, configVersion int
	if err := s.Pool.QueryRow(context.Background(), `SELECT version,config_version FROM item WHERE key='SRX-1'`).Scan(&originalStatus, &configVersion); err != nil || originalStatus != 1 || configVersion != 1 {
		t.Fatal("config edit changed an item", originalStatus, configVersion, err)
	}
	w = versionCall(s, "PUT", "/api/v1/projects/SRX/config", string(encoded), cookie, 1)
	if w.Code != 409 || !strings.Contains(w.Body.String(), "current_config") {
		t.Fatal(w.Code, w.Body)
	}
	if w = versionCall(s, "POST", "/api/v1/items/SRX-1/transition", `{"to_status":"blocked"}`, cookie, 1); w.Code != 422 {
		t.Fatal("missing requirements accepted", w.Code, w.Body)
	}
	var uid string
	if err := s.Pool.QueryRow(context.Background(), `SELECT user_id::text FROM membership WHERE role='admin' LIMIT 1`).Scan(&uid); err != nil {
		t.Fatal(err)
	}
	w = versionCall(s, "POST", "/api/v1/items/SRX-1/transition", `{"to_status":"blocked","fields":{"assignee":"`+uid+`"}}`, cookie, 1)
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	w = versionCall(s, "POST", "/api/v1/items/SRX-1/transition", `{"to_status":"completed"}`, cookie, 2)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"category":"done"`) {
		t.Fatal(w.Code, w.Body)
	}
	w = apiCall(s, "POST", "/api/v1/items", `{"project":"SRX","type":"story","title":"Starts planned"}`, cookie)
	if w.Code != 201 || !strings.Contains(w.Body.String(), `"name":"Planned"`) {
		t.Fatal(w.Code, w.Body)
	}
	invalid := draft
	invalid.Statuses = append([]workflowStatus{}, draft.Statuses...)
	invalid.Statuses[0].Name = "Rewrite history"
	encoded, _ = json.Marshal(invalid)
	if w = versionCall(s, "PUT", "/api/v1/projects/SRX/config", string(encoded), cookie, 2); w.Code != 400 {
		t.Fatal("immutable status accepted", w.Code, w.Body)
	}
	invalid = draft
	invalid.Transitions = map[string][]workflowArc{"todo": {{"blocked", []string{"unknown"}}}}
	encoded, _ = json.Marshal(invalid)
	if w = versionCall(s, "PUT", "/api/v1/projects/SRX/config", string(encoded), cookie, 2); w.Code != 400 {
		t.Fatal("unknown requirement accepted", w.Code, w.Body)
	}
	var versions int
	if err := s.Pool.QueryRow(context.Background(), `SELECT count(*) FROM project_config`).Scan(&versions); err != nil || versions != 2 {
		t.Fatal("rejected write changed config", versions, err)
	}
	encoded, _ = json.Marshal(draft)
	results := make(chan int, 2)
	for range 2 {
		go func() { results <- versionCall(s, "PUT", "/api/v1/projects/SRX/config", string(encoded), cookie, 2).Code }()
	}
	first, second := <-results, <-results
	if !((first == 200 && second == 409) || (first == 409 && second == 200)) {
		t.Fatal("concurrent workflow saves must accept exactly one draft", first, second)
	}
	if err := s.Pool.QueryRow(context.Background(), `SELECT count(*) FROM project_config`).Scan(&versions); err != nil || versions != 3 {
		t.Fatal("concurrent workflow save published extra versions", versions, err)
	}
	if _, err := s.Pool.Exec(context.Background(), `UPDATE membership SET role='member'`); err != nil {
		t.Fatal(err)
	}
	encoded, _ = json.Marshal(draft)
	if w = versionCall(s, "PUT", "/api/v1/projects/SRX/config", string(encoded), cookie, 2); w.Code != 403 {
		t.Fatal("member configured workflow", w.Code, w.Body)
	}
}
