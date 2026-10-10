package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"html"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"net/url"
	"regexp"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/siercks/sierx/internal/api/auth"
	webassets "github.com/siercks/sierx/web"
)

const listProjection = "id,key,title,version,change_seq,status,type,parent,project,assignee,rank,points,updated_at"

var documentKey = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9]{1,9}-[1-9][0-9]*$`)

func (s *Server) ConfigureDocuments() {
	s.Router.Get("/", s.document)
	s.Router.Get("/{key}", s.document)
	s.Router.Get("/{key}/", s.document)
	s.Router.Get("/assets/*", s.asset)
}

func (s *Server) document(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimSuffix(r.URL.Path, "/")
	if path == "" {
		path = "/"
	}
	key := strings.TrimPrefix(path, "/")
	if documentKey.MatchString(key) {
		path = "/" + strings.ToUpper(key)
	}
	if path != r.URL.Path {
		if r.URL.RawQuery != "" {
			path += "?" + r.URL.RawQuery
		}
		http.Redirect(w, r, path, http.StatusPermanentRedirect)
		return
	}
	handler := s.documentRoutes()[path]
	if handler == nil && documentKey.MatchString(key) {
		handler = s.documentRoutes()["/:key"]
	}
	if handler == nil {
		WriteProblem(w, NotFound())
		return
	}
	if path == "/login" || path == "/privacy" || path == "/copyright" || path == "/third-party" {
		handler(w, r)
		return
	}
	rec := httptest.NewRecorder()
	var authorized *http.Request
	s.requireAuth(http.HandlerFunc(func(_ http.ResponseWriter, request *http.Request) { authorized = request })).ServeHTTP(rec, r)
	if authorized == nil {
		if rec.Code == http.StatusUnauthorized && s.auth.cfg.AuthMode == "local" {
			http.Redirect(w, r, "/login", http.StatusSeeOther)
			return
		}
		for k, values := range rec.Header() {
			w.Header()[k] = values
		}
		w.WriteHeader(rec.Code)
		_, _ = w.Write(rec.Body.Bytes())
		return
	}
	handler(w, authorized)
}

func (s *Server) bootstrapPrivacy(w http.ResponseWriter, r *http.Request) {
	var notice map[string]string
	if s.auth != nil {
		c := s.auth.cfg
		notice = map[string]string{"operator": c.OperatorName, "contact": c.PrivacyContact, "retention": c.PrivacyRetention, "backups": c.PrivacyBackups, "services": c.PrivacyServices, "version": c.PrivacyVersion, "effective_date": c.PrivacyEffectiveDate}
	} else {
		notice = map[string]string{}
	}
	complete := true
	for _, key := range []string{"operator", "contact", "retention", "backups", "services", "version", "effective_date"} {
		if strings.TrimSpace(notice[key]) == "" {
			complete = false
		}
	}
	s.renderDocument(w, r, map[string]any{"route": "privacy", "notice": notice, "configured": complete}, auth.Identity{Theme: "system"})
}

func (s *Server) bootstrapCopyright(w http.ResponseWriter, r *http.Request) {
	notice := map[string]string{}
	if s.auth != nil {
		c := s.auth.cfg
		notice = map[string]string{"operator": c.OperatorName, "agent": c.CopyrightAgent, "contact": c.CopyrightContact, "notice_process": c.CopyrightNotice, "counter_notice_process": c.CopyrightCounterNotice, "repeat_infringer_policy": c.RepeatInfringerPolicy}
	}
	complete := true
	for _, key := range []string{"operator", "agent", "contact", "notice_process", "counter_notice_process", "repeat_infringer_policy"} {
		if strings.TrimSpace(notice[key]) == "" {
			complete = false
		}
	}
	s.renderDocument(w, r, map[string]any{"route": "copyright", "notice": notice, "configured": complete}, auth.Identity{Theme: "system"})
}

func (s *Server) bootstrapThirdParty(w http.ResponseWriter, r *http.Request) {
	data, err := fs.ReadFile(webassets.Files, "dist/third-party.json")
	if err != nil {
		WriteProblem(w, Unavailable())
		return
	}
	var inventory map[string]any
	if err = json.Unmarshal(data, &inventory); err != nil {
		WriteProblem(w, InternalError())
		return
	}
	if s.auth != nil {
		if strings.TrimSpace(s.auth.cfg.PrivacyServices) != "" {
			inventory["operator_services"] = s.auth.cfg.PrivacyServices
		}
		inventory["operator"] = s.auth.cfg.OperatorName
	}
	s.renderDocument(w, r, map[string]any{"route": "third-party", "inventory": inventory}, auth.Identity{Theme: "system"})
}

func (s *Server) bootstrapLogin(w http.ResponseWriter, r *http.Request) {
	s.renderDocument(w, r, map[string]any{"route": "login", "auth_mode": s.auth.cfg.AuthMode}, auth.Identity{Theme: "system"})
}

// captureAPI reuses the same workspace-scoped endpoint logic, without a network
// round trip or a separate authorization-free data path.
func captureAPI(r *http.Request, path string, handler http.HandlerFunc, key string) json.RawMessage {
	clone := r.Clone(r.Context())
	u := *r.URL
	clone.URL = &u
	clone.URL.Path = path
	clone.URL.RawQuery = ""
	if i := strings.IndexByte(path, '?'); i >= 0 {
		clone.URL.Path = path[:i]
		clone.URL.RawQuery = path[i+1:]
	}
	clone.Header = r.Header.Clone()
	clone.Header.Del("If-None-Match")
	clone.Header.Del("If-Match")
	route := chi.NewRouteContext()
	route.URLParams.Add("key", key)
	clone = clone.WithContext(context.WithValue(clone.Context(), chi.RouteCtxKey, route))
	rec := httptest.NewRecorder()
	handler(rec, clone)
	return json.RawMessage(rec.Body.Bytes())
}

func (s *Server) bootstrapList(w http.ResponseWriter, r *http.Request) {
	var sequence int64
	if err := s.Pool.QueryRow(r.Context(), `SELECT value FROM seq_counter WHERE workspace_id=$1`, Identity(r).WorkspaceID).Scan(&sequence); err != nil {
		databaseProblem(w, err)
		return
	}
	project := r.URL.Query().Get("project")
	if project != "" {
		var exists bool
		if err := s.Pool.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM project WHERE workspace_id=$1 AND key_prefix=$2 AND archived_at IS NULL)`, Identity(r).WorkspaceID, project).Scan(&exists); err != nil {
			databaseProblem(w, err)
			return
		}
		if !exists {
			WriteProblem(w, NotFound())
			return
		}
	}
	q := url.Values{"q": {r.URL.Query().Get("q")}}
	if project != "" {
		q.Set("project", project)
	}
	q.Set("fields", listProjection)
	q.Set("limit", "100")
	q.Del("cursor")
	data := captureAPI(r, "/api/v1/items?"+q.Encode(), s.listItems, "")
	state := map[string]any{"route": "list", "change_seq": sequence, "query": r.URL.Query().Get("q"), "project": project, "items": data,
		"projects": captureAPI(r, "/api/v1/projects?limit=100", s.listProjects, ""), "me": Identity(r), "auth_mode": s.auth.cfg.AuthMode}
	if project != "" {
		state["selected_project"] = captureAPI(r, "/api/v1/projects/"+project, s.getProject, project)
	}
	s.renderDocument(w, r, state, Identity(r))
}

