package auth

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/netip"
	"strings"

	"github.com/jackc/pgx/v5"
)

// Proxy trusts only the immediate peer. Forwarded headers cannot establish trust.
// Accounts must already exist and have no local password; headers never create users.
func (s *Service) Proxy(ctx context.Context, r *http.Request, trusted []netip.Prefix) (Identity, error) {
	var who Identity
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return who, ErrCredentials
	}
	addr, err := netip.ParseAddr(host)
	if err != nil {
		return who, ErrCredentials
	}
	addr = addr.Unmap()
	allowed := false
	for _, prefix := range trusted {
		if prefix.Contains(addr) {
			allowed = true
			break
		}
	}
	if !allowed {
		return who, ErrCredentials
	}
	values := r.Header.Values("X-Sierx-Email")
	if len(values) != 1 || strings.TrimSpace(values[0]) == "" || strings.ContainsAny(values[0], ",\r\n") || len(values[0]) > 320 {
		return who, ErrCredentials
	}
	err = s.Pool.QueryRow(ctx, `SELECT u.id::text,u.email::text,u.display_name,m.workspace_id::text,m.role,u.theme,u.reduced_motion FROM user_account u JOIN membership m ON m.user_id=u.id WHERE u.email=$1 AND u.is_active AND u.password_hash IS NULL`, strings.TrimSpace(values[0])).Scan(&who.ID, &who.Email, &who.DisplayName, &who.WorkspaceID, &who.Role, &who.Theme, &who.ReducedMotion)
	if errors.Is(err, pgx.ErrNoRows) {
		err = ErrCredentials
	}
	return who, err
}
