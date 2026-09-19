package api

import (
	"encoding/json"
	"github.com/siercks/sierx/internal/api/auth"
	"github.com/siercks/sierx/internal/config"
	"io"
	"log/slog"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDocumentEscapingAndTheme(t *testing.T) {
	s := New(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	for _, theme := range []string{"system", "light", "dark", "light-hc", "dark-hc"} {
		w := httptest.NewRecorder()
		state := map[string]any{"body": "</script><script>alert(1)</script>&\u2028", "nested": json.RawMessage(`{"text":"</script>"}`)}
		s.renderDocument(w, httptest.NewRequest("GET", "/", nil), state, auth.Identity{Theme: theme})
		body := w.Body.String()
		if w.Code != 200 || !strings.Contains(body, `data-theme="`+theme+`"`) || strings.Contains(body, "</script><script>alert") || !strings.Contains(body, `\u003c/script\u003e`) {
			t.Fatal("unsafe or missing initial state/theme")
		}
		if w.Header().Get("Cache-Control") != "private, no-store" {
			t.Fatal("authenticated document can be cached")
		}
		for _, secret := range []string{"session_key", "password_hash", "totp_secret"} {
			if strings.Contains(body, secret) {
				t.Fatal("security state in bootstrap")
			}
		}
	}
}
func TestDocumentCanonicalPaths(t *testing.T) {
	s := New(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	s.ConfigureAuth(config.Env{AuthMode: "local", SessionKey: strings.Repeat("x", 32)})
	s.ConfigureDocuments()
	for _, path := range []string{"/srx-42", "/SRX-42/", "/srx-42/"} {
		w := httptest.NewRecorder()
		s.Router.ServeHTTP(w, httptest.NewRequest("GET", path+"?q=title", nil))
		if w.Code != 308 || w.Header().Get("Location") != "/SRX-42?q=title" {
			t.Fatalf("canonical %s: %d %s", path, w.Code, w.Header().Get("Location"))
		}
	}
	w := httptest.NewRecorder()
	s.Router.ServeHTTP(w, httptest.NewRequest("GET", "/", nil))
	if w.Code != 303 {
		t.Fatal("anonymous document not redirected")
	}
}
func TestDocumentAuthorizedInitialState(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	s.ConfigureDocuments()
	for _, path := range []string{"/", "/?q=project%20%3D%20SRX", "/SRX-1"} {
		w := apiCall(s, "GET", path, "", cookie)
		if w.Code != 200 || !strings.Contains(w.Body.String(), "Original") || !strings.Contains(w.Body.String(), `id="sierx-state"`) {
			t.Fatalf("bootstrap %s: %d %s", path, w.Code, w.Body)
		}
	}
	w := versionCall(s, "DELETE", "/api/v1/items/SRX-1", "", cookie, 1)
	if w.Code != 200 {
		t.Fatal(w.Body)
	}
	w = apiCall(s, "GET", "/SRX-1", "", cookie)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"deleted_at":"`) {
		t.Fatal("deleted item document lost")
	}
}
