package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/siercks/sierx/internal/api/auth"
	"github.com/siercks/sierx/internal/bootstrap"
)

func runBootstrap(ctx context.Context, args []string) error {
	if len(args) != 0 {
		return fmt.Errorf("bootstrap takes environment variables, not arguments")
	}
	if os.Getenv("DATABASE_URL") == "" {
		return fmt.Errorf("DATABASE_URL is required")
	}
	if os.Getenv("SIERX_AUTH_MODE") == "local" {
		if err := auth.ValidatePassword(os.Getenv("SIERX_BOOTSTRAP_ADMIN_PASSWORD")); err != nil {
			return fmt.Errorf("SIERX_BOOTSTRAP_ADMIN_PASSWORD is invalid: %w", err)
		}
	}
	p, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		return fmt.Errorf("DATABASE_URL is malformed")
	}
	defer p.Close()
	result, err := bootstrap.Run(ctx, p, bootstrap.Options{Slug: os.Getenv("SIERX_BOOTSTRAP_WORKSPACE_SLUG"), Name: os.Getenv("SIERX_BOOTSTRAP_WORKSPACE_NAME"), Email: os.Getenv("SIERX_BOOTSTRAP_ADMIN_EMAIL"), DisplayName: os.Getenv("SIERX_BOOTSTRAP_ADMIN_NAME"), Password: os.Getenv("SIERX_BOOTSTRAP_ADMIN_PASSWORD"), AuthMode: os.Getenv("SIERX_AUTH_MODE"), ProjectPrefix: os.Getenv("SIERX_BOOTSTRAP_PROJECT_PREFIX"), ProjectName: os.Getenv("SIERX_BOOTSTRAP_PROJECT_NAME")})
	if err != nil {
		return fmt.Errorf("bootstrap failed; check inputs and database availability (no partial workspace was created)")
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}
