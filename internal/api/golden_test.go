package api

import (
	"encoding/json"
	"github.com/go-chi/chi/v5"
	"github.com/siercks/sierx/internal/config"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestGoldenRouteCoverage(t *testing.T) {
	raw, err := os.ReadFile("../../test/golden/routes.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures map[string]string
	if err = json.Unmarshal(raw, &fixtures); err != nil {
		t.Fatal(err)
	}
	s := New(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	s.ConfigureAuth(config.Env{AuthMode: "local", BaseURL: "https://example.test", SessionKey: strings.Repeat("x", 32)})
	seen := map[string]bool{}
	err = chi.Walk(s.Router, func(method, route string, handler http.Handler, middlewares ...func(http.Handler) http.Handler) error {
		key := method + " " + route
		seen[key] = true
		fixture, ok := fixtures[key]
		if !ok {
			t.Errorf("route has no golden: %s", key)
			return nil
		}
		if _, err := os.Stat(filepath.Join("../../test/golden", fixture)); err != nil {
			t.Errorf("missing fixture for %s: %v", key, err)
		}
		if route != "/api/v1/healthz" && route != "/api/v1/auth/login" {
			path := strings.NewReplacer("{key}", "SRX-1", "{id}", zeroID).Replace(route)
			w := httptest.NewRecorder()
			s.Router.ServeHTTP(w, httptest.NewRequest(method, path, nil))
			if w.Code != 401 {
				t.Errorf("route allows unauthenticated access: %s returned %d", key, w.Code)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	for route := range fixtures {
		if !seen[route] {
			t.Errorf("fixture names unregistered route: %s", route)
		}
	}
}
