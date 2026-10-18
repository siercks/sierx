// Account lifecycle commands use the maintenance connection and preserve
// memberships, project ownership, content, comments, and history.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"regexp"

	"github.com/jackc/pgx/v5"
)

var canonicalUUID = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

type accountLifecycleResult struct {
	AccountID       string
	ActiveBefore    bool
	ActiveAfter     bool
	SessionsRevoked int32
}

func runAccountLifecycle(ctx context.Context, args []string) error {
	if len(args) == 0 || (args[0] != "suspend" && args[0] != "reactivate") {
		return errors.New("usage: sierxctl accounts suspend|reactivate --user UUID --case UUID")
	}
	active := args[0] == "reactivate"
	fs := flag.NewFlagSet("accounts "+args[0], flag.ContinueOnError)
	userID := fs.String("user", "", "account UUID")
	caseRef := fs.String("case", "", "restricted operator case UUID")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if fs.NArg() != 0 || !canonicalUUID.MatchString(*userID) || !canonicalUUID.MatchString(*caseRef) {
		return errors.New("--user and --case must be canonical UUIDs; no positional arguments are accepted")
	}
	dsn := os.Getenv("SIERX_MAINTENANCE_DATABASE_URL")
	if dsn == "" {
		return errors.New("SIERX_MAINTENANCE_DATABASE_URL is unset")
	}
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return fmt.Errorf("connect to maintenance database: %w", err)
	}
	defer conn.Close(ctx)

	var result accountLifecycleResult
	err = conn.QueryRow(ctx,
		`SELECT account_id::text,active_before,active_after,sessions_revoked
		 FROM public.sierx_set_account_active($1::uuid,$2,$3::uuid)`,
		*userID, active, *caseRef,
	).Scan(&result.AccountID, &result.ActiveBefore, &result.ActiveAfter, &result.SessionsRevoked)
	if err != nil {
		return fmt.Errorf("account lifecycle action failed (check case authorization and account UUID)")
	}
	action := "suspended"
	if active {
		action = "reactivated"
	}
	fmt.Printf("account %s: id=%s active_before=%t active_after=%t sessions_revoked=%d case=%s\n",
		action, result.AccountID, result.ActiveBefore, result.ActiveAfter, result.SessionsRevoked, *caseRef)
	return nil
}
