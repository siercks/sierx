package api

import (
	"errors"
	"net/http"
	"time"

	"github.com/siercks/sierx/internal/api/auth"
)

// TOTP attempts share bounded password work and per-account throttling.
func (s *Server) totpAllowed(w http.ResponseWriter, r *http.Request) bool {
	if s.auth.cfg.AuthMode != "local" {
		WriteProblem(w, Forbidden())
		return false
	}
	key := "totp:" + Identity(r).ID
	now := time.Now()
	s.auth.mu.Lock()
	for k, e := range s.auth.attempts {
		if now.Sub(e.start) >= time.Minute {
			delete(s.auth.attempts, k)
		}
	}
	e := s.auth.attempts[key]
	if e.start.IsZero() {
		e.start = now
	}
	e.count++
	limited := e.count > 10 || len(s.auth.attempts) >= 4096
	if !limited {
		s.auth.attempts[key] = e
	}
	s.auth.mu.Unlock()
	if limited {
		w.Header().Set("Retry-After", "60")
		WriteProblem(w, RateLimited())
		return false
	}
	select {
	case s.auth.passwordWork <- struct{}{}:
		return true
	default:
		w.Header().Set("Retry-After", "1")
		WriteProblem(w, RateLimited())
		return false
	}
}

func authError(w http.ResponseWriter, err error) {
	if errors.Is(err, auth.ErrCredentials) {
		WriteProblem(w, Unauthorized())
	} else {
		WriteProblem(w, Unavailable())
	}
}
func (s *Server) totpEnroll(w http.ResponseWriter, r *http.Request) {
	if !s.totpAllowed(w, r) {
		return
	}
	defer func() { <-s.auth.passwordWork }()
	var in struct {
		Password string `json:"password"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	result, err := s.auth.service.Enroll(r.Context(), Identity(r).ID, in.Password)
	if err != nil {
		authError(w, err)
		return
	}
	writeJSON(w, 200, result)
}
func (s *Server) totpConfirm(w http.ResponseWriter, r *http.Request) {
	if !s.totpAllowed(w, r) {
		return
	}
	defer func() { <-s.auth.passwordWork }()
	var in struct {
		Code string `json:"code"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	codes, err := s.auth.service.Confirm(r.Context(), Identity(r).ID, in.Code)
	if err != nil {
		authError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"enabled": true, "recovery_codes": codes, "sign_in_required": true})
}
func (s *Server) totpDisable(w http.ResponseWriter, r *http.Request) {
	if !s.totpAllowed(w, r) {
		return
	}
	defer func() { <-s.auth.passwordWork }()
	var in struct {
		Password string `json:"password"`
		Code     string `json:"code"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	if err := s.auth.service.Disable(r.Context(), Identity(r).ID, in.Password, in.Code); err != nil {
		authError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"enabled": false, "sign_in_required": true})
}
