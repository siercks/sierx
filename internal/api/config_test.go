package api

import (
	"net/http/httptest"
	"testing"
)

func TestResolvedConfig(t *testing.T) {
	s, email, _, _ := authFixture(t)
	cookie := fixtureSession(t, s, email)
	if w := apiCall(s, "POST", "/api/v1/projects", `{"key_prefix":"SRX","name":"Backlog","kind":"delivery"}`, cookie); w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	w := apiCall(s, "GET", "/api/v1/projects/SRX/config", "", cookie)
	if w.Code != 200 {
		t.Fatalf("config %d %s", w.Code, w.Body)
	}
	assertGolden(t, "project-config", w.Body.Bytes(), nil)
	etag := w.Header().Get("ETag")
	if etag == "" {
		t.Fatal("missing ETag")
	}
	r := httptest.NewRequest("GET", "/api/v1/projects/SRX/config", nil)
	r.AddCookie(cookie)
	r.Header.Set("If-None-Match", "W/"+etag)
	w = httptest.NewRecorder()
	s.Router.ServeHTTP(w, r)
	if w.Code != 304 || w.Body.Len() != 0 || w.Header().Get("ETag") != etag {
		t.Fatal("conditional config request failed")
	}
	if w := apiCall(s, "GET", "/api/v1/projects/SRX/config?fields=status", "", cookie); w.Code != 400 {
		t.Fatal("fields accepted on config")
	}
}
