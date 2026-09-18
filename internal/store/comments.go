package store

import (
	"context"
	"github.com/jackc/pgx/v5"
	"github.com/siercks/sierx/internal/store/gen"
)

func applyComment(ctx context.Context, db gen.DBTX, m *Mutation, c *CommentChange) error {
	switch c.Action {
	case "create":
		_, err := db.Exec(ctx, `INSERT INTO comment(id,item_id,author_id,body) VALUES($1,$2,$3,$4)`, c.ID.String(), c.ItemID.String(), m.actorID.String(), c.Body)
		return err
	case "edit":
		tag, err := db.Exec(ctx, `UPDATE comment SET body=$3,edited_at=now() WHERE id=$1 AND item_id=$2 AND deleted_at IS NULL`, c.ID.String(), c.ItemID.String(), c.Body)
		if err != nil {
			return err
		}
		if tag.RowsAffected() != 1 {
			return pgx.ErrNoRows
		}
	case "delete":
		tag, err := db.Exec(ctx, `UPDATE comment SET deleted_at=now() WHERE id=$1 AND item_id=$2 AND deleted_at IS NULL`, c.ID.String(), c.ItemID.String())
		if err != nil {
			return err
		}
		if tag.RowsAffected() != 1 {
			return pgx.ErrNoRows
		}
	}
	return nil
}
