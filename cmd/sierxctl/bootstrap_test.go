package main

import (
	"context"
	"strings"
	"testing"
)

func TestBootstrapExplainsInvalidPasswordBeforeConnecting(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://sierx:sierx@127.0.0.1:1/unreachable")
	t.Setenv("SIERX_AUTH_MODE", "local")
	t.Setenv("SIERX_BOOTSTRAP_ADMIN_PASSWORD", "too-short")

	err := runBootstrap(context.Background(), nil)
	if err == nil || !strings.Contains(err.Error(), "SIERX_BOOTSTRAP_ADMIN_PASSWORD is invalid: password must contain 12 to 1024 bytes") {
		t.Fatalf("unexpected error: %v", err)
	}
}
