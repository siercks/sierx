package seed

import (
	"context"
	"github.com/jackc/pgx/v5"
	"github.com/siercks/sierx/internal/store/gen"
)

// InstallConfig installs the established seed configuration without seed items.
// Callers create the project and call this within the same transaction.
func InstallConfig(ctx context.Context, db gen.DBTX, projectID string) error {
	if _, err := db.Exec(ctx, `INSERT INTO project_config(project_id,version) VALUES($1,1)`, projectID); err != nil {
		return err
	}
	_, err := db.Exec(ctx, configSQL, pgx.QueryExecModeSimpleProtocol, projectID, int32(1))
	return err
}
