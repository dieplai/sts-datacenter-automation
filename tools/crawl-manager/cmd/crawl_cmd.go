package main

import (
	"bytes"
	"fmt"
	"strings"
	"time"

	gossh "golang.org/x/crypto/ssh"

	"github.com/spf13/cobra"
	"github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/config"
	sshpool "github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/ssh"
)

// accountInfo holds control metadata for one crawl account.
type accountInfo struct {
	host    string
	task    string // Task Scheduler task name
	baseDir string // Deploy base dir on crawl server
}

var accountMap = map[string]accountInfo{
	"acc1": {"100.76.219.16", `\STS_StartAcc1`, `C:\Crawl\acc1\crawl_w52_sts`},
	"acc2": {"100.76.219.16", `\STS_StartAcc2`, `C:\Crawl\acc2\crawl_w52_sts`},
	"acc3": {"100.76.65.2", `\STS_StartAcc3`, `C:\Crawl\acc3\crawl_w52_sts`},
	"acc4": {"100.76.65.2", `\STS_StartAcc4`, `C:\Crawl\acc4\crawl_w52_sts`},
}

var crawlCmd = &cobra.Command{
	Use:   "crawl",
	Short: "Control crawl accounts (start / stop / logs)",
}

var crawlStartCmd = &cobra.Command{
	Use:   "start [acc1|acc2|acc3|acc4|all]",
	Short: "Start one or all crawl accounts via Task Scheduler",
	Args:  cobra.MaximumNArgs(1),
	RunE:  runCrawlStart,
}

var crawlStopCmd = &cobra.Command{
	Use:   "stop [acc1|acc2|acc3|acc4|all]",
	Short: "Stop one or all crawl accounts (kills python + chrome processes)",
	Args:  cobra.MaximumNArgs(1),
	RunE:  runCrawlStop,
}

var crawlLogsCmd = &cobra.Command{
	Use:   "logs [acc1|acc2|acc3|acc4]",
	Short: "Show last 60 lines of the latest log for a crawl account",
	Args:  cobra.ExactArgs(1),
	RunE:  runCrawlLogs,
}

var crawlStatusCmd = &cobra.Command{
	Use:   "status [acc1|acc2|acc3|acc4|all]",
	Short: "Print live crawl status for one or all accounts",
	Args:  cobra.MaximumNArgs(1),
	RunE:  runCrawlStatus,
}

func init() {
	crawlCmd.AddCommand(crawlStartCmd, crawlStopCmd, crawlLogsCmd, crawlStatusCmd)
	rootCmd.AddCommand(crawlCmd)
}

// resolveTargets returns ["acc1","acc2","acc3","acc4"] for "all" or empty, else the named account.
func resolveTargets(args []string) ([]string, error) {
	all := []string{"acc1", "acc2", "acc3", "acc4"}
	if len(args) == 0 || strings.ToLower(args[0]) == "all" {
		return all, nil
	}
	name := strings.ToLower(args[0])
	if _, ok := accountMap[name]; !ok {
		return nil, fmt.Errorf("unknown account %q — use acc1/acc2/acc3/acc4/all", args[0])
	}
	return []string{name}, nil
}

func sshRun(client *gossh.Client, cmd string) string {
	sess, err := client.NewSession()
	if err != nil {
		return fmt.Sprintf("session error: %v", err)
	}
	defer sess.Close()
	var buf bytes.Buffer
	sess.Stdout = &buf
	sess.Stderr = &buf
	sess.Run(cmd)
	return strings.TrimSpace(buf.String())
}

func newPool() (*sshpool.Pool, *config.Config, error) {
	cfg := config.DefaultConfig()
	pool, err := sshpool.NewPool(cfg.SSHUser, cfg.SSHKeyPath)
	if err != nil {
		return nil, nil, fmt.Errorf("SSH pool: %w", err)
	}
	return pool, cfg, nil
}

