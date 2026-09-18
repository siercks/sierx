package api

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func TestChanges(t *testing.T) {
	s, cookie, item := itemFixture(t)
	w := apiCall(s, "GET", "/api/v1/changes?since_seq=0", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	var page struct {
		Data    []map[string]any
		NextSeq int64 `json:"next_seq"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &page)
	if page.NextSeq != 1 || len(page.Data) != 1 {
		t.Fatal("creation sequence missing")
	}
	event := page.Data[0]
	replacements := map[string]string{item["id"].(string): "item-1", event["actor_id"].(string): "author-1", event["at"].(string): "timestamp"}
	assertGolden(t, "changes", w.Body.Bytes(), replacements)
	w = apiCall(s, "GET", "/api/v1/changes?since_seq=1", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "changes-empty", w.Body.Bytes(), nil)
	// Large content never gets replicated into the small invalidation feed.
	for n := 0; n < 49; n++ {
		body, _ := json.Marshal(map[string]string{"body": strings.Repeat("markdown ", 5000)})
		w = versionCall(s, "PATCH", "/api/v1/items/SRX-1", string(body), cookie, n+1)
		if w.Code != 200 {
			t.Fatal(w.Body.String())
		}
	}
	w = apiCall(s, "GET", "/api/v1/changes?since_seq=0&limit=50", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	_ = json.Unmarshal(w.Body.Bytes(), &page)
	if len(page.Data) != 50 || page.NextSeq != 50 || w.Body.Len() >= 20000 {
		t.Fatalf("delta size/count %d %d %d", w.Body.Len(), len(page.Data), page.NextSeq)
	}
	if w.Header().Get("ETag") != "" {
		t.Fatal("change feed must not emit ETag")
	}
	for _, value := range []string{"-1", "bad", "9223372036854775808"} {
		w = apiCall(s, "GET", "/api/v1/changes?since_seq="+value, "", cookie)
		if w.Code != 400 {
			t.Fatal("bad sequence accepted")
		}
	}
	var seen int64
	for seen < 50 {
		w = apiCall(s, "GET", fmt.Sprintf("/api/v1/changes?since_seq=%d&limit=7", seen), "", cookie)
		if w.Code != 200 {
			t.Fatal(w.Body.String())
		}
		_ = json.Unmarshal(w.Body.Bytes(), &page)
		for _, event := range page.Data {
			seen++
			if int64(event["seq"].(float64)) != seen {
				t.Fatal("delta sequence gap")
			}
		}
		if page.NextSeq != seen {
			t.Fatal("wrong next sequence")
		}
	}
}
