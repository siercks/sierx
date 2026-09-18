package auth

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base32"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"
)

// The existing bytea column stores an authenticated encrypted state envelope.
// Binding its ciphertext to the user ID prevents swapping secrets between users.
type totpState struct {
	Secret       []byte   `json:"secret"`
	Active       bool     `json:"active"`
	LastStep     int64    `json:"last_step"`
	PendingUntil int64    `json:"pending_until"`
	Recovery     []string `json:"recovery"`
}

func (s *Service) seal(id string, state totpState) ([]byte, error) {
	block, err := aes.NewCipher(s.key[:])
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	nonce := make([]byte, aead.NonceSize())
	if _, err = rand.Read(nonce); err != nil {
		return nil, err
	}
	plain, err := json.Marshal(state)
	if err != nil {
		return nil, err
	}
	return aead.Seal(nonce, nonce, plain, []byte(id)), nil
}
func (s *Service) open(id string, raw []byte) (totpState, error) {
	var state totpState
	if len(raw) == 0 {
		return state, nil
	}
	block, err := aes.NewCipher(s.key[:])
	if err != nil {
		return state, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return state, err
	}
	if len(raw) < aead.NonceSize() {
		return state, ErrCredentials
	}
	plain, err := aead.Open(nil, raw[:aead.NonceSize()], raw[aead.NonceSize():], []byte(id))
	if err != nil {
		return state, err
	}
	err = json.Unmarshal(plain, &state)
	return state, err
}

// Code implements RFC 6238 with SHA-1, six digits and 30-second periods.
func Code(secret []byte, at time.Time) string {
	var counter [8]byte
	binary.BigEndian.PutUint64(counter[:], uint64(at.Unix()/30))
	mac := hmac.New(sha1.New, secret)
	_, _ = mac.Write(counter[:])
	sum := mac.Sum(nil)
	off := sum[len(sum)-1] & 15
	n := binary.BigEndian.Uint32(sum[off:off+4]) & 0x7fffffff
	return fmt.Sprintf("%06d", n%1000000)
}

func consumeCode(state *totpState, code string, now time.Time, allowRecovery bool) bool {
	if len(code) == 6 {
		step := now.Unix() / 30
		for _, offset := range []int64{0, -1, 1} {
			candidate := step + offset
			if candidate > state.LastStep && subtle.ConstantTimeCompare([]byte(code), []byte(Code(state.Secret, time.Unix(candidate*30, 0)))) == 1 {
				state.LastStep = candidate
				return true
			}
		}
	}
	if allowRecovery {
		sum := sha256.Sum256([]byte(code))
		encoded := hex.EncodeToString(sum[:])
		for i, want := range state.Recovery {
			if subtle.ConstantTimeCompare([]byte(encoded), []byte(want)) == 1 {
				state.Recovery = append(state.Recovery[:i], state.Recovery[i+1:]...)
				return true
			}
		}
	}
	return false
}

type Enrollment struct {
	Secret string `json:"secret"`
	URI    string `json:"otpauth_uri"`
}

func (s *Service) Enroll(ctx context.Context, id, password string) (Enrollment, error) {
	var result Enrollment
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return result, err
	}
	defer tx.Rollback(ctx)
	var hash *string
	var raw []byte
	var email string
	if err = tx.QueryRow(ctx, `SELECT password_hash,totp_secret,email::text FROM user_account WHERE id=$1 AND is_active FOR UPDATE`, id).Scan(&hash, &raw, &email); err != nil {
		return result, err
	}
	if hash == nil || !VerifyPassword(*hash, password) {
		return result, ErrCredentials
	}
	state, err := s.open(id, raw)
	if err != nil {
		return result, err
	}
	if state.Active {
		return result, ErrCredentials
	}
	state = totpState{Secret: make([]byte, 20), LastStep: -1, PendingUntil: time.Now().Add(10 * time.Minute).Unix()}
	if _, err = rand.Read(state.Secret); err != nil {
		return result, err
	}
	if err = s.saveTOTP(ctx, tx, id, state); err != nil {
		return result, err
	}
	if err = tx.Commit(ctx); err != nil {
		return result, err
	}
	result.Secret = base32.StdEncoding.WithPadding(base32.NoPadding).EncodeToString(state.Secret)
	q := url.Values{"secret": {result.Secret}, "issuer": {"sierx"}, "algorithm": {"SHA1"}, "digits": {"6"}, "period": {"30"}}
	result.URI = "otpauth://totp/" + url.PathEscape("sierx:"+email) + "?" + q.Encode()
	return result, nil
}

func (s *Service) saveTOTP(ctx context.Context, tx pgx.Tx, id string, state totpState) error {
	raw, err := s.seal(id, state)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `UPDATE user_account SET totp_secret=$1 WHERE id=$2`, raw, id)
	return err
}

func (s *Service) Confirm(ctx context.Context, id, code string) ([]string, error) {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	var raw []byte
	if err = tx.QueryRow(ctx, `SELECT totp_secret FROM user_account WHERE id=$1 AND is_active FOR UPDATE`, id).Scan(&raw); err != nil {
		return nil, err
	}
	state, err := s.open(id, raw)
	if err != nil {
		return nil, err
	}
	if len(state.Secret) != 20 || state.Active || state.PendingUntil < time.Now().Unix() || !consumeCode(&state, code, time.Now(), false) {
		return nil, ErrCredentials
	}
	state.Active = true
	state.PendingUntil = 0
	codes := make([]string, 8)
	for i := range codes {
		b := make([]byte, 16)
		if _, err = rand.Read(b); err != nil {
			return nil, err
		}
		codes[i] = hex.EncodeToString(b)
		sum := sha256.Sum256([]byte(codes[i]))
		state.Recovery = append(state.Recovery, hex.EncodeToString(sum[:]))
	}
	if err = s.saveTOTP(ctx, tx, id, state); err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM session WHERE user_id=$1`, id); err != nil {
		return nil, err
	}
	return codes, tx.Commit(ctx)
}

func (s *Service) checkSecondFactor(ctx context.Context, id, code string) (string, error) {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return "", err
	}
	defer tx.Rollback(ctx)
	var raw []byte
	if err = tx.QueryRow(ctx, `SELECT totp_secret FROM user_account WHERE id=$1 AND is_active FOR UPDATE`, id).Scan(&raw); err != nil {
		return "", err
	}
	state, err := s.open(id, raw)
	if err != nil {
		return "", err
	}
	if state.Active {
		if !consumeCode(&state, code, time.Now(), true) {
			return "", ErrCredentials
		}
		if err = s.saveTOTP(ctx, tx, id, state); err != nil {
			return "", err
		}
	}
	token, err := issueSession(ctx, tx, id)
	if err != nil {
		return "", err
	}
	return token, tx.Commit(ctx)
}

func (s *Service) Disable(ctx context.Context, id, password, code string) error {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var raw []byte
	var hash *string
	if err = tx.QueryRow(ctx, `SELECT totp_secret,password_hash FROM user_account WHERE id=$1 AND is_active FOR UPDATE`, id).Scan(&raw, &hash); err != nil {
		return err
	}
	if hash == nil || !VerifyPassword(*hash, password) {
		return ErrCredentials
	}
	state, err := s.open(id, raw)
	if err != nil {
		return err
	}
	if !state.Active || !consumeCode(&state, code, time.Now(), true) {
		return ErrCredentials
	}
	if _, err = tx.Exec(ctx, `UPDATE user_account SET totp_secret=NULL WHERE id=$1`, id); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM session WHERE user_id=$1`, id); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
