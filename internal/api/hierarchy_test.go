package api

import (
	"encoding/json"
	"fmt"
	"github.com/siercks/sierx/internal/api/projection"
	"net/url"
	"strings"
	"testing"
)

func TestHierarchyReads(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	for n := 2; n <= 6; n++ {
		w := apiCall(s, "POST", "/api/v1/items", fmt.Sprintf(`{"project":"SRX","type":"story","title":"Level %d","parent":"SRX-%d"}`, n, n-1), cookie)
		if w.Code != 201 {
			t.Fatal(w.Body.String())
		}
	}
	for _, tc := range []struct{ path, golden string }{{"children?fields=key,status.category", "hierarchy-children"}, {"descendants?depth=2&fields=key,parent.key", "hierarchy-descendants"}, {"rollup", "hierarchy-rollup"}} {
		w := apiCall(s, "GET", "/api/v1/items/SRX-1/"+tc.path, "", cookie)
		if w.Code != 200 {
			t.Fatal(w.Body.String())
		}
		assertGolden(t, tc.golden, w.Body.Bytes(), nil)
	}
	w := apiCall(s, "GET", "/api/v1/items/SRX-6/rollup", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "hierarchy-leaf", w.Body.Bytes(), nil)
	path := "/api/v1/items/SRX-1/descendants?fields=key&limit=2"
	var got []string
	for {
		w = apiCall(s, "GET", path, "", cookie)
		if w.Code != 200 {
			t.Fatal(w.Body.String())
		}
		var page struct {
			Data       []struct{ Key string }
			NextCursor *string `json:"next_cursor"`
		}
		_ = json.Unmarshal(w.Body.Bytes(), &page)
		for _, item := range page.Data {
			got = append(got, item.Key)
		}
		if page.NextCursor == nil {
			break
		}
		path = "/api/v1/items/SRX-1/descendants?fields=key&limit=2&cursor=" + url.QueryEscape(*page.NextCursor)
	}
	if strings.Join(got, ",") != "SRX-2,SRX-3,SRX-4,SRX-5,SRX-6" {
		t.Fatal(got)
	}
	for _, path := range []string{"children", "descendants?fields=key&depth=9", "rollup?fields=key"} {
		if w := apiCall(s, "GET", "/api/v1/items/SRX-1/"+path, "", cookie); w.Code != 400 {
			t.Fatal("invalid hierarchy request accepted")
		}
	}
	expression, _ := projection.SQL([]string{"rollup"}, 1)
	query := strings.ToUpper(expression + itemJoins)
	for _, forbidden := range []string{"WITH RECURSIVE", "COUNT(", "SUM(", "MIN(", "MAX("} {
		if strings.Contains(query, forbidden) {
			t.Fatal("rollup aggregates on read")
		}
	}
	if !strings.Contains(query, "ITEM_ROLLUP") {
		t.Fatal("rollup not materialized")
	}
}
