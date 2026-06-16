package collector

import "time"

// AccountState holds the latest crawl status for one account.
type AccountState struct {
	Name         string
	Host         string
	Email        string
	Batch        string
	Segment      int
	SegmentStart string
	SegmentEnd   string
	Page         int
	TotalScraped int
	State        string    // "running" | "idle" | "error" | "unknown"
	LastUpdate   time.Time
	ErrMsg       string
}

// StageStatus holds the status of one pipeline stage.
type StageStatus struct {
	Name       string
	Status     string    // "ok" | "running" | "failed" | "unknown"
	LastRun    time.Time
	RowCount   int64
	LastUpdate time.Time
}

// AppState is the complete snapshot of all monitored systems.
type AppState struct {
	Accounts  []AccountState
	Stages    []StageStatus
	PollEvery time.Duration
	PolledAt  time.Time
	FatalErr  string
}
