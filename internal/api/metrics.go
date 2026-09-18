package api

import (
	"fmt"
	"net/http"
)

// Metrics are process-wide and intentionally have no identity or URL labels.
// Admin authorization prevents disclosure across ordinary workspace members.
func (s *Server) metrics(w http.ResponseWriter, r *http.Request) {
	if Identity(r).Role != "admin" {
		WriteProblem(w, Forbidden())
		return
	}
	if !rejectFields(w, r) {
		return
	}
	w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	metric := func(name, kind, help string, value any) {
		_, _ = fmt.Fprintf(w, "# HELP %s %s\n# TYPE %s %s\n%s %v\n", name, help, name, kind, name, value)
	}
	metric("sierx_http_requests_total", "counter", "Completed HTTP requests including failed requests.", s.requests.Load())
	metric("sierx_http_requests_in_flight", "gauge", "HTTP requests currently being handled including this scrape.", s.inflight.Load())
	metric("sierx_http_request_duration_seconds_total", "counter", "Total elapsed time of completed HTTP requests in seconds.", float64(s.durationNS.Load())/1e9)
	stats := s.Pool.Stat()
	metric("sierx_database_connections", "gauge", "Total connections in the application database pool.", stats.TotalConns())
	metric("sierx_database_connections_acquired", "gauge", "Connections currently acquired from the application database pool.", stats.AcquiredConns())
}
