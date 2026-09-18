package api

import (
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

func (s *Server) requestLog(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
		defer func() {
			if recover() != nil {
				http.Error(ww, "Request failed; try again.", http.StatusInternalServerError)
			}
			route := chi.RouteContext(r.Context()).RoutePattern()
			if route == "" {
				route = "unmatched"
			}
			status := ww.Status()
			if status == 0 {
				status = http.StatusOK
			}
			s.Logger.Info("request", "method", r.Method, "route", route, "status", status, "duration_ms", time.Since(start).Milliseconds(), "actor", nil, "workspace", nil)
		}()
		next.ServeHTTP(ww, r)
	})
}
