package api

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
)

type Cursor struct {
	Version int    `json:"v"`
	After   string `json:"after"`
	Sort    []any  `json:"sort,omitempty"`
	Upper   string `json:"upper"`
	Scope   string `json:"scope"`
}

func EncodeCursor(c Cursor, key string) (string, error) {
	c.Version = 1
	raw, err := json.Marshal(c)
	if err != nil {
		return "", err
	}
	mac := hmac.New(sha256.New, []byte(key))
	_, _ = mac.Write(raw)
	return base64.RawURLEncoding.EncodeToString(append(raw, mac.Sum(nil)...)), nil
}
func DecodeCursor(token, key, scope string) (Cursor, error) {
	var c Cursor
	invalid := fmt.Errorf("cursor is invalid for this request; restart from the first page")
	if len(token) > 8192 {
		return c, invalid
	}
	raw, err := base64.RawURLEncoding.DecodeString(token)
	if err != nil || len(raw) <= sha256.Size {
		return c, invalid
	}
	data, signature := raw[:len(raw)-sha256.Size], raw[len(raw)-sha256.Size:]
	mac := hmac.New(sha256.New, []byte(key))
	_, _ = mac.Write(data)
	if !hmac.Equal(signature, mac.Sum(nil)) {
		return c, invalid
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	d.DisallowUnknownFields()
	if err = d.Decode(&c); err != nil || c.Version != 1 || c.Scope != scope || c.After == "" || c.Upper == "" {
		return Cursor{}, invalid
	}
	return c, nil
}

func PageLimit(r *http.Request) (int, error) {
	q := r.URL.Query()
	if q.Has("offset") {
		return 0, fmt.Errorf("offset is not supported; use cursor pagination")
	}
	if len(q["limit"]) > 1 || len(q["cursor"]) > 1 {
		return 0, fmt.Errorf("send one limit and one cursor")
	}
	if !q.Has("limit") {
		return 50, nil
	}
	n, err := strconv.Atoi(q.Get("limit"))
	if err != nil || n < 1 || n > 200 {
		return 0, fmt.Errorf("limit must be between 1 and 200")
	}
	return n, nil
}

func cursorScope(r *http.Request) string {
	q := r.URL.Query()
	q.Del("cursor")
	q.Del("limit")
	who := Identity(r)
	h := sha256.Sum256([]byte(who.WorkspaceID + "\n" + who.ID + "\n" + r.URL.Path + "\n" + q.Encode()))
	return hex.EncodeToString(h[:])
}

type Page struct {
	Data       []any   `json:"data"`
	NextCursor *string `json:"next_cursor"`
}
