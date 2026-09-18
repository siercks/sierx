package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func itemFixture(t *testing.T) (*Server, *http.Cookie, map[string]any) {
	t.Helper()
	s, email, _, _ := authFixture(t)
	cookie := fixtureSession(t, s, email)
	if w := apiCall(s, "POST", "/api/v1/projects", `{"key_prefix":"SRX","name":"Backlog","kind":"delivery"}`, cookie); w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	w := apiCall(s, "POST", "/api/v1/items", `{"project":"SRX","type":"story","title":"Original"}`, cookie)
	if w.Code != 201 {
		t.Fatalf("create item %d %s", w.Code, w.Body)
	}
	var item map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &item); err != nil {
		t.Fatal(err)
	}
	return s, cookie, item
}
func versionCall(s *Server, method, path, body string, cookie *http.Cookie, version int) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("If-Match", fmt.Sprintf(`"%d"`, version))
	r.AddCookie(cookie)
	w := httptest.NewRecorder()
	s.Router.ServeHTTP(w, r)
	return w
}
func itemReplacements(item map[string]any) map[string]string {
	out := map[string]string{item["id"].(string): "item-1"}
	for _, key := range []string{"created_at", "updated_at", "deleted_at"} {
		if value, ok := item[key].(string); ok {
			out[value] = "timestamp"
		}
	}
	return out
}
func TestItemsCRUD(t *testing.T) {
	s, cookie, item := itemFixture(t)
	body, _ := json.Marshal(item)
	assertGolden(t, "items-create", body, itemReplacements(item))
	w := apiCall(s, "GET", "/api/v1/items/SRX-1", "", cookie)
	if w.Code != 200 || w.Header().Get("ETag") != `"1"` {
		t.Fatal("detail failed")
	}
	assertGolden(t, "items-detail", w.Body.Bytes(), itemReplacements(item))
	w = apiCall(s, "GET", "/api/v1/items?fields=key,title,status.category", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "items-list", w.Body.Bytes(), nil)
	if w := apiCall(s, "GET", "/api/v1/items", "", cookie); w.Code != 400 {
		t.Fatal("projection not required")
	}
	if w := apiCall(s, "PATCH", "/api/v1/items/SRX-1", `{"title":"Missing version"}`, cookie); w.Code != 428 {
		t.Fatal("missing If-Match accepted")
	}
	w = versionCall(s, "PATCH", "/api/v1/items/SRX-1", `{"title":"Server edit"}`, cookie, 1)
	if w.Code != 200 {
		t.Fatalf("patch %d %s", w.Code, w.Body)
	}
	var updated map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &updated)
	assertGolden(t, "items-update", w.Body.Bytes(), itemReplacements(updated))
	w = versionCall(s, "PATCH", "/api/v1/items/SRX-1", `{"title":"Client edit"}`, cookie, 1)
	if w.Code != 409 {
		t.Fatal("stale edit accepted")
	}
	assertGolden(t, "items-conflict", w.Body.Bytes(), itemReplacements(updated))
	var originSeq, seq, events int64
	if err := s.Pool.QueryRow(context.Background(), `SELECT origin_seq,change_seq,(SELECT count(*) FROM change_event WHERE item_id=i.id) FROM item i WHERE key='SRX-1'`).Scan(&originSeq, &seq, &events); err != nil {
		t.Fatal(err)
	}
	if originSeq != 1 || seq != 2 || events != 2 {
		t.Fatalf("bad sequence/event state: %d %d %d", originSeq, seq, events)
	}
	w = versionCall(s, "DELETE", "/api/v1/items/SRX-1", "", cookie, 2)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "items-delete", w.Body.Bytes(), nil)
	if w := apiCall(s, "GET", "/api/v1/items/SRX-1", "", cookie); w.Code != 200 || strings.Contains(w.Body.String(), `"deleted_at":null`) {
		t.Fatal("soft-deleted detail disappeared")
	}
	w = apiCall(s, "GET", "/api/v1/items?fields=key", "", cookie)
	assertGolden(t, "empty-page", w.Body.Bytes(), nil)
	w = apiCall(s, "POST", "/api/v1/items", `{"project":"SRX","type":"story","title":"Next"}`, cookie)
	if w.Code != 201 || !strings.Contains(w.Body.String(), `"key":"SRX-2"`) {
		t.Fatal("key reused after delete")
	}
}

func TestFailedCreateRollsBack(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	ctx := context.Background()
	_, err := s.Pool.Exec(ctx, `CREATE FUNCTION fixture_reject_item() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture rejection'; END $$; CREATE TRIGGER fixture_reject_item BEFORE INSERT ON item FOR EACH ROW EXECUTE FUNCTION fixture_reject_item()`)
	if err != nil {
		t.Fatal(err)
	}
	w := apiCall(s, "POST", "/api/v1/items", `{"project":"SRX","type":"story","title":"Rejected"}`, cookie)
	if w.Code < 400 {
		t.Fatal("fault injection accepted")
	}
	var next, seq int
	if err := s.Pool.QueryRow(ctx, `SELECT next_key_num,(SELECT value FROM seq_counter WHERE workspace_id=p.workspace_id) FROM project p WHERE key_prefix='SRX'`).Scan(&next, &seq); err != nil {
		t.Fatal(err)
	}
	if next != 2 || seq != 1 {
		t.Fatalf("failed create burned key/seq: %d %d", next, seq)
	}
}

func TestConcurrentItemEdit(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	codes := make(chan int, 2)
	for _, title := range []string{"First edit", "Second edit"} {
		go func(title string) {
			body, _ := json.Marshal(map[string]string{"title": title})
			codes <- versionCall(s, "PATCH", "/api/v1/items/SRX-1", string(body), cookie, 1).Code
		}(title)
	}
	a, b := <-codes, <-codes
	if !(a == 200 && b == 409 || a == 409 && b == 200) {
		t.Fatalf("concurrent statuses %d %d", a, b)
	}
	var version, events int
	if err := s.Pool.QueryRow(context.Background(), `SELECT version,(SELECT count(*) FROM change_event WHERE item_id=i.id) FROM item i WHERE key='SRX-1'`).Scan(&version, &events); err != nil {
		t.Fatal(err)
	}
	if version != 2 || events != 2 {
		t.Fatal("losing mutation changed state")
	}
}

func TestItemSequencePrecision(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	if _, err := s.Pool.Exec(context.Background(), `UPDATE seq_counter SET value=9007199254740992`); err != nil {
		t.Fatal(err)
	}
	w := apiCall(s, "POST", "/api/v1/items", `{"project":"SRX","type":"story","title":"Large sequence"}`, cookie)
	if w.Code != 201 || !strings.Contains(w.Body.String(), `"change_seq":9007199254740993`) {
		t.Fatalf("sequence rounded: %d %s", w.Code, w.Body)
	}
}
