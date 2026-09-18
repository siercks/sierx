package sxq

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func testOptions() Options {
	return Options{UserID: "01994ed4-0000-7000-8000-000000000001", Now: time.Date(2026, 9, 18, 12, 0, 0, 0, time.UTC), Custom: map[string][]CustomField{"impact": {{ProjectID: "01994ed4-0000-7000-8000-000000000002", Kind: "number"}}}}
}

type goldenCase struct {
	Query  string `json:"query"`
	Where  string `json:"where,omitempty"`
	Order  string `json:"order,omitempty"`
	Desc   bool   `json:"desc,omitempty"`
	Params []any  `json:"params,omitempty"`
	Error  string `json:"error,omitempty"`
}

func TestGolden(t *testing.T) {
	paths, err := filepath.Glob("../../test/golden/sxq/*.json")
	if err != nil || len(paths) == 0 {
		t.Fatal("missing query corpus")
	}
	for _, path := range paths {
		t.Run(filepath.Base(path), func(t *testing.T) {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var expected goldenCase
			if err = json.Unmarshal(raw, &expected); err != nil {
				t.Fatal(err)
			}
			got := goldenCase{Query: expected.Query}
			q, err := Parse(expected.Query)
			if err == nil {
				var plan Plan
				plan, err = Compile(q, testOptions())
				got.Where = plan.Where
				got.Order = plan.OrderExpr
				got.Desc = plan.Desc
				got.Params = plan.Args
			}
			if err != nil {
				got.Error = err.Error()
			}
			if os.Getenv("SIERX_GOLDEN_UPDATE") == "1" {
				raw, _ := json.MarshalIndent(got, "", "  ")
				if err := os.WriteFile(path, append(raw, '\n'), 0644); err != nil {
					t.Fatal(err)
				}
				return
			}
			if !reflect.DeepEqual(got, expected) {
				t.Fatalf("got %#v\nwant %#v", got, expected)
			}
		})
	}
}
func TestInvalidQueries(t *testing.T) {
	for _, input := range []string{"status", "now() +", "due_date < now() +", "status =", "status in ()", "status = 'unterminated", "status == doing", "status = doing; DROP TABLE item", strings.Repeat("not ", 65) + "status=todo"} {
		q, err := Parse(input)
		if err == nil {
			_, err = Compile(q, testOptions())
		}
		if err == nil {
			t.Errorf("accepted %q", input)
		}
	}
}
func TestPrecedence(t *testing.T) {
	q, err := Parse("status=todo OR status=doing AND NOT points=0")
	if err != nil {
		t.Fatal(err)
	}
	if q.Expr.Op != "or" || q.Expr.Right.Op != "and" || q.Expr.Right.Right.Op != "not" {
		t.Fatal("wrong precedence")
	}
}
func TestCompletion(t *testing.T) {
	got, err := Complete("project = SRX and sta", testOptions().Custom)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, []string{"start_date", "status", "status.category"}) {
		t.Fatal(got)
	}
}
func FuzzCompile(f *testing.F) {
	for _, seed := range []string{"status=todo", `title = "x' OR 1=1 --"`, "due_date < now() +", "not (points >= 2)", "fields.impact > 0", "status in (todo,doing)"} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, input string) {
		q, err := Parse(input)
		if err == nil {
			_, _ = Compile(q, testOptions())
		}
		// Every arbitrary string used as a literal produces exactly the same SQL.
		// Only the parameter changes, including quotes, comments and SQL keywords.
		if len(input) > 2000 {
			return
		}
		quoted := strings.ReplaceAll(strings.ReplaceAll(input, "\\", "\\\\"), "\"", "\\\"")
		literal, err := Parse(`title = "` + quoted + `"`)
		if err != nil {
			return
		}
		plan, err := Compile(literal, testOptions())
		if err != nil {
			t.Fatal(err)
		}
		if plan.Where != "(i.title = $1)" || plan.OrderExpr != "i.id" || len(plan.Args) != 1 || plan.Args[0] != input {
			t.Fatalf("literal escaped binding: %#v", plan)
		}
	})
}
