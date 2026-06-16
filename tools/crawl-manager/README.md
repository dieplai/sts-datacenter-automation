# STS Datacenter Monitor

Real-time TUI + CLI tool for monitoring all 4 crawl accounts and the full pipeline.

## Prerequisites
- Go 1.22+
- SSH access to crawl servers (key at `~/.ssh/id_rsa_sts`, override with `STS_SSH_KEY`)
- PostgreSQL access (override DSN with `STS_DB_DSN`)

## Build
```powershell
cd tools/crawl-manager
go mod tidy
go build -o bin/sts-monitor.exe ./cmd/
```

## Run
```powershell
# Launch TUI
.\bin\sts-monitor.exe

# Print JSON status and exit
.\bin\sts-monitor.exe status --json

# Custom poll interval
.\bin\sts-monitor.exe --interval 10s
```

## Environment Variables
| Variable | Default | Description |
|---|---|---|
| `STS_SSH_KEY` | `~/.ssh/id_rsa_sts` | Path to SSH private key |
| `STS_DB_DSN` | `host=localhost port=5433 ...` | PostgreSQL DSN |

## Key Bindings (TUI)
| Key | Action |
|---|---|
| `q` / `Ctrl+C` | Quit |
| `r` | Force refresh |
