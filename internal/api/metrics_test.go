package api

import (
	"context"
	"encoding/json"
	"math"
	"regexp"
	"strconv"
	"strings"
	"testing"
)

// Parse the emitted label-free subset of Prometheus 0.0.4: each family has
// HELP, TYPE, and one numeric sample. Reject duplicate names, invalid names,
// missing metadata, trailing tokens and non-finite or negative samples.
func parseMetrics(t *testing.T, body string) (map[string]float64, string) {
	t.Helper()
	if !strings.HasSuffix(body, "\n") {
		t.Fatal("missing final newline")
	}
	lines := strings.Split(strings.TrimSuffix(body, "\n"), "\n")
	if len(lines)%3 != 0 {
		t.Fatal("incomplete metric family")
	}
	values := map[string]float64{}
	namePattern := regexp.MustCompile(`^[a-zA-Z_:][a-zA-Z0-9_:]*$`)
	for i := 0; i < len(lines); i += 3 {
		sample := strings.Fields(lines[i+2])
		if len(sample) != 2 || !namePattern.MatchString(sample[0]) {
			t.Fatal("invalid sample", lines[i+2])
		}
		name := sample[0]
		if _, exists := values[name]; exists {
			t.Fatal("duplicate metric", name)
		}
		if !strings.HasPrefix(lines[i], "# HELP "+name+" ") || len(lines[i]) <= len("# HELP "+name+" ") {
			t.Fatal("invalid HELP")
		}
		if lines[i+1] != "# TYPE "+name+" counter" && lines[i+1] != "# TYPE "+name+" gauge" {
			t.Fatal("invalid TYPE")
		}
		value, err := strconv.ParseFloat(sample[1], 64)
		if err != nil || math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
			t.Fatal("invalid metric value")
		}
		values[name] = value
		lines[i+2] = name + " <value>"
	}
	return values, strings.Join(lines, "\n") + "\n"
}

func TestMetrics(t *testing.T) {
	s, email, uid, wid := authFixture(t)
	cookie := fixtureSession(t, s, email)
	before := s.requests.Load()
	w := apiCall(s, "GET", "/api/v1/metrics", "", cookie)
	if w.Code != 200 || w.Header().Get("Content-Type") != "text/plain; version=0.0.4; charset=utf-8" || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("metrics response: %d %v %s", w.Code, w.Header(), w.Body)
	}
	values, normalized := parseMetrics(t, w.Body.String())
	if len(values) != 5 || values["sierx_http_requests_total"] != float64(before) || values["sierx_http_requests_in_flight"] != 1 || values["sierx_database_connections"] < 1 {
		t.Fatal(values)
	}
	if s.requests.Load() != before+1 || s.inflight.Load() != 0 {
		t.Fatal("request accounting")
	}
	raw, _ := json.Marshal(map[string]string{"exposition": normalized})
	assertGolden(t, "metrics", raw, nil)
	apiCall(s, "GET", "/missing", "", cookie)
	w = apiCall(s, "GET", "/api/v1/metrics", "", cookie)
	after, _ := parseMetrics(t, w.Body.String())
	if after["sierx_http_requests_total"] != float64(before+2) || after["sierx_http_request_duration_seconds_total"] < values["sierx_http_request_duration_seconds_total"] {
		t.Fatal("counters did not advance", after)
	}
	if _, err := s.Pool.Exec(context.Background(), `UPDATE membership SET role='member' WHERE workspace_id=$1 AND user_id=$2`, wid, uid); err != nil {
		t.Fatal(err)
	}
	if w = apiCall(s, "GET", "/api/v1/metrics", "", cookie); w.Code != 403 {
		t.Fatal("member can scrape", w.Code)
	}
}
