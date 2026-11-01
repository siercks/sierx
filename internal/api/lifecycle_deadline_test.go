package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type fixtureVerificationFailure string

func (e fixtureVerificationFailure) Error() string             { return "private verification cause" }
func (e fixtureVerificationFailure) VerificationStage() string { return string(e) }

func TestLifecycleRejectionDiagnosticsContainOnlyFixedStageAndTiming(t *testing.T) {
	for _, stage := range []string{"checkpoint", "database", "comparison", "private-invalid-stage"} {
		t.Run(stage, func(t *testing.T) {
			var logs bytes.Buffer
			server := New(nil, slog.New(slog.NewJSONHandler(&logs, nil)))
			server.CheckLifecycle = func(context.Context) error { return fixtureVerificationFailure(stage) }
			response := httptest.NewRecorder()
			server.Router.ServeHTTP(response, httptest.NewRequest("POST", "/must-not-run", nil))
			if response.Code != http.StatusServiceUnavailable || strings.Contains(logs.String(), "private") {
				t.Fatal("unverified request passed or private failure details were logged")
			}
			var record map[string]any
			if err := json.Unmarshal(bytes.Split(logs.Bytes(), []byte("\n"))[0], &record); err != nil {
				t.Fatal(err)
			}
			expected := stage
			if stage == "private-invalid-stage" {
				expected = "unknown"
			}
			if record["stage"] != expected || record["verification_timeout_ms"] != float64(1000) {
				t.Fatal("fixed diagnostic stage or actual verification budget missing")
			}
			if elapsed, ok := record["verification_ms"].(float64); !ok || elapsed < 0 {
				t.Fatal("bounded verification elapsed time missing")
			}
		})
	}
}

func TestLifecycleVerificationDeadlineNeverAllowsAnUnverifiedHandler(t *testing.T) {
	for _, mode := range []string{"mismatch", "timeout", "late-success", "canceled", "verified"} {
		t.Run(mode, func(t *testing.T) {
			var logs bytes.Buffer
			server := New(nil, slog.New(slog.NewJSONHandler(&logs, nil)))
			if server.LifecycleCheckTimeout != time.Second {
				t.Fatal("native default changed")
			}
			server.LifecycleCheckTimeout = 10 * time.Millisecond
			checked, handled := false, false
			server.CheckLifecycle = func(ctx context.Context) error {
				checked = true
				deadline, ok := ctx.Deadline()
				if !ok || time.Until(deadline) > 20*time.Millisecond {
					t.Fatal("verification context is not bounded")
				}
				switch mode {
				case "mismatch":
					return errors.New("private verification cause")
				case "timeout", "late-success":
					<-ctx.Done()
					if mode == "late-success" {
						return nil
					}
					return ctx.Err()
				case "canceled":
					return ctx.Err()
				}
				return nil
			}
			server.Router.Post("/checked", func(w http.ResponseWriter, r *http.Request) {
				if !checked {
					t.Fatal("handler ran before verification")
				}
				handled = true
				w.WriteHeader(http.StatusOK)
			})
			request := httptest.NewRequest("POST", "/checked", nil)
			if mode == "canceled" {
				ctx, cancel := context.WithCancel(request.Context())
				cancel()
				request = request.WithContext(ctx)
			}
			response := httptest.NewRecorder()
			server.Router.ServeHTTP(response, request)
			if strings.Contains(logs.String(), "private verification cause") {
				t.Fatal("private verification cause was logged")
			}
			if mode != "verified" && !strings.Contains(logs.String(), "lifecycle verification rejected request") {
				t.Fatal("bounded rejection diagnostic is missing")
			}
			if mode == "verified" {
				if response.Code != http.StatusOK || !handled {
					t.Fatal("verified handler did not run")
				}
			} else if response.Code != http.StatusServiceUnavailable || handled || response.Body.String() != "Service unavailable pending operator recovery verification.\n" {
				t.Fatal("failed verification was bypassed or private cause was exposed")
			}
		})
	}
}
