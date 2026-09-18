package store

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

// Conversions between the store's plain Go types and pgx's wire types. Kept in
// one file so no other file has to think about pgtype.

func toPgNumeric(v *float64) pgtype.Numeric {
	if v == nil {
		return pgtype.Numeric{}
	}
	var n pgtype.Numeric
	// Scan from the decimal text form rather than building the mantissa by
	// hand: points is numeric(6,2) and float rounding would show up as
	// 2.9999999 in the column.
	if err := n.Scan(fmt.Sprintf("%.2f", *v)); err != nil {
		return pgtype.Numeric{}
	}
	return n
}

func fromPgNumeric(n pgtype.Numeric) *float64 {
	if !n.Valid {
		return nil
	}
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return nil
	}
	v := f.Float64
	return &v
}

// toPgDate takes a YYYY-MM-DD string: due dates, start dates and sprint bounds
// are dates, not timestamps (§A.3), and a Go time.Time invites a timezone.
func toPgDate(s *string) pgtype.Date {
	if s == nil || *s == "" {
		return pgtype.Date{}
	}
	t, err := time.Parse(time.DateOnly, *s)
	if err != nil {
		return pgtype.Date{}
	}
	return pgtype.Date{Time: t, Valid: true}
}

func fromPgDate(d pgtype.Date) *string {
	if !d.Valid {
		return nil
	}
	s := d.Time.Format(time.DateOnly)
	return &s
}

// marshalFields renders item.fields. The column is `jsonb NOT NULL DEFAULT
// '{}'`, and an explicit NULL in an INSERT bypasses the default, so a nil map
// becomes an empty object rather than nil bytes.
func marshalFields(f map[string]any) ([]byte, error) {
	if f == nil {
		return []byte("{}"), nil
	}
	return json.Marshal(f)
}

// marshalFieldsPatch is the update form: nil means "leave the column alone",
// which the query's coalesce() handles.
func marshalFieldsPatch(f map[string]any) ([]byte, error) {
	if f == nil {
		return nil, nil
	}
	return json.Marshal(f)
}
