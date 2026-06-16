package collector

import (
	"bufio"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/dieplai/sts-datacenter-automation/tools/crawl-manager/internal/config"
	_ "github.com/lib/pq"
)

// PipelineCollector reads stage log files and DB row counts.
type PipelineCollector struct {
	cfg *config.Config
	db  *sql.DB
}

func NewPipelineCollector(cfg *config.Config) (*PipelineCollector, error) {
	db, err := sql.Open("postgres", cfg.DBDSN)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}
	db.SetMaxOpenConns(2)
	db.SetConnMaxLifetime(30 * time.Second)
	return &PipelineCollector{cfg: cfg, db: db}, nil
}

// Poll returns StageStatus for each pipeline stage.
func (p *PipelineCollector) Poll() []StageStatus {
	stages := []string{"sync", "dq", "staging", "gold"}
	result := make([]StageStatus, len(stages))
	for i, name := range stages {
		result[i] = p.pollStage(name)
	}
	// Enrich staging and gold with DB row counts
	p.enrichDBCounts(result)
	return result
}

func (p *PipelineCollector) pollStage(name string) StageStatus {
	st := StageStatus{Name: name, Status: "unknown"}
	logDir, ok := p.cfg.LogBasePaths[name]
	if !ok {
		return st
	}
	// Find the most-recently-modified .log file in the directory
	entries, err := os.ReadDir(logDir)
	if err != nil {
		return st
	}
	var newest string
	var newestMod time.Time
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".log") {
			continue
		}
		info, _ := e.Info()
		if info != nil && info.ModTime().After(newestMod) {
			newestMod = info.ModTime()
			newest = filepath.Join(logDir, e.Name())
		}
	}
	if newest == "" {
		return st
	}
	st.LastRun = newestMod
	st.Status = parseLogStatus(newest)
	return st
}

// parseLogStatus reads the last 30 lines of a log and returns "ok", "running", or "failed".
func parseLogStatus(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return "unknown"
	}
	defer f.Close()

	var lines []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	// Look at last 30 lines
	start := len(lines) - 30
	if start < 0 {
		start = 0
	}
	tail := strings.Join(lines[start:], " ")
	upper := strings.ToUpper(tail)
	switch {
	case strings.Contains(upper, "RUNNING"):
		return "running"
	case strings.Contains(upper, "SUCCESS") || strings.Contains(upper, "COMPLETED"):
		return "ok"
	case strings.Contains(upper, "FAILED") || strings.Contains(upper, "ERROR"):
		return "failed"
	default:
		return "unknown"
	}
}

func (p *PipelineCollector) enrichDBCounts(stages []StageStatus) {
	if p.db == nil {
		return
	}
	var stagingRows, goldRows int64
	var goldUpdated time.Time

	row := p.db.QueryRow(`
		SELECT
			(SELECT COUNT(*) FROM staging.customs_transactions),
			(SELECT COUNT(*) FROM gold.fact_customs),
			(SELECT COALESCE(MAX(created_at), NOW()) FROM gold.fact_customs)
	`)
	if err := row.Scan(&stagingRows, &goldRows, &goldUpdated); err != nil {
		return
	}
	for i := range stages {
		switch stages[i].Name {
		case "staging":
			stages[i].RowCount = stagingRows
		case "gold":
			stages[i].RowCount = goldRows
			stages[i].LastUpdate = goldUpdated
		}
	}
}

func (p *PipelineCollector) Close() {
	if p.db != nil {
		p.db.Close()
	}
}
