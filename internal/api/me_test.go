package api

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestMePreferences(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	w := apiCall(s, "PATCH", "/api/v1/me", `{"theme":"dark-hc","reduced_motion":true,"display_name":"Updated"}`, cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	var doc map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	replacements := map[string]string{doc["id"].(string): "author-1", doc["workspace_id"].(string): "workspace-1", doc["email"].(string): "author@example.test"}
	assertGolden(t, "me-update", w.Body.Bytes(), replacements)
	w = apiCall(s, "GET", "/api/v1/me", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "me-update", w.Body.Bytes(), replacements)
	w = apiCall(s, "PATCH", "/api/v1/me", `{"theme":"blue"}`, cookie)
	if w.Code != 400 {
		t.Fatal("invalid theme accepted")
	}
	assertGolden(t, "me-invalid-theme", w.Body.Bytes(), nil)
	w = apiCall(s, "PATCH", "/api/v1/me", `{"email":"changed@example.test"}`, cookie)
	if w.Code != 400 {
		t.Fatal("email accepted")
	}
	assertGolden(t, "me-forbidden-field", w.Body.Bytes(), nil)
	w = apiCall(s, "PATCH", "/api/v1/me", `{"reduced_motion":null}`, cookie)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"reduced_motion":null`) {
		t.Fatal("OS preference reset failed")
	}
	if w := apiCall(s, "PATCH", "/api/v1/items/SRX-1", `{"title":"No version"}`, cookie); w.Code != 428 {
		t.Fatal("item lost version requirement")
	}
}