func runCrawlStart(cmd *cobra.Command, args []string) error {
	targets, err := resolveTargets(args)
	if err != nil {
		return err
	}
	pool, _, err := newPool()
	if err != nil {
		return err
	}
	defer pool.Close()

	for _, name := range targets {
		info := accountMap[name]
		client, err := pool.Get(info.host)
		if err != nil {
			fmt.Printf("[%s] SSH error: %v\n", strings.ToUpper(name), err)
			continue
		}
		out := sshRun(client, fmt.Sprintf(`schtasks /run /tn "%s"`, info.task))
		if strings.Contains(strings.ToUpper(out), "SUCCESS") || out == "" {
			fmt.Printf("[%s] Started — task %s triggered on %s\n",
				strings.ToUpper(name), info.task, info.host)
		} else {
			fmt.Printf("[%s] %s\n", strings.ToUpper(name), out)
		}
		// Stagger accounts on same server to avoid Chrome profile conflicts
		time.Sleep(300 * time.Millisecond)
	}
	return nil
}

func runCrawlStop(cmd *cobra.Command, args []string) error {
	targets, err := resolveTargets(args)
	if err != nil {
		return err
	}
	pool, _, err := newPool()
	if err != nil {
		return err
	}
	defer pool.Close()

	for _, name := range targets {
		info := accountMap[name]
		client, err := pool.Get(info.host)
		if err != nil {
			fmt.Printf("[%s] SSH error: %v\n", strings.ToUpper(name), err)
			continue
		}
		// Kill python.exe running from this account's base dir
		escaped := strings.ReplaceAll(info.baseDir, `\`, `\\`)
		killCmd := fmt.Sprintf(
			`wmic process where "commandline like '%%%s%%'" call terminate 2>nul`,
			escaped,
		)
		sshRun(client, killCmd)
		fmt.Printf("[%s] Stop signal sent (processes in %s terminated)\n",
			strings.ToUpper(name), info.baseDir)
	}
	return nil
}

func runCrawlLogs(cmd *cobra.Command, args []string) error {
	name := strings.ToLower(args[0])
	info, ok := accountMap[name]
	if !ok {
		return fmt.Errorf("unknown account: %s", name)
	}
	pool, _, err := newPool()
	if err != nil {
		return err
	}
	defer pool.Close()

	client, err := pool.Get(info.host)
	if err != nil {
		return fmt.Errorf("SSH: %w", err)
	}

	// Find most-recently-modified log file
	latestLog := sshRun(client,
		fmt.Sprintf(`for /f "tokens=*" %%f in ('dir /b /o-d "%s\logs\" 2^>nul') do @(echo %%f & exit)`,
			info.baseDir))
	if latestLog == "" {
		fmt.Printf("[%s] No logs found in %s\\logs\\\n", strings.ToUpper(name), info.baseDir)
		return nil
	}
	logPath := fmt.Sprintf(`%s\logs\%s`, info.baseDir, latestLog)

	// Tail last 60 lines via PowerShell
	content := sshRun(client,
		fmt.Sprintf(`powershell -Command "Get-Content '%s' -Tail 60 -Encoding UTF8 2>$null"`, logPath))

	fmt.Printf("=== %s | %s (last 60 lines) ===\n\n", strings.ToUpper(name), latestLog)
	fmt.Println(content)
	return nil
}

func runCrawlStatus(cmd *cobra.Command, args []string) error {
	targets, err := resolveTargets(args)
	if err != nil {
		return err
	}
	pool, _, err := newPool()
	if err != nil {
		return err
	}
	defer pool.Close()

	for _, name := range targets {
		info := accountMap[name]
		client, err := pool.Get(info.host)
		if err != nil {
			fmt.Printf("[%s] SSH error: %v\n", strings.ToUpper(name), err)
			continue
		}
		statusPath := fmt.Sprintf(`%s\data\status.json`, info.baseDir)
		content := sshRun(client, fmt.Sprintf(`type "%s" 2>nul`, statusPath))
		if content == "" {
			fmt.Printf("[%s] idle — no status.json found\n", strings.ToUpper(name))
		} else {
			fmt.Printf("[%s] %s\n", strings.ToUpper(name), content)
		}
	}
	return nil
}
