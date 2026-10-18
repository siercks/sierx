package main

import (
	"context"
	"strings"
	"testing"
)

func TestDataExportValidatesSubcommandAndCase(t *testing.T) {
	t.Setenv("SIERX_MAINTENANCE_DATABASE_URL", "")
	for _, args := range [][]string{
		{}, {"delete"}, {"create", "--user", "not-a-uuid", "--case", "00000000-0000-7000-8000-000000000001"},
		{"create", "--user", "00000000-0000-7000-8000-000000000001"},
		{"download", "--id", "00000000-0000-7000-8000-000000000001", "--case", "not-a-uuid", "--out", "export.json"},
	} {
		if err := runDataExport(context.Background(), args); err == nil {
			t.Fatalf("runDataExport(%q) succeeded without valid arguments", args)
		}
	}
}

func TestDataExportNeedsMaintenanceDSN(t *testing.T) {
	t.Setenv("SIERX_MAINTENANCE_DATABASE_URL", "")
	err := runDataExport(context.Background(), []string{
		"create", "--user", "00000000-0000-0000-0000-000000000001", "--case", "00000000-0000-0000-0000-000000000002",
	})
	if err == nil || !strings.Contains(err.Error(), "SIERX_MAINTENANCE_DATABASE_URL is unset") {
		t.Fatalf("expected maintenance DSN error, got %v", err)
	}
}
