// partitions — change_event partition maintenance (BUILD task 0.6, SPEC §4.7).
//
//	sierxctl partitions ensure --months-ahead N
//
// Idempotent: creates the monthly partitions for the current UTC month and the
// next N months if missing, via change_event_ensure_partitions() in migration
// 0009, and prints the names it created. There is no drop, prune, or retention
// command and none will be added: pruning destroys the audit trail (§4.7).
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"

	"github.com/jackc/pgx/v5"
)

func runPartitions(ctx context.Context, args []string) error {
	if len(args) < 1 || args[0] != "ensure" {
		return errors.New("usage: sierxctl partitions ensure --months-ahead N")
	}
	fs := flag.NewFlagSet("partitions ensure", flag.ContinueOnError)
	months := fs.Int("months-ahead", 1, "months beyond the current one to have partitions for")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if *months < 0 {
		return errors.New("--months-ahead must be >= 0")
	}
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		return errors.New("DATABASE_URL is unset")
	}
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return fmt.Errorf("connect: %w", err)
	}
	defer conn.Close(ctx)

	rows, err := conn.Query(ctx, "SELECT change_event_ensure_partitions($1)", *months)
	if err != nil {
		return fmt.Errorf("ensure partitions: %w", err)
	}
	created, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return err
	}
	for _, name := range created {
		fmt.Println("created", name)
	}
	fmt.Printf("partitions ensure: %d created, months-ahead=%d\n", len(created), *months)
	return nil
}