func (s *Server) bootstrapItem(w http.ResponseWriter, r *http.Request) {
	var sequence int64
	if err := s.Pool.QueryRow(r.Context(), `SELECT value FROM seq_counter WHERE workspace_id=$1`, Identity(r).WorkspaceID).Scan(&sequence); err != nil {
		databaseProblem(w, err)
		return
	}
	key := strings.TrimPrefix(r.URL.Path, "/")
	data := captureAPI(r, "/api/v1/items/"+key, s.getItem, key)
	state := map[string]any{"route": "item", "change_seq": sequence, "item": data, "me": Identity(r), "auth_mode": s.auth.cfg.AuthMode}
	var item struct {
		Key       string `json:"key"`
		Title     string `json:"title"`
		Project struct {
			Key string `json:"key_prefix"`
		} `json:"project"`
		DeletedAt *string `json:"deleted_at"`
	}
	if json.Unmarshal(data, &item) == nil && item.Project.Key != "" {
		state["document_title"] = item.Key + " · " + item.Title + " · Sierx"
		state["config"] = captureAPI(r, "/api/v1/projects/"+item.Project.Key+"/config", s.projectConfig, item.Project.Key)
		state["history"] = captureAPI(r, "/api/v1/items/"+key+"/history", s.itemHistory, key)
		if item.DeletedAt == nil {
			children := url.Values{"q": {fmt.Sprintf("parent = %q order by rank", key)}, "fields": {"key,title,status,rank"}, "limit": {"100"}}
			state["children"] = captureAPI(r, "/api/v1/items?"+children.Encode(), s.listItems, "")
			state["comments"] = captureAPI(r, "/api/v1/comments?item="+key, s.listComments, key)
			state["links"] = captureAPI(r, "/api/v1/items/"+key+"/links", s.listLinks, key)
		}
	}
	s.renderDocument(w, r, state, Identity(r))
}

