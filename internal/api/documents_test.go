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
	themes := append(append([]string{}, appearanceThemes...), legacyThemes...)
	for _, theme := range themes {
		w := httptest.NewRecorder()
		state := map[string]any{"body": "</script><script>alert(1)</script>&\u2028", "nested": json.RawMessage(`{"text":"</script>"}`)}
		s.renderDocument(w, httptest.NewRequest("GET", "/", nil), state, auth.Identity{Theme: theme})
		body := w.Body.String()
		if w.Code != 200 || !strings.Contains(body, `data-theme="`+canonicalTheme(theme)+`"`) || strings.Contains(body, "</script><script>alert") || !strings.Contains(body, `\u003c/script\u003e`) {
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

func TestDocumentPurposeTitlesAreEscaped(t *testing.T) {
	s := New(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	for _, tc := range []struct {
		route string
		state map[string]any
		want  string
	}{
		{route: "login", want: "Sign in · Sierx"},
		{route: "list", want: "Workspace · Sierx"},
		{route: "item", want: "Work item · Sierx"},
		{route: "privacy", want: "Privacy · Sierx"},
		{route: "copyright", want: "Copyright · Sierx"},
		{route: "third-party", want: "Third-party notices · Sierx"},
		{route: "item", state: map[string]any{"document_title": `<svg onload=alert(1)>`}, want: `&lt;svg onload=alert(1)&gt;`},
	} {
		t.Run(tc.route+tc.want, func(t *testing.T) {
			state := map[string]any{"route": tc.route}
			for key, value := range tc.state {
				state[key] = value
			}
			w := httptest.NewRecorder()
			s.renderDocument(w, httptest.NewRequest("GET", "/", nil), state, auth.Identity{Theme: "system"})
			if !strings.Contains(w.Body.String(), "<title>"+tc.want+"</title>") {
				t.Fatalf("document title did not match safely escaped purpose title %q", tc.want)
			}
		})
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

func TestPublicNoticePagesAreAccessibleAndOperatorConfigured(t *testing.T) {
	s := New(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	s.ConfigureAuth(config.Env{AuthMode: "local", SessionKey: strings.Repeat("x", 32)})
	s.ConfigureDocuments()

	for _, tc := range []struct {
		path string
		want string
	}{
		{path: "/privacy", want: `"configured":false`},
		{path: "/copyright", want: `"configured":false`},
		{path: "/third-party", want: `"runtime":[`},
	} {
		t.Run(tc.path, func(t *testing.T) {
			w := httptest.NewRecorder()
			s.Router.ServeHTTP(w, httptest.NewRequest("GET", tc.path, nil))
			body := w.Body.String()
			if w.Code != 200 || !strings.Contains(body, tc.want) {
				t.Fatalf("public page %s: %d %s", tc.path, w.Code, body)
			}
			if !strings.Contains(body, `id="sierx-state"`) || w.Header().Get("Cache-Control") != "private, no-store" {
				t.Fatalf("public page %s lost its bootstrap or no-store headers", tc.path)
			}
			if w.Header().Get("Content-Security-Policy") == "" {
				t.Fatalf("public page %s did not receive the local-resource policy", tc.path)
			}
		})
	}
}

func TestPrivacyNoticeConfigurationIsEscapedAndDoesNotInventFacts(t *testing.T) {
	s := New(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	s.ConfigureAuth(config.Env{
		AuthMode: "local", SessionKey: strings.Repeat("x", 32),
		OperatorName: `<img src=x onerror=alert(1)>`, PrivacyContact: `operator@example.test`,
	})
	s.ConfigureDocuments()
	w := httptest.NewRecorder()
	s.Router.ServeHTTP(w, httptest.NewRequest("GET", "/privacy", nil))
	body := w.Body.String()
	if w.Code != 200 || strings.Contains(body, `<img src=x onerror=alert(1)>`) || !strings.Contains(body, `\u003cimg`) {
		t.Fatal("operator-configured notice content was not safely serialized")
	}
	for _, claim := range []string{"No retention data", "30 days", "never shared"} {
		if strings.Contains(strings.ToLower(body), strings.ToLower(claim)) {
			t.Fatalf("page invented an operator fact: %q", claim)
		}
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
