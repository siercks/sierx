package api

import (
	"context"
	"encoding/json"
	"net/url"
	"testing"
)

func TestItemHistory(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	if w := versionCall(s, "PATCH", "/api/v1/items/SRX-1", `{"title":"Edited"}`, cookie, 1); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	if w := versionCall(s, "POST", "/api/v1/items/SRX-1/transition", `{"to_status":"dropped"}`, cookie, 2); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	if w := versionCall(s, "POST", "/api/v1/items/SRX-1/move", `{"parent":null}`, cookie, 3); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	// Keep partition placement stable, while proving old timestamps survive.
	if _, err := s.Pool.Exec(context.Background(), `UPDATE change_event SET at=at-interval '1 minute' WHERE seq=3`); err != nil {
		t.Fatal(err)
	}
	w := apiCall(s, "GET", "/api/v1/items/SRX-1/history", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	var page struct {
		Data       []map[string]any
		NextCursor *string `json:"next_cursor"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &page)
	replacements := map[string]string{}
	for _, event := range page.Data {
		replacements[event["at"].(string)] = "timestamp"
		actor := event["actor"].(map[string]any)
		replacements[actor["id"].(string)] = "author-1"
		replacements[actor["display_name"].(string)] = "Author"
		if event["kind"] == "created" {
			replacements[event["new_value"].(map[string]any)["project_id"].(string)] = "project-1"
		}
	}
	assertGolden(t, "history", w.Body.Bytes(), replacements)
	w = apiCall(s, "GET", "/api/v1/items/SRX-1/history?limit=2", "", cookie)
	_ = json.Unmarshal(w.Body.Bytes(), &page)
	if len(page.Data) != 2 || page.NextCursor == nil {
		t.Fatal("missing history continuation")
	}
	cursor := *page.NextCursor
	// A new event belongs to a refresh, not the already bounded traversal.
	if w := versionCall(s, "PATCH", "/api/v1/items/SRX-1", `{"title":"Later"}`, cookie, 4); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	w = apiCall(s, "GET", "/api/v1/items/SRX-1/history?limit=2&cursor="+url.QueryEscape(cursor), "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	_ = json.Unmarshal(w.Body.Bytes(), &page)
	if len(page.Data) != 2 || page.Data[0]["seq"] != float64(2) || page.Data[1]["seq"] != float64(1) || page.NextCursor != nil {
		t.Fatal("unstable history pagination")
	}
}
