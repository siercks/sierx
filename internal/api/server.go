package api

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Server struct {
	auth   *authState
	Pool   *pgxpool.Pool
	Router *chi.Mux
	Logger *slog.Logger
}

func New(pool *pgxpool.Pool, logger *slog.Logger) *Server {
	s := &Server{Pool: pool, Router: chi.NewRouter(), Logger: logger}
	s.Router.Use(s.requestLog)
	s.Router.Use(compression)
	s.Router.NotFound(func(w http.ResponseWriter, r *http.Request) { WriteProblem(w, NotFound()) })
	s.Router.MethodNotAllowed(func(w http.ResponseWriter, r *http.Request) { WriteProblem(w, MethodNotAllowed()) })
	s.Router.Get("/api/v1/healthz", s.health)
	return s
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), time.Second)
	defer cancel()
	state, status := "reachable", http.StatusOK
	if err := s.Pool.Ping(ctx); err != nil {
		state, status = "unavailable", http.StatusServiceUnavailable
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"alive": true, "database": state})
}

// Serve drains active requests on cancellation and bounds both client reads and shutdown.
func (s *Server) Serve(ctx context.Context, listener net.Listener) error {
	h := &http.Server{Handler: s.Router, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32 << 10}
	done := make(chan error, 1)
	go func() { done <- h.Serve(listener) }()
	select {
	case err := <-done:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := h.Shutdown(shutdown); err != nil {
			_ = h.Close()
			<-done
			return err
		}
		err := <-done
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	}
}
