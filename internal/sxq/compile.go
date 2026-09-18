package sxq

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"
	"uuid"
)

type Field struct{ SQL, Kind string }

var Fields = map[string]Field{
	"id": {"i.id", "uuid"}, "key": {"i.key", "text"}, "title": {"i.title", "text"}, "body": {"i.body", "text"}, "rank": {"i.rank", "text"},
	"project": {"p.key_prefix", "text"}, "type": {"t.key", "text"}, "type.level": {"t.level", "number"}, "status": {"s.key", "text"}, "status.category": {"s.category", "text"}, "assignee": {"i.assignee_id", "uuid"}, "parent": {"par.key", "text"},
	"points": {"i.points", "number"}, "version": {"i.version", "number"}, "change_seq": {"i.change_seq", "number"}, "config_version": {"i.config_version", "number"},
	"start_date": {"i.start_date", "date"}, "due_date": {"i.due_date", "date"}, "created_at": {"i.created_at", "timestamp"}, "updated_at": {"i.updated_at", "timestamp"}, "deleted_at": {"i.deleted_at", "timestamp"},
	"rollup.descendant_count": {"r.descendant_count", "number"}, "rollup.done_count": {"r.done_count", "number"}, "rollup.points_total": {"r.points_total", "number"}, "rollup.points_done": {"r.points_done", "number"}, "rollup.earliest_start": {"r.earliest_start", "date"}, "rollup.latest_due": {"r.latest_due", "date"},
	"text": {"i.search_tsv", "search"},
}

type CustomField struct{ ProjectID, Kind string }
type Options struct {
	UserID string
	Now    time.Time
	Start  int
	Custom map[string][]CustomField
}
type Plan struct {
	Where, OrderExpr, OrderKind string
	Desc                        bool
	Args                        []any
}
type compiler struct {
	options Options
	args    []any
}

