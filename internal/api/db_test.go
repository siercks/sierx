package api

import (
	"context"
	"errors"
	"testing"
)

func TestRequestDBRejectsQueriesWithoutAuthenticatedScope(t *testing.T) {
	db := &requestDB{}
	ctx := context.Background()
	if _, err := db.Exec(ctx, "SELECT 1"); !errors.Is(err, errMissingRequestScope) {
		t.Fatalf("Exec without scope error = %v", err)
	}
	if _, err := db.Query(ctx, "SELECT 1"); !errors.Is(err, errMissingRequestScope) {
		t.Fatalf("Query without scope error = %v", err)
	}
	if err := db.QueryRow(ctx, "SELECT 1").Scan(new(int)); !errors.Is(err, errMissingRequestScope) {
		t.Fatalf("QueryRow without scope error = %v", err)
	}
	if _, err := db.Begin(ctx); !errors.Is(err, errMissingRequestScope) {
		t.Fatalf("Begin without scope error = %v", err)
	}
}
