package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestRestoreRotationExternalState(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "operator-state")
	t.Setenv("SIERX_RESTORE_STATE_DIR", dir)
	if got := readRotation(); got != 0 {
		t.Fatalf("new state started at %d", got)
	}
	writeRotation(3)
	if got := readRotation(); got != 3 {
		t.Fatalf("rotation did not survive write: %d", got)
	}
	if _, err := os.Stat(filepath.Join(dir, "restore-test-rotation")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SIERX_RESTORE_STATE_DIR", "")
	if rotationPath() != filepath.Join(".backups", "restore-test-rotation") {
		t.Fatal("connected default changed")
	}
}
