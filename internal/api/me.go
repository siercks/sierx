package api

import (
	"encoding/json"
	"net/http"
	"strings"
	"unicode/utf8"
)

func (s *Server) updateMe(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	var raw map[string]json.RawMessage
	if !decodeJSON(w, r, &raw) {
		return
	}
	if len(raw) == 0 {
		requestProblem(w, "Provide theme, reduced_motion or display_name.")
		return
	}
	for field := range raw {
		switch field {
		case "theme", "reduced_motion", "display_name":
		default:
			requestProblem(w, "Field "+field+" cannot be changed here. Use the account security flow.")
			return
		}
	}
	var theme, name string
	var motion *bool
	_, setTheme := raw["theme"]
	_, setName := raw["display_name"]
	_, setMotion := raw["reduced_motion"]
	if setTheme {
		if json.Unmarshal(raw["theme"], &theme) != nil {
			requestProblem(w, "theme must be system, light, dark, light-hc or dark-hc.")
			return
		}
		switch theme {
		case "system", "light", "dark", "light-hc", "dark-hc":
		default:
			requestProblem(w, "theme must be system, light, dark, light-hc or dark-hc.")
			return
		}
	}
	if setName && (json.Unmarshal(raw["display_name"], &name) != nil || strings.TrimSpace(name) == "" || utf8.RuneCountInString(name) > 200) {
		requestProblem(w, "display_name must contain 1-200 characters.")
		return
	}
	if setMotion && json.Unmarshal(raw["reduced_motion"], &motion) != nil {
		requestProblem(w, "reduced_motion must be true, false or null.")
		return
	}
	who := Identity(r)
	err := s.Pool.QueryRow(r.Context(), `UPDATE user_account SET theme=CASE WHEN $2 THEN $3 ELSE theme END,display_name=CASE WHEN $4 THEN $5 ELSE display_name END,reduced_motion=CASE WHEN $6 THEN $7 ELSE reduced_motion END WHERE id=$1 RETURNING theme,display_name,reduced_motion`, who.ID, setTheme, theme, setName, name, setMotion, motion).Scan(&who.Theme, &who.DisplayName, &who.ReducedMotion)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	writeJSON(w, 200, who)
}
