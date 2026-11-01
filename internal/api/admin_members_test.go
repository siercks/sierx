package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"net/url"
	"os/exec"
	"strings"
	"testing"
	"uuid"

	"github.com/jackc/pgx/v5/pgconn"
	"github.com/siercks/sierx/internal/api/auth"
	"github.com/siercks/sierx/internal/config"
)

func TestAdminMemberProvisioningAuthorizationAndCredentials(t *testing.T) {
	s, email, adminID, workspace := authFixture(t)
	admin := fixtureSession(t, s, email)
	password := "private-test-password-12345"
	payload := `{"display_name":"New member","email":"new-member@example.test","initial_password":"` + password + `"}`
	created := apiCall(s, "POST", "/api/v1/admin/members", payload, admin)
	if created.Code != 201 {
		t.Fatal(created.Code, created.Body)
	}
	if created.Header().Get("Cache-Control") != "no-store" || strings.Contains(created.Body.String(), password) || strings.Contains(created.Body.String(), "password_hash") {
		t.Fatal("credential leak", created.Body)
	}
	var member AdminMember
	if err := json.Unmarshal(created.Body.Bytes(), &member); err != nil || member.Role != "member" || !member.Active {
		t.Fatal(member, err)
	}
	assertGolden(t, "admin-member-created", created.Body.Bytes(), map[string]string{member.ID: "member-1"})
	var hash, oldAdminHash string
	if err := s.Pool.QueryRow(context.Background(), `SELECT password_hash FROM user_account WHERE id=$1`, member.ID).Scan(&hash); err != nil || !auth.VerifyPassword(hash, password) {
		t.Fatal("new password is unusable", err)
	}
	if err := s.Pool.QueryRow(context.Background(), `SELECT password_hash FROM user_account WHERE id=$1`, adminID).Scan(&oldAdminHash); err != nil {
		t.Fatal(err)
	}
	if w := apiCall(s, "POST", "/api/v1/admin/members", strings.ReplaceAll(payload, password, "replacement-password-12345"), admin); w.Code != 409 {
		t.Fatal("duplicate email", w.Code, w.Body)
	}
	var after string
	if err := s.Pool.QueryRow(context.Background(), `SELECT password_hash FROM user_account WHERE id=$1`, member.ID).Scan(&after); err != nil || after != hash {
		t.Fatal("existing credential replaced", err)
	}
	if err := s.Pool.QueryRow(context.Background(), `SELECT password_hash FROM user_account WHERE id=$1`, adminID).Scan(&after); err != nil || after != oldAdminHash {
		t.Fatal("administrator credential changed", err)
	}
	login := apiCall(s, "POST", "/api/v1/auth/login", `{"email":"new-member@example.test","password":"`+password+`"}`, nil)
	if login.Code != 200 {
		t.Fatal("member login", login.Code, login.Body)
	}
	memberCookie := login.Result().Cookies()[0]
	for _, method := range []string{"GET", "POST"} {
		if w := apiCall(s, method, "/api/v1/admin/members", payload, memberCookie); w.Code != 403 {
			t.Fatal("member accessed administration", method, w.Code)
		}
	}
	roster := apiCall(s, "GET", "/api/v1/members?q=New", "", memberCookie)
	if roster.Code != 200 || !strings.Contains(roster.Body.String(), member.ID) || strings.Contains(roster.Body.String(), "email") || strings.Contains(roster.Body.String(), password) {
		t.Fatal("assignment roster", roster.Code, roster.Body)
	}
	list := apiCall(s, "GET", "/api/v1/admin/members?q=new-member&limit=1", "", admin)
	if list.Code != 200 || !strings.Contains(list.Body.String(), "new-member@example.test") || strings.Contains(list.Body.String(), "password") {
		t.Fatal("admin list", list.Code, list.Body)
	}
	assertGolden(t, "admin-members", list.Body.Bytes(), map[string]string{member.ID: "member-1"})
	for _, body := range []string{
		`{"display_name":" ","email":"bad","initial_password":"short"}`,
		`{"display_name":"Member","email":"\"space local\"@example.test","initial_password":"long-password-12345"}`,
		`{"display_name":"Member","email":"\"quoted@local\"@example.test","initial_password":"long-password-12345"}`,
		`{"display_name":"Member","email":"valid@example.test","initial_password":"short"}`,
		`{"display_name":"Member","email":"valid@example.test","initial_password":"long-password-12345","role":"admin"}`,
		`{"display_name":"Member","email":"valid@example.test","initial_password":"long-password-12345","workspace_id":"` + workspace + `"}`,
	} {
		if w := apiCall(s, "POST", "/api/v1/admin/members", body, admin); w.Code != 400 {
			t.Fatal("invalid input", w.Code, w.Body)
		}
	}
	s.ConfigureDocuments()
	document := httptest.NewRecorder()
	r := httptest.NewRequest("GET", "/admin", nil)
	r.AddCookie(memberCookie)
	s.Router.ServeHTTP(document, r)
	if document.Code != 403 {
		t.Fatal("member admin document", document.Code)
	}
	document = httptest.NewRecorder()
	r = httptest.NewRequest("GET", "/admin", nil)
	r.AddCookie(admin)
	s.Router.ServeHTTP(document, r)
	if document.Code != 200 || !strings.Contains(document.Body.String(), "Administrator Home") {
		t.Fatal("admin document", document.Code, document.Body)
	}
	s.auth.cfg = config.Env{AuthMode: "proxy"}
	direct := httptest.NewRecorder()
	// Route authentication remains separately covered; assert mode at the handler boundary.
	proxyRequest := httptest.NewRequest("POST", "/api/v1/admin/members", strings.NewReader(payload))
	proxyRequest = proxyRequest.WithContext(context.WithValue(proxyRequest.Context(), identityKey{}, auth.Identity{Role: "admin"}))
	s.addAdminMember(direct, proxyRequest)
	if direct.Code != 400 {
		t.Fatal("proxy provisioning", direct.Code)
	}
}

