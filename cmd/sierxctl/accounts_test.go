package main

import (
	"context"
	"strings"
	"testing"
)

func TestAccountLifecycleRequiresKnownActionAndCase(t *testing.T) {
	t.Setenv("SIERX_MAINTENANCE_DATABASE_URL", "")
	for _, args := range [][]string{
		{}, {"delete"}, {"suspend", "--user", "not-a-uuid", "--case", "00000000-0000-7000-8000-000000000001"},
		{"reactivate", "--user", "00000000-0000-7000-8000-000000000001", "--case", "not-a-uuid"},
		{"suspend", "--user", "00000000-0000-7000-8000-000000000001"},
	} {
		if err := runAccountLifecycle(context.Background(), args); err == nil {
			t.Fatalf("runAccountLifecycle(%q) succeeded without a valid action and case", args)
		}
	}
}

func TestAccountLifecycleNeedsMaintenanceDSN(t *testing.T) {
	t.Setenv("SIERX_MAINTENANCE_DATABASE_URL", "")
	err := runAccountLifecycle(context.Background(), []string{
		"suspend", "--user", "00000000-0000-7000-8000-000000000001", "--case", "00000000-0000-7000-8000-000000000002",
	})
	if err == nil || !strings.Contains(err.Error(), "SIERX_MAINTENANCE_DATABASE_URL is unset") {
		t.Fatalf("expected maintenance DSN error, got %v", err)
	}
}