func Compile(q *Query, options Options) (Plan, error) {
	if options.Start < 1 {
		options.Start = 1
	}
	if options.Now.IsZero() {
		options.Now = time.Now().UTC()
	}
	c := compiler{options: options}
	where, err := c.expr(q.Expr)
	if err != nil {
		return Plan{}, err
	}
	order, err := c.field(q.Order)
	if err != nil {
		return Plan{}, err
	}
	if order.Kind == "search" || order.Kind == "array" {
		return Plan{}, fmt.Errorf("cannot order by %s; try rank or key", q.Order)
	}
	return Plan{Where: where, OrderExpr: order.SQL, OrderKind: order.Kind, Desc: q.Desc, Args: c.args}, nil
}
func (c *compiler) param(value any) string {
	c.args = append(c.args, value)
	return fmt.Sprintf("$%d", c.options.Start+len(c.args)-1)
}
func (c *compiler) field(name string) (Field, error) {
	if f, ok := Fields[name]; ok {
		return f, nil
	}
	if strings.HasPrefix(name, "fields.") {
		key := strings.TrimPrefix(name, "fields.")
		defs := c.options.Custom[key]
		if len(defs) > 0 {
			kind := defs[0].Kind
			var ids []string
			for _, def := range defs {
				if def.Kind != kind {
					return Field{}, fmt.Errorf("custom field %q has different types across projects; constrain project before using it", key)
				}
				ids = append(ids, def.ProjectID)
			}
			sort.Strings(ids)
			var params []string
			for _, id := range ids {
				params = append(params, c.param(id)+"::uuid")
			}
			k := c.param(key)
			cast, typ := map[string]string{"text": "text", "number": "numeric", "bool": "boolean", "date": "date", "url": "text", "user": "uuid", "select": "text", "multiselect": "jsonb"}[kind], map[string]string{"text": "text", "number": "number", "bool": "bool", "date": "date", "url": "text", "user": "uuid", "select": "text", "multiselect": "array"}[kind]
			if cast == "" {
				return Field{}, fmt.Errorf("unsupported configured field type")
			}
			extract := "(i.fields ->> " + k + "::text)::" + cast
			if kind == "multiselect" {
				extract = "(i.fields -> " + k + "::text)"
			}
			return Field{"CASE WHEN i.project_id IN (" + strings.Join(params, ",") + ") THEN " + extract + " ELSE NULL END", typ}, nil
		}
	}
	return Field{}, fmt.Errorf("unknown field %q; try %q", name, nearest(name, c.options.Custom))
}
func (c *compiler) expr(e *Expr) (string, error) {
	if e == nil {
		return "TRUE", nil
	}
	if e.Op == "and" || e.Op == "or" {
		a, err := c.expr(e.Left)
		if err != nil {
			return "", err
		}
		b, err := c.expr(e.Right)
		if err != nil {
			return "", err
		}
		return "(" + a + " " + strings.ToUpper(e.Op) + " " + b + ")", nil
	}
	if e.Op == "not" {
		a, err := c.expr(e.Left)
		return "(NOT " + a + ")", err
	}
	field, err := c.field(e.Field)
	if err != nil {
		return "", err
	}
	if len(e.Values) == 0 {
		return "", fmt.Errorf("comparison requires a value")
	}
	if e.Op == "~" || e.Op == ":" {
		if e.Field != "text" && e.Field != "title" && e.Field != "body" {
			return "", fmt.Errorf("full-text matching requires text, title or body")
		}
		value, ok := e.Values[0].Literal.(string)
		if !ok {
			return "", fmt.Errorf("full-text matching requires a quoted text value")
		}
		sql := field.SQL
		if e.Field != "text" {
			sql = "to_tsvector('english',coalesce(" + sql + ",''))"
		}
		return "(" + sql + " @@ plainto_tsquery('english'," + c.param(value) + "))", nil
	}
	if field.Kind == "search" {
		return "", fmt.Errorf("text requires ~ or : for full-text matching")
	}
	null := e.Values[0].Literal == nil && e.Values[0].Function == ""
	if e.Op == "is" || e.Op == "is not" || ((e.Op == "=" || e.Op == "!=") && null) {
		if !null {
			return "", fmt.Errorf("is and is not require null; use = for a value")
		}
		if e.Op == "is not" || e.Op == "!=" {
			return "(" + field.SQL + " IS NOT NULL)", nil
		}
		return "(" + field.SQL + " IS NULL)", nil
	}
	if null {
		return "", fmt.Errorf("null requires is null or is not null")
	}
	if field.Kind == "array" {
		return "", fmt.Errorf("multiselect comparisons are not supported; use is null or is not null")
	}
	op := map[string]string{"=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<=", "in": "IN", "not in": "NOT IN"}[e.Op]
	if op == "" {
		return "", fmt.Errorf("unsupported comparison operator")
	}
	var params []string
	for _, v := range e.Values {
		value, err := c.value(v, field.Kind)
		if err != nil {
			return "", fmt.Errorf("%s: %w", e.Field, err)
		}
		parameter := c.param(value)
		switch field.Kind {
		case "number":
			parameter += "::text::numeric"
		case "date":
			parameter += "::text::date"
		case "timestamp":
			parameter += "::text::timestamptz"
		case "uuid":
			parameter += "::text::uuid"
		}
		params = append(params, parameter)
	}
	if op == "IN" || op == "NOT IN" {
		return "(" + field.SQL + " " + op + " (" + strings.Join(params, ",") + "))", nil
	}
	return "(" + field.SQL + " " + op + " " + params[0] + ")", nil
}
func (c *compiler) value(v Value, kind string) (any, error) {
	if v.Function == "me" {
		if kind != "uuid" {
			return nil, fmt.Errorf("me() requires a user field")
		}
		if _, err := uuid.Parse(c.options.UserID); err != nil {
			return nil, fmt.Errorf("me() requires an authenticated user")
		}
		return c.options.UserID, nil
	}
	if v.Function == "now" {
		if kind != "date" && kind != "timestamp" {
			return nil, fmt.Errorf("now() requires a date or timestamp field")
		}
		at := c.options.Now.UTC().Add(v.Offset)
		if kind == "date" {
			return at.Format(time.DateOnly), nil
		}
		return at.Format(time.RFC3339Nano), nil
	}
	switch kind {
	case "number":
		if n, ok := v.Literal.(json.Number); ok {
			return n.String(), nil
		}
	case "bool":
		if b, ok := v.Literal.(bool); ok {
			return b, nil
		}
	case "uuid":
		if text, ok := v.Literal.(string); ok {
			if _, err := uuid.Parse(text); err == nil {
				return text, nil
			}
		}
	case "text":
		if text, ok := v.Literal.(string); ok {
			return text, nil
		}
	case "date":
		if text, ok := v.Literal.(string); ok {
			if _, err := time.Parse(time.DateOnly, text); err == nil {
				return text, nil
			}
		}
	case "timestamp":
		if text, ok := v.Literal.(string); ok {
			if _, err := time.Parse(time.RFC3339Nano, text); err == nil {
				return text, nil
			}
		}
	}
	return nil, fmt.Errorf("expected a %s value; quote text and dates", kind)
}
func nearest(input string, custom map[string][]CustomField) string {
	names := FieldNames(custom)
	best := "key"
	score := 10000
	for _, name := range names {
		d := distance(input, name)
		if d < score {
			score = d
			best = name
		}
	}
	return best
}
func distance(a, b string) int {
	prev := make([]int, len(b)+1)
	for i := range prev {
		prev[i] = i
	}
	for i := 1; i <= len(a); i++ {
		next := make([]int, len(b)+1)
		next[0] = i
		for j := 1; j <= len(b); j++ {
			cost := 0
			if a[i-1] != b[j-1] {
				cost = 1
			}
			next[j] = min(next[j-1]+1, prev[j]+1, prev[j-1]+cost)
		}
		prev = next
	}
	return prev[len(b)]
}
func FieldNames(custom map[string][]CustomField) []string {
	names := make([]string, 0, len(Fields)+len(custom))
	for k := range Fields {
		names = append(names, k)
	}
	for k := range custom {
		names = append(names, "fields."+k)
	}
	sort.Strings(names)
	return names
}

// Complete shares the lexer, fields and keywords with parsing. It returns
// replacements for the final incomplete token, never SQL or database details.
func Complete(partial string, custom map[string][]CustomField) ([]string, error) {
	if len(partial) > 4096 {
		return nil, fmt.Errorf("partial query is too long")
	}
	prefix := ""
	tokens, err := lex(partial)
	if err != nil {
		return nil, err
	}
	if len(tokens) > 1 && !strings.HasSuffix(partial, " ") {
		prefix = canonical(tokens[len(tokens)-2].text)
	}
	candidates := append(FieldNames(custom), "and", "or", "not", "in", "is null", "is not null", "order by", "asc", "desc", "me()", "now()")
	var out []string
	for _, candidate := range candidates {
		if strings.HasPrefix(candidate, prefix) {
			out = append(out, candidate)
		}
	}
	sort.Strings(out)
	return out, nil
}
