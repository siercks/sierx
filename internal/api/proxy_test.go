package api

import (
	"context"
	"net/http/httptest"
	"net/netip"
	"testing"
)

func TestAuthProxy(t *testing.T) {
	s, email, uid, _ := authFixture(t)
	request := func(peer string, headers map[string]string) int {
		r := httptest.NewRequest("GET", "/api/v1/me", nil)
		r.RemoteAddr = peer
		for k, v := range headers {
			r.Header.Set(k, v)
		}
		w := httptest.NewRecorder()
		s.Router.ServeHTTP(w, r)
		return w.Code
	}
	headers := map[string]string{"X-Sierx-Email": email}
	if request("127.0.0.1:1234", headers) != 401 {
		t.Fatal("local mode inferred proxy auth")
	}
	s.auth.cfg.AuthMode = "proxy"
	s.auth.cfg.TrustedProxies = []netip.Prefix{netip.MustParsePrefix("127.0.0.1/32")}
	if request("127.0.0.1:1234", headers) != 401 {
		t.Fatal("password account accepted as proxy identity")
	}
	if _, err := s.Pool.Exec(context.Background(), `UPDATE user_account SET password_hash=NULL WHERE id=$1`, uid); err != nil {
		t.Fatal(err)
	}
	if request("127.0.0.1:1234", headers) != 200 {
		t.Fatal("trusted proxy rejected")
	}
	headers["X-Forwarded-For"] = "127.0.0.1"
	headers["X-Real-IP"] = "127.0.0.1"
	if request("192.0.2.1:1234", headers) != 401 {
		t.Fatal("spoofed identity accepted")
	}
	if request("invalid", headers) != 401 {
		t.Fatal("invalid peer accepted")
	}
	headers["X-Sierx-Email"] = "unknown@example.test"
	if request("127.0.0.1:1234", headers) != 401 {
		t.Fatal("unknown identity accepted")
	}
	if w := apiCall(s, "POST", "/api/v1/auth/login", `{}`, nil); w.Code != 403 {
		t.Fatal("local login enabled in proxy mode")
	}
}
