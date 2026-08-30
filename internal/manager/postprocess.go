package manager

import (
	"regexp"
	"strings"
)

// Final HTML post-processing for the assembled visual newsletter body. This is
// the delivery-layer equivalent of the email-builder's renderHtmlWithMeta: it
// guarantees that ColumnsContainer cells are marked responsive so they stack
// on mobile, regardless of when or how the body was saved.

const (
	// viewportMeta is injected into the document <head> when missing.
	viewportMeta = `<meta name="viewport" content="width=device-width, initial-scale=1.0">`

	// lmColCSS stacks ColumnsContainer cells (class "lm-col") into rows on narrow
	// screens. It mirrors scripts/convert_stacked_columns.py:STACK_COLUMNS_CSS;
	// keep the two in sync.
	lmColCSS = `<style>@media only screen and (max-width: 600px) { .lm-col { display: block !important; width: 100% !important; } }</style>`
)

// columnCellTagRe matches a ColumnsContainer cell <td> whose inline style has
// the signature `box-sizing: content-box` (with or without a space) that is
// unique to those cells. Already-marked cells carry class="lm-col" first and
// are skipped by the marking regex.
var columnCellTagRe = regexp.MustCompile(`(?i)<td style="box-sizing: ?content-box;`)

// styleTagRe matches whole <style>…</style> blocks.
var styleTagRe = regexp.MustCompile(`(?is)<style(?:\s[^>]*)?>[\s\S]*?</style>`)

var headCloseRe = regexp.MustCompile(`(?i)</head\s*>`)
var htmlOpenRe = regexp.MustCompile(`(?i)<html\b([^>]*)>`)

// markResponsiveColumns tags every ColumnsContainer cell with class="lm-col",
// backing out the same transformation the email-builder applies at save time
// so that old, previously-saved bodies also become responsive at delivery.
// Already-marked cells are left untouched.
func markResponsiveColumns(html string) string {
	return columnCellTagRe.ReplaceAllStringFunc(html, func(td string) string {
		return strings.Replace(td, "<td style=\"", `<td class="lm-col" style="`, 1)
	})
}

// ensureResponsiveHead guarantees the final document <head> carries the viewport
// meta and the mobile stacking rule for .lm-col cells, inserting them if they
// are missing (e.g. old bodies or mailing templates that left them out).
func ensureResponsiveHead(html string) string {
	if headCloseRe.MatchString(html) {
		// Insert only what's missing, before </head>.
		inserts := ""
		if !strings.Contains(html, "width=device-width, initial-scale=1.0") {
			inserts += viewportMeta + "\n"
		}
		if !styleTagRe.MatchString(html) || !strings.Contains(html, ".lm-col") {
			inserts += lmColCSS + "\n"
		}
		if inserts == "" {
			return html
		}
		return headCloseRe.ReplaceAllString(html, inserts+"\n  </head>")
	}

	// No <head> at all. If the document is a full <html> shell, create one;
	// otherwise the chosen base layer is a fragment and we avoid injecting a
	// head that could be dropped. The email-builder output and the stock
	// listmonk templates always ship a head.
	if htmlOpenRe.MatchString(html) || strings.HasPrefix(strings.TrimSpace(html), "<html") {
		inject := "<head>\n  " + viewportMeta + "\n  " + lmColCSS + "\n</head>"
		return htmlOpenRe.ReplaceAllString(html, "<html$1>"+inject)
	}

	return html
}

// PostProcessHTML finalizes the assembled visual newsletter HTML for delivery:
// it marks ColumnsContainer cells responsive and guarantees the viewport meta
// plus mobile stacking rule live in the document <head>. It is idempotent and
// safe to run on any visual message body.
func PostProcessHTML(body []byte) []byte {
	html := string(body)
	html = markResponsiveColumns(html)
	html = ensureResponsiveHead(html)
	return []byte(html)
}
