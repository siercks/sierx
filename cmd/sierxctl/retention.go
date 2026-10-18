package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"runtime"
	"time"

	"github.com/siercks/sierx/internal/lifecycle"
)

type retentionPolicy struct {
	Enabled    bool   `json:"enabled"`
	CaseRef    string `json:"case_ref"`
	Workspaces []struct {
		ID          string `json:"workspace_id"`
		DeletedDays int    `json:"deleted_content_days"`
	} `json:"workspaces"`
}

// Maintenance has no default content duration. The operator supplies a private,
// explicit policy; each run processes at most 512 deleted items/comments per
// workspace. Active content, immutable keys, metadata and partitions survive.
func runLifecycleMaintenance(ctx context.Context, args []string) error {
	if len(args) != 2 || args[0] != "--policy" {
		return errors.New("usage: sierxctl lifecycle maintain --policy protected-retention.json")
	}
	info, err := os.Lstat(args[1])
	if err != nil || !info.Mode().IsRegular() || info.Size() > 32768 {
		return errors.New("private bounded policy file required")
	}
	if runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0 {
		return errors.New("retention policy must have owner-only permissions")
	}
	b, err := os.ReadFile(args[1])
	if err != nil {
		return err
	}
	var policy retentionPolicy
	decoder := json.NewDecoder(bytes.NewReader(b))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&policy); err != nil || decoder.Decode(new(any)) != io.EOF {
		return errors.New("invalid retention policy")
	}
	if !policy.Enabled {
		fmt.Println("lifecycle maintenance disabled by operator policy")
		return nil
	}
	if !canonicalUUID.MatchString(policy.CaseRef) || len(policy.Workspaces) > 128 {
		return errors.New("policy requires a case UUID and at most 128 workspaces")
	}
	seen := map[string]bool{}
	for _, w := range policy.Workspaces {
		if !canonicalUUID.MatchString(w.ID) || w.DeletedDays < 1 || w.DeletedDays > 365000 || seen[w.ID] {
			return errors.New("each workspace requires a unique UUID and explicit positive deleted-content duration")
		}
		seen[w.ID] = true
	}
	apply := func(a lifecycle.Action) error {
		file, err := os.CreateTemp("", "sierx-lifecycle-maintenance-*.json")
		if err != nil {
			return err
		}
		name := file.Name()
		defer os.Remove(name)
		b, _ := json.Marshal(a)
		_, err = file.Write(b)
		ce := file.Close()
		if err != nil {
			return err
		}
		if ce != nil {
			return ce
		}
		return runLifecycle(ctx, []string{"apply", "--file", name})
	}
	failures := 0
	for _, w := range policy.Workspaces {
		cutoff := time.Now().UTC().AddDate(0, 0, -w.DeletedDays).Format(time.RFC3339)
		if err = apply(lifecycle.Action{Kind: "retention", CaseRef: policy.CaseRef, WorkspaceID: w.ID, Cutoff: cutoff}); err != nil {
			failures++
		}
	}
	if err = apply(lifecycle.Action{Kind: "cleanup", CaseRef: policy.CaseRef}); err != nil {
		failures++
	}
	if failures > 0 {
		return fmt.Errorf("%d lifecycle maintenance operation(s) refused; review holds and restricted audit", failures)
	}
	return nil
}
