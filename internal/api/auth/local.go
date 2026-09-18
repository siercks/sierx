// Package auth handles credentials and sessions without HTTP response policy.
package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrCredentials = errors.New("invalid credentials")

const CookieName = "__Host-sierx_session"
const SessionLifetime = 12 * time.Hour

type Identity struct {
	ID            string `json:"id"`
	Email         string `json:"email"`
	DisplayName   string `json:"display_name"`
	WorkspaceID   string `json:"workspace_id"`
	Role          string `json:"role"`
	Theme         string `json:"theme"`
	ReducedMotion *bool  `json:"reduced_motion"`
}

type Service struct {
	Pool      *pgxpool.Pool
	dummyHash string
}

func New(pool *pgxpool.Pool) *Service {
	// Fixed non-user material; this only equalizes password work for unknown users.
	salt := base64.RawStdEncoding.EncodeToString(make([]byte, 16))
	return &Service{Pool: pool, dummyHash: "$argon2id$v=19$m=65536,t=3,p=1$" + salt + "$" + base64.RawStdEncoding.EncodeToString(make([]byte, 32))}
}

func (s *Service) Login(ctx context.Context, email, password string) (string, error) {
	var id string
	var hash *string
	var secret []byte
	err := s.Pool.QueryRow(ctx, `SELECT u.id::text,u.password_hash,u.totp_secret FROM user_account u JOIN membership m ON m.user_id=u.id WHERE u.email=$1 AND u.is_active`, email).Scan(&id, &hash, &secret)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", err
	}
	encoded := s.dummyHash
	if hash != nil {
		encoded = *hash
	}
	valid := VerifyPassword(encoded, password)
	if err != nil || hash == nil || !valid || len(secret) > 0 {
		return "", ErrCredentials
	}
	return s.CreateSession(ctx, id)
}

func (s *Service) CreateSession(ctx context.Context, id string) (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	token := base64.RawURLEncoding.EncodeToString(raw)
	hash := sha256.Sum256([]byte(token))
	result, err := s.Pool.Exec(ctx, `INSERT INTO session(id_hash,user_id,expires_at) SELECT $1,id,now()+interval '12 hours' FROM user_account WHERE id=$2 AND is_active`, hash[:], id)
	if err == nil && result.RowsAffected() != 1 {
		return "", ErrCredentials
	}
	return token, err
}

func (s *Service) Session(ctx context.Context, token string) (Identity, error) {
	var who Identity
	if len(token) != 43 {
		return who, ErrCredentials
	}
	hash := sha256.Sum256([]byte(token))
	err := s.Pool.QueryRow(ctx, `SELECT u.id::text,u.email::text,u.display_name,m.workspace_id::text,m.role,u.theme,u.reduced_motion FROM session s JOIN user_account u ON u.id=s.user_id JOIN membership m ON m.user_id=u.id WHERE s.id_hash=$1 AND s.expires_at>now() AND u.is_active`, hash[:]).Scan(&who.ID, &who.Email, &who.DisplayName, &who.WorkspaceID, &who.Role, &who.Theme, &who.ReducedMotion)
	if errors.Is(err, pgx.ErrNoRows) {
		err = ErrCredentials
	}
	return who, err
}

func (s *Service) Logout(ctx context.Context, token string) error {
	hash := sha256.Sum256([]byte(token))
	_, err := s.Pool.Exec(ctx, `DELETE FROM session WHERE id_hash=$1`, hash[:])
	return err
}
