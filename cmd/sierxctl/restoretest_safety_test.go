package main

import "testing"

func TestRestoreTargetCannotRecreateSource(t *testing.T) {
	for _, tc := range []struct{ dsn, scratch string }{
		{"postgres://fixture@localhost/live", "live"},
		{"postgres://fixture@localhost/live", "postgres"},
		{"postgres://fixture@localhost/live", "template1"},
		{"postgres://fixture@localhost/sierx_restore_test", "sierx_restore_test"},
		{"postgres://fixture@localhost/sierx%5Frestore_test", "sierx_restore_test"},
		{"postgres://fixture@localhost/live?dbname=sierx_restore_test", "sierx_restore_test"},
		{"dbname=live", "sierx_restore_test"},
		{"postgres://fixture@localhost/", "sierx_restore_test"},
	} {
		if validateRestoreTarget(tc.dsn, tc.scratch) == nil {
			t.Errorf("accepted unsafe target %q", tc.scratch)
		}
	}
	if err := validateRestoreTarget("postgres://fixture@localhost/live?sslmode=disable", "sierx_restore_test"); err != nil {
		t.Fatal(err)
	}
}