func TestAdminMemberFunctionRejectsForgedOrMissingScope(t *testing.T) {
	s, _, adminID, workspace := authFixture(t)
	ctx := context.Background()
	otherUser := uuid.NewV7().String()
	if _, err := s.Pool.Exec(ctx, `INSERT INTO user_account(id,email,display_name) VALUES($1,$2,'Regular member');`, otherUser, otherUser+"@example.test"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Pool.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$2,'member')`, workspace, otherUser); err != nil {
		t.Fatal(err)
	}
	hash, err := auth.HashPassword("private-test-password-12345")
	if err != nil {
		t.Fatal(err)
	}
	for _, identity := range []struct{ user, workspace, role string }{
		{otherUser, workspace, "admin"}, {adminID, uuid.NewV7().String(), "admin"}, {"", workspace, "admin"}, {adminID, workspace, "member"}, {"", "", ""},
	} {
		tx, err := s.Pool.Begin(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = tx.Exec(ctx, `SET LOCAL ROLE sierx_runtime`); err != nil {
			t.Fatal(err)
		}
		if _, err = tx.Exec(ctx, `SELECT set_config('sierx.user_id',$1,true),set_config('sierx.workspace_id',$2,true),set_config('sierx.role',$3,true)`, identity.user, identity.workspace, identity.role); err != nil {
			t.Fatal(err)
		}
		_, err = tx.Exec(ctx, `SELECT public.sierx_admin_add_member('forged@example.test','Forged',$1)`, hash)
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "42501" {
			t.Fatal("forged context accepted", identity, err)
		}
		tx.Rollback(ctx)
		tx, err = s.Pool.Begin(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = tx.Exec(ctx, `SET LOCAL ROLE sierx_runtime`); err != nil {
			t.Fatal(err)
		}
		if _, err = tx.Exec(ctx, `SELECT set_config('sierx.user_id',$1,true),set_config('sierx.workspace_id',$2,true),set_config('sierx.role',$3,true)`, identity.user, identity.workspace, identity.role); err != nil {
			t.Fatal(err)
		}
		_, err = tx.Exec(ctx, `SELECT * FROM public.sierx_admin_list_members($1::uuid,$2::uuid,'',1)`, zeroID, adminID)
		if !errors.As(err, &pgErr) || pgErr.Code != "42501" {
			t.Fatal("forged list context accepted", identity, err)
		}
		tx.Rollback(ctx)
	}
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SET LOCAL ROLE sierx_runtime`); err != nil {
		t.Fatal(err)
	}
	if _, err = tx.Exec(ctx, `SELECT set_config('sierx.user_id',$1,true),set_config('sierx.workspace_id',$2,true),set_config('sierx.role','admin',true)`, adminID, workspace); err != nil {
		t.Fatal(err)
	}
	var added string
	if err = tx.QueryRow(ctx, `SELECT public.sierx_admin_add_member('runtime-created@example.test','Runtime member',$1)::text`, hash).Scan(&added); err != nil || added == "" {
		t.Fatal("restricted runtime cannot create authorized member", err)
	}
	if err = tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	var secretReadable, canLogin, canRuntimeInsert bool
	if err = s.Pool.QueryRow(ctx, `SELECT has_column_privilege('sierx_member_provisioner','user_account','password_hash','SELECT'),
        (SELECT rolcanlogin FROM pg_roles WHERE rolname='sierx_member_provisioner'),has_column_privilege('sierx_runtime','user_account','password_hash','INSERT')`).Scan(&secretReadable, &canLogin, &canRuntimeInsert); err != nil || secretReadable || canLogin || canRuntimeInsert {
		t.Fatal("provisioning privilege boundary", err)
	}
}

