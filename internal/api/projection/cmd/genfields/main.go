package main

import (
	"flag"
	"fmt"
	"github.com/siercks/sierx/internal/api/projection"
	"os"
	"path/filepath"
)

func main() {
	check := flag.Bool("check", false, "verify generated output")
	flag.Parse()
	path := "web/src/api/fields.ts"
	if flag.NArg() > 0 {
		path = flag.Arg(0)
	}
	want := projection.TypeScript()
	if *check {
		got, err := os.ReadFile(path)
		if err != nil || string(got) != want {
			fmt.Fprintln(os.Stderr, "gate-gen: generated fields differ; run make gen-fields")
			os.Exit(1)
		}
		fmt.Println("gate-gen: OK")
		return
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		panic(err)
	}
	if err := os.WriteFile(path, []byte(want), 0644); err != nil {
		panic(err)
	}
}
