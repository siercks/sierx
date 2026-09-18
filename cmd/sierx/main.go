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
	pool, err := pgxpool.New(ctx, c.DatabaseURL)
	if err != nil {
		logger.Error("database pool could not be created; check DATABASE_URL")
		os.Exit(1)
	}
	defer pool.Close()
	listener, err := net.Listen("tcp", c.ListenAddr)
	if err != nil {
		logger.Error("server could not listen; check SIERX_LISTEN_ADDR")
		os.Exit(1)
	}
	logger.Info("server ready")
	server := api.New(pool, logger)
	server.ConfigureAuth(c)
	if err := server.Serve(ctx, listener); err != nil {
		logger.Error("server stopped with an error")
		os.Exit(1)
	}
	logger.Info("server stopped")
}
