package api

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"uuid"
)

func TestViews(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	w := apiCall(s, "POST", "/api/v1/views", `{"name":"Mine","query":"stats=todo","layout":"list"}`, cookie)
	if w.Code != 400 {
		t.Fatal("invalid saved query accepted")
	}
	assertGolden(t, "views-invalid", w.Body.Bytes(), nil)
	w = apiCall(s, "POST", "/api/v1/views", `{"name":"Mine","query":"status=todo order by rank","layout":"list"}`, cookie)
	if w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	var doc map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	replacements := map[string]string{doc["id"].(string): "view-1", doc["owner_id"].(string): "author-1"}
	assertGolden(t, "views-create", w.Body.Bytes(), replacements)
	w = apiCall(s, "GET", "/api/v1/views", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "views-list", w.Body.Bytes(), replacements)
	ctx := context.Background()
	otherID := uuid.NewV7().String()
	email := otherID + "@example.test"
	_, err := s.Pool.Exec(ctx, `INSERT INTO user_account(id,email,display_name,password_hash) SELECT $1,$2,'Other',password_hash FROM user_account LIMIT 1`, otherID, email)
	if err != nil {
		t.Fatal(err)
	}
	_, err = s.Pool.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) SELECT workspace_id,$1,'member' FROM membership LIMIT 1`, otherID)
	if err != nil {
		t.Fatal(err)
	}
	other := fixtureSession(t, s, email)
	w = apiCall(s, "GET", "/api/v1/views", "", other)
	if w.Code != 200 || strings.Contains(w.Body.String(), "Mine") {
		t.Fatal("private view leaked")
	}
	w = apiCall(s, "POST", "/api/v1/views", `{"name":"Team","query":"status=todo","layout":"board","shared":true}`, cookie)
	if w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	w = apiCall(s, "GET", "/api/v1/views", "", other)
	if w.Code != 200 || !strings.Contains(w.Body.String(), "Team") || strings.Contains(w.Body.String(), "Mine") {
		t.Fatal("shared visibility incorrect")
	}
}
