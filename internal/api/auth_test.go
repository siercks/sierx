package api

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"uuid"

	"github.com/siercks/sierx/internal/api/auth"
	"github.com/siercks/sierx/internal/config"
)

func authFixture(t *testing.T) (*Server, string, string, string) {
	t.Helper()
	p := isolatedPool(t)
	wid, uid := uuid.NewV7().String(), uuid.NewV7().String()
	email := uid + "@example.test"
	hash, err := auth.HashPassword("test-password-12345")
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if _, err = p.Exec(ctx, `INSERT INTO workspace(id,slug,name,origin_id) VALUES($1::uuid,$2,'Test workspace',$1::uuid)`, wid, wid); err != nil {
		t.Fatal(err)
	}
	if _, err = p.Exec(ctx, `INSERT INTO user_account(id,email,display_name,password_hash) VALUES($1,$2,'Test user',$3)`, uid, email, hash); err != nil {
		t.Fatal(err)
	}
	if _, err = p.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$2,'admin')`, wid, uid); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = p.Exec(ctx, `DELETE FROM membership WHERE workspace_id=$1`, wid)
		_, _ = p.Exec(ctx, `DELETE FROM user_account WHERE id=$1`, uid)
		_, _ = p.Exec(ctx, `DELETE FROM seq_counter WHERE workspace_id=$1`, wid)
		_, _ = p.Exec(ctx, `DELETE FROM workspace WHERE id=$1`, wid)
		p.Close()
	})
	s := New(p, slog.New(slog.NewTextHandler(io.Discard, nil)))
	s.ConfigureAuth(config.Env{AuthMode: "local", BaseURL: "https://example.test", SessionKey: strings.Repeat("x", 32)})
	return s, email, uid, wid
}

func apiCall(s *Server, method, path, body string, cookie *http.Cookie) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	if cookie != nil {
		r.AddCookie(cookie)
	}
	w := httptest.NewRecorder()
	s.Router.ServeHTTP(w, r)
	return w
}

func TestAuthLocal(t *testing.T) {
	s, email, uid, _ := authFixture(t)
	login := func() *http.Cookie {
		t.Helper()
		body, _ := json.Marshal(map[string]string{"email": email, "password": "test-password-12345"})
		w := apiCall(s, "POST", "/api/v1/auth/login", string(body), nil)
		if w.Code != 200 {
			t.Fatalf("login %d %s", w.Code, w.Body)
		}
		assertGolden(t, "auth-login", w.Body.Bytes(), nil)
		cookies := w.Result().Cookies()
		if len(cookies) != 1 {
			t.Fatal("missing cookie")
		}
		c := cookies[0]
		if !c.Secure || !c.HttpOnly || c.SameSite != http.SameSiteLaxMode || c.Path != "/" || c.Domain != "" {
			t.Fatal("unsafe cookie")
		}
		return c
	}
	c := login()
	sum := sha256.Sum256([]byte(c.Value))
	var stored []byte
	if err := s.Pool.QueryRow(context.Background(), `SELECT id_hash FROM session WHERE user_id=$1`, uid).Scan(&stored); err != nil {
		t.Fatal(err)
	}
	if string(stored) == c.Value || string(stored) != string(sum[:]) {
		t.Fatal("token was not hashed")
	}
	for range 2 {
		w := apiCall(s, "GET", "/api/v1/me", "", c)
		if w.Code != 200 || !strings.Contains(w.Body.String(), email) {
			t.Fatalf("session %d %s", w.Code, w.Body)
		}
	}
	if w := apiCall(s, "POST", "/api/v1/auth/logout", "", c); w.Code != 204 {
		t.Fatalf("logout %d", w.Code)
	} else {
		body, _ := json.Marshal(map[string]any{"status": w.Code, "body": w.Body.String()})
		assertGolden(t, "auth-logout", body, nil)
	}
	if w := apiCall(s, "GET", "/api/v1/me", "", c); w.Code != 401 {
		t.Fatal("revoked session accepted")
	}
	c = login()
	_, err := s.Pool.Exec(context.Background(), `UPDATE session SET expires_at=now()-interval '1 second' WHERE user_id=$1`, uid)
	if err != nil {
		t.Fatal(err)
	}
	if w := apiCall(s, "GET", "/api/v1/me", "", c); w.Code != 401 {
		t.Fatal("expired session accepted")
	}
	c = login()
	_, err = s.Pool.Exec(context.Background(), `UPDATE user_account SET is_active=false WHERE id=$1`, uid)
	if err != nil {
		t.Fatal(err)
	}
	if w := apiCall(s, "GET", "/api/v1/me", "", c); w.Code != 401 {
		t.Fatal("inactive user accepted")
	}
	if w := apiCall(s, "POST", "/api/v1/auth/login", `{"email":"missing@example.test","password":"wrong-password"}`, nil); w.Code != 401 {
		t.Fatal("invalid login accepted")
	}
}

func TestAuthOriginAndLimits(t *testing.T) {
	s, _, _, _ := authFixture(t)
	r := httptest.NewRequest("POST", "/api/v1/auth/login", strings.NewReader(`{}`))
	r.Header.Set("Origin", "https://attacker.example")
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	s.Router.ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatal("cross-origin login accepted")
	}
	for i := 0; i < 11; i++ {
		w = apiCall(s, "POST", "/api/v1/auth/login", `{}`, nil)
	}
	if w.Code != 429 || w.Header().Get("Retry-After") == "" {
		t.Fatal("login not throttled")
	}
}

func TestPasswordHash(t *testing.T) {
	hash, err := auth.HashPassword("correct-password")
	if err != nil {
		t.Fatal(err)
	}
	if !auth.VerifyPassword(hash, "correct-password") || auth.VerifyPassword(hash, "wrong-password") {
		t.Fatal("password verification failed")
	}
	if auth.VerifyPassword(strings.Replace(hash, "m=65536", "m=999999999", 1), "correct-password") {
		t.Fatal("unbounded parameters accepted")
	}
	if _, err := auth.HashPassword("short"); err == nil {
		t.Fatal("short password accepted")
	}
}
