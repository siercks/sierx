package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"uuid"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/siercks/sierx/internal/store"
)

func (s *Server) moveItem(w http.ResponseWriter, r *http.Request) {
	if !rejectFields(w, r) {
		return
	}
	version, ok := expectedVersion(w, r)
	if !ok {
		return
	}
	var in struct {
		Parent    json.RawMessage `json:"parent"`
		RankAfter json.RawMessage `json:"rank_after"`
	}
	if !decodeJSON(w, r, &in) {
		return
	}
	if len(in.Parent) == 0 {
		requestProblem(w, "Provide parent as an item key or null for a root item.")
		return
	}
	var parentKey, afterKey *string
	if json.Unmarshal(in.Parent, &parentKey) != nil || (len(in.RankAfter) > 0 && json.Unmarshal(in.RankAfter, &afterKey) != nil) {
		requestProblem(w, "parent and rank_after must be item keys or null.")
		return
	}
	who := Identity(r)
	key := chi.URLParam(r, "key")
	var idString, project, path string
	err := s.Pool.QueryRow(r.Context(), `SELECT i.id::text,p.key_prefix,i.path::text FROM item i JOIN project p ON p.id=i.project_id WHERE i.workspace_id=$1 AND i.key=$2 AND i.deleted_at IS NULL`, who.WorkspaceID, key).Scan(&idString, &project, &path)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	id, _ := uuid.Parse(idString)
	move := store.ItemReparent{ID: id, SetRank: len(in.RankAfter) > 0}
	parentDepth := 0
	if parentKey != nil {
		var parentID, parentProject, parentPath string
		err = s.Pool.QueryRow(r.Context(), `SELECT i.id::text,p.key_prefix,i.path::text FROM item i JOIN project p ON p.id=i.project_id WHERE i.workspace_id=$1 AND i.key=$2 AND i.deleted_at IS NULL`, who.WorkspaceID, *parentKey).Scan(&parentID, &parentProject, &parentPath)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				invalidChange(w, fmt.Sprintf("Parent item %s was not found. Enter a live item key in project %s.", *parentKey, project))
				return
			}
			databaseProblem(w, err)
			return
		}
		if parentProject != project {
			invalidChange(w, fmt.Sprintf("Cannot move an item from project %s under a parent in project %s. Choose a parent in %s.", project, parentProject, project))
			return
		}
		if parentPath == path || strings.HasPrefix(parentPath, path+".") {
			invalidChange(w, "parent cannot be this item or one of its descendants.")
			return
		}
		v, _ := uuid.Parse(parentID)
		move.NewParentID = &v
		parentDepth = strings.Count(parentPath, ".") + 1
	}
	var height int
	err = s.Pool.QueryRow(r.Context(), `SELECT max(nlevel(path))-nlevel($1::ltree)+1 FROM item WHERE path <@ $1::ltree`, path).Scan(&height)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	if parentDepth+height > 8 {
		invalidChange(w, "parent would place this item or its descendants beyond the maximum depth of 8.")
		return
	}
	if afterKey != nil {
		var afterID string
		err = s.Pool.QueryRow(r.Context(), `SELECT i.id::text FROM item i JOIN project p ON p.id=i.project_id WHERE i.workspace_id=$1 AND i.key=$2 AND p.key_prefix=$3 AND i.deleted_at IS NULL`, who.WorkspaceID, *afterKey, project).Scan(&afterID)
		if err != nil {
			invalidChange(w, "rank_after must name another live item in the same project.")
			return
		}
		v, _ := uuid.Parse(afterID)
		if v == id {
			invalidChange(w, "rank_after cannot name the item being moved.")
			return
		}
		move.RankAfter = &v
	}
	wid, _ := uuid.Parse(who.WorkspaceID)
	actor, _ := uuid.Parse(who.ID)
	_, err = store.New(s.Pool).Mutate(r.Context(), wid, func(m *store.Mutation) error { m.Reparent(move); return nil }, store.WithActor(actor), store.WithExpectedVersion(id, version))
	if errors.Is(err, store.ErrInvalidMove) {
		invalidChange(w, "The hierarchy changed. Choose a live parent without cycles and within depth 8, then retry.")
		return
	}
	if err != nil {
		s.mutationError(w, r, err, in)
		return
	}
	doc, v, err := s.readItem(r.Context(), who.WorkspaceID, key, nil)
	if err != nil {
		databaseProblem(w, err)
		return
	}
	w.Header().Set("ETag", fmt.Sprintf(`"%d"`, v))
	writeJSON(w, 200, doc)
}
