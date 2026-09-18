// Package bootstrap initializes the single workspace without benchmark fixtures.
package bootstrap

import (
	"context"
	"errors"
	"fmt"
	"net/mail"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/siercks/sierx/internal/api/auth"
	"github.com/siercks/sierx/internal/store/seed"
)

type Options struct{ Slug, Name, Email, DisplayName, Password, AuthMode, ProjectPrefix, ProjectName string }
type Result struct {
	WorkspaceID string `json:"workspace_id"`
	UserID      string `json:"user_id"`
	ProjectID   string `json:"project_id"`
	Existing    bool   `json:"existing"`
}

func Run(ctx context.Context, pool *pgxpool.Pool, o Options) (Result, error) {
	var result Result
	if !regexp.MustCompile(`^[a-z][a-z0-9-]{0,62}$`).MatchString(o.Slug) || strings.TrimSpace(o.Name) == "" {
		return result, fmt.Errorf("set a valid workspace slug and name")
	}
	address, err := mail.ParseAddress(o.Email)
	if err != nil || address.Address != o.Email || o.DisplayName == "" {
		return result, fmt.Errorf("set a valid administrator email and display name")
	}
	if !regexp.MustCompile(`^[A-Z][A-Z0-9]{1,9}$`).MatchString(o.ProjectPrefix) || o.ProjectName == "" {
		return result, fmt.Errorf("set a valid initial project prefix and name")
	}
	for _, reserved := range []string{"API", "LOGIN", "BOARD", "VIEWS", "SETTINGS", "ROADMAP", "PROJECTS", "ASSETS"} {
		if o.ProjectPrefix == reserved {
			return result, fmt.Errorf("initial project prefix is reserved")
		}
	}
	if o.AuthMode != "local" && o.AuthMode != "proxy" {
		return result, fmt.Errorf("SIERX_AUTH_MODE must be local or proxy")
	}
	tx, err := pool.Begin(ctx)
	if err != nil {
		return result, err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(1936287096)`); err != nil {
		return result, err
	}
	var slug string
	err = tx.QueryRow(ctx, `SELECT id::text,slug FROM workspace ORDER BY created_at LIMIT 1`).Scan(&result.WorkspaceID, &slug)
	if err == nil {
		var count int
		if err = tx.QueryRow(ctx, `SELECT count(*) FROM workspace`).Scan(&count); err != nil {
			return result, err
		}
		if count != 1 || slug != o.Slug {
			return result, fmt.Errorf("a different workspace already exists; refusing to create another")
		}
		err = tx.QueryRow(ctx, `SELECT u.id::text,p.id::text FROM membership m JOIN user_account u ON u.id=m.user_id JOIN project p ON p.workspace_id=m.workspace_id WHERE m.workspace_id=$1 AND m.role='admin' AND u.email=$2 AND p.key_prefix=$3`, result.WorkspaceID, o.Email, o.ProjectPrefix).Scan(&result.UserID, &result.ProjectID)
		if err != nil {
			return result, fmt.Errorf("workspace already exists with different bootstrap inputs; no changes made")
		}
		result.Existing = true
		return result, tx.Commit(ctx)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return result, err
	}
	var hash *string
	if o.AuthMode == "local" {
		encoded, err := auth.HashPassword(o.Password)
		if err != nil {
			return result, err
		}
		hash = &encoded
	}
	if err = tx.QueryRow(ctx, `INSERT INTO workspace(slug,name,origin_id) VALUES($1,$2,uuidv7()) RETURNING id::text`, o.Slug, o.Name).Scan(&result.WorkspaceID); err != nil {
		return result, err
	}
	// The workspace trigger inserts the required seq_counter row in this transaction.
	if err = tx.QueryRow(ctx, `INSERT INTO user_account(email,display_name,password_hash) VALUES($1,$2,$3) RETURNING id::text`, o.Email, o.DisplayName, hash).Scan(&result.UserID); err != nil {
		return result, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$2,'admin')`, result.WorkspaceID, result.UserID); err != nil {
		return result, err
	}
	if err = tx.QueryRow(ctx, `INSERT INTO project(workspace_id,key_prefix,name,kind) VALUES($1,$2,$3,'delivery') RETURNING id::text`, result.WorkspaceID, o.ProjectPrefix, o.ProjectName).Scan(&result.ProjectID); err != nil {
		return result, err
	}
	if err = seed.InstallConfig(ctx, tx, result.ProjectID); err != nil {
		return result, err
	}
	return result, tx.Commit(ctx)
}
