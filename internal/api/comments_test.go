package api

import (
	"context"
	"encoding/json"
	"testing"
)

func TestComments(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	w := versionCall(s, "POST", "/api/v1/comments", `{"item":"SRX-1","body":"**Raw** <script>example</script>"}`, cookie, 1)
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	var doc map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	id := doc["id"].(string)
	actor := doc["author"].(map[string]any)
	replacements := map[string]string{id: "comment-1", actor["id"].(string): "author-1", actor["display_name"].(string): "Author", doc["created_at"].(string): "timestamp"}
	assertGolden(t, "comments-create", w.Body.Bytes(), replacements)
	w = apiCall(s, "GET", "/api/v1/comments?item=SRX-1", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "comments-list", w.Body.Bytes(), replacements)
	w = versionCall(s, "PATCH", "/api/v1/comments/"+id, `{"body":"Edited Markdown"}`, cookie, 1)
	if w.Code != 409 {
		t.Fatal("stale comment accepted")
	}
	w = versionCall(s, "PATCH", "/api/v1/comments/"+id, `{"body":"Edited Markdown"}`, cookie, 2)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	replacements[doc["edited_at"].(string)] = "timestamp"
	assertGolden(t, "comments-edit", w.Body.Bytes(), replacements)
	w = versionCall(s, "DELETE", "/api/v1/comments/"+id, "", cookie, 3)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	replacements[doc["deleted_at"].(string)] = "timestamp"
	assertGolden(t, "comments-delete", w.Body.Bytes(), replacements)
	var version, events int
	if err := s.Pool.QueryRow(context.Background(), `SELECT version,(SELECT count(*) FROM change_event WHERE item_id=i.id AND field='comment') FROM item i WHERE key='SRX-1'`).Scan(&version, &events); err != nil || version != 4 || events != 3 {
		t.Fatalf("%d %d %v", version, events, err)
	}
}
