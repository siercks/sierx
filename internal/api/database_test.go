package api

import (
	"context"
	"net/url"
	"os"
	"os/exec"
	"strings"
	"testing"
	"uuid"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func isolatedPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	ctx := context.Background()
	base := os.Getenv("DATABASE_URL")
	if base == "" {
		t.Fatal("DATABASE_URL required")
	}
	admin, err := pgxpool.New(ctx, base)
	if err != nil {
		t.Fatal(err)
	}
	name := "api_" + strings.ReplaceAll(uuid.NewV7().String(), "-", "")
	if _, err = admin.Exec(ctx, "CREATE DATABASE "+pgx.Identifier{name}.Sanitize()+" TEMPLATE template0"); err != nil {
		admin.Close()
		t.Fatal(err)
	}
	dsn, err := url.Parse(base)
	if err != nil {
		t.Fatal(err)
	}
	dsn.Path = "/" + name
	p, err := pgxpool.New(ctx, dsn.String())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		p.Close()
		if _, err := admin.Exec(ctx, "DROP DATABASE "+pgx.Identifier{name}.Sanitize()+" WITH (FORCE)"); err != nil {
			t.Error(err)
		}
		admin.Close()
	})
	if out, err := exec.Command("../../bin/goose", "-dir", "../../migrations", "postgres", dsn.String(), "up").CombinedOutput(); err != nil {
		t.Fatalf("migrate fixture: %v %s", err, out)
	}
	return p
}
