package api

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	neturl "net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"uuid"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/siercks/sierx/internal/bootstrap"
	"github.com/siercks/sierx/internal/config"
)

func TestBootstrap(t *testing.T) {
	ctx := context.Background()
	url := os.Getenv("DATABASE_URL")
	if url == "" {
		t.Fatal("DATABASE_URL required")
	}
	admin, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Close()
	name := "bootstrap_" + strings.ReplaceAll(uuid.NewV7().String(), "-", "")
	if _, err = admin.Exec(ctx, "CREATE DATABASE "+pgx.Identifier{name}.Sanitize()+" TEMPLATE template0"); err != nil {
		t.Fatal(err)
	}
	defer func() { _, _ = admin.Exec(ctx, "DROP DATABASE "+pgx.Identifier{name}.Sanitize()+" WITH (FORCE)") }()
	dsn, err := neturl.Parse(url)
	if err != nil {
		t.Fatal(err)
	}
	dsn.Path = "/" + name
	url = dsn.String()
	p, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()
	cmd := exec.Command("../../bin/goose", "-dir", "../../migrations", "postgres", url, "up")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("migrate: %v %s", err, out)
	}
	binary := filepath.Join(t.TempDir(), "sierxctl")
	if out, err := exec.Command("go", "build", "-o", binary, "../../cmd/sierxctl").CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, out)
	}
	env := []string{"DATABASE_URL=" + url, "SIERX_AUTH_MODE=local", "SIERX_BOOTSTRAP_WORKSPACE_SLUG=test", "SIERX_BOOTSTRAP_WORKSPACE_NAME=Test", "SIERX_BOOTSTRAP_ADMIN_EMAIL=admin@example.test", "SIERX_BOOTSTRAP_ADMIN_NAME=Admin", "SIERX_BOOTSTRAP_ADMIN_PASSWORD=test-password-12345", "SIERX_BOOTSTRAP_PROJECT_PREFIX=SRX", "SIERX_BOOTSTRAP_PROJECT_NAME=Backlog"}
	run := func() bootstrap.Result {
		t.Helper()
		cmd := exec.Command(binary, "bootstrap")
		cmd.Env = append(os.Environ(), env...)
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("bootstrap: %v %s", err, out)
		}
		var result bootstrap.Result
		if err := json.Unmarshal(out, &result); err != nil {
			t.Fatal(err)
		}
		return result
	}
	first := run()
	if first.Existing {
		t.Fatal("first bootstrap was no-op")
	}
	var before string
	const snapshot = `SELECT jsonb_build_object('workspace',(SELECT jsonb_agg(to_jsonb(w)) FROM workspace w),'users',(SELECT jsonb_agg(to_jsonb(u)) FROM user_account u),'projects',(SELECT jsonb_agg(to_jsonb(p)) FROM project p),'config',(SELECT jsonb_agg(to_jsonb(c)) FROM project_config c),'counter',(SELECT jsonb_agg(to_jsonb(s)) FROM seq_counter s))::text`
	if err = p.QueryRow(ctx, snapshot).Scan(&before); err != nil {
		t.Fatal(err)
	}
	second := run()
	if !second.Existing || first.WorkspaceID != second.WorkspaceID || first.UserID != second.UserID || first.ProjectID != second.ProjectID {
		t.Fatal("bootstrap not idempotent")
	}
	var after string
	if err = p.QueryRow(ctx, snapshot).Scan(&after); err != nil {
		t.Fatal(err)
	}
	if before != after {
		t.Fatal("second bootstrap changed stored data")
	}
	var statuses int
	if err = p.QueryRow(ctx, `SELECT count(*) FROM config_status`).Scan(&statuses); err != nil || statuses != 5 {
		t.Fatalf("config not installed: %d %v", statuses, err)
	}
	s := New(p, slog.New(slog.NewTextHandler(io.Discard, nil)))
	s.ConfigureAuth(config.Env{AuthMode: "local", BaseURL: "https://example.test", SessionKey: strings.Repeat("s", 32)})
	w := apiCall(s, "POST", "/api/v1/auth/login", `{"email":"admin@example.test","password":"test-password-12345"}`, nil)
	if w.Code != 200 {
		t.Fatalf("bootstrap login %d %s", w.Code, w.Body)
	}
	if _, err := bootstrap.Run(ctx, p, bootstrap.Options{Slug: "another", Name: "Other", Email: "admin@example.test", DisplayName: "Admin", AuthMode: "local", ProjectPrefix: "SRX", ProjectName: "Backlog"}); err == nil {
		t.Fatal("second workspace accepted")
	}
}
