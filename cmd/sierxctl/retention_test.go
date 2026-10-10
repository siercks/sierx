package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestMaintenanceRequiresExplicitValidPolicy(t *testing.T) {
	for _, raw := range []string{
		`{"enabled":false}`, // Disabled policy has no connection or content side effects.
		`{"enabled":true,"case_ref":"invalid"}`,
		`{"enabled":true,"case_ref":"00000000-0000-4000-8000-000000000001","workspaces":[{"workspace_id":"00000000-0000-4000-8000-000000000002","deleted_content_days":0}]}`,
		`{"enabled":true,"case_ref":"00000000-0000-4000-8000-000000000001","workspaces":[{"workspace_id":"00000000-0000-4000-8000-000000000002","deleted_content_days":-1}]}`,
		`{"enabled":false,"unknown":true}`,
		`{"enabled":false} {}`,
	} {
		t.Run(raw, func(t *testing.T) {
			t.Setenv("SIERX_MAINTENANCE_DATABASE_URL", "")
			p := filepath.Join(t.TempDir(), "policy.json")
			if err := os.WriteFile(p, []byte(raw), 0600); err != nil {
				t.Fatal(err)
			}
			err := runLifecycleMaintenance(context.Background(), []string{"--policy", p})
			if (err == nil) != (raw == `{"enabled":false}`) {
				t.Fatalf("unexpected policy result: %v", err)
			}
		})
	}
	for _, args := range [][]string{nil, {"--policy"}, {"--policy", "missing", "extra"}} {
		if runLifecycleMaintenance(context.Background(), args) == nil {
			t.Fatal("invalid arguments accepted")
		}
	}
}
