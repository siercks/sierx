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
	RuntimeDatabaseURL string
	AuthDatabaseURL         string
	AuthMode                string
	RegistrationMode        string
	TrustedProxies          []netip.Prefix
	BaseURL                 string
	SessionKey              string
	ListenAddr              string
	OperatorName            string
	PrivacyContact          string
	PrivacyRetention        string
	PrivacyBackups          string
	PrivacyServices         string
	PrivacyVersion          string
	PrivacyEffectiveDate    string
	CopyrightAgent          string
	CopyrightContact        string
	CopyrightNotice         string
	CopyrightCounterNotice  string
	RepeatInfringerPolicy   string
}

func Load(get func(string) string) (Env, error) {
	c := Env{RuntimeDatabaseURL: get("SIERX_RUNTIME_DATABASE_URL"), AuthDatabaseURL: get("SIERX_AUTH_DATABASE_URL"), AuthMode: get("SIERX_AUTH_MODE"), RegistrationMode: strings.TrimSpace(get("SIERX_REGISTRATION_MODE")), BaseURL: get("SIERX_BASE_URL"), SessionKey: get("SIERX_SESSION_KEY"), ListenAddr: get("SIERX_LISTEN_ADDR"),
		OperatorName: get("SIERX_OPERATOR_NAME"), PrivacyContact: get("SIERX_PRIVACY_CONTACT"), PrivacyRetention: get("SIERX_PRIVACY_RETENTION"), PrivacyBackups: get("SIERX_PRIVACY_BACKUPS"), PrivacyServices: get("SIERX_PRIVACY_SERVICES"), PrivacyVersion: get("SIERX_PRIVACY_VERSION"), PrivacyEffectiveDate: get("SIERX_PRIVACY_EFFECTIVE_DATE"),
		CopyrightAgent: get("SIERX_COPYRIGHT_AGENT"), CopyrightContact: get("SIERX_COPYRIGHT_CONTACT"), CopyrightNotice: get("SIERX_COPYRIGHT_NOTICE_PROCESS"), CopyrightCounterNotice: get("SIERX_COPYRIGHT_COUNTER_NOTICE_PROCESS"), RepeatInfringerPolicy: get("SIERX_REPEAT_INFRINGER_POLICY")}
	if c.RegistrationMode == "" {
		c.RegistrationMode = "private"
	}
	if c.RegistrationMode != "private" && c.RegistrationMode != "invitation" && c.RegistrationMode != "public" {
		return Env{}, fmt.Errorf("SIERX_REGISTRATION_MODE must be private, invitation, or public")
	}
	if c.RegistrationMode != "private" {
		return Env{}, fmt.Errorf("SIERX_REGISTRATION_MODE=%s is not available: account admission routes and required safeguards are not implemented", c.RegistrationMode)
	}
	for _, pair := range [][2]string{{"SIERX_RUNTIME_DATABASE_URL", c.RuntimeDatabaseURL}, {"SIERX_AUTH_DATABASE_URL", c.AuthDatabaseURL}, {"SIERX_AUTH_MODE", c.AuthMode}, {"SIERX_BASE_URL", c.BaseURL}, {"SIERX_SESSION_KEY", c.SessionKey}} {
		if strings.TrimSpace(pair[1]) == "" {
			return Env{}, fmt.Errorf("%s is required; set the environment variable", pair[0])
		}
	}
	runtimeURL, err := url.Parse(c.RuntimeDatabaseURL)
	if err != nil || runtimeURL == nil || (runtimeURL.Scheme != "postgres" && runtimeURL.Scheme != "postgresql") || runtimeURL.Hostname() == "" || runtimeURL.Path == "" || runtimeURL.Path == "/" {
		return Env{}, fmt.Errorf("SIERX_RUNTIME_DATABASE_URL must be a PostgreSQL URL")
	}
	if _, err := pgxpool.ParseConfig(c.RuntimeDatabaseURL); err != nil {
		return Env{}, fmt.Errorf("SIERX_RUNTIME_DATABASE_URL is malformed; check its connection settings")
	}
	if _, err := pgxpool.ParseConfig(c.AuthDatabaseURL); err != nil {
		return Env{}, fmt.Errorf("SIERX_AUTH_DATABASE_URL is malformed; check its connection settings")
	}
	authURL, err := url.Parse(c.AuthDatabaseURL)
	if err != nil || authURL == nil || (authURL.Scheme != "postgres" && authURL.Scheme != "postgresql") || authURL.Hostname() == "" || authURL.Path == "" || authURL.Path == "/" {
		return Env{}, fmt.Errorf("SIERX_AUTH_DATABASE_URL must be a PostgreSQL URL")
	}
	if runtimeURL.User == nil || authURL.User == nil || runtimeURL.User.Username() != "sierx_runtime" || authURL.User.Username() != "sierx_auth" {
		return Env{}, fmt.Errorf("SIERX_RUNTIME_DATABASE_URL and SIERX_AUTH_DATABASE_URL must use the dedicated sierx_runtime and sierx_auth roles")
	}
	runtimePassword, runtimeHasPassword := runtimeURL.User.Password()
	authPassword, authHasPassword := authURL.User.Password()
	if !runtimeHasPassword || runtimePassword == "" || !authHasPassword || authPassword == "" {
		return Env{}, fmt.Errorf("SIERX_RUNTIME_DATABASE_URL and SIERX_AUTH_DATABASE_URL must include their dedicated role passwords")
	}
	runtimePort, authPort := runtimeURL.Port(), authURL.Port()
	if runtimePort == "" {
		runtimePort = "5432"
	}
	if authPort == "" {
		authPort = "5432"
	}
	if runtimeURL.Hostname() != authURL.Hostname() || runtimePort != authPort || runtimeURL.Path != authURL.Path {
		return Env{}, fmt.Errorf("SIERX_RUNTIME_DATABASE_URL and SIERX_AUTH_DATABASE_URL must target the same database")
	}
	if c.AuthMode != "local" && c.AuthMode != "proxy" {
		return Env{}, fmt.Errorf("SIERX_AUTH_MODE must be local or proxy")
	}
	baseURL, err := url.Parse(c.BaseURL)
	if err != nil || baseURL == nil || (baseURL.Scheme != "http" && baseURL.Scheme != "https") || baseURL.Hostname() == "" || baseURL.User != nil || baseURL.RawQuery != "" || baseURL.Fragment != "" || (baseURL.Path != "" && baseURL.Path != "/") {
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
