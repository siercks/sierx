// Package bench holds the §12 performance gates as executable assertions
// (BUILD task 0.14).
//
// ADR-016 splits this into two targets:
//
//	bench-smoke  CI, inside gate-0. Runs every scenario once, asserts none
//	             *errors*, prints timings, never fails on a threshold. Catches
//	             a benchmark that stopped compiling or a query that started
//	             erroring — which is what CI can actually detect on a shared
//	             runner with no stable timing.
//	gate-bench   Reference hardware, human-run. The thresholds below as
//	             assertions against a checked-in baseline.
//
// Every threshold lives in this file and nowhere else, so §12 has exactly one
// executable representation.
package bench

import "time"

// Threshold is one row of the §12 table.
type Threshold struct {
	// Name matches the scenario name in §12 verbatim, because a renamed
	// scenario is how a gate silently stops being the gate that was agreed.
	Name string
	// P95 is the server-time budget. Zero means the scenario is measured by
	// something other than latency (see Bytes, Total, RSS).
	P95 time.Duration
	// Total is a whole-operation budget rather than a per-request p95.
	Total time.Duration
	// Bytes caps a response size.
	Bytes int
	// RSSBytes caps steady-state resident memory.
	RSSBytes int
}

// §12, transcribed. All measured on the Pi 5 reference box with a 10k-item
// seeded workspace — which is why gate-bench is not a CI gate (ADR-016).
var Thresholds = []Threshold{
	{Name: "board view, 500 items, projected fields", P95: 150 * time.Millisecond},
	{Name: "item detail with rollup and history", P95: 100 * time.Millisecond},
	{Name: "sxq query over 10k items, indexed fields", P95: 200 * time.Millisecond},
	{Name: "descendant rollup read, depth 6", P95: 50 * time.Millisecond},
	{Name: "delta sync, 50 changes", P95: 80 * time.Millisecond, Bytes: 20 * 1024},
	{Name: "full-text search over 10k items", P95: 300 * time.Millisecond},
	{Name: "rollup recompute after a 200-item bulk transition", Total: 2 * time.Second},
	{Name: "steady-state RSS, sierx process", RSSBytes: 80 * 1024 * 1024},
	{Name: "cold start to serving", P95: 1 * time.Second},
}

// ThresholdFor returns the named threshold. It panics on an unknown name
// rather than returning a zero value: a zero threshold silently passes, which
// would turn a typo into a disabled gate.
func ThresholdFor(name string) Threshold {
	for _, t := range Thresholds {
		if t.Name == name {
			return t
		}
	}
	panic("bench: no §12 threshold named " + name + " — the scenario name must match SPEC §12 verbatim")
}

// BaselinePath is where `make bench-baseline` writes reference-hardware
// numbers. gate-bench exits nonzero with "no baseline" until it exists, which
// is the documented behaviour until task 2.16 (ADR-016).
const BaselinePath = "test/bench/baseline.json"
