package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"testing"
)

func TestProblemGolden(t *testing.T) {
	// Ensure every golden detail is an authored literal in this package.
	f, err := parser.ParseFile(token.NewFileSet(), "problem.go", nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	literals := map[string]bool{}
	ast.Inspect(f, func(n ast.Node) bool {
		if lit, ok := n.(*ast.BasicLit); ok && lit.Kind == token.STRING {
			v, _ := strconv.Unquote(lit.Value)
			literals[v] = true
		}
		return true
	})
	for _, p := range []Problem{BadRequest(), Unauthorized(), Forbidden(), NotFound(), MethodNotAllowed(), Conflict(map[string]any{"key": "SRX-1", "title": "Server edit", "version": 2}), TooLarge(), UnsupportedMediaType(), Unprocessable(), PreconditionRequired(), RateLimited(), InternalError(), Unavailable()} {
		t.Run(strconv.Itoa(p.Status), func(t *testing.T) {
			w := httptest.NewRecorder()
			WriteProblem(w, p)
			path := filepath.Join("..", "..", "test", "golden", "problems", fmt.Sprintf("%d.json", p.Status))
			want, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(want, w.Body.Bytes()) {
				t.Fatalf("golden mismatch\nwant %s\ngot %s", want, w.Body.Bytes())
			}
			if w.Code != p.Status || w.Header().Get("Content-Type") != "application/problem+json" {
				t.Fatal("wrong status/content type")
			}
			var stored Problem
			if err := json.Unmarshal(want, &stored); err != nil {
				t.Fatal(err)
			}
			if !literals[stored.Detail] {
				t.Fatal("detail is not authored in internal/api/problem.go")
			}
		})
	}
}

func TestRouterProblems(t *testing.T) {
	s := New(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	s.Router.Get("/panic", func(http.ResponseWriter, *http.Request) { panic("private implementation error") })
	for _, tc := range []struct {
		method, path string
		status       int
	}{{"GET", "/missing", 404}, {"POST", "/api/v1/healthz", 405}, {"GET", "/panic", 500}} {
		w := httptest.NewRecorder()
		s.Router.ServeHTTP(w, httptest.NewRequest(tc.method, tc.path, nil))
		if w.Code != tc.status || w.Header().Get("Content-Type") != "application/problem+json" || bytes.Contains(w.Body.Bytes(), []byte("private")) {
			t.Fatalf("%d %s", w.Code, w.Body)
		}
	}
}
