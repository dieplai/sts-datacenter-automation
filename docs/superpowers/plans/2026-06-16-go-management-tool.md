# Plan B: Go Management Tool — STS Datacenter Monitor
**Date:** 2026-06-16  
**Goal:** Single TUI/CLI binary that gives the admin a real-time view of ALL 5 pipeline stages across all 4 crawl accounts  
**Status:** Ready for implementation

---

## Context

**Pipeline stages (end-to-end):**
1. **Crawl** — 4 accounts, 2 servers (100.76.219.16: ACC1/ACC2, 100.76.65.2: ACC3/ACC4)
2. **Sync** — UNC copy from crawl servers to pipeline server (`D:\datacenter\`)
3. **DQ** — data quality checks on Bronze CSVs
4. **Staging** — load into PostgreSQL staging tables
5. **Gold** — promote staging → fact tables

**Data sources the tool polls:**
- `data/status.json` on each crawl server (via SSH) — live crawl progress
- `D:\datacenter\scripts\` — Task Scheduler log files for sync/DQ/staging/gold
- PostgreSQL `localhost:5433 db=sts-dev` — row counts in staging and gold tables

**Target users:** Admin (single user, local machine)  
**Update interval:** 5s (configurable via flag)

---

## Architecture

```
tools/crawl-manager/
├── cmd/
│   └── root.go          # cobra root + subcommands
├── internal/
│   ├── config/
│   │   └── config.go    # loads servers.json + DB DSN from env
│   ├── ssh/
│   │   └── pool.go      # persistent SSH connections (one per server)
│   ├── collector/
│   │   ├── crawl.go     # polls data/status.json via SSH SFTP
│   │   ├── pipeline.go  # reads Task Scheduler log files + DB counts
│   │   └── types.go     # PipelineState, AccountState structs
│   ├── tui/
│   │   ├── model.go     # bubbletea Model
│   │   ├── view.go      # lipgloss rendering
│   │   └── update.go    # tea.Msg handlers
│   └── reporter/
│       └── json.go      # --json output for CI/scripts
├── go.mod
└── go.sum
```

---

## Key Data Structures

```go
// types.go

type AccountState struct {
    Name          string    // "ACC1", "ACC2", etc.
    Host          string    // "100.76.219.16"
    Account       string    // "vtic.stsgroup@gmail.com"
    Batch         string    // batch item name
    Segment       int
    SegmentStart  string
    SegmentEnd    string
    Page          int
    TotalScraped  int
    State         string    // "running" | "idle" | "error"
    LastUpdate    time.Time
    Error         string    // last error message if state == "error"
}

type PipelineState struct {
    SyncLastRun    time.Time
    SyncStatus     string    // "ok" | "running" | "failed" | "unknown"
    DQLastRun      time.Time
    DQStatus       string
    StagingRows    int64     // current row count in staging tables
    GoldRows       int64     // current row count in gold tables
    GoldLastUpdate time.Time
}

type AppState struct {
    Accounts  [4]AccountState
    Pipeline  PipelineState
    PollAt    time.Duration
    LastPoll  time.Time
    Error     string
}
```

---

## SSH Pool (`internal/ssh/pool.go`)

**Rationale:** Open one connection per server (not per account) and reuse it. Each poll re-uses the existing connection; reconnect on failure.

```go
type Pool struct {
    mu    sync.Mutex
    conns map[string]*ssh.Client  // keyed by host
    cfg   *ssh.ClientConfig
}

func (p *Pool) Get(host string) (*ssh.Client, error)
func (p *Pool) Close()
```

**SSH key:** `C:\Users\tanmi\.ssh\id_rsa_sts`  
**Username:** `pc`  
**Authentication:** RSA public key

**Connection error strategy:** If a host is unreachable, mark all accounts on that host as `state=error` with `error="SSH unavailable"`. Continue polling other hosts.

---

## Crawl Collector (`internal/collector/crawl.go`)

**Reads `data/status.json` via SFTP every 5s:**

```go
type CrawlCollector struct {
    pool *ssh.Pool
}

func (c *CrawlCollector) Poll(accounts []AccountConfig) ([4]AccountState, error)
```

**Account → remote path mapping:**

| Account | Host             | Status path |
|---------|------------------|-------------|
| ACC1    | 100.76.219.16    | `C:\CRAWL_STS\ACC1\DEPLOY_ACC_1\data\status.json` |
| ACC2    | 100.76.219.16    | `C:\CRAWL_STS\ACC2\DEPLOY_ACC_2\data\status.json` |
| ACC3    | 100.76.65.2      | `C:\CRAWL_STS\ACC3\DEPLOY_ACC_3\data\status.json` |
| ACC4    | 100.76.65.2      | `C:\CRAWL_STS\ACC4\DEPLOY_ACC_4\data\status.json` |

**Handle missing file:** Status file may not exist if crawl hasn't started. Return `state=idle` in that case.

---

## Pipeline Collector (`internal/collector/pipeline.go`)

**Polls two sources:**

### 1. Task Scheduler log files

Log files are written by `D:\datacenter\scripts\` automation. Parse the last modified `.log` file in each stage's log directory.

**Stage → log directory mapping:**
```go
var stageLogDirs = map[string]string{
    "sync":    `D:\datacenter\logs\sync\`,
    "dq":      `D:\datacenter\logs\dq\`,
    "staging": `D:\datacenter\logs\staging\`,
    "gold":    `D:\datacenter\logs\gold\`,
}
```

**Parse last line of each log:** Look for `SUCCESS` or `FAILED` or `RUNNING` in the last 20 lines.

### 2. PostgreSQL row counts

```go
const countQuery = `
    SELECT 
        (SELECT COUNT(*) FROM staging.customs_transactions) AS staging_rows,
        (SELECT COUNT(*) FROM gold.fact_customs)            AS gold_rows,
        (SELECT MAX(created_at) FROM gold.fact_customs)     AS gold_last_update
`
```

**DSN:** `host=localhost port=5433 dbname=sts-dev user=dev4 password=IBM@Cognos#`  
**Driver:** `github.com/lib/pq`  
**Timeout:** 3s per query  
**Error handling:** If DB is unavailable, show last-known counts with staleness indicator.

---

## TUI Layout (bubbletea + lipgloss)

```
╔══════════════════════════════════════════════════════════════════════════╗
║            STS DATACENTER MONITOR   2026-06-16 10:30:45   [5s]         ║
╠══════════════════════════════════════════════════════════════════════════╣
║  CRAWL ACCOUNTS                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  ACC1  100.76.219.16   RUNNING   54_Import_Q1   seg 3   page 147/333   ║
║         vtic.stsgroup@gmail.com   scraped 4,410   2026-02-15..02-28     ║
║  ACC2  100.76.219.16   RUNNING   55_Export_Q1   seg 1   page  23/333   ║
║         no.vo@stsgroup.org.vn     scraped   690                          ║
║  ACC3  100.76.65.2     IDLE      —                                       ║
║         kay.nguyen@stsgroup.org.vn                                       ║
║  ACC4  100.76.65.2     ERROR     deep recovery failed                    ║
║         nguyenkhanhtailscale@gmail.com                                   ║
╠══════════════════════════════════════════════════════════════════════════╣
║  PIPELINE                                                                ║
╠══════════════════════════════════════════════════════════════════════════╣
║  SYNC     OK    last: 10:15:00                                           ║
║  DQ       OK    last: 10:17:32                                           ║
║  STAGING  OK    rows: 1,247,831                                          ║
║  GOLD     OK    rows:   987,432   updated: 10:20:15                      ║
╠══════════════════════════════════════════════════════════════════════════╣
║  q quit   r refresh   j/k scroll   ? help                                ║
╚══════════════════════════════════════════════════════════════════════════╝
```

**Color coding (lipgloss):**
- `RUNNING` → green
- `IDLE` → yellow
- `ERROR` → red bold
- `OK` → green
- `FAILED` → red bold
- Header/borders → blue

**Key bindings:**
- `q` — quit
- `r` — force refresh now
- `j` / `k` — scroll (if content > terminal height)
- `?` — toggle help overlay

---

## CLI Subcommands (cobra)

```
sts-monitor [flags]              # launch TUI (default)
sts-monitor status               # print JSON to stdout and exit
sts-monitor status --json        # same, explicit
sts-monitor crawl acc1           # show only ACC1 crawl detail
sts-monitor pipeline             # show only pipeline stages
sts-monitor logs [stage]         # tail last 50 lines from stage log
```

**Global flags:**
- `--interval 5s` — poll interval (default 5s)
- `--ssh-key path` — override SSH key path
- `--db dsn` — override PostgreSQL DSN

---

## Config (`internal/config/config.go`)

Loaded from `D:\datacenter\config\servers.json` + environment variables:

```go
type Config struct {
    Accounts []AccountConfig
    DB       DBConfig
    SSH      SSHConfig
    PollInterval time.Duration
}

type AccountConfig struct {
    Name        string `json:"name"`
    Host        string // parsed from name: "CRAWL-16-acc1" -> "100.76.219.16"
    AcctNum     int    // 1-4
    DeployPath  string // "C:\\CRAWL_STS\\ACC1\\DEPLOY_ACC_1"
    StatusPath  string // DeployPath + "\\data\\status.json"
}

type DBConfig struct {
    DSN string  // from env STS_DB_DSN or hardcoded default
}

type SSHConfig struct {
    User    string  // "pc"
    KeyPath string  // "C:\Users\tanmi\.ssh\id_rsa_sts"
}
```

---

## Go Module Setup

```
module github.com/dieplai/sts-datacenter-automation/tools/crawl-manager

go 1.22

require (
    github.com/charmbracelet/bubbletea v0.26.0
    github.com/charmbracelet/bubbles v0.18.0
    github.com/charmbracelet/lipgloss v0.11.0
    github.com/spf13/cobra v1.8.1
    github.com/lib/pq v1.10.9
    golang.org/x/crypto v0.24.0
)
```

**Binary name:** `sts-monitor`  
**Build output:** `tools/crawl-manager/bin/sts-monitor.exe`

**Build command:**
```powershell
cd tools/crawl-manager
go build -o bin/sts-monitor.exe ./cmd/
```

---

## Implementation Tasks

### B-1: Scaffold module + build
- Create `tools/crawl-manager/` directory tree
- Write `go.mod` with required deps
- Write `cmd/root.go` with cobra root command
- `go mod tidy` and verify `go build` succeeds (empty binary is fine at this stage)

### B-2: SSH pool
- Implement `internal/ssh/pool.go`
- Unit-testable: mock `ssh.Client` interface
- Test: connect to 100.76.219.16, read one file via SFTP

### B-3: Crawl collector
- Implement `internal/collector/crawl.go`
- Parse `status.json` into `AccountState`
- Handle: file missing, SSH error, malformed JSON

### B-4: Pipeline collector
- Implement `internal/collector/pipeline.go`
- Parse log files for stage status
- Query PostgreSQL for row counts
- 3s query timeout with graceful degradation

### B-5: TUI model
- Implement `internal/tui/model.go` (bubbletea Init/Update/View)
- Implement `internal/tui/view.go` (lipgloss layout)
- Wire tick message to collectors every 5s
- Test: run with mock data, verify layout renders correctly in terminal

### B-6: CLI subcommands
- Add `status`, `crawl`, `pipeline`, `logs` subcommands to cobra
- `status --json` prints `AppState` as JSON and exits

### B-7: Integration test
- Run against live crawl server (ACC1 must be crawling for full test)
- Verify: status.json is polled, displayed correctly, updates every 5s
- Verify: DB row counts are shown
- Verify: Error state shown when SSH host is unreachable

---

## Acceptance Criteria (Plan B complete)

- [ ] `sts-monitor` TUI launches and shows all 4 accounts + pipeline stages
- [ ] TUI updates every 5s without user interaction
- [ ] SSH disconnect from one server marks its accounts as ERROR, does not crash the tool
- [ ] `sts-monitor status --json` outputs valid JSON and exits 0
- [ ] `sts-monitor logs sync` shows last 50 lines of sync log
- [ ] Colors: RUNNING=green, ERROR=red, IDLE=yellow
- [ ] No panic on empty `status.json` or missing log files
- [ ] Binary size < 20 MB
- [ ] Build succeeds with `go build ./cmd/` on Windows (GOOS=windows, GOARCH=amd64)

---

## Dependencies on Plan A

- **Task 3 in Plan A** (status reporter) must be deployed before B-3 can be tested with live data
- SSH key and servers.json (`D:\datacenter\config\servers.json`) must exist (already confirmed)
- PostgreSQL must have `staging.customs_transactions` and `gold.fact_customs` tables (verify before B-4)
