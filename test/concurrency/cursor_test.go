package concurrency

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"
	"uuid"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/siercks/sierx/internal/api"
	"github.com/siercks/sierx/internal/bootstrap"
	"github.com/siercks/sierx/internal/config"
	"github.com/siercks/sierx/internal/store"
)

func pool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	ctx := context.Background()
	base := os.Getenv("DATABASE_URL")
	if base == "" {
		t.Fatal("DATABASE_URL is required")
	}
	admin, err := pgxpool.New(ctx, base)
	if err != nil {
		t.Fatal(err)
	}
	name := "concurrency_" + strings.ReplaceAll(uuid.NewV7().String(), "-", "")
	if _, err = admin.Exec(ctx, "CREATE DATABASE "+pgx.Identifier{name}.Sanitize()+" TEMPLATE template0"); err != nil {
		t.Fatal(err)
	}
	dsn, err := url.Parse(base)
	if err != nil {
		t.Fatal(err)
	}
	dsn.Path = "/" + name
	p, err := pgxpool.New(ctx, dsn.String())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		p.Close()
		_, err := admin.Exec(ctx, "DROP DATABASE "+pgx.Identifier{name}.Sanitize()+" WITH (FORCE)")
		if err != nil {
			t.Error(err)
		}
		admin.Close()
	})
	if output, err := exec.Command("../../bin/goose", "-dir", "../../migrations", "postgres", dsn.String(), "up").CombinedOutput(); err != nil {
		t.Fatalf("migrations: %v %s", err, output)
	}
	return p
}

