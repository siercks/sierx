// sierxctl — operator CLI. BUILD §2. Subcommands are added by the task that
// needs them; this file only dispatches.
package main

import (
	"context"
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "partitions":
		err = runPartitions(context.Background(), os.Args[2:])
	default:
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "sierxctl:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: sierxctl partitions ensure --months-ahead N")
}
