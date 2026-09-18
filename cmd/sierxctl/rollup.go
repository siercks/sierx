// rollup — ADR-005 control 2: recompute every rollup and report disagreements.
//
//	sierxctl rollup --verify
//
// Exits nonzero if any row disagrees, so it can be used as an assertion by the
// backup conformance check (task 0.11) against a restored copy, where a
// silently wrong rollup would otherwise be invisible.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/siercks/sierx/internal/store"
)

func runRollup(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("rollup", flag.ContinueOnError)
	verify := fs.Bool("verify", false, "recompute every rollup and report rows that disagree")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if !*verify {
		return errors.New("usage: sierxctl rollup --verify")
	}
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		return errors.New("DATABASE_URL is unset")
	}
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return err
	}
	defer pool.Close()

	st := store.New(pool)
	items, rollups, err := st.CountItemsAndRollups(ctx)
	if err != nil {
		return err
	}
	bad, err := st.VerifyRollups(ctx)
	if err != nil {
		return err
	}
	fmt.Printf("rollup --verify: items=%d rollups=%d mismatches=%d\n", items, rollups, len(bad))
	for i, m := range bad {
		if i == 20 {
			fmt.Printf("  ... and %d more\n", len(bad)-20)
			break
		}
		fmt.Printf("  %s descendants stored=%d actual=%d done stored=%d actual=%d\n",
			m.ItemID, m.StoredDescendants, m.ActualDescendants, m.StoredDone, m.ActualDone)
	}
	// ADR-013: a missing rollup row is as much a failure as a wrong one.
	if items != rollups {
		return fmt.Errorf("count(item)=%d but count(item_rollup)=%d (ADR-013)", items, rollups)
	}
	if len(bad) > 0 {
		return fmt.Errorf("%d rollup row(s) disagree with a fresh aggregate", len(bad))
	}
	return nil
}
