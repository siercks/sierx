package projection

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestProjectionGolden(t *testing.T) {
	raw, err := os.ReadFile("../../../test/golden/projection/item.json")
	if err != nil {
		t.Fatal(err)
	}
	var source map[string]any
	if err = json.Unmarshal(raw, &source); err != nil {
		t.Fatal(err)
	}
	if len(source) != len(Registry) {
		t.Fatal("golden must cover every registry entry")
	}
	for _, f := range Registry {
		if _, ok := source[f.Name]; !ok {
			t.Fatalf("missing golden %s", f.Name)
		}
		fields, err := Parse(f.Name, true, Required, nil)
		if err != nil {
			t.Fatal(err)
		}
		got := Apply(source, fields)
		if len(got) != 1 {
			t.Fatal("unrequested fields leaked")
		}
		expected, _ := json.Marshal(source[f.Name])
		actual, _ := json.Marshal(got[f.Name])
		if string(expected) != string(actual) {
			t.Fatal("shape mismatch")
		}
		sql, _ := SQL(fields, 1)
		if !strings.Contains(sql, f.SQL) {
			t.Fatalf("SQL registry ignored for %s", f.Name)
		}
	}
	fields, err := Parse("status.category,assignee.id,fields.component,fields.impact", true, Required, map[string]string{"component": "select", "impact": "number"})
	if err != nil {
		t.Fatal(err)
	}
	got, _ := json.Marshal(Apply(source, fields))
	if string(got) != `{"assignee":{"id":"user-1"},"fields":{"component":"api","impact":3},"status":{"category":"open"}}` {
		t.Fatalf("dotted fields: %s", got)
	}
	sql, args := SQL(fields, 4)
	if len(args) != 2 || args[0] != "component" || args[1] != "impact" || !strings.Contains(sql, "$4") || !strings.Contains(sql, "$5") {
		t.Fatalf("custom field parameters: %s %v", sql, args)
	}
	fields, err = Parse("status.category,status", true, Required, nil)
	if err != nil || len(fields) != 1 || fields[0] != "status" {
		t.Fatal("redundant leaf was not removed")
	}
}

func TestProjectionPolicies(t *testing.T) {
	for _, name := range []string{"items", "children", "descendants"} {
		t.Run(name, func(t *testing.T) {
			if _, err := Parse("", false, Required, nil); err == nil {
				t.Fatal("missing fields accepted")
			}
		})
	}
	for _, name := range []string{"changes", "comments", "views", "history", "rollup", "projects", "links"} {
		t.Run(name, func(t *testing.T) {
			if _, err := Parse("key", true, Rejected, nil); err == nil {
				t.Fatal("fields silently ignored")
			}
			if _, err := Parse("", false, Rejected, nil); err != nil {
				t.Fatal(err)
			}
		})
	}
	if fields, err := Parse("", false, Optional, nil); err != nil || len(fields) != len(Registry) {
		t.Fatal("detail default incomplete")
	}
	if _, err := Parse("titel", true, Required, nil); err == nil || !strings.Contains(err.Error(), `"title"`) {
		t.Fatalf("missing nearest field suggestion: %v", err)
	}
	if _, err := Parse("fields.unconfigured", true, Required, nil); err == nil {
		t.Fatal("unconfigured custom field accepted")
	}
}
