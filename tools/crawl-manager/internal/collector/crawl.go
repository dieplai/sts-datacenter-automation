package collector

import (
	"bytes"
	"encoding/json"
	"fmt"
	"time"

	"github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/config"
	sshpool "github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/ssh"
	gossh "golang.org/x/crypto/ssh"
)

// statusJSON mirrors the schema written by Python's _write_status().
type statusJSON struct {
	TS           string `json:"ts"`
	Account      string `json:"account"`
	Batch        string `json:"batch"`
	Segment      int    `json:"segment"`
	SegmentStart string `json:"segment_start"`
	SegmentEnd   string `json:"segment_end"`
	Page         int    `json:"page"`
	TotalScraped int    `json:"total_scraped"`
	State        string `json:"state"`
	Reason       string `json:"reason,omitempty"`
}

// CrawlCollector polls status.json for each account over SSH.
type CrawlCollector struct {
	pool *sshpool.Pool
	cfg  *config.Config
}

func NewCrawlCollector(pool *sshpool.Pool, cfg *config.Config) *CrawlCollector {
	return &CrawlCollector{pool: pool, cfg: cfg}
}

// Poll fetches the latest AccountState for every configured account.
func (c *CrawlCollector) Poll() []AccountState {
	results := make([]AccountState, len(c.cfg.Accounts))
	for i, acct := range c.cfg.Accounts {
		results[i] = c.pollOne(acct)
	}
	return results
}

func (c *CrawlCollector) pollOne(acct config.AccountConfig) AccountState {
	base := AccountState{
		Name:       acct.Name,
		Host:       acct.Host,
		Email:      acct.Email,
		State:      "unknown",
		LastUpdate: time.Now(),
	}

	sshClient, err := c.pool.Get(acct.Host)
	if err != nil {
		base.State = "error"
		base.ErrMsg = fmt.Sprintf("SSH: %v", err)
		return base
	}

	data, err := readRemoteFile(sshClient, acct.StatusPath())
	if err != nil {
		// File missing = crawl not started yet
		base.State = "idle"
		return base
	}

	var s statusJSON
	if err := json.Unmarshal(data, &s); err != nil {
		base.State = "error"
		base.ErrMsg = "bad status.json"
		return base
	}

	base.Batch = s.Batch
	base.Segment = s.Segment
	base.SegmentStart = s.SegmentStart
	base.SegmentEnd = s.SegmentEnd
	base.Page = s.Page
	base.TotalScraped = s.TotalScraped
	base.State = s.State
	base.ErrMsg = s.Reason
	return base
}

// readRemoteFile reads a file from the remote server via SSH exec (type command).
func readRemoteFile(client *gossh.Client, remotePath string) ([]byte, error) {
	session, err := client.NewSession()
	if err != nil {
		return nil, err
	}
	defer session.Close()

	var buf bytes.Buffer
	session.Stdout = &buf
	// Use Windows `type` command to read the file
	cmd := fmt.Sprintf(`type "%s"`, remotePath)
	if err := session.Run(cmd); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}
