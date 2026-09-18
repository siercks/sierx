package sxq

import (
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
)

type Value struct {
	Literal  any
	Function string
	Offset   time.Duration
}
type Expr struct {
	Op, Field   string
	Values      []Value
	Left, Right *Expr
}
type Query struct {
	Expr  *Expr
	Order string
	Desc  bool
}
type parser struct {
	tokens    []token
	at, depth int
}

func Parse(input string) (*Query, error) {
	tokens, err := lex(input)
	if err != nil {
		return nil, err
	}
	p := parser{tokens: tokens}
	q := &Query{Order: "id"}
	if p.peek().text != "" && !p.is("order") {
		q.Expr, err = p.or()
		if err != nil {
			return nil, err
		}
	}
	if p.take("order") {
		if !p.take("by") {
			return nil, p.expected("by after order")
		}
		q.Order = canonical(p.peek().text)
		if p.peek().quoted || q.Order == "" {
			return nil, p.expected("an order field")
		}
		p.at++
		q.Desc = p.take("desc")
		if !q.Desc {
			p.take("asc")
		}
	}
	if p.peek().text != "" {
		return nil, p.expected("and, or, or order by")
	}
	return q, nil
}
func (p *parser) peek() token {
	if p.at >= len(p.tokens) {
		return p.tokens[len(p.tokens)-1]
	}
	return p.tokens[p.at]
}
func (p *parser) is(s string) bool { return !p.peek().quoted && canonical(p.peek().text) == s }
func (p *parser) take(s string) bool {
	if p.is(s) {
		p.at++
		return true
	}
	return false
}
func (p *parser) expected(s string) error {
	return fmt.Errorf("expected %s at byte %d; check the query syntax", s, p.peek().pos)
}
func (p *parser) or() (*Expr, error) {
	left, err := p.and()
	if err != nil {
		return nil, err
	}
	for p.take("or") {
		right, err := p.and()
		if err != nil {
			return nil, err
		}
		left = &Expr{Op: "or", Left: left, Right: right}
	}
	return left, nil
}
func (p *parser) and() (*Expr, error) {
	left, err := p.unary()
	if err != nil {
		return nil, err
	}
	for p.take("and") {
		right, err := p.unary()
		if err != nil {
			return nil, err
		}
		left = &Expr{Op: "and", Left: left, Right: right}
	}
	return left, nil
}
func (p *parser) unary() (*Expr, error) {
	p.depth++
	defer func() { p.depth-- }()
	if p.depth > 64 {
		return nil, p.expected("less than 64 levels of nesting")
	}
	if p.take("not") {
		e, err := p.unary()
		return &Expr{Op: "not", Left: e}, err
	}
	if p.take("(") {
		e, err := p.or()
		if err != nil {
			return nil, err
		}
		if !p.take(")") {
			return nil, p.expected("a closing parenthesis")
		}
		return e, nil
	}
	field := canonical(p.peek().text)
	if field == "descendants" || field == "ancestors" {
		return nil, fmt.Errorf("%s is not available until phase 5", field)
	}
	if p.peek().quoted || field == "" {
		return nil, p.expected("a field name")
	}
	p.at++
	op := canonical(p.peek().text)
	if p.peek().quoted {
		return nil, p.expected("a comparison operator")
	}
	p.at++
	switch op {
	case "not":
		if !p.take("in") {
			return nil, p.expected("in after not")
		}
		op = "not in"
	case "is":
		if p.take("not") {
			op = "is not"
		}
	case "=", "!=", ">", ">=", "<", "<=", "in", "~", ":":
	default:
		return nil, fmt.Errorf("unknown operator %q; use =, !=, in, is null or ~", op)
	}
	e := &Expr{Field: field, Op: op}
	if op == "in" || op == "not in" {
		if !p.take("(") {
			return nil, p.expected("a parenthesized list")
		}
		for {
			v, err := p.value()
			if err != nil {
				return nil, err
			}
			e.Values = append(e.Values, v)
			if len(e.Values) > 200 {
				return nil, fmt.Errorf("lists may contain at most 200 values")
			}
			if !p.take(",") {
				break
			}
		}
		if !p.take(")") {
			return nil, p.expected("a closing list parenthesis")
		}
	} else {
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		e.Values = []Value{v}
	}
	return e, nil
}
func (p *parser) value() (Value, error) {
	t := p.peek()
	if t.text == "" {
		return Value{}, p.expected("a value")
	}
	if t.quoted {
		p.at++
		return Value{Literal: t.text}, nil
	}
	name := canonical(t.text)
	if name == "startofsprint" || name == "endofsprint" {
		return Value{}, fmt.Errorf("%s is not available until phase 4", t.text)
	}
	if name == "me" || name == "now" {
		p.at++
		if !p.take("(") || !p.take(")") {
			return Value{}, p.expected("empty function parentheses")
		}
		v := Value{Function: name}
		if name == "now" && (p.is("+") || p.is("-")) {
			negative := p.take("-")
			if !negative {
				p.take("+")
			}
			d := p.peek()
			p.at++
			if d.quoted || len(d.text) < 2 {
				return v, p.expected("a duration such as 7d")
			}
			n, err := strconv.ParseInt(d.text[:len(d.text)-1], 10, 64)
			units := map[byte]time.Duration{'d': 24 * time.Hour, 'w': 7 * 24 * time.Hour, 'h': time.Hour, 'm': time.Minute}
			unit, ok := units[d.text[len(d.text)-1]]
			if err != nil || !ok || n < 0 || n > 1000000 || n > int64((1<<63-1)/unit) {
				return v, fmt.Errorf("invalid duration; use bounded Nd, Nw, Nh or Nm")
			}
			v.Offset = time.Duration(n) * unit
			if negative {
				v.Offset = -v.Offset
			}
		}
		return v, nil
	}
	if name == "null" {
		p.at++
		return Value{}, nil
	}
	if name == "true" || name == "false" {
		p.at++
		return Value{Literal: name == "true"}, nil
	}
	sign := ""
	if p.take("-") {
		sign = "-"
		t = p.peek()
	}
	if n, err := strconv.ParseFloat(sign+t.text, 64); err == nil && !math.IsInf(n, 0) && !math.IsNaN(n) {
		p.at++
		return Value{Literal: json.Number(sign + t.text)}, nil
	}
	if sign != "" {
		return Value{}, p.expected("a number after -")
	}
	if strings.ContainsAny(t.text, "()~,+:=<>!") || name == "and" || name == "or" || name == "order" {
		return Value{}, p.expected("a literal value")
	}
	p.at++
	return Value{Literal: t.text}, nil
}

// ProjectKeys returns a safe narrowing implied by the boolean expression.
// An unrestricted OR branch prevents narrowing; AND may retain either bound.
func (q *Query) ProjectKeys() []string { return projectKeys(q.Expr) }
func projectKeys(e *Expr) []string {
	if e == nil {
		return nil
	}
	if e.Op == "and" {
		a, b := projectKeys(e.Left), projectKeys(e.Right)
		if len(a) > 0 {
			return a
		}
		return b
	}
	if e.Op == "or" {
		a, b := projectKeys(e.Left), projectKeys(e.Right)
		if len(a) == 0 || len(b) == 0 {
			return nil
		}
		return append(a, b...)
	}
	if e.Field == "project" && (e.Op == "=" || e.Op == "in") {
		var keys []string
		for _, v := range e.Values {
			if k, ok := v.Literal.(string); ok {
				keys = append(keys, k)
			} else {
				return nil
			}
		}
		return keys
	}
	return nil
}
