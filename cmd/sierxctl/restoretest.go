// restoretest — the scheduled restore test (ADR-017, §14.2).
//
//	sierxctl restore-test
//
// Calls `driver.sh <driver> restore-to <scratch dsn>` and nothing else: the
// restore path is the only thing under test, and naming a tool here would
// defeat gate-nobackupleak. Rotates across the configured drivers so a
// secondary that has never been restored from cannot stay untested (ADR-010),
// using the run counter in .backups/restore-test-rotation.
//
// There is deliberately no --force, --skip-verify or --dry-run: a restore test
// with an escape hatch becomes a restore test that never fully runs.
package main

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
)

const rotationFile = ".backups/restore-test-rotation"

func runRestoreTest(ctx context.Context, args []string) error {
	if len(args) > 0 {
		return fmt.Errorf("restore-test takes no arguments (got %q); it has no escape hatches by design", args[0])
	}
	list := os.Getenv("SIERX_BACKUP_DRIVERS")
	if list == "" {
		return errors.New("SIERX_BACKUP_DRIVERS is unset")
	}
	drivers := strings.FieldsFunc(list, func(r rune) bool { return r == ',' || r == ' ' })
	if len(drivers) == 0 {
		return errors.New("SIERX_BACKUP_DRIVERS names no drivers")
	}
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		return errors.New("DATABASE_URL is unset")
	}

	n := readRotation()
	driver := drivers[n%len(drivers)]
	scratch := os.Getenv("SIERX_RESTORE_SCRATCH_DB")
	if scratch == "" {
		scratch = "sierx_restore_test"
	}
	target, err := replaceDatabase(dsn, scratch)
	if err != nil {
		return err
	}

	fmt.Printf("restore-test: run %d of the rotation -> driver %q (configured: %s)\n",
		n+1, driver, strings.Join(drivers, ", "))

	// Recreate the scratch database through the driver-agnostic admin path.
	adminDSN, err := replaceDatabase(dsn, "postgres")
	if err != nil {
		return err
	}
	for _, sql := range []string{
		"DROP DATABASE IF EXISTS " + quoteIdent(scratch),
		// Pinned, not inherited: a scratch database created from template1 on a
		// cluster initdb'd without --encoding=UTF8 comes out SQL_ASCII, and a
		// restore into it would be testing a different database than the one
		// that was backed up (§4.4).
		"CREATE DATABASE " + quoteIdent(scratch) + " TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C'",
	} {
		if err := psqlExec(ctx, adminDSN, sql); err != nil {
			return fmt.Errorf("preparing scratch database: %w", err)
		}
	}

	cmd := exec.CommandContext(ctx, "bash", "scripts/backup/driver.sh", driver, "restore-to", target)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("restore-test FAILED for driver %q: %w", driver, err)
	}
	writeRotation(n + 1)
	fmt.Printf("restore-test: driver %q restored into the scratch database\n", driver)
	return nil
}

func psqlExec(ctx context.Context, dsn, sql string) error {
	cmd := exec.CommandContext(ctx, "psql", dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql)
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func quoteIdent(s string) string { return `"` + strings.ReplaceAll(s, `"`, `""`) + `"` }

// replaceDatabase swaps the database name in a postgres:// dsn.
func replaceDatabase(dsn, db string) (string, error) {
	base, query := dsn, ""
	if i := strings.Index(dsn, "?"); i >= 0 {
		base, query = dsn[:i], dsn[i:]
	}
	i := strings.LastIndex(base, "/")
	if i < 0 {
		return "", fmt.Errorf("cannot parse DATABASE_URL")
	}
	return base[:i+1] + db + query, nil
}

func readRotation() int {
	f, err := os.Open(rotationFile)
	if err != nil {
		return 0
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	if s.Scan() {
		if n, err := strconv.Atoi(strings.TrimSpace(s.Text())); err == nil && n >= 0 {
			return n
		}
	}
	return 0
}

func writeRotation(n int) {
	if err := os.MkdirAll(filepath.Dir(rotationFile), 0o755); err != nil {
		return
	}
	// Best effort: losing the counter means repeating a driver, not a failure.
	_ = os.WriteFile(rotationFile, []byte(strconv.Itoa(n)+"\n"), 0o644)
}
