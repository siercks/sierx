// Package projection is the API field authority (ADR-007).
package projection

import (
	"fmt"
	"sort"
	"strings"
)

type Field struct{ Name, SQL, Type string }

var Registry = []Field{
	{"id", "i.id::text", "string"}, {"key", "i.key", "string"}, {"title", "i.title", "string"}, {"body", "i.body", "string | null"},
	{"version", "i.version", "number"}, {"change_seq", "i.change_seq", "number"}, {"config_version", "i.config_version", "number"},
	{"rank", "i.rank", "string"}, {"points", "i.points", "number | null"}, {"start_date", "i.start_date", "string | null"}, {"due_date", "i.due_date", "string | null"},
	{"created_at", "i.created_at", "string"}, {"updated_at", "i.updated_at", "string"}, {"deleted_at", "i.deleted_at", "string | null"},
	{"status", "jsonb_build_object('key',s.key,'name',s.name,'category',s.category)", "{ key: string; name: string; category: string }"},
	{"assignee", "CASE WHEN u.id IS NULL THEN NULL ELSE jsonb_build_object('id',u.id,'display_name',u.display_name) END", "{ id: string; display_name: string } | null"},
	{"type", "jsonb_build_object('key',t.key,'name',t.name,'level',t.level)", "{ key: string; name: string; level: number }"},
	{"parent", "CASE WHEN par.id IS NULL THEN NULL ELSE jsonb_build_object('key',par.key) END", "{ key: string } | null"},
	{"project", "jsonb_build_object('key_prefix',p.key_prefix,'name',p.name)", "{ key_prefix: string; name: string }"},
	{"fields", "i.fields", "Record<string, unknown>"},
	{"rollup", "jsonb_build_object('descendant_count',r.descendant_count,'done_count',r.done_count,'points_total',r.points_total,'points_done',r.points_done,'earliest_start',r.earliest_start,'latest_due',r.latest_due)", "{ descendant_count: number; done_count: number; points_total: number | null; points_done: number | null; earliest_start: string | null; latest_due: string | null }"},
}

var leaves = map[string][]string{"status": {"key", "name", "category"}, "assignee": {"id", "display_name"}, "type": {"key", "name", "level"}, "parent": {"key"}, "project": {"key_prefix", "name"}, "rollup": {"descendant_count", "done_count", "points_total", "points_done", "earliest_start", "latest_due"}}

type Policy int

const (
	Required Policy = iota
	Optional
	Rejected
)

func Parse(raw string, present bool, policy Policy, custom map[string]string) ([]string, error) {
	if policy == Rejected {
		if present {
			return nil, fmt.Errorf("fields is not supported for this endpoint; remove it")
		}
		return nil, nil
	}
	if !present || strings.TrimSpace(raw) == "" {
		if policy == Required {
			return nil, fmt.Errorf("fields is required; choose fields such as key,title,status")
		}
		if present {
			return nil, fmt.Errorf("fields must not be empty")
		}
		out := make([]string, len(Registry))
		for i, f := range Registry {
			out[i] = f.Name
		}
		return out, nil
	}
	valid := map[string]bool{}
	for _, f := range Registry {
		valid[f.Name] = true
	}
	for parent, names := range leaves {
		for _, name := range names {
			valid[parent+"."+name] = true
		}
	}
	for key := range custom {
		valid["fields."+key] = true
	}
	seen := map[string]bool{}
	var out []string
	for _, name := range strings.Split(raw, ",") {
		name = strings.TrimSpace(name)
		if !valid[name] {
			return nil, fmt.Errorf("unknown field %q; try %q", name, nearest(name, valid))
		}
		if !seen[name] {
			seen[name] = true
			out = append(out, name)
		}
	}
	var compact []string
	for _, name := range out {
		root, _, dotted := strings.Cut(name, ".")
		if dotted && seen[root] {
			continue
		}
		compact = append(compact, name)
	}
	return compact, nil
}