func TestAdminMemberListIsolationAndPagination(t *testing.T) {
	s, email, _, workspace := authFixture(t)
	cookie := fixtureSession(t, s, email)
	ctx := context.Background()
	expected := map[string]bool{}
	for _, active := range []bool{true, false} {
		id := uuid.NewV7().String()
		if _, err := s.Pool.Exec(ctx, `INSERT INTO user_account(id,email,display_name,is_active) VALUES($1,$2,'Searchable member',$3)`, id, id+"@example.test", active); err != nil {
			t.Fatal(err)
		}
		if _, err := s.Pool.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$2,'member')`, workspace, id); err != nil {
			t.Fatal(err)
		}
		expected[id] = active
	}
	foreignWorkspace, foreignUser := uuid.NewV7().String(), uuid.NewV7().String()
	if _, err := s.Pool.Exec(ctx, `INSERT INTO workspace(id,slug,name,origin_id) VALUES($1,$2,'Other workspace',$1)`, foreignWorkspace, "other-"+foreignWorkspace); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Pool.Exec(ctx, `INSERT INTO user_account(id,email,display_name) VALUES($1,$2,'Searchable outsider')`, foreignUser, foreignUser+"@example.test"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Pool.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$2,'admin')`, foreignWorkspace, foreignUser); err != nil {
		t.Fatal(err)
	}
	type memberPage struct {
		Data       []AdminMember `json:"data"`
		NextCursor *string       `json:"next_cursor"`
	}
	read := func(path string) memberPage {
		t.Helper()
		response := apiCall(s, "GET", path, "", cookie)
		if response.Code != 200 {
			t.Fatal(response.Code, response.Body)
		}
		var page memberPage
		if err := json.Unmarshal(response.Body.Bytes(), &page); err != nil {
			t.Fatal(err)
		}
		return page
	}
	base := "/api/v1/admin/members?q=Searchable&limit=1"
	first := read(base)
	if len(first.Data) != 1 || first.NextCursor == nil {
		t.Fatal("first page", first)
	}
	// Later accounts must not drift into this traversal's signed upper bound.
	later := uuid.NewV7().String()
	if _, err := s.Pool.Exec(ctx, `INSERT INTO user_account(id,email,display_name) VALUES($1,$2,'Searchable later')`, later, later+"@example.test"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Pool.Exec(ctx, `INSERT INTO membership(workspace_id,user_id,role) VALUES($1,$2,'member')`, workspace, later); err != nil {
		t.Fatal(err)
	}
	second := read(base + "&cursor=" + url.QueryEscape(*first.NextCursor))
	if len(second.Data) != 1 || second.NextCursor != nil {
		t.Fatal("second page", second)
	}
	for _, member := range append(first.Data, second.Data...) {
		active, ok := expected[member.ID]
		if !ok || member.Active != active || member.Role != "member" {
			t.Fatal("unscoped or inconsistent list", member)
		}
		delete(expected, member.ID)
	}
	if len(expected) != 0 {
		t.Fatal("missing members", expected)
	}
	if changed := apiCall(s, "GET", "/api/v1/admin/members?q=outsider&cursor="+url.QueryEscape(*first.NextCursor), "", cookie); changed.Code != 400 {
		t.Fatal("cursor accepted changed search", changed.Code)
	}
	if outsider := read("/api/v1/admin/members?q=" + foreignUser); len(outsider.Data) != 0 {
		t.Fatal("foreign email disclosed", outsider)
	}
}

