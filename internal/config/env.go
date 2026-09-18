// Package config validates process configuration without exposing secrets.
package config

import (
	"fmt"
	"net"
	"net/netip"
	"net/url"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Env struct {
	DatabaseURL    string
	AuthMode       string
	TrustedProxies []netip.Prefix
	BaseURL        string
	SessionKey     string
	ListenAddr     string
}

func Load(get func(string) string) (Env, error) {
	c := Env{DatabaseURL: get("DATABASE_URL"), AuthMode: get("SIERX_AUTH_MODE"), BaseURL: get("SIERX_BASE_URL"), SessionKey: get("SIERX_SESSION_KEY"), ListenAddr: get("SIERX_LISTEN_ADDR")}
	for _, pair := range [][2]string{{"DATABASE_URL", c.DatabaseURL}, {"SIERX_AUTH_MODE", c.AuthMode}, {"SIERX_BASE_URL", c.BaseURL}, {"SIERX_SESSION_KEY", c.SessionKey}} {
		if strings.TrimSpace(pair[1]) == "" {
			return Env{}, fmt.Errorf("%s is required; set the environment variable", pair[0])
		}
	}
	u, err := url.Parse(c.DatabaseURL)
	if err != nil || u == nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") || u.Hostname() == "" {
		return Env{}, fmt.Errorf("DATABASE_URL must be a PostgreSQL URL")
	}
	if _, err := pgxpool.ParseConfig(c.DatabaseURL); err != nil {
		return Env{}, fmt.Errorf("DATABASE_URL is malformed; check its connection settings")
	}
	if c.AuthMode != "local" && c.AuthMode != "proxy" {
		return Env{}, fmt.Errorf("SIERX_AUTH_MODE must be local or proxy")
	}
	u, err = url.Parse(c.BaseURL)
	if err != nil || u == nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return Env{}, fmt.Errorf("SIERX_BASE_URL must be an HTTP or HTTPS origin")
	}
	if len(c.SessionKey) < 32 {
		return Env{}, fmt.Errorf("SIERX_SESSION_KEY must contain at least 32 bytes; generate a random secret")
	}
	if c.AuthMode == "proxy" {
		if strings.TrimSpace(get("SIERX_TRUSTED_PROXIES")) == "" {
			return Env{}, fmt.Errorf("SIERX_TRUSTED_PROXIES is required in proxy mode")
		}
		for _, raw := range strings.Split(get("SIERX_TRUSTED_PROXIES"), ",") {
			p, err := netip.ParsePrefix(strings.TrimSpace(raw))
			if err != nil {
				return Env{}, fmt.Errorf("SIERX_TRUSTED_PROXIES must be comma-separated CIDRs")
			}
			c.TrustedProxies = append(c.TrustedProxies, p.Masked())
		}
	}
	if c.ListenAddr == "" {
		c.ListenAddr = ":8080"
	}
	if _, port, err := net.SplitHostPort(c.ListenAddr); err != nil || port == "" {
		return Env{}, fmt.Errorf("SIERX_LISTEN_ADDR must be host:port")
	}
	if _, err := net.ResolveTCPAddr("tcp", c.ListenAddr); err != nil {
		return Env{}, fmt.Errorf("SIERX_LISTEN_ADDR is invalid")
	}
	return c, nil
}
