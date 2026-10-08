package api

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAppearanceThemeCatalogMatchesTokens(t *testing.T) {
	entries, err := os.ReadDir(filepath.Join("..", "..", "web", "design", "tokens"))
	if err != nil {
		t.Fatal(err)
	}
	found := map[string]bool{}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") || entry.Name()[0] < '0' || entry.Name()[0] > '9' {
			continue
		}
		data, err := os.ReadFile(filepath.Join("..", "..", "web", "design", "tokens", entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		var token struct{ ID string `json:"id"` }
		if err := json.Unmarshal(data, &token); err != nil {
			t.Fatalf("%s: %v", entry.Name(), err)
		}
		if !validAppearanceTheme(token.ID) {
			t.Errorf("token theme %q is not accepted by the API", token.ID)
		}
		found[token.ID] = true
	}
	if len(found) != len(appearanceThemes) {
		t.Fatalf("found %d token themes, API accepts %d", len(found), len(appearanceThemes))
	}
	for _, theme := range appearanceThemes {
		if !found[theme] {
			t.Errorf("API theme %q has no token file", theme)
		}
	}
	for _, theme := range legacyThemes {
		if !validTheme(theme) {
			t.Errorf("legacy theme %q no longer renders", theme)
		}
	}
	for legacy, want := range map[string]string{
		"light": "quiet", "dark": "dusk", "light-hc": "eink", "dark-hc": "eink-dark",
	} {
		if got := canonicalTheme(legacy); got != want {
			t.Errorf("legacy theme %q renders as %q; want %q", legacy, got, want)
		}
	}
	if validTheme("unlisted-theme") {
		t.Fatal("unknown theme accepted")
	}
	if got := canonicalTheme("unlisted-theme"); got != "system" {
		t.Errorf("unknown theme renders as %q; want system", got)
	}
}

func validAppearanceTheme(theme string) bool {
	for _, candidate := range appearanceThemes {
		if candidate == theme {
			return true
		}
	}
	return false
}
