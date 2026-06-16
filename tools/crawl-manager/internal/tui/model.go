package tui

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/collector"
	"github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/config"
	sshpool "github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/ssh"
)

type tickMsg time.Time
type stateMsg collector.AppState

// Model is the bubbletea application model.
type Model struct {
	state    collector.AppState
	cfg      *config.Config
	crawlCol *collector.CrawlCollector
	pipeCol  *collector.PipelineCollector
	err      string
}

func NewModel(cfg *config.Config, pool *sshpool.Pool) (*Model, error) {
	crawlCol := collector.NewCrawlCollector(pool, cfg)
	pipeCol, err := collector.NewPipelineCollector(cfg)
	if err != nil {
		// DB unavailable is non-fatal — continue without DB counts
		pipeCol = nil
	}
	return &Model{
		cfg:      cfg,
		crawlCol: crawlCol,
		pipeCol:  pipeCol,
		state: collector.AppState{
			PollEvery: cfg.PollInterval(),
		},
	}, nil
}

func (m Model) Init() tea.Cmd {
	return tea.Batch(
		m.doTick(),
		m.doPoll(),
	)
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "r":
			return m, m.doPoll()
		}
	case tickMsg:
		return m, tea.Batch(m.doTick(), m.doPoll())
	case stateMsg:
		m.state = collector.AppState(msg)
		return m, nil
	}
	return m, nil
}

func (m Model) doTick() tea.Cmd {
	return tea.Tick(m.state.PollEvery, func(t time.Time) tea.Msg {
		return tickMsg(t)
	})
}

func (m Model) doPoll() tea.Cmd {
	return func() tea.Msg {
		accounts := m.crawlCol.Poll()
		var stages []collector.StageStatus
		if m.pipeCol != nil {
			stages = m.pipeCol.Poll()
		}
		return stateMsg(collector.AppState{
			Accounts:  accounts,
			Stages:    stages,
			PollEvery: m.state.PollEvery,
			PolledAt:  time.Now(),
		})
	}
}
