package sxq

import (
	"fmt"
	"strings"
	"unicode/utf8"
)

type token struct {
	text   string
	quoted bool
	pos    int
}

func lex(input string) ([]token, error) {
	if len(input) > 4096 {
		return nil, fmt.Errorf("query is too long; use at most 4096 bytes")
	}
	if !utf8.ValidString(input) {
		return nil, fmt.Errorf("query must be valid UTF-8")
	}
	var out []token
	for i := 0; i < len(input); {
		if strings.ContainsRune(" \t\r\n", rune(input[i])) {
			i++
			continue
		}
		start := i
		ch := input[i]
		if ch == '\'' || ch == '"' {
			quote := ch
			i++
			var value strings.Builder
			closed := false
			for i < len(input) {
				c := input[i]
				i++
				if c == quote {
					closed = true
					break
				}
				if c == '\\' {
					if i >= len(input) {
						break
					}
					c = input[i]
					i++
					switch c {
					case 'n':
						c = '\n'
					case 'r':
						c = '\r'
					case 't':
						c = '\t'
					case '\\', '\'', '"':
					default:
						return nil, fmt.Errorf("invalid escape at byte %d; escape quotes or backslashes", i)
					}
				}
				value.WriteByte(c)
			}
			if !closed {
				return nil, fmt.Errorf("unterminated string at byte %d; add the closing quote", start)
			}
			out = append(out, token{value.String(), true, start})
			continue
		}
		if strings.ContainsRune("()~,+:=<>!-", rune(ch)) {
			i++
			if i < len(input) && input[i] == '=' && strings.ContainsRune("<>!", rune(ch)) {
				i++
			}
			if ch == '!' && i == start+1 {
				return nil, fmt.Errorf("use != for inequality at byte %d", start)
			}
			out = append(out, token{input[start:i], false, start})
			continue
		}
		for i < len(input) {
			c := input[i]
			if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '-' {
				i++
			} else {
				break
			}
		}
		if i == start {
			return nil, fmt.Errorf("unexpected character at byte %d; quote text values", start)
		}
		out = append(out, token{input[start:i], false, start})
		if len(out) > 1024 {
			return nil, fmt.Errorf("query has too many terms; simplify the expression")
		}
	}
	out = append(out, token{"", false, len(input)})
	return out, nil
}
