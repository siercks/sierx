package api

import (
	"encoding/json"
	"net/http"
)

// Problem is the RFC 9457 response contract. Details are authored here rather
// than copied from database, decoder, or other dependency errors.
type Problem struct {
	Type      string `json:"type"`
	Title     string `json:"title"`
	Status    int    `json:"status"`
	Detail    string `json:"detail"`
	Current   any    `json:"current,omitempty"`
	Submitted any    `json:"submitted,omitempty"`
}

func problem(status int, title, detail string) Problem {
	return Problem{Type: "about:blank", Title: title, Status: status, Detail: detail}
}
func BadRequest() Problem {
	return problem(400, "Bad Request", "The request is invalid. Check the fields and try again.")
}
func Unauthorized() Problem { return problem(401, "Unauthorized", "Sign in to continue.") }
func Forbidden() Problem {
	return problem(403, "Forbidden", "Your account cannot perform this action. Contact a workspace administrator.")
}
func NotFound() Problem {
	return problem(404, "Not Found", "This resource was not found. Check its identifier and try again.")
}
func MethodNotAllowed() Problem {
	return problem(405, "Method Not Allowed", "This method is not supported for this resource. Check the API method.")
}
func NotAcceptable() Problem {
	return problem(406, "Not Acceptable", "Accept br, gzip or identity encoding for this response.")
}
func Conflict(current any) Problem {
	p := problem(409, "Conflict", "This item changed. Compare the current version with your edits and retry using its version.")
	p.Current = current
	return p
}
func TooLarge() Problem {
	return problem(413, "Content Too Large", "The request is too large. Reduce its size and try again.")
}
func UnsupportedMediaType() Problem {
	return problem(415, "Unsupported Media Type", "Send a JSON request with Content-Type: application/json.")
}
func Unprocessable() Problem {
	return problem(422, "Unprocessable Content", "This change is not valid for the resource. Review its configuration and try again.")
}
func PreconditionRequired() Problem {
	return problem(428, "Precondition Required", "Send If-Match with the current item version before changing this item.")
}
func RateLimited() Problem {
	return problem(429, "Too Many Requests", "Too many attempts. Wait before trying again.")
}
func InternalError() Problem {
	return problem(500, "Internal Server Error", "The request could not be completed. Try again.")
}
func Unavailable() Problem {
	return problem(503, "Service Unavailable", "The service is temporarily unavailable. Try again shortly.")
}

func WriteProblem(w http.ResponseWriter, p Problem) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(p.Status)
	_ = json.NewEncoder(w).Encode(p)
}
