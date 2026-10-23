package api

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

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
