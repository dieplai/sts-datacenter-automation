package main

import (
	"fmt"
	"os"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/spf13/cobra"

	"github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/config"
	sshpool "github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/ssh"
	"github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/tui"
)

var (
	interval time.Duration
	jsonMode bool
)

var rootCmd = &cobra.Command{
	Use:   "sts-monitor",
	Short: "STS Datacenter real-time monitor",
	Long:  "TUI and CLI tool to monitor all 4 crawl accounts and the full pipeline.",
	RunE: func(cmd *cobra.Command, args []string) error {
		return runTUI()
	},
}

var statusCmd = &cobra.Command{
	Use:   "status",
	Short: "Print current status as JSON and exit",
	RunE: func(cmd *cobra.Command, args []string) error {
		return runStatus()
	},
}

func init() {
	rootCmd.PersistentFlags().DurationVar(&interval, "interval", 5*time.Second, "poll interval")
	rootCmd.PersistentFlags().BoolVar(&jsonMode, "json", false, "output JSON")
	rootCmd.AddCommand(statusCmd)
}

func runTUI() error {
	cfg := config.DefaultConfig()
	pool, err := sshpool.NewPool(cfg.SSHUser, cfg.SSHKeyPath)
	if err != nil {
		return fmt.Errorf("ssh pool: %w", err)
	}
	defer pool.Close()

	m, err := tui.NewModel(cfg, pool)
	if err != nil {
		return err
	}
	p := tea.NewProgram(m, tea.WithAltScreen())
	_, err = p.Run()
	return err
}

func runStatus() error {
	// TODO: collect state and print JSON
	fmt.Println("{\"status\": \"not implemented yet\"}")
	return nil
}

func main() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
