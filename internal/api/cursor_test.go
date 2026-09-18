package api

import (
	"context"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
)

func TestCursor(t *testing.T) {
	key := strings.Repeat("k", 32)
	c := Cursor{After: "2", Upper: "5", Scope: "items", Sort: []any{"rank", 2}}
	token, err := EncodeCursor(c, key)
	if err != nil {
		t.Fatal(err)
	}
	got, err := DecodeCursor(token, key, "items")
	if err != nil || got.After != c.After || got.Upper != c.Upper {
		t.Fatalf("roundtrip: %v %v", got, err)
	}
	for _, bad := range []string{token + "x", "not-base64", strings.Repeat("x", 8193)} {
		if _, err := DecodeCursor(bad, key, "items"); err == nil {
			t.Fatal("malformed cursor accepted")
		}
	}
	if _, err := DecodeCursor(token, key, "other-user"); err == nil {
		t.Fatal("cursor escaped scope")
	}
	if _, err := DecodeCursor(token, "wrong-key", "items"); err == nil {
		t.Fatal("forged cursor accepted")
	}
	for _, query := range []string{"?offset=0", "?limit=0", "?limit=201", "?limit=no", "?limit=1&limit=2"} {
		if _, err := PageLimit(httptest.NewRequest("GET", "/"+query, nil)); err == nil {
			t.Fatal("invalid pagination accepted")
		}
	}
	if n, err := PageLimit(httptest.NewRequest("GET", "/", nil)); err != nil || n != 50 {
		t.Fatal("wrong default")
	}
}

func TestCursorConcurrentInsert(t *testing.T) {
	ctx := context.Background()
	url := os.Getenv("DATABASE_URL")
	if url == "" {
		t.Fatal("DATABASE_URL required")
	}
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	if _, err = conn.Exec(ctx, `CREATE TEMP TABLE cursor_fixture(id int PRIMARY KEY); INSERT INTO cursor_fixture SELECT generate_series(1,5)`); err != nil {
		t.Fatal(err)
	}
	last, upper := 0, 5
	var ids []int
	key := strings.Repeat("k", 32)
	for page := 0; page < 3; page++ {
		rows, err := conn.Query(ctx, `SELECT id FROM cursor_fixture WHERE id>$1 AND id<=$2 ORDER BY id LIMIT 2`, last, upper)
		if err != nil {
			t.Fatal(err)
		}
		for rows.Next() {
			var id int
			if err := rows.Scan(&id); err != nil {
				t.Fatal(err)
			}
			ids = append(ids, id)
			last = id
		}
		rows.Close()
		if rows.Err() != nil {
			t.Fatal(rows.Err())
		}
		if page == 0 {
			if _, err := conn.Exec(ctx, `INSERT INTO cursor_fixture SELECT generate_series(6,8)`); err != nil {
				t.Fatal(err)
			}
		}
		token, err := EncodeCursor(Cursor{After: strconv.Itoa(last), Upper: strconv.Itoa(upper), Scope: "fixture"}, key)
		if err != nil {
			t.Fatal(err)
		}
		c, err := DecodeCursor(token, key, "fixture")
		if err != nil {
			t.Fatal(err)
		}
		last, _ = strconv.Atoi(c.After)
		upper, _ = strconv.Atoi(c.Upper)
	}
	if len(ids) != 5 {
		t.Fatalf("skipped/repeated rows: %v", ids)
	}
	for i, id := range ids {
		if id != i+1 {
			t.Fatalf("skipped/repeated rows: %v", ids)
		}
	}
}
