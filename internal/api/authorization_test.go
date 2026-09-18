package api

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"uuid"
)

func TestWorkspaceIsolation(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	ctx := context.Background()
	w := versionCall(s, "POST", "/api/v1/comments", `{"item":"SRX-1","body":"Private workspace comment"}`, cookie, 1)
	if w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	var comment map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &comment)
	otherID, wid := uuid.NewV7().String(), uuid.NewV7().String()
	email := otherID + "@example.test"
	if _, err := s.Pool.Exec(ctx, `INSERT INTO workspace(id,slug,name,origin_id) VALUES($1,$2,'Other',$1)`, wid, "other-"+wid); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Pool.Exec(ctx, `INSERT INTO user_account(id,email,display_name,password_hash) SELECT $1,$2,'Other',password_hash FROM user_account LIMIT 1`, otherID, email); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Pool.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$2,'admin')`, wid, otherID); err != nil {
		t.Fatal(err)
	}
	other := fixtureSession(t, s, email)
	for _, path := range []string{"/items/SRX-1", "/items/SRX-1/history", "/items/SRX-1/links", "/items/SRX-1/children?fields=key", "/items/SRX-1/rollup", "/comments?item=SRX-1", "/projects/SRX", "/projects/SRX/config"} {
		w = apiCall(s, "GET", "/api/v1"+path, "", other)
		if w.Code != 404 {
			t.Fatalf("cross-workspace %s: %d", path, w.Code)
		}
	}
	for _, tc := range []struct{ method, path, body string }{{"PATCH", "/items/SRX-1", `{"title":"Stolen"}`}, {"DELETE", "/items/SRX-1", ""}, {"POST", "/items/SRX-1/transition", `{"to_status":"dropped"}`}, {"PATCH", "/comments/" + comment["id"].(string), `{"body":"Stolen"}`}} {
		w = versionCall(s, tc.method, "/api/v1"+tc.path, tc.body, other, 2)
		if w.Code != 404 {
			t.Fatalf("cross-workspace mutation %s: %d %s", tc.path, w.Code, w.Body)
		}
	}
	for _, path := range []string{"/items?fields=key", "/changes?since_seq=0", "/views", "/projects"} {
		w = apiCall(s, "GET", "/api/v1"+path, "", other)
		if w.Code != 200 || !strings.Contains(w.Body.String(), `"data":[]`) {
			t.Fatalf("workspace list leaked: %s", w.Body)
		}
	}
	// A different member of the owning workspace still cannot edit this author.
	member := uuid.NewV7().String()
	memberEmail := member + "@example.test"
	if _, err := s.Pool.Exec(ctx, `INSERT INTO user_account(id,email,display_name,password_hash) SELECT $1,$2,'Member',password_hash FROM user_account LIMIT 1`, member, memberEmail); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Pool.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) SELECT workspace_id,$1,'member' FROM project WHERE key_prefix='SRX'`, member); err != nil {
		t.Fatal(err)
	}
	memberCookie := fixtureSession(t, s, memberEmail)
	for _, method := range []string{"PATCH", "DELETE"} {
		w = versionCall(s, method, fmt.Sprint("/api/v1/comments/", comment["id"]), `{"body":"Stolen"}`, memberCookie, 2)
		if w.Code != 403 {
			t.Fatal("comment author fence failed")
		}
	}
}
