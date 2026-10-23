package api

import (
	"errors"
	"net/http"
	"net/mail"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/jackc/pgx/v5/pgconn"
	"github.com/siercks/sierx/internal/api/auth"
)

type AdminMember struct {
	ID          string `json:"id"`
	DisplayName string `json:"display_name"`
	Email       string `json:"email"`
	Role        string `json:"role"`
	Active      bool   `json:"is_active"`
}

func (s *Server) listAdminMembers(w http.ResponseWriter, r *http.Request) {
	if Identity(r).Role != "admin" {
		WriteProblem(w, Forbidden())
		return
	}
	if !rejectFields(w, r) {
		return
	}
	limit, err := PageLimit(r)
	if err != nil {
		requestProblem(w, err.Error())
		return
	}
	search := strings.TrimSpace(r.URL.Query().Get("q"))
	if len(search) > 100 {
		requestProblem(w, "q must be at most 100 characters.")
		return
	}
	c := Cursor{After: zeroID, Upper: zeroID, Scope: cursorScope(r)}
	if token := r.URL.Query().Get("cursor"); token != "" {
		c, err = DecodeCursor(token, s.auth.cfg.SessionKey, c.Scope)
		if err != nil {
			requestProblem(w, err.Error())
			return
		}
	} else if err = s.DB.QueryRow(r.Context(), `SELECT coalesce(max(user_id::text),$2) FROM membership WHERE workspace_id=$1`, Identity(r).WorkspaceID, zeroID).Scan(&c.Upper); err != nil {
		databaseProblem(w, err)
		return
	}
	rows, err := s.DB.Query(r.Context(), `SELECT id::text,display_name,email,role,is_active FROM public.sierx_admin_list_members($1::uuid,$2::uuid,$3,$4)`, c.After, c.Upper, search, limit+1)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	defer rows.Close()
	page := Page{Data: []any{}}
	for rows.Next() {
		var member AdminMember
		if err = rows.Scan(&member.ID, &member.DisplayName, &member.Email, &member.Role, &member.Active); err != nil {
			databaseProblem(w, err)
			return
		}
		if len(page.Data) == limit {
			token, encodeErr := EncodeCursor(c, s.auth.cfg.SessionKey)
			if encodeErr != nil {
				WriteProblem(w, InternalError())
				return
			}
			page.NextCursor = &token
			break
		}
		page.Data = append(page.Data, member)
		c.After = member.ID
	}
	if rows.Err() != nil {
		databaseProblem(w, rows.Err())
		return
	}
	writeJSON(w, 200, page)
}

func (s *Server) addAdminMember(w http.ResponseWriter, r *http.Request) {
	if Identity(r).Role != "admin" {
		WriteProblem(w, Forbidden())
		return
	}
	if s.auth.cfg.AuthMode != "local" {
		requestProblem(w, "Member creation is available for local sign-in. Proxy identities require operator provisioning.")
		return
	}
	if !rejectFields(w, r) {
		return
	}
	var in struct {
		DisplayName     string `json:"display_name"`
		Email           string `json:"email"`
		InitialPassword string `json:"initial_password"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	in.DisplayName = strings.TrimSpace(in.DisplayName)
	in.Email = strings.ToLower(strings.TrimSpace(in.Email))
	address, err := mail.ParseAddress(in.Email)
	if err != nil || address.Address != in.Email || len(in.Email) > 320 || strings.Count(in.Email, "@") != 1 || strings.IndexFunc(in.Email, unicode.IsSpace) >= 0 || utf8.RuneCountInString(in.DisplayName) < 1 || utf8.RuneCountInString(in.DisplayName) > 200 {
		requestProblem(w, "Enter a valid email address and a display name of 1–200 characters.")
		return
	}
	if err = auth.ValidatePassword(in.InitialPassword); err != nil {
		requestProblem(w, "Generate an initial password of 12–1024 bytes.")
		return
	}
	// Share the bounded password-work slot with login; never queue Argon2 work.
	select {
	case s.auth.passwordWork <- struct{}{}:
		defer func() { <-s.auth.passwordWork }()
	default:
		w.Header().Set("Retry-After", "1")
		WriteProblem(w, RateLimited())
		return
	}
	hash, err := auth.HashPassword(in.InitialPassword)
	if err != nil {
		WriteProblem(w, Unavailable())
		return
	}
	member := AdminMember{DisplayName: in.DisplayName, Email: in.Email, Role: "member", Active: true}
	if err = s.DB.QueryRow(r.Context(), `SELECT public.sierx_admin_add_member($1,$2,$3)::text`, in.Email, in.DisplayName, hash).Scan(&member.ID); err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23505" {
			WriteProblem(w, problem(409, "Member could not be added", "That email cannot be added. Check the member list or contact the operator."))
			return
		}
		if errors.As(err, &pgErr) && pgErr.Code == "42501" {
			WriteProblem(w, Forbidden())
			return
		}
		databaseProblem(w, err)
		return
	}
	// Commit before reporting success. The browser retains the generated login
	// credential even if a response is lost; it is never returned or cached here.
	if err = s.DB.transaction(r.Context()).Commit(r.Context()); err != nil {
		databaseProblem(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, member)
}