func TestAdminMemberMigrationPreservesPopulatedAccountsAndItems(t *testing.T) {
	s, email, _, _ := authFixture(t)
	cookie := fixtureSession(t, s, email)
	for _, request := range []struct{ path, body string }{
		{"/api/v1/projects", `{"key_prefix":"MIG","name":"Migration fixture","kind":"delivery"}`},
		{"/api/v1/items", `{"project":"MIG","type":"story","title":"Keep this backlog item"}`},
	} {
		response := apiCall(s, "POST", request.path, request.body, cookie)
		if response.Code != 201 {
			t.Fatal(response.Code, response.Body)
		}
	}
	migrate := func(direction string) {
		t.Helper()
		command := exec.Command("../../bin/goose", "-dir", "../../migrations", "postgres", s.Pool.Config().ConnString(), direction)
		if output, err := command.CombinedOutput(); err != nil {
			t.Fatalf("member migration %s: %v %s", direction, err, output)
		}
	}
	fingerprint := func() string {
		t.Helper()
		// Compare all columns, including credential hashes, without printing them.
		var result string
		if err := s.Pool.QueryRow(context.Background(), `SELECT md5(jsonb_build_object(
            'users',(SELECT jsonb_agg(to_jsonb(u) ORDER BY id) FROM user_account u),
            'members',(SELECT jsonb_agg(to_jsonb(m) ORDER BY workspace_id,user_id) FROM membership m),
            'projects',(SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM project p),
            'items',(SELECT jsonb_agg(to_jsonb(i) ORDER BY id) FROM item i))::text)`).Scan(&result); err != nil {
			t.Fatal(err)
		}
		return result
	}
	migrate("down") // Schema 15 with existing administrator, membership and item.
	before := fingerprint()
	migrate("up")
	if fingerprint() != before {
		t.Fatal("schema 15 to 16 changed existing records")
	}
	password := "migration-member-password-12345"
	response := apiCall(s, "POST", "/api/v1/admin/members", `{"display_name":"Migration member","email":"migration@example.test","initial_password":"`+password+`"}`, cookie)
	if response.Code != 201 {
		t.Fatal(response.Code, response.Body)
	}
	before = fingerprint()
	migrate("down")
	if fingerprint() != before {
		t.Fatal("schema 16 rollback deleted or changed records")
	}
	migrate("up")
	if fingerprint() != before {
		t.Fatal("schema 16 reapply changed records")
	}
	login := apiCall(s, "POST", "/api/v1/auth/login", `{"email":"migration@example.test","password":"`+password+`"}`, nil)
	if login.Code != 200 {
		t.Fatal("preserved member cannot sign in", login.Code)
	}
	t.Log("Populated 15→16→15→16 preserved accounts, credential hashes, memberships, projects and items; member login passed.")
}
