package api

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/siercks/sierx/internal/config"
)

func TestServerBoot(t *testing.T) {
	t.Run("configuration", func(t *testing.T) {
		valid := map[string]string{"DATABASE_URL": "postgres://test:test@localhost/test", "SIERX_AUTH_MODE": "local", "SIERX_BASE_URL": "http://localhost:8080", "SIERX_SESSION_KEY": strings.Repeat("s", 32)}
		for key := range valid {
			t.Run("missing_"+key, func(t *testing.T) {
				_, err := config.Load(func(k string) string {
					if k == key {
						return ""
					}
					return valid[k]
				})
				if err == nil || !strings.Contains(err.Error(), key) {
					t.Fatalf("expected named error, got %v", err)
				}
			})
		}
		for key, value := range map[string]string{"DATABASE_URL": "postgres://secret:secret@bad/%zz", "SIERX_AUTH_MODE": "guess", "SIERX_BASE_URL": "ftp://localhost", "SIERX_SESSION_KEY": "secret", "SIERX_LISTEN_ADDR": "localhost:99999"} {
			t.Run("malformed_"+key, func(t *testing.T) {
				_, err := config.Load(func(k string) string {
					if k == key {
						return value
					}
					return valid[k]
				})
				if err == nil || !strings.Contains(err.Error(), key) || strings.Contains(err.Error(), "secret") && key != "SIERX_SESSION_KEY" {
					t.Fatalf("unsafe/missing error: %v", err)
				}
			})
		}
		if _, err := config.Load(func(k string) string { return valid[k] }); err != nil {
			t.Fatal(err)
		}
		valid["SIERX_AUTH_MODE"] = "proxy"
		if _, err := config.Load(func(k string) string { return valid[k] }); err == nil {
			t.Fatal("proxy without allowlist accepted")
		}
		valid["SIERX_TRUSTED_PROXIES"] = "127.0.0.1/32,::1/128"
		if _, err := config.Load(func(k string) string { return valid[k] }); err != nil {
			t.Fatal(err)
		}
		valid["SIERX_TRUSTED_PROXIES"] = "invalid"
		if _, err := config.Load(func(k string) string { return valid[k] }); err == nil {
			t.Fatal("invalid CIDR accepted")
		}
	})
	db := os.Getenv("DATABASE_URL")
	if db == "" {
		t.Fatal("DATABASE_URL is required; use make test-api")
	}
	pool, err := pgxpool.New(context.Background(), db)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err := pool.Ping(context.Background()); err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	s := New(pool, slog.New(slog.NewJSONHandler(&logs, nil)))
	t.Run("reachable", func(t *testing.T) {
		w := httptest.NewRecorder()
		s.Router.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/healthz?secret=never-log-this", nil))
		if w.Code != 200 || w.Body.String() != "{\"alive\":true,\"database\":\"reachable\"}\n" {
			t.Fatalf("%d %s", w.Code, w.Body)
		}
		var entry map[string]any
		if err := json.Unmarshal(logs.Bytes(), &entry); err != nil {
			t.Fatal(err)
		}
		for _, key := range []string{"method", "route", "status", "duration_ms", "actor", "workspace"} {
			if _, ok := entry[key]; !ok {
				t.Errorf("missing %s", key)
			}
		}
		if strings.Contains(logs.String(), "secret") {
			t.Fatal("query leaked")
		}
	})
	t.Run("unavailable", func(t *testing.T) {
		// A listener that accepts TCP but never completes PostgreSQL startup proves timeout handling.
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		defer ln.Close()
		go func() {
			c, err := ln.Accept()
			if err == nil {
				defer c.Close()
				_, _ = io.Copy(io.Discard, c)
			}
		}()
		p, err := pgxpool.New(context.Background(), "postgres://test:test@"+ln.Addr().String()+"/test?sslmode=disable")
		if err != nil {
			t.Fatal(err)
		}
		defer p.Close()
		w := httptest.NewRecorder()
		New(p, slog.New(slog.NewTextHandler(io.Discard, nil))).Router.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/healthz", nil))
		if w.Code != 503 || w.Body.String() != "{\"alive\":true,\"database\":\"unavailable\"}\n" {
			t.Fatalf("%d %s", w.Code, w.Body)
		}
	})
	t.Run("startup_shutdown", func(t *testing.T) {
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		done := make(chan error, 1)
		go func() { done <- New(pool, slog.New(slog.NewTextHandler(io.Discard, nil))).Serve(ctx, ln) }()
		client := &http.Client{Timeout: time.Second}
		start := time.Now()
		resp, err := client.Get("http://" + ln.Addr().String() + "/api/v1/healthz")
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != 200 || time.Since(start) >= time.Second {
			t.Fatal("startup acceptance failed")
		}
		cancel()
		select {
		case err := <-done:
			if err != nil {
				t.Fatal(err)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("shutdown hung")
		}
	})
}
