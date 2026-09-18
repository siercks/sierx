package api

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/url"
	"slices"
	"strings"
	"time"
	"unicode/utf8"
	"uuid"
)

func (s *Server) memberExists(ctx context.Context, workspace, id string) bool {
	if _, err := uuid.Parse(id); err != nil {
		return false
	}
	var exists bool
	err := s.Pool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM membership m JOIN user_account u ON u.id=m.user_id WHERE m.workspace_id=$1 AND m.user_id=$2 AND u.is_active)`, workspace, id).Scan(&exists)
	return err == nil && exists
}

func (s *Server) validateInput(ctx context.Context, workspace, projectID string, in itemInput, titleRequired bool) error {
	if titleRequired && (strings.TrimSpace(in.Title) == "" || utf8.RuneCountInString(in.Title) > 500) {
		return fmt.Errorf("title must contain 1–500 characters")
	}
	if in.Body != nil && len(*in.Body) > 100000 {
		return fmt.Errorf("body must not exceed 100000 bytes")
	}
	if in.Points != nil && (*in.Points < 0 || *in.Points > 9999.99 || math.IsNaN(*in.Points) || math.IsInf(*in.Points, 0) || math.Abs(*in.Points*100-math.Round(*in.Points*100)) > 0.000001) {
		return fmt.Errorf("points must be between 0 and 9999.99 with at most two decimal places")
	}
	for _, value := range []*string{in.StartDate, in.DueDate} {
		if value != nil {
			if _, err := time.Parse(time.DateOnly, *value); err != nil {
				return fmt.Errorf("dates must use YYYY-MM-DD")
			}
		}
	}
	if in.Assignee != nil && !s.memberExists(ctx, workspace, *in.Assignee) {
		return fmt.Errorf("assignee must identify an active workspace member")
	}
	if len(in.Fields) == 0 {
		return nil
	}
	rows, err := s.Pool.Query(ctx, `SELECT key,data_type,options FROM field_def WHERE project_id=$1`, projectID)
	if err != nil {
		return fmt.Errorf("project field definitions could not be read; try again")
	}
	defer rows.Close()
	type definition struct {
		kind    string
		options []string
	}
	defs := map[string]definition{}
	for rows.Next() {
		var key, kind string
		var raw []byte
		if err = rows.Scan(&key, &kind, &raw); err != nil {
			return fmt.Errorf("project field definitions could not be read; try again")
		}
		var options []string
		if err = json.Unmarshal(raw, &options); err != nil {
			return fmt.Errorf("project field options are invalid; contact an administrator")
		}
		defs[key] = definition{kind, options}
	}
	if rows.Err() != nil {
		return fmt.Errorf("project field definitions could not be read; try again")
	}
	for key, value := range in.Fields {
		def, ok := defs[key]
		if !ok {
			return fmt.Errorf("custom field %q is not configured for this project", key)
		}
		if value == nil {
			continue
		}
		valid := false
		switch def.kind {
		case "text":
			_, valid = value.(string)
		case "number":
			_, valid = value.(float64)
		case "bool":
			_, valid = value.(bool)
		case "date":
			if text, ok := value.(string); ok {
				_, err := time.Parse(time.DateOnly, text)
				valid = err == nil
			}
		case "url":
			if text, ok := value.(string); ok {
				u, err := url.Parse(text)
				valid = err == nil && u.Hostname() != "" && (u.Scheme == "https" || u.Scheme == "http")
			}
		case "user":
			if id, ok := value.(string); ok {
				valid = s.memberExists(ctx, workspace, id)
			}
		case "select":
			if text, ok := value.(string); ok {
				valid = slices.Contains(def.options, text)
			}
		case "multiselect":
			if list, ok := value.([]any); ok {
				valid = true
				for _, entry := range list {
					text, ok := entry.(string)
					if !ok || !slices.Contains(def.options, text) {
						valid = false
						break
					}
				}
			}
		}
		if !valid {
			return fmt.Errorf("custom field %q must match its %s definition and configured options", key, def.kind)
		}
	}
	return nil
}
