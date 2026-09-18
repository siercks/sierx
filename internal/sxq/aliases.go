package sxq

import "strings"

var aliases = map[string]string{"currentuser": "me", "empty": "null"}

func canonical(value string) string {
	value = strings.ToLower(value)
	if replacement, ok := aliases[value]; ok {
		return replacement
	}
	return value
}
