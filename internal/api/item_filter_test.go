package api

import (
	"strings"
	"testing"
)

func TestItemFiltersBoundThePageBeforeHydration(t *testing.T) {
	for _, c := range []struct {
		sql     string
		aliases []string
	}{
		{"i.rank i.search_tsv", nil},
		{"s.key = $6 AND t.level = $7", []string{"status s", "item_type t"}},
		{"par.key", []string{"item par"}},
		{"u.display_name par.key r.points_total", []string{"user_account u", "item par", "item_rollup r"}},
	} {
		joins := itemFilterJoins(c.sql)
		if !strings.Contains(joins, "project p") {
			t.Fatal("project scope is required")
		}
		for _, alias := range []string{"status s", "item_type t", "user_account u", "item par", "item_rollup r"} {
			want := false
			for _, selected := range c.aliases {
				if selected == alias {
					want = true
				}
			}
			if strings.Contains(joins, alias) != want {
				t.Fatalf("unexpected filter join %s in %s", alias, joins)
			}
		}
	}
}
