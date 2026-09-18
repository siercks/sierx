package store

import (
	"errors"
	"fmt"
	"strings"
)

// LexoRank-style ordering (SPEC §5.5). A rank is a string over a fixed
// alphabet; to place an item between two neighbours you generate a string that
// sorts strictly between theirs. Never integer positions: every reorder would
// rewrite the whole column.
//
// The alphabet is '0'-'9' then 'a'-'z', which sorts identically under Go's
// byte comparison and under Postgres's C collation — the database column is
// `text` and the C locale is pinned for exactly this kind of reason (§4.4).
// Uppercase is deliberately excluded: mixing cases makes the two orderings
// disagree.
const rankAlphabet = "0123456789abcdefghijklmnopqrstuvwxyz"

// RankRebalanceThreshold is the length at which a generated rank triggers a
// project rebalance (§5.5).
const RankRebalanceThreshold = 40

var (
	// RankFirst and RankLast bracket the initial space. Starting in the middle
	// leaves room to append and prepend without immediately lengthening.
	RankFirst = "n"
	RankLast  = "u"

	ErrRankOrder = errors.New("store: rank bounds are not in ascending order")
)

func rankIndex(b byte) int { return strings.IndexByte(rankAlphabet, b) }

// rankAt returns the digit at position i, or 0 ('0') past the end of s.
func rankAt(s string, i int) int {
	if i >= len(s) {
		return 0
	}
	return rankIndex(s[i])
}

// RankBetween returns a rank that sorts strictly between lo and hi. An empty
// lo means "before everything", an empty hi means "after everything".
//
// The result is the shortest string in that interval, which is what keeps ranks
// from growing under normal use: repeated appends stay one character until the
// alphabet is exhausted at that position.
func RankBetween(lo, hi string) (string, error) {
	if lo != "" && hi != "" && lo >= hi {
		return "", fmt.Errorf("%w: %q >= %q", ErrRankOrder, lo, hi)
	}
	if hi == "" {
		// After everything: bump the last digit if there is room, else append.
		if lo == "" {
			return RankFirst, nil
		}
		last := len(lo) - 1
		if d := rankIndex(lo[last]); d < len(rankAlphabet)-1 {
			return lo[:last] + string(rankAlphabet[d+1]), nil
		}
		return lo + RankFirst, nil
	}

	var b strings.Builder
	for i := 0; ; i++ {
		dlo, dhi := rankAt(lo, i), rankAt(hi, i)
		if dlo == dhi {
			// Shared prefix; keep descending.
			b.WriteByte(rankAlphabet[dlo])
			continue
		}
		if dhi-dlo > 1 {
			// Room for a digit strictly between them.
			b.WriteByte(rankAlphabet[(dlo+dhi)/2])
			return b.String(), nil
		}
		// Adjacent digits: take the lower one and extend past lo's remainder.
		b.WriteByte(rankAlphabet[dlo])
		for j := i + 1; ; j++ {
			dl := rankAt(lo, j)
			if dl < len(rankAlphabet)-1 {
				// Midpoint between lo's digit and the top of the alphabet keeps
				// the result well clear of both neighbours.
				b.WriteByte(rankAlphabet[(dl+len(rankAlphabet))/2])
				return b.String(), nil
			}
			b.WriteByte(rankAlphabet[dl])
		}
	}
}

// RankSequence returns n ranks in ascending order spanning the whole space,
// for bulk insertion where no neighbours exist yet (the seed generator).
// Evenly spaced rather than generated pairwise, so a 10k-item seed produces
// short ranks instead of a 10k-deep chain.
func RankSequence(n int) []string {
	if n <= 0 {
		return nil
	}
	base := len(rankAlphabet)
	width := 1
	for pow := base; pow < n+2; pow *= base {
		width++
	}
	// Leave the endpoints free so callers can still prepend and append.
	step := 1
	if capacity := intPow(base, width); capacity > n+2 {
		step = (capacity - 2) / (n + 1)
		if step < 1 {
			step = 1
		}
	}
	out := make([]string, 0, n)
	for i := range n {
		out = append(out, rankEncode((i+1)*step, width))
	}
	return out
}

func intPow(base, exp int) int {
	r := 1
	for range exp {
		r *= base
	}
	return r
}

func rankEncode(v, width int) string {
	buf := make([]byte, width)
	for i := width - 1; i >= 0; i-- {
		buf[i] = rankAlphabet[v%len(rankAlphabet)]
		v /= len(rankAlphabet)
	}
	return string(buf)
}

// RankNeedsRebalance reports whether a generated rank has grown past the
// threshold in §5.5, meaning the project's ranks should be respread.
func RankNeedsRebalance(rank string) bool {
	return len(rank) > RankRebalanceThreshold
}
