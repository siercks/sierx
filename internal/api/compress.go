package api

import (
	"compress/gzip"
	"github.com/andybalholm/brotli"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"
)

func encodingChoice(header string) (string, bool) {
	values := map[string]float64{}
	for _, part := range strings.Split(header, ",") {
		pieces := strings.Split(part, ";")
		name := strings.ToLower(strings.TrimSpace(pieces[0]))
		if name == "" {
			continue
		}
		quality := 1.0
		for _, parameter := range pieces[1:] {
			key, value, ok := strings.Cut(strings.TrimSpace(parameter), "=")
			if ok && strings.EqualFold(key, "q") {
				q, err := strconv.ParseFloat(value, 64)
				if err != nil || q < 0 || q > 1 || math.IsNaN(q) {
					quality = 0
				} else {
					quality = q
				}
			}
		}
		values[name] = quality
	}
	best := ""
	bestQ := 0.0
	for _, name := range []string{"br", "gzip"} {
		q, ok := values[name]
		if !ok {
			q = values["*"]
		}
		if q > bestQ {
			best = name
			bestQ = q
		}
	}
	if q, ok := values["identity"]; ok && q > bestQ {
		return "", true
	}
	if best != "" {
		return best, true
	}
	if q, ok := values["identity"]; ok {
		return "", q > 0
	}
	if q, ok := values["*"]; ok && q == 0 {
		return "", false
	}
	return "", true
}
func compression(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Enrollment and recovery responses carry fresh authentication secrets.
		if strings.HasPrefix(r.URL.Path, "/api/v1/auth/") {
			next.ServeHTTP(w, r)
			return
		}
		w.Header().Add("Vary", "Accept-Encoding")
		encoding, ok := encodingChoice(strings.Join(r.Header.Values("Accept-Encoding"), ","))
		if !ok {
			WriteProblem(w, NotAcceptable())
			return
		}
		cw := &compressedWriter{ResponseWriter: w, encoding: encoding, head: r.Method == "HEAD"}
		defer func() {
			if cw.encoder != nil {
				_ = cw.encoder.Close()
			}
		}()
		next.ServeHTTP(cw, r)
	})
}

type compressedWriter struct {
	http.ResponseWriter
	encoding    string
	encoder     io.WriteCloser
	wrote, head bool
}

func (w *compressedWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }
func (w *compressedWriter) WriteHeader(status int) {
	if status < 200 {
		w.ResponseWriter.WriteHeader(status)
		return
	}
	if w.wrote {
		return
	}
	w.wrote = true
	content := w.Header().Get("Content-Type")
	compressible := strings.HasPrefix(content, "text/") || strings.HasPrefix(content, "application/json") || strings.HasPrefix(content, "application/problem+json") || strings.HasPrefix(content, "application/javascript") || strings.HasPrefix(content, "image/svg+xml")
	if !w.head && status != 204 && status != 304 && compressible && w.encoding != "" && w.Header().Get("Content-Encoding") == "" {
		if w.encoding == "br" {
			w.encoder = brotli.NewWriterLevel(w.ResponseWriter, 4)
		} else {
			w.encoder, _ = gzip.NewWriterLevel(w.ResponseWriter, 5)
		}
		w.Header().Set("Content-Encoding", w.encoding)
		w.Header().Del("Content-Length")
	}
	w.ResponseWriter.WriteHeader(status)
}
func (w *compressedWriter) Write(body []byte) (int, error) {
	if !w.wrote {
		w.WriteHeader(200)
	}
	if w.head {
		return len(body), nil
	}
	if w.encoder != nil {
		return w.encoder.Write(body)
	}
	return w.ResponseWriter.Write(body)
}
