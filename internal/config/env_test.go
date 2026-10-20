package config

import (
	"strings"
	"testing"
	"time"
)

func TestLifecycleCheckTimeoutIsBoundedAndDefaultsToOneSecond(t *testing.T) {
	for _, raw := range []string{"", "1s", "1.5s", "10s"} {
		values := validEnvironment("")
		values["SIERX_LIFECYCLE_CHECK_TIMEOUT"] = raw
		cfg, err := Load(func(key string) string { return values[key] })
		if err != nil {
			t.Fatal(err)
		}
		want := time.Second
		if raw != "" {
			want, _ = time.ParseDuration(raw)
		}
		if cfg.LifecycleCheckTimeout != want {
			t.Fatal("verification deadline differs from bounded configuration")
		}
	}
	for _, raw := range []string{"0s", "999ms", "10.001s", "-1s", "1m", "private-invalid-value"} {
		values := validEnvironment("")
		values["SIERX_LIFECYCLE_CHECK_TIMEOUT"] = raw
		_, err := Load(func(key string) string { return values[key] })
		if err == nil || !strings.Contains(err.Error(), "SIERX_LIFECYCLE_CHECK_TIMEOUT") || strings.Contains(err.Error(), "private-invalid-value") {
			t.Fatal("unbounded or privately reflected verification configuration")
		}
	}
}

func validEnvironment(registrationMode string) map[string]string {
	return map[string]string{
		"SIERX_RUNTIME_DATABASE_URL": "postgres://sierx_runtime:runtime-secret@localhost/sierx",
		"SIERX_AUTH_DATABASE_URL":    "postgres://sierx_auth:auth-secret@localhost/sierx",
		"SIERX_AUTH_MODE":            "local",
		"SIERX_BASE_URL":             "https://sierx.example.test",
		"SIERX_SESSION_KEY":          strings.Repeat("k", 32),
		"SIERX_REGISTRATION_MODE":    registrationMode,
	}
}

func TestRegistrationModeDefaultsToPrivate(t *testing.T) {
	values := validEnvironment("")
	cfg, err := Load(func(key string) string { return values[key] })
	if err != nil {
		t.Fatal(err)
	}
	if cfg.RegistrationMode != "private" {
		t.Fatalf("default registration mode = %q, want private", cfg.RegistrationMode)
	}
}

func TestRegistrationModesFailClosedUntilAdmissionIsImplemented(t *testing.T) {
	for _, mode := range []string{"invitation", "public"} {
		t.Run(mode, func(t *testing.T) {
			values := validEnvironment(mode)
			_, err := Load(func(key string) string { return values[key] })
			if err == nil || !strings.Contains(err.Error(), "account admission routes and required safeguards are not implemented") {
				t.Fatalf("mode %q should fail closed, got %v", mode, err)
			}
		})
	}
}

func TestRegistrationModeRejectsUnknownValues(t *testing.T) {
	values := validEnvironment("open")
	_, err := Load(func(key string) string { return values[key] })
	if err == nil || !strings.Contains(err.Error(), "must be private, invitation, or public") {
		t.Fatalf("unknown mode should be rejected, got %v", err)
	}
}
