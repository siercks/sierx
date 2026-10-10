// Package lifecycle keeps operator decisions outside database backups.
package lifecycle

import (
	"bufio"
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
)

// Action is an explicit, case-bound operation. IDs materialized by the database
// are recorded before applying a retention batch, so recovery never widens it.
type Action struct {
	Kind            string   `json:"kind"`
	CaseRef         string   `json:"case_ref"`
	WorkspaceID     string   `json:"workspace_id,omitempty"`
	TargetID        string   `json:"target_id,omitempty"`
	ReplacementID   string   `json:"replacement_id,omitempty"`
	AuthorityRef    string   `json:"authority_ref,omitempty"`
	ReviewAt        string   `json:"review_at,omitempty"`
	Cutoff          string   `json:"cutoff,omitempty"`
	Correction      string   `json:"correction,omitempty"`
	EventSeq        int64    `json:"event_seq,omitempty"`
	At              string   `json:"at"`
	InstanceID      string   `json:"instance_id,omitempty"`
	WorkspaceOrigin string   `json:"workspace_origin,omitempty"`
	ItemIDs         []string `json:"item_ids,omitempty"`
	CommentIDs      []string `json:"comment_ids,omitempty"`
	ViewIDs         []string `json:"view_ids,omitempty"`
}

type Head struct {
	InstanceID string `json:"instance_id"`
	Sequence   int64  `json:"sequence"`
	Hash       string `json:"hash"`
	MAC        string `json:"mac,omitempty"`
}

type Record struct {
	InstanceID string `json:"instance_id"`
	Sequence   int64  `json:"sequence"`
	Previous   string `json:"previous"`
	Action     Action `json:"action"`
	Hash       string `json:"-"`
}

type envelope struct {
	Nonce      []byte `json:"nonce"`
	Ciphertext []byte `json:"ciphertext"`
}

type Journal struct {
	Path, Checkpoint string
	Key              []byte
	Head             Head
	Records          []Record
}

func privateFile(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() {
		return nil, errors.New("protected regular file is unavailable")
	}
	if runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("protected file must have owner-only permissions")
	}
	if info.Size() > 128<<20 {
		return nil, errors.New("protected file exceeds the journal limit")
	}
	return os.ReadFile(path)
}

func keyFile(path string) ([]byte, error) {
	b, err := privateFile(path)
	if err != nil {
		return nil, err
	}
	if len(b) != 32 {
		return nil, errors.New("journal key must contain exactly 32 random bytes")
	}
	return b, nil
}

func guardKey(key []byte) []byte {
	m := hmac.New(sha256.New, key)
	m.Write([]byte("sierx-lifecycle-checkpoint-v1"))
	return m.Sum(nil)
}

func authenticate(h Head, key []byte) string {
	h.MAC = ""
	b, _ := json.Marshal(h)
	m := hmac.New(sha256.New, key)
	m.Write(b)
	return hex.EncodeToString(m.Sum(nil))
}

func strictJSON(b []byte, v any) error {
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		return errors.New("invalid structured lifecycle data")
	}
	if d.Decode(new(any)) != io.EOF {
		return errors.New("trailing lifecycle data")
	}
	return nil
}

func Load(path, keyPath, checkpoint string) (*Journal, error) {
	return load(path, keyPath, checkpoint, false)
}

// RecoverCheckpoint only advances an authenticated checkpoint along its exact
// existing prefix. It cannot accept truncation, another instance or another key.
func RecoverCheckpoint(path, keyPath, checkpoint string) (*Journal, error) {
	j, err := load(path, keyPath, checkpoint, true)
	if err != nil {
		return nil, err
	}
	if err = j.writeHead(); err != nil {
		return nil, err
	}
	return j, nil
}

func load(path, keyPath, checkpoint string, allowTail bool) (*Journal, error) {
	key, err := keyFile(keyPath)
	if err != nil {
		return nil, err
	}
	hb, err := privateFile(checkpoint)
	if err != nil {
		return nil, err
	}
	var saved Head
	if err = strictJSON(hb, &saved); err != nil {
		return nil, err
	}
	if !hmac.Equal([]byte(saved.MAC), []byte(authenticate(saved, guardKey(key)))) || saved.InstanceID == "" || saved.Sequence < 0 {
		return nil, errors.New("journal checkpoint authentication failed")
	}
	data, err := privateFile(path)
	if err != nil {
		return nil, err
	}
	block, _ := aes.NewCipher(key)
	aead, _ := cipher.NewGCM(block)
	j := &Journal{Path: path, Checkpoint: checkpoint, Key: key, Head: Head{InstanceID: saved.InstanceID}}
	s := bufio.NewScanner(bytes.NewReader(data))
	s.Buffer(make([]byte, 4096), 2<<20)
	matched := saved.Sequence == 0 && saved.Hash == ""
	for s.Scan() {
		var e envelope
		if err = strictJSON(s.Bytes(), &e); err != nil {
			return nil, err
		}
		if len(e.Nonce) != aead.NonceSize() {
			return nil, errors.New("invalid journal nonce")
		}
		plain, err := aead.Open(nil, e.Nonce, e.Ciphertext, []byte(j.Head.InstanceID+":"+j.Head.Hash))
		if err != nil {
			return nil, errors.New("journal decryption or chain authentication failed")
		}
		var r Record
		if err = strictJSON(plain, &r); err != nil {
			return nil, err
		}
		if r.InstanceID != saved.InstanceID || r.Sequence != j.Head.Sequence+1 || r.Previous != j.Head.Hash || r.Action.InstanceID != saved.InstanceID {
			return nil, errors.New("journal sequence or instance mismatch")
		}
		sum := sha256.Sum256(s.Bytes())
		r.Hash = hex.EncodeToString(sum[:])
		j.Records = append(j.Records, r)
		j.Head.Sequence, j.Head.Hash = r.Sequence, r.Hash
		if r.Sequence == saved.Sequence && r.Hash == saved.Hash {
			matched = true
		}
	}
	if err = s.Err(); err != nil {
		return nil, errors.New("journal record exceeds limit")
	}
	if len(data) > 0 && data[len(data)-1] != '\n' {
		return nil, errors.New("journal has a partial record")
	}
	if !matched || (!allowTail && (j.Head.Sequence != saved.Sequence || j.Head.Hash != saved.Hash)) {
		return nil, errors.New("journal is truncated or does not match the trusted checkpoint")
	}
	return j, nil
}

