package tui

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/collector"
)

var (
	styleHeader  = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39"))
	styleBorder  = lipgloss.NewStyle().BorderStyle(lipgloss.NormalBorder()).Padding(0, 1)
	styleRunning = lipgloss.NewStyle().Foreground(lipgloss.Color("46"))  // green
	styleIdle    = lipgloss.NewStyle().Foreground(lipgloss.Color("226")) // yellow
	styleError   = lipgloss.NewStyle().Foreground(lipgloss.Color("196")).Bold(true)
	styleOK      = lipgloss.NewStyle().Foreground(lipgloss.Color("46"))
	styleUnknown = lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
	styleFaint   = lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
)

// Suppress unused variable warning for styleBorder — it can be used later for panels.
var _ = styleBorder

func (m Model) View() string {
	var b strings.Builder

	// Header
	b.WriteString(styleHeader.Render(
		fmt.Sprintf("  STS DATACENTER MONITOR   %s   [%s]",
			time.Now().Format("2006-01-02 15:04:05"),
			m.state.PollEvery,
		),
	))
	b.WriteString("\n")
	b.WriteString(strings.Repeat("-", 76))
	b.WriteString("\n")

	// Crawl accounts
	b.WriteString(styleHeader.Render("  CRAWL ACCOUNTS"))
	b.WriteString("\n")
	b.WriteString(strings.Repeat("-", 76))
	b.WriteString("\n")

	for _, a := range m.state.Accounts {
		b.WriteString(renderAccount(a))
	}

	// Pipeline
	b.WriteString(strings.Repeat("-", 76))
	b.WriteString("\n")
	b.WriteString(styleHeader.Render("  PIPELINE"))
	b.WriteString("\n")
	b.WriteString(strings.Repeat("-", 76))
	b.WriteString("\n")

	for _, s := range m.state.Stages {
		b.WriteString(renderStage(s))
	}

	b.WriteString(strings.Repeat("-", 76))
	b.WriteString("\n")
	b.WriteString(styleFaint.Render("  q quit   r refresh   ? help"))
	b.WriteString("\n")
	return b.String()
}

func stateStyle(state string) lipgloss.Style {
	switch state {
	case "running":
		return styleRunning
	case "idle":
		return styleIdle
	case "error":
		return styleError
	case "ok":
		return styleOK
	default:
		return styleUnknown
	}
}

func renderAccount(a collector.AccountState) string {
	stateFmt := stateStyle(a.State).Render(fmt.Sprintf("%-8s", strings.ToUpper(a.State)))
	line1 := fmt.Sprintf("  %-5s %-16s %s %-24s seg %-2d page %d",
		a.Name, a.Host, stateFmt, truncate(a.Batch, 24), a.Segment, a.Page)
	line2 := fmt.Sprintf("       %-36s scraped %s",
		a.Email, fmtInt(a.TotalScraped))
	if a.ErrMsg != "" {
		line2 = fmt.Sprintf("       %s", styleError.Render(truncate(a.ErrMsg, 60)))
	}
	return line1 + "\n" + line2 + "\n"
}

func renderStage(s collector.StageStatus) string {
	stateFmt := stateStyle(s.Status).Render(fmt.Sprintf("%-8s", strings.ToUpper(s.Status)))
	extra := ""
	if s.RowCount > 0 {
		extra = fmt.Sprintf("rows: %s", fmtInt64(s.RowCount))
	}
	if !s.LastRun.IsZero() {
		if extra != "" {
			extra += "   "
		}
		extra += fmt.Sprintf("last: %s", s.LastRun.Format("15:04:05"))
	}
	return fmt.Sprintf("  %-8s %s %s\n", strings.ToUpper(s.Name), stateFmt, extra)
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "~"
}

func fmtInt(n int) string    { return fmt.Sprintf("%d", n) }
func fmtInt64(n int64) string { return fmt.Sprintf("%d", n) }