func (s *Server) renderDocument(w http.ResponseWriter, r *http.Request, state map[string]any, who auth.Identity) {
	template, err := fs.ReadFile(webassets.Files, "dist/index.html")
	if err != nil {
		WriteProblem(w, Unavailable())
		return
	}
	// json.Marshal escapes script terminators even inside nested RawMessage data.
	payload, err := json.Marshal(state)
	if err != nil {
		WriteProblem(w, InternalError())
		return
	}
	theme := canonicalTheme(who.Theme)
	motion := "system"
	if who.ReducedMotion != nil {
		if *who.ReducedMotion {
			motion = "reduce"
		} else {
			motion = "full"
		}
	}
	template = bytes.Replace(template, []byte(`data-theme="system"`), []byte(`data-theme="`+theme+`"`), 1)
	template = bytes.Replace(template, []byte(`data-motion="system"`), []byte(`data-motion="`+motion+`"`), 1)
	title := "Sierx"
	switch state["route"] {
	case "login": title = "Sign in · Sierx"
	case "list":
		if project, ok := state["selected_project"].(json.RawMessage); ok {
			var metadata struct { Name string `json:"name"` }
			if json.Unmarshal(project, &metadata) == nil && metadata.Name != "" { title = metadata.Name + " · Sierx" } else { title = "Workspace · Sierx" }
		} else { title = "Workspace · Sierx" }
	case "item": title = "Work item · Sierx"
	case "privacy": title = "Privacy · Sierx"
	case "copyright": title = "Copyright · Sierx"
	case "third-party": title = "Third-party notices · Sierx"
	}
	if custom, ok := state["document_title"].(string); ok && custom != "" { title = custom }
	template = bytes.Replace(template, []byte(`<title>Sierx</title>`), []byte(`<title>`+html.EscapeString(title)+`</title>`), 1)
	bootstrap := append([]byte(`<script id="sierx-state" type="application/json">`), payload...)
	bootstrap = append(bootstrap, []byte("</script></head>")...)
	template = bytes.Replace(template, []byte("</head>"), bootstrap, 1)
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Add("Vary", "Cookie")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "same-origin")
	w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
	_, _ = w.Write(template)
}

func (s *Server) asset(w http.ResponseWriter, r *http.Request) {
	path := "dist" + r.URL.Path
	if strings.Contains(path, "..") || !(strings.HasSuffix(path, ".js") || strings.HasSuffix(path, ".css")) {
		http.NotFound(w, r)
		return
	}
	content, err := fs.ReadFile(webassets.Files, path)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	if strings.HasSuffix(path, ".js") {
		w.Header().Set("Content-Type", "text/javascript; charset=utf-8")
	} else {
		w.Header().Set("Content-Type", "text/css; charset=utf-8")
	}
	w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	w.Header().Set("Vary", "Accept-Encoding")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	coding, ok := encodingChoice(r.Header.Get("Accept-Encoding"))
	if !ok {
		w.WriteHeader(http.StatusNotAcceptable)
		return
	}
	if coding != "" {
		suffix := ".br"
		if coding == "gzip" {
			suffix = ".gz"
		}
		if compressed, e := fs.ReadFile(webassets.Files, path+suffix); e == nil {
			content = compressed
			w.Header().Set("Content-Encoding", coding)
		}
	}
	_, _ = w.Write(content)
}
