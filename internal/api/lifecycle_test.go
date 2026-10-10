package api

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"testing"
	"time"
	"uuid"

	"github.com/jackc/pgx/v5"
)

func roleURL(t *testing.T, key, database string) string {
	t.Helper()
	u, err := url.Parse(os.Getenv(key))
	if err != nil || u.Host == "" {
		t.Fatalf("%s is not a valid PostgreSQL URL", key)
	}
	u.Path = "/" + database
	return u.String()
}

func waitForLock(t *testing.T, ctx context.Context, p interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}, applicationName string) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		var waiting bool
		if err := p.QueryRow(ctx, `SELECT EXISTS(
			SELECT 1 FROM pg_stat_activity
			WHERE application_name=$1 AND state='active' AND wait_event_type='Lock'
		)`, applicationName).Scan(&waiting); err != nil {
			t.Fatal(err)
		}
		if waiting {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("%s did not block on the account row lock", applicationName)
}

func TestAccountSuspensionSerializesSessionIssueAndRevocation(t *testing.T) {
	admin := isolatedPool(t)
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()

	var database string
	if err := admin.QueryRow(ctx, `SELECT current_database()`).Scan(&database); err != nil {
		t.Fatal(err)
	}
	authConn, err := pgx.Connect(ctx, roleURL(t, "SIERX_AUTH_DATABASE_URL", database))
	if err != nil {
		t.Fatal(err)
	}
	defer authConn.Close(context.Background())
	maintenanceConn, err := pgx.Connect(ctx, roleURL(t, "SIERX_MAINTENANCE_DATABASE_URL", database))
	if err != nil {
		t.Fatal(err)
	}
	defer maintenanceConn.Close(context.Background())
	if _, err = authConn.Exec(ctx, `SET application_name='sierx_test_lifecycle_auth'`); err != nil {
		t.Fatal(err)
	}
	if _, err = maintenanceConn.Exec(ctx, `SET application_name='sierx_test_lifecycle_maintenance'`); err != nil {
		t.Fatal(err)
	}

	firstID, secondID := uuid.NewV7().String(), uuid.NewV7().String()
	for _, id := range []string{firstID, secondID} {
		if _, err = admin.Exec(ctx, `INSERT INTO user_account(id,email,display_name) VALUES($1,$2,'Lifecycle test')`, id, id+"@example.test"); err != nil {
			t.Fatal(err)
		}
	}

	// Login acquires the account lock first. Suspension waits, then revokes the
	// session inserted by that login before reporting success.
	issueTx, err := authConn.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var created bool
	if err = issueTx.QueryRow(ctx, `SELECT public.sierx_create_session($1,$2)`, make([]byte, 32), firstID).Scan(&created); err != nil || !created {
		t.Fatalf("create session: created=%t err=%v", created, err)
	}
	suspended := make(chan error, 1)
	go func() {
		var revoked int
		err := maintenanceConn.QueryRow(ctx,
			`SELECT sessions_revoked FROM public.sierx_set_account_active($1,false,$2)`,
			firstID, uuid.NewV7().String(),
		).Scan(&revoked)
		if err == nil && revoked != 1 {
			err = errUnexpectedRevokedCount(revoked)
		}
		suspended <- err
	}()
	waitForLock(t, ctx, admin, "sierx_test_lifecycle_maintenance")
	if err = issueTx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	if err = <-suspended; err != nil {
		t.Fatalf("suspend after session creation: %v", err)
	}
	if _, err = maintenanceConn.Exec(ctx, `SELECT public.sierx_set_account_active($1,true,$2)`, firstID, uuid.NewV7().String()); err != nil {
		t.Fatal(err)
	}
	var count int
	if err = admin.QueryRow(ctx, `SELECT count(*) FROM session WHERE user_id=$1`, firstID).Scan(&count); err != nil || count != 0 {
		t.Fatalf("reactivation restored an old session: count=%d err=%v", count, err)
	}

	// Suspension acquires the account lock first. A waiting login rechecks the
	// inactive account and returns false, even after its request began earlier.
	suspendTx, err := maintenanceConn.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var prior, active bool
	var revoked int
	if err = suspendTx.QueryRow(ctx,
		`SELECT active_before,active_after,sessions_revoked FROM public.sierx_set_account_active($1,false,$2)`,
		secondID, uuid.NewV7().String(),
	).Scan(&prior, &active, &revoked); err != nil {
		t.Fatal(err)
	}
	if !prior || active || revoked != 0 {
		t.Fatalf("suspend second account: before=%t after=%t revoked=%d", prior, active, revoked)
	}
	createdAfterSuspend := make(chan bool, 1)
	go func() {
		var result bool
		err := authConn.QueryRow(ctx, `SELECT public.sierx_create_session($1,$2)`, make([]byte, 32), secondID).Scan(&result)
		if err != nil {
			createdAfterSuspend <- true
			return
		}
		createdAfterSuspend <- result
	}()
	waitForLock(t, ctx, admin, "sierx_test_lifecycle_auth")
	if err = suspendTx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	if created = <-createdAfterSuspend; created {
		t.Fatal("login created a session after suspension committed")
	}
	if err = admin.QueryRow(ctx, `SELECT count(*) FROM session WHERE user_id=$1`, secondID).Scan(&count); err != nil || count != 0 {
		t.Fatalf("suspended account has a session: count=%d err=%v", count, err)
	}
}

func errUnexpectedRevokedCount(n int) error {
	return fmt.Errorf("expected to revoke one session, revoked %d", n)
}
