package api

import (
	"encoding/base32"
	"encoding/json"
	"net/http"
	"testing"
	"time"

	"github.com/siercks/sierx/internal/api/auth"
)

func TestTOTP(t *testing.T) {
	s, email, _, _ := authFixture(t)
	login := func(code string) *http.Cookie {
		t.Helper()
		b, _ := json.Marshal(map[string]string{"email": email, "password": "test-password-12345", "code": code})
		w := apiCall(s, "POST", "/api/v1/auth/login", string(b), nil)
		if w.Code != 200 {
			t.Fatalf("login %d %s", w.Code, w.Body)
		}
		return w.Result().Cookies()[0]
	}
	cookie := login("")
	w := apiCall(s, "POST", "/api/v1/auth/totp/enroll", `{"password":"wrong-password"}`, cookie)
	if w.Code != 401 {
		t.Fatal("enrollment without password accepted")
	}
	w = apiCall(s, "POST", "/api/v1/auth/totp/enroll", `{"password":"test-password-12345"}`, cookie)
	if w.Code != 200 {
		t.Fatalf("enroll %d %s", w.Code, w.Body)
	}
	var enrollment auth.Enrollment
	if err := json.Unmarshal(w.Body.Bytes(), &enrollment); err != nil {
		t.Fatal(err)
	}
	secret, err := base32.StdEncoding.WithPadding(base32.NoPadding).DecodeString(enrollment.Secret)
	if err != nil {
		t.Fatal(err)
	}
	w = apiCall(s, "POST", "/api/v1/auth/totp/verify", `{"code":"bad"}`, cookie)
	if w.Code != 401 {
		t.Fatal("bad code accepted")
	}
	b, _ := json.Marshal(map[string]string{"code": auth.Code(secret, time.Now())})
	w = apiCall(s, "POST", "/api/v1/auth/totp/verify", string(b), cookie)
	if w.Code != 200 {
		t.Fatalf("verify %d %s", w.Code, w.Body)
	}
	var confirmed struct {
		Codes []string `json:"recovery_codes"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &confirmed); err != nil {
		t.Fatal(err)
	}
	if len(confirmed.Codes) != 8 {
		t.Fatal("missing recovery codes")
	}
	if w := apiCall(s, "GET", "/api/v1/me", "", cookie); w.Code != 401 {
		t.Fatal("pre-enrollment session survived")
	}
	b, _ = json.Marshal(map[string]string{"email": email, "password": "test-password-12345"})
	if w := apiCall(s, "POST", "/api/v1/auth/login", string(b), nil); w.Code != 401 {
		t.Fatal("second factor bypassed")
	}
	cookie = login(confirmed.Codes[0])
	b, _ = json.Marshal(map[string]string{"email": email, "password": "test-password-12345", "code": confirmed.Codes[0]})
	if w := apiCall(s, "POST", "/api/v1/auth/login", string(b), nil); w.Code != 401 {
		t.Fatal("recovery code reused")
	}
	b, _ = json.Marshal(map[string]string{"password": "test-password-12345", "code": confirmed.Codes[1]})
	if w := apiCall(s, "POST", "/api/v1/auth/totp/disable", string(b), cookie); w.Code != 200 {
		t.Fatalf("disable %d %s", w.Code, w.Body)
	}
	if w := apiCall(s, "GET", "/api/v1/me", "", cookie); w.Code != 401 {
		t.Fatal("session survived disable")
	}
	_ = login("")
}
