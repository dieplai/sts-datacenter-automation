package config

import (
	"os"
	"path/filepath"
	"runtime"
	"time"
)

// AccountConfig holds connection info for one crawl account.
type AccountConfig struct {
	Name       string
	AcctNum    int    // 1-4
	Host       string // "100.76.219.16" or "100.76.65.2"
	DeployDir  string // e.g. "C:\\CRAWL_STS\\ACC1\\DEPLOY_ACC_1"
	Email      string
}

// Config holds all runtime configuration.
type Config struct {
	Accounts     []AccountConfig
	DBDSN        string
	SSHUser      string
	SSHKeyPath   string
	LogBasePaths map[string]string // stage -> log directory
}

func DefaultConfig() *Config {
	sshKey := filepath.Join(homeDir(), ".ssh", "id_rsa_sts")
	if v := os.Getenv("STS_SSH_KEY"); v != "" {
		sshKey = v
	}
	dsn := "host=localhost port=5433 dbname=sts-dev user=dev4 password=IBM@Cognos# sslmode=disable"
	if v := os.Getenv("STS_DB_DSN"); v != "" {
		dsn = v
	}
	return &Config{
		Accounts: []AccountConfig{
			{Name: "ACC1", AcctNum: 1, Host: "100.76.219.16", DeployDir: `C:\CRAWL_STS\ACC1\DEPLOY_ACC_1`, Email: "vtic.stsgroup@gmail.com"},
			{Name: "ACC2", AcctNum: 2, Host: "100.76.219.16", DeployDir: `C:\CRAWL_STS\ACC2\DEPLOY_ACC_2`, Email: "no.vo@stsgroup.org.vn"},
			{Name: "ACC3", AcctNum: 3, Host: "100.76.65.2",   DeployDir: `C:\CRAWL_STS\ACC3\DEPLOY_ACC_3`, Email: "kay.nguyen@stsgroup.org.vn"},
			{Name: "ACC4", AcctNum: 4, Host: "100.76.65.2",   DeployDir: `C:\CRAWL_STS\ACC4\DEPLOY_ACC_4`, Email: "nguyenkhanhtailscale@gmail.com"},
		},
		DBDSN:      dsn,
		SSHUser:    "pc",
		SSHKeyPath: sshKey,
		LogBasePaths: map[string]string{
			"sync":    `D:\datacenter\logs\sync\`,
			"dq":      `D:\datacenter\logs\dq\`,
			"staging": `D:\datacenter\logs\staging\`,
			"gold":    `D:\datacenter\logs\gold\`,
		},
	}
}

// StatusPath returns the remote path to status.json for this account.
func (c *AccountConfig) StatusPath() string {
	return filepath.Join(c.DeployDir, "data", "status.json")
}

// PollInterval returns the default polling interval.
func (c *Config) PollInterval() time.Duration {
	return 5 * time.Second
}

func homeDir() string {
	if h := os.Getenv("USERPROFILE"); h != "" {
		return h
	}
	if h := os.Getenv("HOME"); h != "" {
		return h
	}
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("HOMEDRIVE"), os.Getenv("HOMEPATH"))
	}
	return "."
}
