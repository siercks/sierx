package api

import "slices"

// appearanceThemes is the persisted, user-selectable design catalog. Keep it
// aligned with web/design/tokens; TestAppearanceThemeCatalogMatchesTokens guards
// the boundary between the server and the generated browser themes.
var appearanceThemes = []string{
	"swiss", "quiet", "ledger", "commander", "platinum", "blueprint",
	"eink", "eink-dark", "ticker", "plain", "brutal", "civic", "dusk",
	"cockpit", "chart", "appliance", "redlight", "celadon", "riso",
	"vellum", "kraft", "indigo", "indexcard",
}

var legacyThemes = []string{"system", "light", "dark", "light-hc", "dark-hc"}

func validTheme(theme string) bool {
	return slices.Contains(appearanceThemes, theme) || slices.Contains(legacyThemes, theme)
}

func canonicalTheme(theme string) string {
	switch theme {
	case "light":
		return "quiet"
	case "dark":
		return "dusk"
	case "light-hc":
		return "eink"
	case "dark-hc":
		return "eink-dark"
	default:
		if validTheme(theme) {
			return theme
		}
		return "system"
	}
}
