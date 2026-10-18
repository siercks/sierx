package api

import (
	"context"
	"errors"
	"net/http"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

type requestTxKey struct{}

var errMissingRequestScope = errors.New("database query requires an authenticated request scope")

type failedRow struct{ err error }

func (r failedRow) Scan(...any) error { return r.err }

type requestDB struct {
	pool *pgxpool.Pool
}

func (db *requestDB) transaction(ctx context.Context) pgx.Tx {
	tx, _ := ctx.Value(requestTxKey{}).(pgx.Tx)
	return tx
}

func (db *requestDB) Exec(ctx context.Context, sql string, args ...any) (pgconn.CommandTag, error) {
	if tx := db.transaction(ctx); tx != nil {
		return tx.Exec(ctx, sql, args...)
	}
	return pgconn.CommandTag{}, errMissingRequestScope
}

func (db *requestDB) Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error) {
	if tx := db.transaction(ctx); tx != nil {
		return tx.Query(ctx, sql, args...)
	}
	return nil, errMissingRequestScope
}

func (db *requestDB) QueryRow(ctx context.Context, sql string, args ...any) pgx.Row {
	if tx := db.transaction(ctx); tx != nil {
		return tx.QueryRow(ctx, sql, args...)
	}
	return failedRow{err: errMissingRequestScope}
}

func (db *requestDB) Begin(ctx context.Context) (pgx.Tx, error) {
	if tx := db.transaction(ctx); tx != nil {
		return tx.Begin(ctx)
	}
	return nil, errMissingRequestScope
}

func (db *requestDB) Ping(ctx context.Context) error {
	return db.pool.Ping(ctx)
}

func (db *requestDB) Stat() *pgxpool.Stat {
	return db.pool.Stat()
}

// withRequestScope binds the authenticated identity to one transaction. Every
// endpoint query uses this transaction, and SET LOCAL clears the identity when
// the transaction ends, including on rollback or cancellation.
func (s *Server) withRequestScope(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if s.rawPool == nil {
			WriteProblem(w, Unavailable())
			return
		}
		who := Identity(r)
		tx, err := s.rawPool.Begin(r.Context())
		if err != nil {
			databaseProblem(w, err)
			return
		}
		defer tx.Rollback(context.Background())
		_, err = tx.Exec(r.Context(), `SELECT set_config('sierx.workspace_id',$1,true),set_config('sierx.user_id',$2,true),set_config('sierx.role',$3,true)`, who.WorkspaceID, who.ID, who.Role)
		if err != nil {
			databaseProblem(w, err)
			return
		}
		ctx := context.WithValue(r.Context(), requestTxKey{}, tx)
		next.ServeHTTP(w, r.WithContext(ctx))
		if err := tx.Commit(r.Context()); err != nil && s.Logger != nil {
			s.Logger.Error("request database transaction could not commit", "error", err)
		}
	})
}
