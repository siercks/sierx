package api

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"uuid"

	"github.com/leanovate/gopter"
	"github.com/leanovate/gopter/gen"
	"github.com/leanovate/gopter/prop"
	"github.com/siercks/sierx/internal/store"
)

func TestMove(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	for _, body := range []string{`{"project":"SRX","type":"story","title":"Second"}`, `{"project":"SRX","type":"story","title":"Third","parent":"SRX-1"}`} {
		if w := apiCall(s, "POST", "/api/v1/items", body, cookie); w.Code != 201 {
			t.Fatal(w.Body.String())
		}
	}
	w := versionCall(s, "POST", "/api/v1/items/SRX-1/move", `{"parent":"SRX-3"}`, cookie, 1)
	if w.Code != 422 {
		t.Fatal("cycle accepted")
	}
	w = versionCall(s, "POST", "/api/v1/items/SRX-1/move", `{"parent":"SRX-2","rank_after":"SRX-2"}`, cookie, 1)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	var doc map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &doc)
	if doc["version"] != float64(2) || doc["parent"].(map[string]any)["key"] != "SRX-2" {
		t.Fatal(doc)
	}
	assertGolden(t, "move-success", w.Body.Bytes(), itemReplacements(doc))
	var correct bool
	if err := s.Pool.QueryRow(context.Background(), `SELECT (SELECT rank FROM item WHERE key='SRX-2')<(SELECT rank FROM item WHERE key='SRX-1') AND (SELECT rank FROM item WHERE key='SRX-1')<(SELECT rank FROM item WHERE key='SRX-3') AND (SELECT nlevel(path) FROM item WHERE key='SRX-3')=3`).Scan(&correct); err != nil || !correct {
		t.Fatalf("rank/subtree %v %v", correct, err)
	}
	if w = apiCall(s, "POST", "/api/v1/projects", `{"key_prefix":"OTH","name":"Other","kind":"delivery"}`, cookie); w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	if w = apiCall(s, "POST", "/api/v1/items", `{"project":"OTH","type":"story","title":"Other"}`, cookie); w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	w = versionCall(s, "POST", "/api/v1/items/SRX-1/move", `{"parent":"OTH-1"}`, cookie, 2)
	if w.Code != 422 {
		t.Fatal(w.Body.String())
	}
	assertGolden(t, "move-cross-project", w.Body.Bytes(), nil)
	// Grow SRX-3's branch to depth 8, then try moving a separate root under it.
	parent := "SRX-3"
	for n := 4; n <= 8; n++ {
		w = apiCall(s, "POST", "/api/v1/items", fmt.Sprintf(`{"project":"SRX","type":"story","title":"Depth","parent":%q}`, parent), cookie)
		if w.Code != 201 {
			t.Fatal(w.Body.String())
		}
		parent = fmt.Sprintf("SRX-%d", n)
	}
	w = apiCall(s, "POST", "/api/v1/items", `{"project":"SRX","type":"story","title":"Root"}`, cookie)
	if w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	w = versionCall(s, "POST", "/api/v1/items/SRX-9/move", `{"parent":"SRX-8"}`, cookie, 1)
	if w.Code != 422 {
		t.Fatal("depth 9 accepted")
	}
}

func TestAPIHierarchyProperty(t *testing.T) {
	parameters := gopter.DefaultTestParameters()
	parameters.MinSuccessfulTests = 8
	parameters.MaxSize = 12
	properties := gopter.NewProperties(parameters)
	properties.Property("API mutations preserve paths and materialized rollups", prop.ForAll(func(ops []uint8) string {
		s, cookie, _ := itemFixture(t)
		keys := []string{"SRX-1"}
		ctx := context.Background()
		for _, op := range ops {
			key := keys[int(op)%len(keys)]
			w := apiCall(s, "GET", "/api/v1/items/"+key, "", cookie)
			var doc map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &doc)
			version := int(doc["version"].(float64))
			switch op % 5 {
			case 0, 1:
				parent := "null"
				if op%5 == 1 && doc["deleted_at"] == nil {
					encoded, _ := json.Marshal(key)
					parent = string(encoded)
				}
				w = apiCall(s, "POST", "/api/v1/items", fmt.Sprintf(`{"project":"SRX","type":"story","title":"Property","points":3,"parent":%s}`, parent), cookie)
				if w.Code == 201 {
					var created map[string]any
					_ = json.Unmarshal(w.Body.Bytes(), &created)
					keys = append(keys, created["key"].(string))
				} else if w.Code != 422 {
					return w.Body.String()
				}
			case 2:
				if doc["deleted_at"] != nil {
					continue
				}
				parent := "null"
				if len(keys) > 1 {
					encoded, _ := json.Marshal(keys[(int(op)+1)%len(keys)])
					parent = string(encoded)
				}
				w = versionCall(s, "POST", "/api/v1/items/"+key+"/move", fmt.Sprintf(`{"parent":%s}`, parent), cookie, version)
				if w.Code != 200 && w.Code != 422 && w.Code != 404 {
					return w.Body.String()
				}
			case 3:
				if doc["deleted_at"] != nil {
					continue
				}
				w = versionCall(s, "POST", "/api/v1/items/"+key+"/transition", `{"to_status":"dropped"}`, cookie, version)
				if w.Code != 200 && w.Code != 422 {
					return w.Body.String()
				}
			case 4:
				if doc["deleted_at"] != nil {
					continue
				}
				w = versionCall(s, "DELETE", "/api/v1/items/"+key, "", cookie, version)
				if w.Code != 200 {
					return w.Body.String()
				}
			}
			var projectID string
			if err := s.Pool.QueryRow(ctx, `SELECT id::text FROM project WHERE key_prefix='SRX'`).Scan(&projectID); err != nil {
				return err.Error()
			}
			pid, _ := uuid.Parse(projectID)
			bad, err := store.New(s.Pool).VerifyRollupsForProject(ctx, pid)
			if err != nil {
				return err.Error()
			}
			if len(bad) > 0 {
				return fmt.Sprintf("rollup mismatches: %v", bad)
			}
			var invalid int
			if err = s.Pool.QueryRow(ctx, `SELECT count(*) FROM item i LEFT JOIN item p ON p.id=i.parent_id WHERE nlevel(i.path)>8 OR subpath(i.path,-1)::text<>i.id::text OR (p.id IS NOT NULL AND i.path<>p.path||i.id::text::ltree)`).Scan(&invalid); err != nil {
				return err.Error()
			}
			if invalid != 0 {
				return "invalid path"
			}
		}
		return ""
	}, gen.SliceOf(gen.UInt8())))
	properties.TestingRun(t)
}