func TestCommitOrderedCursor(t *testing.T) {
	p := pool(t)
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	initial, err := bootstrap.Run(ctx, p, bootstrap.Options{Slug: "cursor", Name: "Cursor", Email: "cursor@example.test", DisplayName: "Cursor", Password: "test-password-12345", AuthMode: "local", ProjectPrefix: "CUR", ProjectName: "Concurrency"})
	if err != nil {
		t.Fatal(err)
	}
	s := api.New(p, slog.New(slog.NewTextHandler(io.Discard, nil)))
	s.ConfigureAuth(config.Env{AuthMode: "local", BaseURL: "https://example.test", SessionKey: strings.Repeat("x", 32)})
	call := func(method, path, body string, cookie *http.Cookie, version int) (*httptest.ResponseRecorder, error) {
		r := httptest.NewRequest(method, path, bytes.NewBufferString(body)).WithContext(ctx)
		r.Header.Set("Content-Type", "application/json")
		if cookie != nil {
			r.AddCookie(cookie)
		}
		if version > 0 {
			r.Header.Set("If-Match", fmt.Sprintf(`"%d"`, version))
		}
		w := httptest.NewRecorder()
		s.Router.ServeHTTP(w, r)
		if w.Code < 200 || w.Code >= 300 {
			return w, fmt.Errorf("%s %s: %d %s", method, path, w.Code, w.Body)
		}
		return w, nil
	}
	login, err := call("POST", "/api/v1/auth/login", `{"email":"cursor@example.test","password":"test-password-12345"}`, nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	cookie := login.Result().Cookies()[0]
	wid, _ := uuid.Parse(initial.WorkspaceID)
	pid, _ := uuid.Parse(initial.ProjectID)
	actor, _ := uuid.Parse(initial.UserID)
	var typeID, todoID, doneID, originID string
	if err = p.QueryRow(ctx, `SELECT t.id::text,s.id::text,d.id::text,(SELECT origin_id::text FROM workspace WHERE id=p.workspace_id) FROM item_type t JOIN project p ON p.id=t.project_id JOIN status s ON s.project_id=t.project_id AND s.key='todo' JOIN status d ON d.project_id=t.project_id AND d.key='dropped' WHERE t.project_id=$1 AND t.key='story'`, initial.ProjectID).Scan(&typeID, &todoID, &doneID, &originID); err != nil {
		t.Fatal(err)
	}
	origin, _ := uuid.Parse(originID)
	tid, _ := uuid.Parse(typeID)
	todo, _ := uuid.Parse(todoID)
	done, _ := uuid.Parse(doneID)
	ids := make([]uuid.UUID, 200)
	for i := range ids {
		ids[i] = uuid.NewV7()
	}
	st := store.New(p)
	_, err = st.Mutate(ctx, wid, func(m *store.Mutation) error {
		for _, id := range ids {
			m.Create(store.ItemInsert{ID: id, ProjectID: pid, ItemTypeID: tid, StatusID: todo, Title: "Bulk", OriginID: origin})
		}
		return nil
	}, store.WithActor(actor))
	if err != nil {
		t.Fatal(err)
	}
	const writers = 6
	const perWriter = 12
	const expected = 200 + 200 + writers*perWriter*2
	failures := make(chan error, writers+2)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for worker := 0; worker < writers; worker++ {
		wg.Add(1)
		go func(worker int) {
			defer wg.Done()
			<-start
			for i := 0; i < perWriter; i++ {
				w, err := call("POST", "/api/v1/items", fmt.Sprintf(`{"project":"CUR","type":"story","title":"Writer %d item %d"}`, worker, i), cookie, 0)
				if err != nil {
					failures <- err
					return
				}
				var item struct{ Key string }
				if err = json.Unmarshal(w.Body.Bytes(), &item); err != nil {
					failures <- err
					return
				}
				if _, err = call("PATCH", "/api/v1/items/"+item.Key, `{"title":"Edited concurrently"}`, cookie, 1); err != nil {
					failures <- err
					return
				}
			}
		}(worker)
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		<-start
		_, err := st.Mutate(ctx, wid, func(m *store.Mutation) error {
			for _, id := range ids {
				m.Update(store.ItemUpdate{ID: id, StatusID: &done}, store.FieldChange{Kind: store.EventStatusChanged, Field: "status", Old: "todo", New: "dropped"})
			}
			return nil
		}, store.WithActor(actor))
		if err != nil {
			failures <- err
		}
	}()
	finished := make(chan struct{})
	go func() { wg.Wait(); close(finished) }()
	close(start)
	observed := map[int64]bool{}
	var cursor int64
	polls := 0
	for cursor < expected {
		if ctx.Err() != nil {
			t.Fatalf("poller timeout at %d: %v", cursor, ctx.Err())
		}
		select {
		case err := <-failures:
			t.Fatal(err)
		default:
		}
		w, err := call("GET", fmt.Sprintf("/api/v1/changes?since_seq=%d&limit=17", cursor), "", cookie, 0)
		if err != nil {
			t.Fatal(err)
		}
		var page struct {
			Data    []struct{ Seq int64 }
			NextSeq int64 `json:"next_seq"`
		}
		if err = json.Unmarshal(w.Body.Bytes(), &page); err != nil {
			t.Fatal(err)
		}
		polls++
		for _, event := range page.Data {
			if event.Seq != cursor+1 || observed[event.Seq] {
				t.Fatalf("gap or duplicate: cursor=%d got=%d", cursor, event.Seq)
			}
			observed[event.Seq] = true
			cursor = event.Seq
		}
		if page.NextSeq != cursor {
			t.Fatal("incorrect next_seq")
		}
		if len(page.Data) == 0 {
			select {
			case <-finished:
				// The last commit may have happened after this poll's snapshot.
				continue
			case <-time.After(time.Millisecond):
			}
		}
	}
	<-finished
	select {
	case err := <-failures:
		t.Fatal(err)
	default:
	}
	var committed, maxSeq int64
	if err = p.QueryRow(ctx, `SELECT count(*),max(seq) FROM change_event WHERE workspace_id=$1`, initial.WorkspaceID).Scan(&committed, &maxSeq); err != nil {
		t.Fatal(err)
	}
	if committed != expected || maxSeq != expected || len(observed) != expected {
		t.Fatalf("committed=%d max=%d observed=%d", committed, maxSeq, len(observed))
	}
	t.Logf("observed all %d committed events exactly once across %d polls, including a 200-item transition", expected, polls)
}
