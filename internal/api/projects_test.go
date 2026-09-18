package api

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func fixtureSession(t *testing.T, s *Server, email string) *http.Cookie {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"email": email, "password": "test-password-12345"})
	w := apiCall(s, "POST", "/api/v1/auth/login", string(body), nil)
	if w.Code != 200 {
		t.Fatalf("login %d %s", w.Code, w.Body)
	}
	return w.Result().Cookies()[0]
}

func assertGolden(t *testing.T, name string, got []byte, replacements map[string]string) {
	t.Helper()
	text := string(got)
	want, err := os.ReadFile(filepath.Join("..", "..", "test", "golden", "api", name+".json"))
	if err != nil {
		t.Fatal(err)
	}
	var a, b any
	if err = json.Unmarshal([]byte(text), &a); err != nil {
		t.Fatal(err)
	}
	a = normalizeGolden(a, replacements)
	if err = json.Unmarshal(want, &b); err != nil {
		t.Fatal(err)
	}
	aa, _ := json.Marshal(a)
	bb, _ := json.Marshal(b)
	if string(aa) != string(bb) {
		t.Fatalf("golden %s\nwant %s\ngot %s", name, bb, aa)
	}
}

func normalizeGolden(value any, replacements map[string]string) any {
	switch v := value.(type) {
	case string:
		if replacement, ok := replacements[v]; ok {
			return replacement
		}
	case map[string]any:
		for k, child := range v {
			v[k] = normalizeGolden(child, replacements)
		}
	case []any:
		for i, child := range v {
			v[i] = normalizeGolden(child, replacements)
		}
	}
	return value
}

func TestProjects(t *testing.T) {
	s, email, uid, wid := authFixture(t)
	cookie := fixtureSession(t, s, email)
	w := apiCall(s, "POST", "/api/v1/projects", `{"key_prefix":"SRX","name":"Backlog","kind":"delivery"}`, cookie)
	if w.Code != 201 {
		t.Fatalf("create %d %s", w.Code, w.Body)
	}
	var project Project
	if err := json.Unmarshal(w.Body.Bytes(), &project); err != nil {
		t.Fatal(err)
	}
	replace := map[string]string{project.ID: "project-1"}
	assertGolden(t, "projects-create", w.Body.Bytes(), replace)
	w = apiCall(s, "GET", "/api/v1/projects/SRX", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	assertGolden(t, "projects-detail", w.Body.Bytes(), replace)
	w = apiCall(s, "GET", "/api/v1/projects", "", cookie)
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	assertGolden(t, "projects-list", w.Body.Bytes(), replace)
	var versions, statuses, next int
	if err := s.Pool.QueryRow(context.Background(), `SELECT (SELECT count(*) FROM project_config WHERE project_id=$1),(SELECT count(*) FROM config_status WHERE project_id=$1),next_key_num FROM project WHERE id=$1`, project.ID).Scan(&versions, &statuses, &next); err != nil {
		t.Fatal(err)
	}
	if versions != 1 || statuses != 5 || next != 1 {
		t.Fatal("incomplete project config")
	}
	for _, prefix := range append(append([]string{}, ReservedPrefixes...), "bad", "A", "TOO_LONG_PREFIX") {
		body, _ := json.Marshal(map[string]string{"key_prefix": prefix, "name": "Rejected", "kind": "delivery"})
		w := apiCall(s, "POST", "/api/v1/projects", string(body), cookie)
		if w.Code != 400 {
			t.Fatalf("prefix %s: %d", prefix, w.Code)
		}
	}
	if _, err := s.Pool.Exec(context.Background(), `UPDATE membership SET role='member' WHERE workspace_id=$1 AND user_id=$2`, wid, uid); err != nil {
		t.Fatal(err)
	}
	if w := apiCall(s, "POST", "/api/v1/projects", `{"key_prefix":"NEW","name":"New","kind":"delivery"}`, cookie); w.Code != 403 {
		t.Fatal("member created project")
	}
	if _, err := s.Pool.Exec(context.Background(), `UPDATE project SET archived_at=now() WHERE id=$1`, project.ID); err != nil {
		t.Fatal(err)
	}
	w = apiCall(s, "GET", "/api/v1/projects", "", cookie)
	assertGolden(t, "empty-page", w.Body.Bytes(), nil)
	w = apiCall(s, "GET", "/api/v1/projects?archived=true", "", cookie)
	if !strings.Contains(w.Body.String(), "SRX") {
		t.Fatal("archived project missing")
	}
	if w := apiCall(s, "GET", "/api/v1/projects?fields=name", "", cookie); w.Code != 400 {
		t.Fatal("fields silently ignored")
	}
}
