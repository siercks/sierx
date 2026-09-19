// Package web embeds the built browser distribution. Run make web-build first.
package web

import "embed"

//go:embed dist/index.html dist/assets/*
var Files embed.FS