// Lock serializes init, append and replay for a journal. A stale lock after a
// crash is deliberately retained until the operator confirms no process owns it.
func Lock(path string) (func(), error) {
	lock := path + ".lock"
	if err := os.Mkdir(lock, 0700); err != nil {
		return nil, errors.New("journal is locked or its protected directory is missing")
	}
	return func() { _ = os.Remove(lock) }, nil
}

func Init(path, keyPath, checkpoint, instance string) (*Journal, error) {
	if path == keyPath || path == checkpoint || keyPath == checkpoint || instance == "" {
		return nil, errors.New("distinct protected paths and an instance UUID are required")
	}
	verification := filepath.Join(filepath.Dir(checkpoint), "verification.key")
	for _, p := range []string{path, keyPath, checkpoint, verification} {
		if _, err := os.Lstat(p); !os.IsNotExist(err) {
			return nil, errors.New("journal initialization never overwrites files")
		}
	}
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(keyPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return nil, err
	}
	if _, err = f.Write(key); err == nil {
		err = f.Sync()
	}
	ce := f.Close()
	if err != nil {
		return nil, err
	}
	if ce != nil {
		return nil, ce
	}
	f, err = os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return nil, err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return nil, err
	}
	if err = f.Close(); err != nil {
		return nil, err
	}
	f, err = os.OpenFile(verification, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return nil, err
	}
	if _, err = f.Write(guardKey(key)); err == nil {
		err = f.Sync()
	}
	ce = f.Close()
	if err != nil {
		return nil, err
	}
	if ce != nil {
		return nil, ce
	}
	j := &Journal{Path: path, Checkpoint: checkpoint, Key: key, Head: Head{InstanceID: instance}}
	if err = j.writeHead(); err != nil {
		return nil, err
	}
	return j, nil
}

func syncDir(path string) error {
	if runtime.GOOS == "windows" {
		return nil
	}
	f, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}

func (j *Journal) writeHead() error {
	h := j.Head
	h.MAC = authenticate(h, guardKey(j.Key))
	b, _ := json.Marshal(h)
	f, err := os.CreateTemp(filepath.Dir(j.Checkpoint), ".checkpoint-*")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if err = f.Chmod(0600); err == nil {
		_, err = f.Write(append(b, '\n'))
	}
	if err == nil {
		err = f.Sync()
	}
	ce := f.Close()
	if err != nil {
		return err
	}
	if ce != nil {
		return ce
	}
	if err = os.Rename(name, j.Checkpoint); err != nil {
		return err
	}
	return syncDir(j.Checkpoint)
}

func (j *Journal) Append(a Action) (Record, error) {
	if a.InstanceID != j.Head.InstanceID {
		return Record{}, errors.New("action belongs to another instance")
	}
	r := Record{InstanceID: j.Head.InstanceID, Sequence: j.Head.Sequence + 1, Previous: j.Head.Hash, Action: a}
	plain, err := json.Marshal(r)
	if err != nil {
		return r, err
	}
	block, _ := aes.NewCipher(j.Key)
	aead, _ := cipher.NewGCM(block)
	nonce := make([]byte, aead.NonceSize())
	if _, err = rand.Read(nonce); err != nil {
		return r, err
	}
	b, _ := json.Marshal(envelope{Nonce: nonce, Ciphertext: aead.Seal(nil, nonce, plain, []byte(r.InstanceID+":"+r.Previous))})
	if len(b) > 2<<20 {
		return r, errors.New("journal record exceeds limit")
	}
	if _, err = privateFile(j.Path); err != nil {
		return r, err
	}
	info, err := os.Stat(j.Path)
	if err != nil {
		return r, err
	}
	if info.Size()+int64(len(b))+1 > 128<<20 {
		return r, errors.New("journal capacity reached; no decision was appended")
	}
	f, err := os.OpenFile(j.Path, os.O_WRONLY|os.O_APPEND, 0600)
	if err != nil {
		return r, err
	}
	_, err = f.Write(append(b, '\n'))
	if err == nil {
		err = f.Sync()
	}
	ce := f.Close()
	if err != nil {
		return r, err
	}
	if ce != nil {
		return r, ce
	}
	sum := sha256.Sum256(b)
	r.Hash = hex.EncodeToString(sum[:])
	j.Records = append(j.Records, r)
	j.Head.Sequence, j.Head.Hash = r.Sequence, r.Hash
	if err = j.writeHead(); err != nil {
		return r, fmt.Errorf("journal intent persisted; reconcile checkpoint before replay: %w", err)
	}
	return r, nil
}

// DecodeAction rejects unknown fields and trailing data in an operator request.
func DecodeAction(b []byte, a *Action) error { return strictJSON(b, a) }
