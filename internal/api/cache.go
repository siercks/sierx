package api

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/http"
)

func writeCachedJSON(w http.ResponseWriter, r *http.Request, value any) {
	body, err := json.Marshal(value)
	if err != nil {
		WriteProblem(w, InternalError())
		return
	}
	sum := sha256.Sum256(body)
	etag := fmt.Sprintf(`W/"%x"`, sum)
	w.Header().Set("ETag", etag)
	w.Header().Set("Cache-Control", "private, no-cache")
	w.Header().Set("Content-Type", "application/json")
	if etagMatches(r.Header.Get("If-None-Match"), etag) {
		w.WriteHeader(http.StatusNotModified)
		return
	}
	_, _ = w.Write(append(body, '\n'))
}
