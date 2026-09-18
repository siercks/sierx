package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/siercks/sierx/internal/api/auth"
	"github.com/siercks/sierx/internal/config"
)

type identityKey struct{}

func Identity(r *http.Request) auth.Identity {
	who, _ := r.Context().Value(identityKey{}).(auth.Identity)
	return who
}

type attemptWindow struct {
	start time.Time
	count int
}
type authState struct {
	passwordWork chan struct{}
	service      *auth.Service
	cfg          config.Env
	mu           sync.Mutex
	attempts     map[string]attemptWindow
}

func (s *Server) ConfigureAuth(c config.Env) {
	s.auth = &authState{service: auth.New(s.Pool, c.SessionKey), cfg: c, attempts: map[string]attemptWindow{}, passwordWork: make(chan struct{}, 1)}
	s.Router.Post("/api/v1/auth/login", s.login)
	s.Router.With(s.requireAuth).Post("/api/v1/auth/logout", s.logout)
	s.Router.With(s.requireAuth).Get("/api/v1/me", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, Identity(r)) })
	s.Router.With(s.requireAuth).Post("/api/v1/auth/totp/enroll", s.totpEnroll)
	s.Router.With(s.requireAuth).Post("/api/v1/auth/totp/verify", s.totpConfirm)
	s.Router.With(s.requireAuth).Post("/api/v1/auth/totp/disable", s.totpDisable)
	s.Router.With(s.requireAuth).Get("/api/v1/projects", s.listProjects)
	s.Router.With(s.requireAuth).Post("/api/v1/projects", s.createProject)
	s.Router.With(s.requireAuth).Get("/api/v1/projects/{key}", s.getProject)
	s.Router.With(s.requireAuth).Get("/api/v1/projects/{key}/config", s.projectConfig)
	s.Router.With(s.requireAuth).Get("/api/v1/items", s.listItems)
	s.Router.With(s.requireAuth).Post("/api/v1/items", s.createItem)
	s.Router.With(s.requireAuth).Get("/api/v1/items/{key}", s.getItem)
	s.Router.With(s.requireAuth).Patch("/api/v1/items/{key}", s.updateItem)
	s.Router.With(s.requireAuth).Delete("/api/v1/items/{key}", s.deleteItem)
	s.Router.With(s.requireAuth).Post("/api/v1/items/{key}/transition", s.transitionItem)
	s.Router.With(s.requireAuth).Post("/api/v1/items/{key}/move", s.moveItem)
	s.Router.With(s.requireAuth).Get("/api/v1/items/{key}/links", s.listLinks)
	s.Router.With(s.requireAuth).Post("/api/v1/items/{key}/links", s.createLink)
	s.Router.With(s.requireAuth).Delete("/api/v1/links/{id}", s.deleteLink)
	s.Router.With(s.requireAuth).Get("/api/v1/comments", s.listComments)
	s.Router.With(s.requireAuth).Post("/api/v1/comments", s.createComment)
	s.Router.With(s.requireAuth).Patch("/api/v1/comments/{id}", s.changeComment)
	s.Router.With(s.requireAuth).Delete("/api/v1/comments/{id}", s.changeComment)
	s.Router.With(s.requireAuth).Get("/api/v1/items/{key}/children", s.children)
	s.Router.With(s.requireAuth).Get("/api/v1/items/{key}/descendants", s.descendants)
	s.Router.With(s.requireAuth).Get("/api/v1/items/{key}/rollup", s.itemRollup)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func decodeJSON(w http.ResponseWriter, r *http.Request, value any) bool {
	media, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || media != "application/json" {
		WriteProblem(w, UnsupportedMediaType())
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if err := d.Decode(value); err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			WriteProblem(w, TooLarge())
		} else {
			WriteProblem(w, BadRequest())
		}
		return false
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		WriteProblem(w, BadRequest())
		return false
	}
	return true
}
func (s *Server) validOrigin(w http.ResponseWriter, r *http.Request) bool {
	if origin := r.Header.Get("Origin"); origin != "" && origin != strings.TrimRight(s.auth.cfg.BaseURL, "/") {
		WriteProblem(w, Forbidden())
		return false
	}
	return true
}

func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	if s.auth.cfg.AuthMode != "local" {
		WriteProblem(w, Forbidden())
		return
	}
	if !s.validOrigin(w, r) {
		return
	}
	ip, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		ip = r.RemoteAddr
	}
	now := time.Now()
	s.auth.mu.Lock()
	for key, entry := range s.auth.attempts {
		if now.Sub(entry.start) >= time.Minute {
			delete(s.auth.attempts, key)
		}
	}
	entry := s.auth.attempts[ip]
	if entry.start.IsZero() {
		entry.start = now
	}
	entry.count++
	limited := entry.count > 10 || len(s.auth.attempts) >= 4096
	if !limited {
		s.auth.attempts[ip] = entry
	}
	s.auth.mu.Unlock()
	if limited {
		w.Header().Set("Retry-After", "60")
		WriteProblem(w, RateLimited())
		return
	}
	var input struct {
		Email    string `json:"email"`
		Password string `json:"password"`
		Code     string `json:"code"`
	}
	if !decodeJSON(w, r, &input) {
		return
	}
	if input.Email == "" || len(input.Email) > 320 || len(input.Password) > 1024 {
		WriteProblem(w, BadRequest())
		return
	}
	select {
	case s.auth.passwordWork <- struct{}{}:
		defer func() { <-s.auth.passwordWork }()
	default:
		w.Header().Set("Retry-After", "1")
		WriteProblem(w, RateLimited())
		return
	}
	token, err := s.auth.service.Login(r.Context(), input.Email, input.Password, input.Code)
	if errors.Is(err, auth.ErrCredentials) {
		WriteProblem(w, Unauthorized())
		return
	}
	if err != nil {
		WriteProblem(w, Unavailable())
		return
	}
	http.SetCookie(w, &http.Cookie{Name: auth.CookieName, Value: token, Path: "/", HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode, MaxAge: int(auth.SessionLifetime.Seconds())})
	writeJSON(w, 200, map[string]bool{"authenticated": true})
}

func (s *Server) requireAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" && r.Method != "HEAD" && !s.validOrigin(w, r) {
			return
		}
		var who auth.Identity
		var err error
		if s.auth.cfg.AuthMode == "proxy" {
			who, err = s.auth.service.Proxy(r.Context(), r, s.auth.cfg.TrustedProxies)
		} else {
			c, cookieErr := r.Cookie(auth.CookieName)
			if cookieErr != nil {
				WriteProblem(w, Unauthorized())
				return
			}
			who, err = s.auth.service.Session(r.Context(), c.Value)
		}
		if errors.Is(err, auth.ErrCredentials) {
			WriteProblem(w, Unauthorized())
			return
		}
		if err != nil {
			WriteProblem(w, Unavailable())
			return
		}
		if logged, ok := r.Context().Value(logIdentityKey{}).(*logIdentity); ok {
			logged.actor, logged.workspace = who.ID, who.WorkspaceID
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), identityKey{}, who)))
	})
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	if s.auth.cfg.AuthMode != "local" {
		WriteProblem(w, Forbidden())
		return
	}
	c, _ := r.Cookie(auth.CookieName)
	if err := s.auth.service.Logout(r.Context(), c.Value); err != nil {
		WriteProblem(w, Unavailable())
		return
	}
	http.SetCookie(w, &http.Cookie{Name: auth.CookieName, Value: "", Path: "/", HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode, MaxAge: -1})
	w.WriteHeader(http.StatusNoContent)
}
