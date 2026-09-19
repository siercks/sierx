package api

import (
	"context"
	"encoding/base32"
	"encoding/json"
	"fmt"
	"github.com/siercks/sierx/internal/api/auth"
	"github.com/siercks/sierx/internal/bootstrap"
	"github.com/siercks/sierx/internal/config"
	"github.com/siercks/sierx/internal/store"
	"io"
	"log/slog"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
	"uuid"
)

// Invoked explicitly by gate-browser. Regular API tests do not silently stand
// in for browser acceptance. The harness owns an isolated PostgreSQL database
// and serves the actual embedded build over HTTPS with real secure cookies.
func TestBrowserAcceptance(t *testing.T) {
	if os.Getenv("SIERX_BROWSER_TEST") != "1" {
		t.Skip("run make gate-browser for browser acceptance")
	}
	pool := isolatedPool(t)
	s := New(pool, slog.New(slog.NewTextHandler(io.Discard, nil)))
	tls := httptest.NewUnstartedServer(s.Router)
	s.ConfigureAuth(config.Env{AuthMode: "local", SessionKey: strings.Repeat("browser-fixture-", 4)})
	s.ConfigureDocuments()
	tls.StartTLS()
	defer tls.Close()
	s.auth.cfg.BaseURL = tls.URL
	fixture, err := bootstrap.Run(context.Background(), pool, bootstrap.Options{Slug: "browser", Name: "Browser acceptance", Email: "browser@example.test", DisplayName: "Browser tester", Password: "browser-test-password-12345", AuthMode: "local", ProjectPrefix: "SRX", ProjectName: "Backlog"})
	if err != nil {
		t.Fatal(err)
	}
	if os.Getenv("SIERX_BROWSER_SCALE") == "1" {
		var tid, sid, origin string
		err = pool.QueryRow(context.Background(), `SELECT t.id::text,s.id::text,w.origin_id::text FROM item_type t JOIN status s ON s.project_id=t.project_id JOIN project p ON p.id=t.project_id JOIN workspace w ON w.id=p.workspace_id WHERE p.id=$1 AND t.key='story' AND s.key='todo'`, fixture.ProjectID).Scan(&tid, &sid, &origin)
		if err != nil {
			t.Fatal(err)
		}
		wid, _ := uuid.Parse(fixture.WorkspaceID)
		pid, _ := uuid.Parse(fixture.ProjectID)
		typeID, _ := uuid.Parse(tid)
		statusID, _ := uuid.Parse(sid)
		oid, _ := uuid.Parse(origin)
		version := int32(1)
		for batch := 0; batch < 50; batch++ {
			_, err = store.New(pool).Mutate(context.Background(), wid, func(m *store.Mutation) error {
				for i := 0; i < 200; i++ {
					m.Create(store.ItemInsert{ID: uuid.NewV7(), ProjectID: pid, ItemTypeID: typeID, StatusID: statusID, OriginID: oid, ConfigVersion: &version, Title: fmt.Sprintf("Scale item %05d", batch*200+i)})
				}
				return nil
			})
			if err != nil {
				t.Fatal(err)
			}
		}
	}
	token, err := s.auth.service.Login(context.Background(), "browser@example.test", "browser-test-password-12345", "")
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("node", "node_modules/playwright/cli.js", "test")
	if os.Getenv("SIERX_BROWSER_SCALE") == "1" {
		cmd = exec.Command("node", "node_modules/playwright/cli.js", "test", "scale.spec.ts")
	} else {
		cmd = exec.Command("node", "node_modules/playwright/cli.js", "test", "workflow.spec.ts")
	}
	cmd.Dir = "../../web"
	cmd.Env = append(os.Environ(), "SIERX_TEST_URL="+tls.URL, "SIERX_TEST_SESSION="+token)
	if os.Getenv("SIERX_BROWSER_SCALE") != "1" {
		// Separate users keep one-use TOTP/recovery codes independent per engine.
		credentials := map[string]any{}
		for _, engine := range []string{"chromium", "firefox", "webkit"} {
			email := engine + "@browser.example.test"
			hash, err := auth.HashPassword("browser-test-password-12345")
			if err != nil {
				t.Fatal(err)
			}
			var userID string
			err = pool.QueryRow(context.Background(), `INSERT INTO user_account(email,display_name,password_hash) VALUES($1,'MFA tester',$2) RETURNING id::text`, email, hash).Scan(&userID)
			if err != nil {
				t.Fatal(err)
			}
			_, err = pool.Exec(context.Background(), `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$2,'member')`, fixture.WorkspaceID, userID)
			if err != nil {
				t.Fatal(err)
			}
			enrollment, err := s.auth.service.Enroll(context.Background(), userID, "browser-test-password-12345")
			if err != nil {
				t.Fatal(err)
			}
			secret, err := base32.StdEncoding.WithPadding(base32.NoPadding).DecodeString(enrollment.Secret)
			if err != nil {
				t.Fatal(err)
			}
			codes, err := s.auth.service.Confirm(context.Background(), userID, auth.Code(secret, time.Now().Add(-30*time.Second)))
			if err != nil {
				t.Fatal(err)
			}
			credentials[engine] = map[string]string{"email": email, "secret": enrollment.Secret, "recovery": codes[0]}
		}
		data, _ := json.Marshal(credentials)
		cmd.Env = append(cmd.Env, "SIERX_TEST_MFA="+string(data))
	}
	engines := []string{"chromium"}
	if os.Getenv("SIERX_CHROMIUM_ONLY") != "1" {
		engines = append(engines, "firefox")
	}
	if os.Getenv("SIERX_WEBKIT") == "1" {
		engines = append(engines, "webkit")
	}
	for _, engine := range engines {
		// Each matrix entry gets a fresh login-attempt window. Within an engine
		// all real authentication throttling remains enabled and tested.
		s.auth.mu.Lock()
		clear(s.auth.attempts)
		s.auth.mu.Unlock()
		args := append(append([]string{}, cmd.Args[1:]...), "--project="+engine, "--output=test-results/"+engine)
		run := exec.Command("node", args...)
		run.Dir, run.Env = cmd.Dir, cmd.Env
		run.Stdout, run.Stderr = os.Stdout, os.Stderr
		if err := run.Run(); err != nil {
			t.Fatal("browser acceptance failed: ", err)
		}
	}
}
