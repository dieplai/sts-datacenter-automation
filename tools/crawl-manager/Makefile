.PHONY: build clean

BINARY = bin/sts-monitor.exe
GOFLAGS = -ldflags="-s -w"

build:
	go build $(GOFLAGS) -o $(BINARY) ./cmd/

clean:
	del /F /Q $(BINARY) 2>nul || true
