package api

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
)

func TestTransitions(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	path := "/api/v1/items/SRX-1/transition"
	for _, tc := range []struct{ body, golden string }{{`{"to_status":"done"}`, "transition-rejected"}, {`{"to_status":"doing"}`, "transition-required"}} {
		w := versionCall(s, "POST", path, tc.body, cookie, 1)
		if w.Code != 422 {
			t.Fatalf("%d %s", w.Code, w.Body)
		}
		assertGolden(t, tc.golden, w.Body.Bytes(), nil)
	}
	ctx := context.Background()
	var actor string
	if err := s.Pool.QueryRow(ctx, `SELECT id::text FROM user_account WHERE email='admin@example.test'`).Scan(&actor); err != nil {
		if err = s.Pool.QueryRow(ctx, `SELECT user_id::text FROM membership WHERE role='admin' LIMIT 1`).Scan(&actor); err != nil {
			t.Fatal(err)
		}
	}
	w := versionCall(s, "POST", path, fmt.Sprintf(`{"to_status":"doing","fields":{"assignee":%q}}`, actor), cookie, 1)
	if w.Code != 200 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	var doc map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	if doc["version"] != float64(2) || doc["status"].(map[string]any)["key"] != "doing" {
		t.Fatal(doc)
	}
	var count int
	if err := s.Pool.QueryRow(ctx, `SELECT count(*) FROM change_event WHERE kind='status_changed' AND old_value='"todo"'::jsonb AND new_value='"doing"'::jsonb`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("status event %d %v", count, err)
	}
	// Current configuration changes independently; ordinary edits retain v1.
	_, err := s.Pool.Exec(ctx, `INSERT INTO project_config(project_id,version) SELECT id,2 FROM project; INSERT INTO config_transition(project_id,version,from_status_id,to_status_id,requires) SELECT project_id,2,from_status_id,to_status_id,requires FROM config_transition WHERE version=1`)
	if err != nil {
		t.Fatal(err)
	}
	w = versionCall(s, "PATCH", "/api/v1/items/SRX-1", `{"title":"Edited"}`, cookie, 2)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	if doc["config_version"] != float64(1) {
		t.Fatal("edit advanced config")
	}
	w = versionCall(s, "POST", path, `{"to_status":"review"}`, cookie, 3)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	if doc["config_version"] != float64(2) {
		t.Fatal("transition did not advance config")
	}
	w = versionCall(s, "POST", path, `{"to_status":"done"}`, cookie, 3)
	if w.Code != 409 {
		t.Fatal("stale transition accepted")
	}
}

func TestWildcardTransitions(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	ctx := context.Background()
	var actor string
	if err := s.Pool.QueryRow(ctx, `SELECT user_id::text FROM membership WHERE role='admin' LIMIT 1`).Scan(&actor); err != nil {
		t.Fatal(err)
	}
	for n, steps := range [][]string{{}, {"doing"}, {"doing", "review"}, {"doing", "review", "done"}} {
		key := "SRX-1"
		if n > 0 {
			w := apiCall(s, "POST", "/api/v1/items", `{"project":"SRX","type":"story","title":"Wildcard"}`, cookie)
			if w.Code != 201 {
				t.Fatal(w.Body.String())
			}
			key = fmt.Sprintf("SRX-%d", n+1)
		}
		path := "/api/v1/items/" + key + "/transition"
		version := 1
		for _, status := range steps {
			w := versionCall(s, "POST", path, fmt.Sprintf(`{"to_status":%q,"fields":{"assignee":%q}}`, status, actor), cookie, version)
			if w.Code != 200 {
				t.Fatal(w.Body.String())
			}
			version++
		}
		w := versionCall(s, "POST", path, `{"to_status":"dropped"}`, cookie, version)
		if w.Code != 200 {
			t.Fatal(w.Body.String())
		}
		w = versionCall(s, "POST", path, `{"to_status":"dropped"}`, cookie, version+1)
		if w.Code != 422 {
			t.Fatal("dropped self-transition accepted")
		}
	}
}
