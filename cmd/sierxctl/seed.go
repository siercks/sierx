// seed — build a realistic workspace (BUILD task 0.9).
//
//	sierxctl seed [--seed N] [--items N] [--projects N] [--max-depth N]
//
// Deterministic: the same --seed reproduces the same workspace, which is what
// the acceptance check compares. Writes through store.Mutate like everything
// else, so sequences, rollups and events are correct by construction.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/siercks/sierx/internal/store/seed"
)

func runSeed(ctx context.Context, args []string) error {
	opts := seed.DefaultOptions()
	fs := flag.NewFlagSet("seed", flag.ContinueOnError)
	fs.Int64Var(&opts.Seed, "seed", opts.Seed, "random seed; the same value reproduces the same workspace")
	fs.IntVar(&opts.Items, "items", opts.Items, "number of items to create")
	fs.IntVar(&opts.Projects, "projects", opts.Projects, "number of projects")
	fs.IntVar(&opts.MaxDepth, "max-depth", opts.MaxDepth, "maximum hierarchy depth (SPEC §5.3 caps this at 8)")
	fs.IntVar(&opts.Users, "users", opts.Users, "number of users to create")
	fs.StringVar(&opts.Slug, "slug", opts.Slug, "workspace slug prefix")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if opts.MaxDepth > 8 {
		return errors.New("--max-depth cannot exceed 8 (SPEC §5.3)")
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

	sum, err := seed.Run(ctx, pool, opts)
	if err != nil {
		return err
	}
	fmt.Printf("seed: workspace=%s items=%d max_depth=%d links=%d events=%d\n",
		sum.WorkspaceID, sum.Items, sum.MaxDepth, sum.Links, sum.Events)
	fmt.Printf("seed: checksum=%s\n", sum.Checksum)
	return nil
}