// SQL projects only requested top-level values. Dotted leaves are trimmed by
// Apply; body and other potentially large fields are never selected implicitly.
// Custom field names are bound as parameters, never interpolated into SQL.
func SQL(fields []string, start int) (string, []any) {
	registry := map[string]Field{}
	for _, f := range Registry {
		registry[f.Name] = f
	}
	var parts []string
	var args []any
	seen := map[string]bool{}
	for _, name := range fields {
		root, leaf, dotted := strings.Cut(name, ".")
		if root == "fields" && dotted {
			args = append(args, leaf)
			parameter := fmt.Sprintf("$%d", start+len(args)-1)
			parts = append(parts, "jsonb_build_object('fields',jsonb_build_object("+parameter+"::text,i.fields -> "+parameter+"::text))")
			continue
		}
		if seen[root] {
			continue
		}
		seen[root] = true
		f, ok := registry[root]
		if !ok {
			panic("unvalidated projection")
		}
		parts = append(parts, "jsonb_build_object('"+root+"',"+f.SQL+")")
	}
	// Custom fields must merge within their object, rather than replace siblings.
	var customParts, normal []string
	for _, part := range parts {
		if strings.HasPrefix(part, "jsonb_build_object('fields',jsonb_build_object(") {
			customParts = append(customParts, strings.TrimSuffix(strings.TrimPrefix(part, "jsonb_build_object('fields',"), ")"))
		} else {
			normal = append(normal, part)
		}
	}
	if len(customParts) > 0 {
		normal = append(normal, "jsonb_build_object('fields',"+strings.Join(customParts, " || ")+")")
	}
	if len(normal) == 0 {
		return "'{}'::jsonb", args
	}
	return strings.Join(normal, " || "), args
}

func Apply(source map[string]any, fields []string) map[string]any {
	out := map[string]any{}
	for _, name := range fields {
		root, leaf, dotted := strings.Cut(name, ".")
		value := source[root]
		if !dotted {
			out[root] = value
			continue
		}
		if value == nil {
			out[root] = nil
			continue
		}
		obj, ok := value.(map[string]any)
		if !ok {
			continue
		}
		target, ok := out[root].(map[string]any)
		if !ok {
			target = map[string]any{}
			out[root] = target
		}
		target[leaf] = obj[leaf]
	}
	return out
}

func TypeScript() string {
	var b strings.Builder
	b.WriteString("// Generated by make gen-fields. Do not edit.\nexport interface ItemFields {\n")
	for _, f := range Registry {
		fmt.Fprintf(&b, "  %s: %s;\n", f.Name, f.Type)
	}
	b.WriteString("}\nexport type FieldName =\n")
	var names []string
	for _, f := range Registry {
		names = append(names, f.Name)
	}
	for root, list := range leaves {
		for _, leaf := range list {
			names = append(names, root+"."+leaf)
		}
	}
	sort.Strings(names)
	for _, name := range names {
		fmt.Fprintf(&b, "  | %q\n", name)
	}
	b.WriteString("  | `fields.${string}`;\n")
	return b.String()
}

func nearest(value string, valid map[string]bool) string {
	names := make([]string, 0, len(valid))
	for name := range valid {
		names = append(names, name)
	}
	sort.Strings(names)
	best, score := "", int(^uint(0)>>1)
	for _, name := range names {
		d := distance(value, name)
		if d < score {
			best, score = name, d
		}
	}
	return best
}
func distance(a, b string) int {
	x, y := []rune(a), []rune(b)
	row := make([]int, len(y)+1)
	for j := range row {
		row[j] = j
	}
	for i, r := range x {
		prev := row[0]
		row[0] = i + 1
		for j, s := range y {
			old := row[j+1]
			cost := 0
			if r != s {
				cost = 1
			}
			row[j+1] = min(row[j+1]+1, row[j]+1, prev+cost)
			prev = old
		}
	}
	return row[len(y)]
}
