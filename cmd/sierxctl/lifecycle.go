package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"runtime"
	"time"
	"uuid"

	"github.com/jackc/pgx/v5"
	"github.com/siercks/sierx/internal/lifecycle"
)

func runLifecycle(ctx context.Context, args []string) error {
	if len(args) == 0 {
		return errors.New("usage: sierxctl lifecycle init|plan|apply|replay|verify|reconcile-checkpoint|maintain [--file protected-action.json]")
	}
	mode := args[0]
	if mode == "maintain" {
		return runLifecycleMaintenance(ctx, args[1:])
	}
	switch mode {
	case "init", "plan", "apply", "replay", "verify", "reconcile-checkpoint":
	default:
		return errors.New("unknown lifecycle command")
	}
	fs := flag.NewFlagSet("lifecycle "+mode, flag.ContinueOnError)
	file := fs.String("file", "", "protected explicit operator decision JSON")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if fs.NArg() != 0 || (mode == "plan" || mode == "apply") != (*file != "") {
		return errors.New("only plan/apply require --file; positional arguments are not accepted")
	}
	dsn := os.Getenv("SIERX_MAINTENANCE_DATABASE_URL")
	if dsn == "" {
		return errors.New("SIERX_MAINTENANCE_DATABASE_URL is unset")
	}
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return errors.New("maintenance connection failed")
	}
	defer conn.Close(ctx)
	if mode == "plan" {
		a, err := readLifecycleAction(*file)
		if err != nil {
			return err
		}
		return planLifecycle(ctx, conn, a)
	}
	paths, err := lifecycle.EnvironmentPaths()
	if err != nil {
		return err
	}
	unlock, err := lifecycle.Lock(paths.Journal)
	if err != nil {
		return err
	}
	defer unlock()
	h, err := lifecycle.DatabaseHead(ctx, conn)
	if err != nil {
		return err
	}
	if mode == "init" {
		if h.Sequence != 0 || h.Hash != "" {
			return errors.New("cannot initialize over existing decisions; recover the original journal and key")
		}
		_, err = lifecycle.Init(paths.Journal, paths.Key, paths.Checkpoint, h.InstanceID)
		if err == nil {
			fmt.Printf("lifecycle journal initialized: instance=%s\n", h.InstanceID)
		}
		return err
	}
	var j *lifecycle.Journal
	if mode == "reconcile-checkpoint" {
		j, err = lifecycle.RecoverCheckpoint(paths.Journal, paths.Key, paths.Checkpoint)
	} else {
		j, err = lifecycle.Load(paths.Journal, paths.Key, paths.Checkpoint)
	}
	if err != nil {
		return err
	}
	if !j.Prefix(h) {
		return errors.New("database is not an authenticated prefix of this instance journal")
	}
	if mode == "verify" || mode == "reconcile-checkpoint" {
		if !j.Matches(h) {
			return errors.New("journal is verified; database replay is required before application access")
		}
		fmt.Printf("lifecycle verified: instance=%s sequence=%d\n", h.InstanceID, h.Sequence)
		return nil
	}
	tx, err := conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SELECT public.sierx_lifecycle_lock()`); err != nil {
		return errors.New("lifecycle writer lock unavailable")
	}
	// Re-read under the transaction lock, including a process that uses another
	// journal path. Only an exact instance/checkpoint match can be extended.
	h, err = lifecycle.DatabaseHead(ctx, tx)
	if err != nil {
		return err
	}
	if mode == "replay" {
		if !j.Prefix(h) {
			return errors.New("restored database does not match journal prefix")
		}
		for _, r := range j.Records {
			if r.Sequence > h.Sequence {
				if err = lifecycle.ApplyRecord(ctx, tx, r); err != nil {
					return err
				}
			}
		}
	} else {
		if !j.Matches(h) {
			return errors.New("replay the pending journal decisions before adding an operation")
		}
		a, err := readLifecycleAction(*file)
		if err != nil {
			return err
		}
		b, _ := json.Marshal(a)
		var prepared []byte
		if err = tx.QueryRow(ctx, `SELECT public.sierx_lifecycle_plan($1::jsonb)`, b).Scan(&prepared); err != nil {
			_ = tx.Rollback(ctx)
			// A denied action cannot retain a transaction lock or change data, but its
			// case-bound metadata is recorded separately without correction text.
			if _, auditErr := conn.Exec(ctx, `SELECT public.sierx_lifecycle_blocked($1::jsonb)`, b); auditErr != nil {
				return errors.New("operation refused; blocked-attempt audit failed")
			}
			return errors.New("operation refused by lifecycle validation (check hold, target, scope, prerequisite and bounds)")
		}
		var p lifecycle.Action
		if err = json.Unmarshal(prepared, &p); err != nil {
			return err
		}
		r, err := j.Append(p)
		if err != nil {
			return err
		}
		if err = lifecycle.ApplyRecord(ctx, tx, r); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return errors.New("database commit uncertain; verify and replay before application access")
	}
	if mode == "apply" && len(j.Records) > 0 {
		a := j.Records[len(j.Records)-1].Action
		fmt.Printf("lifecycle decision: kind=%s case=%s workspace=%s target=%s items=%d comments=%d views=%d\n", a.Kind, a.CaseRef, a.WorkspaceID, a.TargetID, len(a.ItemIDs), len(a.CommentIDs), len(a.ViewIDs))
	}
	fmt.Printf("lifecycle %s completed: instance=%s sequence=%d\n", mode, j.Head.InstanceID, j.Head.Sequence)
	return nil
}

func readLifecycleAction(path string) (lifecycle.Action, error) {
	var a lifecycle.Action
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() > 32768 {
		return a, errors.New("action must be a bounded regular JSON file")
	}
	if runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0 {
		return a, errors.New("action file must have owner-only permissions")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return a, err
	}
	if err = lifecycle.DecodeAction(b, &a); err != nil {
		return a, err
	}
	if !canonicalUUID.MatchString(a.CaseRef) || a.InstanceID != "" || a.WorkspaceOrigin != "" || len(a.ItemIDs) > 0 || len(a.CommentIDs) > 0 || len(a.ViewIDs) > 0 {
		return a, errors.New("case UUID required; materialized internal decision fields are not accepted")
	}
	for _, id := range []string{a.WorkspaceID, a.TargetID, a.ReplacementID, a.AuthorityRef} {
		if id != "" && !canonicalUUID.MatchString(id) {
			return a, errors.New("all identifiers must be canonical UUIDs")
		}
	}
	if a.Kind == "hold-create" && a.TargetID == "" {
		a.TargetID = uuid.NewV7().String()
	}
	a.At = time.Now().UTC().Format(time.RFC3339Nano)
	return a, nil
}

func planLifecycle(ctx context.Context, conn *pgx.Conn, a lifecycle.Action) error {
	tx, err := conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SELECT public.sierx_lifecycle_lock()`); err != nil {
		return errors.New("lifecycle lock unavailable")
	}
	b, _ := json.Marshal(a)
	var raw []byte
	if err = tx.QueryRow(ctx, `SELECT public.sierx_lifecycle_plan($1::jsonb)`, b).Scan(&raw); err != nil {
		return errors.New("plan refused (check target, hold, scope, prerequisite and bounds)")
	}
	var p lifecycle.Action
	if err = json.Unmarshal(raw, &p); err != nil {
		return err
	}
	fmt.Printf("lifecycle plan: kind=%s case=%s workspace=%s target=%s items=%d comments=%d views=%d; no data changed\n", p.Kind, p.CaseRef, p.WorkspaceID, p.TargetID, len(p.ItemIDs), len(p.CommentIDs), len(p.ViewIDs))
	return nil
}
