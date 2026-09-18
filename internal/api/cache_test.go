package api

import (
	"compress/gzip"
	"github.com/andybalholm/brotli"
	"io"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCachingCompression(t *testing.T) {
	s, cookie, _ := itemFixture(t)
	call := func(path, encoding, etag string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("GET", path, nil)
		r.AddCookie(cookie)
		r.Header.Set("Accept-Encoding", encoding)
		r.Header.Set("If-None-Match", etag)
		w := httptest.NewRecorder()
		s.Router.ServeHTTP(w, r)
		return w
	}
	path := "/api/v1/items/SRX-1"
	plain := call(path, "", "")
	if plain.Code != 200 {
		t.Fatal(plain.Body.String())
	}
	etag := plain.Header().Get("ETag")
	if plain.Header().Get("Cache-Control") != "private, no-cache" || !strings.HasPrefix(etag, "W/") {
		t.Fatal("missing private representation tag")
	}
	for _, tc := range []struct{ accept, encoding string }{{"br, gzip", "br"}, {"gzip", "gzip"}, {"br;q=0,gzip;q=1", "gzip"}, {"br;q=.2,gzip;q=.8", "gzip"}, {"br;q=0,gzip;q=0", ""}} {
		w := call(path, tc.accept, "")
		if w.Code != 200 || w.Header().Get("Content-Encoding") != tc.encoding {
			t.Fatalf("negotiation %q: %d %s", tc.accept, w.Code, w.Header())
		}
		var reader io.Reader = w.Body
		if tc.encoding == "br" {
			reader = brotli.NewReader(reader)
		} else if tc.encoding == "gzip" {
			decoder, err := gzip.NewReader(reader)
			if err != nil {
				t.Fatal(err)
			}
			defer decoder.Close()
			reader = decoder
		}
		body, err := io.ReadAll(reader)
		if err != nil || string(body) != plain.Body.String() {
			t.Fatalf("decompression %v", err)
		}
		if w.Header().Get("ETag") != etag || !strings.Contains(w.Header().Get("Vary"), "Accept-Encoding") {
			t.Fatal("invalid cache variants")
		}
		w = call(path, tc.accept, etag)
		if w.Code != 304 || w.Body.Len() != 0 || w.Header().Get("Content-Encoding") != "" {
			t.Fatal("304 emitted a compressed body")
		}
	}
	if w := call(path, "identity;q=0,br;q=0,gzip;q=0", ""); w.Code != 406 {
		t.Fatal("unacceptable encoding ignored")
	}
	if w := call(path+"?fields=key", "", etag); w.Code != 200 || w.Header().Get("ETag") == etag {
		t.Fatal("projection cache collision")
	}
	// A child changes the parent rollup but not the parent's edit version.
	if w := apiCall(s, "POST", "/api/v1/items", `{"project":"SRX","type":"story","title":"Child","parent":"SRX-1"}`, cookie); w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	if w := call(path, "", etag); w.Code != 200 || w.Header().Get("ETag") == etag {
		t.Fatal("rollup change hidden by stale cache")
	}
	if w := call("/api/v1/changes?since_seq=0", "br", "*"); w.Code != 200 || w.Header().Get("ETag") != "" {
		t.Fatal("delta endpoint used ETag")
	}
	config := call("/api/v1/projects/SRX/config", "gzip", "")
	if w := call("/api/v1/projects/SRX/config", "br", config.Header().Get("ETag")); w.Code != 304 || w.Body.Len() != 0 {
		t.Fatal("config conditional request failed")
	}
}
