package manager

import (
	"regexp"
	"testing"
)

func TestMarkResponsiveColumns(t *testing.T) {
	in := `<tr><td style="box-sizing:content-box;vertical-align:top;">a</td><td class="lm-col" style="box-sizing:content-box;">b</td></tr>`
	once := markResponsiveColumns(in)
	if want := `<td class="lm-col" style="box-sizing:content-box;vertical-align:top;">`; !contains(once, want) {
		t.Errorf("first pass did not mark unmarked cell: %s", once)
	}
	if contains(once, `<td class="lm-col" class="lm-col"`) {
		t.Errorf("double-marked a cell: %s", once)
	}
	if again := markResponsiveColumns(once); again != once {
		t.Errorf("not idempotent: %s != %s", again, once)
	}
}

func TestEnsureResponsiveHead(t *testing.T) {
	in := `<!DOCTYPE html><html><head><title>x</title></head><body><table><tr><td>hi</td></tr></table></body></html>`
	got := ensureResponsiveHead(in)
	if !contains(got, "width=device-width, initial-scale=1.0") {
		t.Errorf("viewport meta missing: %s", got)
	}
	if !contains(got, ".lm-col { display: block !important; width: 100% !important; }") {
		t.Errorf("lm-col media rule missing: %s", got)
	}
	headHead := headCloseRe.FindStringIndex(got)
	headBody := regexp.MustCompile(`(?i)<body\b`).FindStringIndex(got)
	if headHead == nil || headBody == nil || headHead[0] > headBody[0] {
		t.Errorf("injected content not before <body>: %s", got)
	}
	if again := ensureResponsiveHead(got); again != got {
		t.Errorf("ensureResponsiveHead not idempotent")
	}
}

func TestPostProcessHTMLFullDoc(t *testing.T) {
	in := `<!DOCTYPE html><html><head></head><body><table><tbody><tr><td style="box-sizing:content-box;">x</td></tr></tbody></table><div style="padding:16px 24px 16px 24px">y</div></body></html>`
	got := string(PostProcessHTML([]byte(in)))
	if !contains(got, `class="lm-col"`) {
		t.Errorf("cell not marked: %s", got)
	}
	if !contains(got, "@media only screen and (max-width: 600px)") {
		t.Errorf("media query missing: %s", got)
	}
}

func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
