package api

import (
	"context"
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
		next.ServeHTTP(ww, r)
	})
}
