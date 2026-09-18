package api

import (
	"context"
	"encoding/json"
	"testing"
)

func TestLinks(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	if w := apiCall(s, "POST", "/api/v1/projects", `{"key_prefix":"OTH","name":"Other","kind":"delivery"}`, cookie); w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	if w := apiCall(s, "POST", "/api/v1/items", `{"project":"OTH","type":"story","title":"Dependency"}`, cookie); w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	w := versionCall(s, "POST", "/api/v1/items/SRX-1/links", `{"to":"SRX-1","kind":"blocks"}`, cookie, 1)
	if w.Code != 422 {
		t.Fatal("self link accepted")
	}
	w = versionCall(s, "POST", "/api/v1/items/SRX-1/links", `{"to":"OTH-1","kind":"blocks"}`, cookie, 1)
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	var doc map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	id := doc["id"].(string)
	replacements := map[string]string{id: "link-1", doc["created_at"].(string): "timestamp"}
	assertGolden(t, "links-create", w.Body.Bytes(), replacements)
	w = apiCall(s, "GET", "/api/v1/items/OTH-1/links", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "links-list", w.Body.Bytes(), replacements)
	w = versionCall(s, "DELETE", "/api/v1/links/"+id, "", cookie, 1)
	if w.Code != 409 {
		t.Fatal("stale unlink accepted")
	}
	w = versionCall(s, "DELETE", "/api/v1/links/"+id, "", cookie, 2)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "links-delete", w.Body.Bytes(), replacements)
	var version, events int
	if err := s.Pool.QueryRow(context.Background(), `SELECT version,(SELECT count(*) FROM change_event WHERE item_id=i.id AND kind IN ('linked','unlinked')) FROM item i WHERE key='SRX-1'`).Scan(&version, &events); err != nil || version != 3 || events != 2 {
		t.Fatalf("version/events %d %d %v", version, events, err)
	}
}
