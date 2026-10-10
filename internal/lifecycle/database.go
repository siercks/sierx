package lifecycle

import (
	"context"
	"crypto/hmac"
	"encoding/json"
	"errors"
	"os"
	"sync"

	"github.com/jackc/pgx/v5"
)

type DB interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}

func DatabaseHead(ctx context.Context, db DB) (Head, error) {
	var h Head
	err := db.QueryRow(ctx, `SELECT instance_id::text,sequence,head FROM public.sierx_lifecycle_status()`).Scan(&h.InstanceID, &h.Sequence, &h.Hash)
	if err != nil {
		return h, errors.New("lifecycle database checkpoint is unavailable")
	}
	return h, nil
}

func (j *Journal) Matches(h Head) bool {
	return j.Head.InstanceID == h.InstanceID && j.Head.Sequence == h.Sequence && j.Head.Hash == h.Hash
}

// Prefix verifies a restored database against the exact authenticated journal
// prefix. A database ahead of the latest trusted checkpoint is never accepted.
func (j *Journal) Prefix(h Head) bool {
	if h.InstanceID != j.Head.InstanceID || h.Sequence < 0 || h.Sequence > j.Head.Sequence {
		return false
	}
	if h.Sequence == 0 {
		return h.Hash == ""
	}
	return j.Records[h.Sequence-1].Hash == h.Hash
}

func ApplyRecord(ctx context.Context, db DB, r Record) error {
	b, err := json.Marshal(r.Action)
	if err != nil {
		return err
	}
	var unused any
	if err = db.QueryRow(ctx, `SELECT public.sierx_lifecycle_apply($1::jsonb,$2,$3,$4)`, b, r.Sequence, r.Previous, r.Hash).Scan(&unused); err != nil {
		return errors.New("lifecycle decision could not be applied; application access stays blocked until reconciliation")
	}
	return nil
}

type Paths struct{ Journal, Key, Checkpoint string }

func EnvironmentPaths() (Paths, error) {
	p := Paths{os.Getenv("SIERX_LIFECYCLE_JOURNAL"), os.Getenv("SIERX_LIFECYCLE_KEY_FILE"), os.Getenv("SIERX_LIFECYCLE_CHECKPOINT")}
	if p.Journal == "" || p.Key == "" || p.Checkpoint == "" || p.Journal == p.Key || p.Journal == p.Checkpoint || p.Key == p.Checkpoint {
		return p, errors.New("distinct SIERX_LIFECYCLE_JOURNAL, SIERX_LIFECYCLE_KEY_FILE and SIERX_LIFECYCLE_CHECKPOINT paths are required")
	}
	return p, nil
}

// Guard receives only a checkpoint verification key. It cannot decrypt the
// operator journal or read correction text from other workspaces.
type Guard struct {
	Checkpoint, Key string
	DB              DB
	mu              sync.Mutex
	files           [2]os.FileInfo
	head            *Head
}

func NewGuard(db DB) (*Guard, error) {
	g := &Guard{DB: db, Checkpoint: os.Getenv("SIERX_LIFECYCLE_CHECKPOINT"), Key: os.Getenv("SIERX_LIFECYCLE_GUARD_KEY_FILE")}
	if g.Checkpoint == "" || g.Key == "" || g.Checkpoint == g.Key {
		return nil, errors.New("SIERX_LIFECYCLE_CHECKPOINT and SIERX_LIFECYCLE_GUARD_KEY_FILE are required before serving")
	}
	return g, nil
}

func (g *Guard) checkpoint() (Head, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	var latest [2]os.FileInfo
	changed := g.head == nil
	for i, path := range []string{g.Checkpoint, g.Key} {
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsRegular() || (i == 0 && info.Size() > 4096) || (i == 1 && info.Size() != 32) {
			return Head{}, errors.New("lifecycle recovery checkpoint is unavailable")
		}
		latest[i] = info
		prior := g.files[i]
		if prior == nil || !os.SameFile(prior, info) || prior.Size() != info.Size() || !prior.ModTime().Equal(info.ModTime()) || prior.Mode() != info.Mode() {
			changed = true
		}
	}
	if changed {
		key, err := keyFile(g.Key)
		if err != nil {
			return Head{}, err
		}
		b, err := privateFile(g.Checkpoint)
		if err != nil {
			return Head{}, err
		}
		var h Head
		if err = strictJSON(b, &h); err != nil {
			return Head{}, err
		}
		if h.InstanceID == "" || h.Sequence < 0 || !hmac.Equal([]byte(h.MAC), []byte(authenticate(h, key))) {
			return Head{}, errors.New("lifecycle checkpoint authentication failed")
		}
		g.head = &h
		g.files = latest
	}
	return *g.head, nil
}

func (g *Guard) Check(ctx context.Context) error {
	expected, err := g.checkpoint()
	if err != nil {
		return err
	}
	h, err := DatabaseHead(ctx, g.DB)
	if err != nil {
		return err
	}
	if h.InstanceID != expected.InstanceID || h.Sequence != expected.Sequence || h.Hash != expected.Hash {
		return errors.New("lifecycle recovery replay required before application access")
	}
	return nil
}
