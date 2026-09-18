package auth

import (
	"strings"
	"testing"
	"time"
)

func TestTOTPVectors(t *testing.T) {
	// RFC 6238 Appendix B SHA-1 vectors, reduced to the six configured digits.
	for _, tc := range []struct {
		at   int64
		code string
	}{{59, "287082"}, {1111111109, "081804"}, {1111111111, "050471"}, {1234567890, "005924"}, {2000000000, "279037"}, {20000000000, "353130"}} {
		if got := Code([]byte("12345678901234567890"), time.Unix(tc.at, 0)); got != tc.code {
			t.Fatalf("at %d: got %s want %s", tc.at, got, tc.code)
		}
	}
	now := time.Unix(1234567890, 0)
	state := totpState{Secret: []byte("12345678901234567890"), LastStep: -1}
	if !consumeCode(&state, Code(state.Secret, now), now, false) || consumeCode(&state, Code(state.Secret, now), now, false) {
		t.Fatal("replay accepted")
	}
}

func TestTOTPEncryption(t *testing.T) {
	s := New(nil, strings.Repeat("x", 32))
	original := totpState{Secret: []byte("12345678901234567890"), Active: true}
	raw, err := s.seal("user-a", original)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), string(original.Secret)) {
		t.Fatal("secret stored in cleartext")
	}
	if _, err := s.open("user-b", raw); err == nil {
		t.Fatal("ciphertext accepted for another user")
	}
	raw[len(raw)-1] ^= 1
	if _, err := s.open("user-a", raw); err == nil {
		t.Fatal("tampered ciphertext accepted")
	}
}
