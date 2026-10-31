package api

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

type logIdentityKey struct{}
type logIdentity struct{ actor, workspace any }

func (s *Server) requestLog(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		s.inflight.Add(1)
		identity := &logIdentity{}
		r = r.WithContext(context.WithValue(r.Context(), logIdentityKey{}, identity))
		ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
		defer func() {
			s.inflight.Add(-1)
			s.requests.Add(1)
			s.durationNS.Add(uint64(time.Since(start)))
			if recover() != nil {
				if ww.Status() == 0 {
					WriteProblem(ww, InternalError())
				}
			}
			route := chi.RouteContext(r.Context()).RoutePattern()
			if route == "" {
				route = "unmatched"
			}
			status := ww.Status()
			if status == 0 {
				status = http.StatusOK
			}
			s.Logger.Info("request", "method", r.Method, "route", route, "status", status, "duration_ms", time.Since(start).Milliseconds(), "actor", identity.actor, "workspace", identity.workspace)
		}()
		if s.CheckLifecycle != nil {
			timeout := s.LifecycleCheckTimeout
			if timeout <= 0 {
				timeout = time.Second
			}
			ctx, cancel := context.WithTimeout(r.Context(), timeout)
			verificationStart := time.Now()
			err := s.CheckLifecycle(ctx)
			contextError := ctx.Err()
			if err == nil {
				err = contextError
			}
			cancel()
			if err != nil {
				reason := "verification-unavailable"
				if contextError == context.DeadlineExceeded {
					reason = "deadline-exceeded"
				} else if contextError == context.Canceled {
					reason = "request-canceled"
				}
				stage := "unknown"
				var staged interface{ VerificationStage() string }
				if errors.As(err, &staged) {
					switch value := staged.VerificationStage(); value {
					case "checkpoint", "database", "comparison":
						stage = value
					}
				}
				fields := []any{"reason", reason, "stage", stage,
					"verification_ms", time.Since(verificationStart).Milliseconds(), "verification_timeout_ms", timeout.Milliseconds()}
				if s.rawPool != nil {
					stats := s.rawPool.Stat()
					fields = append(fields, "pool_acquired", stats.AcquiredConns(), "pool_total", stats.TotalConns(), "pool_max", stats.MaxConns())
				}
				s.Logger.Warn("lifecycle verification rejected request", fields...)
				http.Error(ww, "Service unavailable pending operator recovery verification.", http.StatusServiceUnavailable)
				return
			}
		}
		next.ServeHTTP(ww, r)
	})
}
