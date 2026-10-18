package main

import (
	"context"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"syscall"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/siercks/sierx/internal/api"
	"github.com/siercks/sierx/internal/config"
	"github.com/siercks/sierx/internal/lifecycle"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	c, err := config.Load(os.Getenv)
	if err != nil {
		logger.Error("configuration rejected", "error", err.Error())
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	pool, err := pgxpool.New(ctx, c.RuntimeDatabaseURL)
	if err != nil {
		logger.Error("runtime database pool could not be created; check SIERX_RUNTIME_DATABASE_URL")
		os.Exit(1)
	}
	defer pool.Close()
	authPool, err := pgxpool.New(ctx, c.AuthDatabaseURL)
	if err != nil {
		logger.Error("authentication database pool could not be created; check SIERX_AUTH_DATABASE_URL")
		os.Exit(1)
	}
	defer authPool.Close()
	guard, err := lifecycle.NewGuard(pool)
	if err != nil {
		logger.Error("lifecycle recovery configuration is required")
		os.Exit(1)
	}
	if err = guard.Check(ctx); err != nil {
		logger.Error("lifecycle recovery verification failed; reconcile before serving")
		os.Exit(1)
	}
	listener, err := net.Listen("tcp", c.ListenAddr)
	if err != nil {
		logger.Error("server could not listen; check SIERX_LISTEN_ADDR")
		os.Exit(1)
	}
	logger.Info("server ready")
	server := api.NewWithAuthPool(pool, authPool, logger)
	server.CheckLifecycle = guard.Check
	server.ConfigureAuth(c)
	server.ConfigureDocuments()
	if err := server.Serve(ctx, listener); err != nil {
		logger.Error("server stopped with an error")
		os.Exit(1)
	}
	logger.Info("server stopped")
}
