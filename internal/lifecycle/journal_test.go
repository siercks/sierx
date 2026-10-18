package lifecycle

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/jackc/pgx/v5"
)

func journalFixture(t *testing.T) (*Journal, Paths) {
	t.Helper()
	dir := t.TempDir()
	guard := filepath.Join(dir, "guard")
	if err := os.Mkdir(guard, 0700); err != nil {
		t.Fatal(err)
	}
	p := Paths{filepath.Join(dir, "journal"), filepath.Join(dir, "key"), filepath.Join(guard, "checkpoint")}
	j, err := Init(p.Journal, p.Key, p.Checkpoint, "18000000-0000-7000-8000-000000000001")
	if err != nil {
		t.Fatal(err)
	}
	return j, p
}

func TestJournalAuthenticatesEncryptedDecisionsAndTrustedPrefix(t *testing.T) {
	j, p := journalFixture(t)
	initial, _ := os.ReadFile(p.Checkpoint)
	a := Action{Kind: "correct-history", InstanceID: j.Head.InstanceID, CaseRef: "18000000-0000-7000-8000-000000000002", Correction: "private correction text"}
	r, err := j.Append(a)
	if err != nil {
		t.Fatal(err)
	}
	loaded, err := Load(p.Journal, p.Key, p.Checkpoint)
	if err != nil || len(loaded.Records) != 1 || loaded.Records[0].Action.Correction != a.Correction {
		t.Fatalf("roundtrip failed: %v", err)
	}
	if !loaded.Prefix(Head{InstanceID: j.Head.InstanceID}) || !loaded.Matches(j.Head) || loaded.Prefix(Head{InstanceID: "other"}) {
		t.Fatal("prefix identity/sequence verification failed")
	}
	b, _ := os.ReadFile(p.Journal)
	if string(b) == a.Correction || contains(b, []byte(a.Correction)) {
		t.Fatal("journal exposes correction plaintext")
	}
	checkpoint, _ := os.ReadFile(p.Checkpoint)
	// Losing the newest line cannot pass a retained external checkpoint.
	if err = os.WriteFile(p.Journal, nil, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = Load(p.Journal, p.Key, p.Checkpoint); err == nil {
		t.Fatal("truncated journal accepted")
	}
	if _, err = RecoverCheckpoint(p.Journal, p.Key, p.Checkpoint); err == nil {
		t.Fatal("checkpoint repair accepted truncation")
	}
	_ = os.WriteFile(p.Journal, b, 0600)
	// Crash after journal fsync but before checkpoint replacement: repair may
	// advance only after proving the existing checkpoint's exact prefix.
	_ = os.WriteFile(p.Checkpoint, initial, 0600)
	if _, err = Load(p.Journal, p.Key, p.Checkpoint); err == nil {
		t.Fatal("uncheckpointed intent silently accepted")
	}
	repaired, err := RecoverCheckpoint(p.Journal, p.Key, p.Checkpoint)
	if err != nil || repaired.Head.Hash != r.Hash {
		t.Fatalf("authenticated tail recovery failed: %v", err)
	}
	_ = os.WriteFile(p.Checkpoint, checkpoint, 0600)
	b[len(b)/2] ^= 1
	_ = os.WriteFile(p.Journal, b, 0600)
	if _, err = Load(p.Journal, p.Key, p.Checkpoint); err == nil {
		t.Fatal("corrupt ciphertext accepted")
	}
}

func contains(a, b []byte) bool {
	for i := 0; i+len(b) <= len(a); i++ {
		if string(a[i:i+len(b)]) == string(b) {
			return true
		}
	}
	return false
}

func TestJournalRejectsWrongKeyPartialRecordsUnknownFieldsAndConcurrentWriters(t *testing.T) {
	j, p := journalFixture(t)
	unlock, err := Lock(p.Journal)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = Lock(p.Journal); err == nil {
		t.Fatal("concurrent writer accepted")
	}
	unlock()
	if _, err = Init(p.Journal, p.Key, p.Checkpoint, j.Head.InstanceID); err == nil {
		t.Fatal("initialization overwrote protected data")
	}
	if _, err = j.Append(Action{InstanceID: "different"}); err == nil {
		t.Fatal("another instance appended")
	}
	if err = DecodeAction([]byte(`{"kind":"cleanup","extra":"unknown"}`), new(Action)); err == nil {
		t.Fatal("unknown action field accepted")
	}
	if err = DecodeAction([]byte(`{"kind":"cleanup"} {}`), new(Action)); err == nil {
		t.Fatal("trailing JSON accepted")
	}
	if _, err = j.Append(Action{Kind: "cleanup", InstanceID: j.Head.InstanceID}); err != nil {
		t.Fatal(err)
	}
	original, _ := os.ReadFile(p.Key)
	_ = os.WriteFile(p.Key, make([]byte, 32), 0600)
	if _, err = Load(p.Journal, p.Key, p.Checkpoint); err == nil {
		t.Fatal("wrong key accepted")
	}
	_ = os.WriteFile(p.Key, original, 0600)
	b, _ := os.ReadFile(p.Journal)
	_ = os.WriteFile(p.Journal, b[:len(b)-1], 0600)
	if _, err = Load(p.Journal, p.Key, p.Checkpoint); err == nil {
		t.Fatal("partial record accepted")
	}
}

type headDB struct {
	h   Head
	err error
}

func (d *headDB) QueryRow(context.Context, string, ...any) pgx.Row { return headRow{d} }

type headRow struct{ d *headDB }

func (r headRow) Scan(v ...any) error {
	if r.d.err != nil {
		return r.d.err
	}
	*(v[0].(*string)) = r.d.h.InstanceID
	*(v[1].(*int64)) = r.d.h.Sequence
	*(v[2].(*string)) = r.d.h.Hash
	return nil
}

func TestGuardChecksLatestCheckpointAndCannotDecryptOperatorJournal(t *testing.T) {
	j, p := journalFixture(t)
	db := &headDB{h: j.Head}
	g := &Guard{DB: db, Checkpoint: p.Checkpoint, Key: filepath.Join(filepath.Dir(p.Checkpoint), "verification.key")}
	if err := g.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := j.Append(Action{Kind: "cleanup", InstanceID: j.Head.InstanceID}); err != nil {
		t.Fatal(err)
	}
	if err := g.Check(context.Background()); err == nil {
		t.Fatal("stale database served")
	}
	db.h = j.Head
	if err := g.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(p.Checkpoint); err != nil {
		t.Fatal(err)
	}
	if err := g.Check(context.Background()); err == nil {
		t.Fatal("missing checkpoint served")
	}
	if err := j.writeHead(); err != nil {
		t.Fatal(err)
	}
	db.err = errors.New("database down")
	if err := g.Check(context.Background()); err == nil {
		t.Fatal("unreachable database served")
	}
	db.err = nil
	// The application's derived verification key cannot open the encrypted log.
	if _, err := Load(p.Journal, g.Key, p.Checkpoint); err == nil {
		t.Fatal("application verification key decrypts operator journal")
	}
	h := j.Head
	h.Hash = "forged"
	b, _ := json.Marshal(h)
	_ = os.WriteFile(p.Checkpoint, b, 0600)
	if err := g.Check(context.Background()); err == nil {
		t.Fatal("forged checkpoint served")
	}
}
