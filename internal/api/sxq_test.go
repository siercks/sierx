package api

import (
	"encoding/json"
	"net/url"
	"reflect"
	"testing"
)

func TestSXQItems(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	for _, body := range []string{`{"project":"SRX","type":"story","title":"Certificate rotation","points":3,"fields":{"impact":4}}`, `{"project":"SRX","type":"story","title":"Equal points","points":3,"fields":{"impact":7}}`, `{"project":"SRX","type":"story","title":"Larger","points":9}`} {
		if w := apiCall(s, "POST", "/api/v1/items", body, cookie); w.Code != 201 {
			t.Fatal(w.Body.String())
		}
	}
	for _, tc := range []struct {
		q    string
		keys []string
	}{
		{"points >= 3 order by points desc", []string{"SRX-4", "SRX-2", "SRX-3"}},
		{"project=SRX order by points", []string{"SRX-2", "SRX-3", "SRX-4", "SRX-1"}},
		{"project=SRX order by points desc", []string{"SRX-4", "SRX-2", "SRX-3", "SRX-1"}},
		{"fields.impact >= 4 order by fields.impact desc", []string{"SRX-3", "SRX-2"}},
		{`text ~ "certificate rotation"`, []string{"SRX-2"}},
		{`title = "x' OR 1=1 --"`, nil},
		{"points is NULL", []string{"SRX-1"}},
		{"due_date < now() + 7d", nil},
		{"assignee=me()", nil},
	} {
		t.Run(tc.q, func(t *testing.T) {
			base := "/api/v1/items?fields=key&limit=1&q=" + url.QueryEscape(tc.q)
			path := base
			var keys []string
			for n := 0; n < 10; n++ {
				w := apiCall(s, "GET", path, "", cookie)
				if w.Code != 200 {
					t.Fatalf("%d %s", w.Code, w.Body)
				}
				var page struct {
					Data       []struct{ Key string }
					NextCursor *string `json:"next_cursor"`
				}
				_ = json.Unmarshal(w.Body.Bytes(), &page)
				for _, item := range page.Data {
					keys = append(keys, item.Key)
				}
				if page.NextCursor == nil {
					break
				}
				path = base + "&cursor=" + url.QueryEscape(*page.NextCursor)
			}
			if !reflect.DeepEqual(keys, tc.keys) {
				t.Fatalf("got %v want %v", keys, tc.keys)
			}
		})
	}
	for _, q := range []string{"stats=todo", "descendants(status=todo)>0", "due_date < endOfSprint()", "fields.unknown=3"} {
		if w := apiCall(s, "GET", "/api/v1/items?fields=key&q="+url.QueryEscape(q), "", cookie); w.Code != 400 {
			t.Fatal("invalid query accepted: " + w.Body.String())
		}
	}
	w := apiCall(s, "GET", "/api/v1/sxq/complete?partial=sta", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "sxq-complete", w.Body.Bytes(), nil)
}
