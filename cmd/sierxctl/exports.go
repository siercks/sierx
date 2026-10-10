package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/jackc/pgx/v5"
)

func runDataExport(ctx context.Context, args []string) error {
	if len(args) == 0 || (args[0] != "create" && args[0] != "download") {
		return errors.New("usage: sierxctl exports create|download --case UUID [--user UUID | --id UUID --out FILE]")
	}
	fs := flag.NewFlagSet("exports "+args[0], flag.ContinueOnError)
	userID := fs.String("user", "", "account UUID")
	exportID := fs.String("id", "", "export UUID")
	caseRef := fs.String("case", "", "restricted operator case UUID")
	out := fs.String("out", "", "new local output file (must not already exist)")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if fs.NArg() != 0 || !canonicalUUID.MatchString(*caseRef) {
		return errors.New("--case must be a canonical UUID; no positional arguments are accepted")
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

	switch args[0] {
	case "create":
		if !canonicalUUID.MatchString(*userID) || *exportID != "" || *out != "" {
			return errors.New("create requires --user UUID and does not accept --id or --out")
		}
		var id string
		var expires time.Time
		if err := conn.QueryRow(ctx,
			`SELECT export_id::text, expires_at FROM public.sierx_create_data_export($1::uuid,$2::uuid)`,
			*userID, *caseRef,
		).Scan(&id, &expires); err != nil {
			return errors.New("export creation failed (check case authorization and account UUID)")
		}
		fmt.Printf("limited export created: id=%s case=%s expires_at=%s\n", id, *caseRef, expires.UTC().Format(time.RFC3339))
		return nil
	case "download":
		if !canonicalUUID.MatchString(*exportID) || *userID != "" || *out == "" {
			return errors.New("download requires --id UUID and --out FILE; --user is not accepted")
		}
		var payload []byte
		if err := conn.QueryRow(ctx,
			`SELECT public.sierx_read_data_export($1::uuid,$2::uuid)`, *exportID, *caseRef,
		).Scan(&payload); err != nil {
			return errors.New("export download failed (check case authorization, expiry, and export UUID)")
		}
		file, err := os.OpenFile(*out, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if err != nil {
			return fmt.Errorf("create export file without overwriting an existing path: %w", err)
		}
		if _, err = file.Write(payload); err == nil {
			err = file.Sync()
		}
		closeErr := file.Close()
		if err != nil {
			_ = os.Remove(*out)
			return fmt.Errorf("write export file: %w", err)
		}
		if closeErr != nil {
			_ = os.Remove(*out)
			return fmt.Errorf("close export file: %w", closeErr)
		}
		fmt.Printf("limited export written: id=%s case=%s path=%s\n", *exportID, *caseRef, *out)
		return nil
	default:
		return errors.New("usage: sierxctl exports create|download")
	}
}
