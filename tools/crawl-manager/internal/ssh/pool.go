package ssh

import (
	"fmt"
	"net"
	"os"
	"sync"
	"time"

	gossh "golang.org/x/crypto/ssh"
)

// Pool manages one persistent SSH connection per host.
type Pool struct {
	mu    sync.Mutex
	conns map[string]*gossh.Client
	cfg   *gossh.ClientConfig
}

// NewPool creates a pool using the given RSA private key file.
func NewPool(user, keyPath string) (*Pool, error) {
	keyBytes, err := os.ReadFile(keyPath)
	if err != nil {
		return nil, fmt.Errorf("read ssh key %s: %w", keyPath, err)
	}
	signer, err := gossh.ParsePrivateKey(keyBytes)
	if err != nil {
		return nil, fmt.Errorf("parse ssh key: %w", err)
	}
	cfg := &gossh.ClientConfig{
		User:            user,
		Auth:            []gossh.AuthMethod{gossh.PublicKeys(signer)},
		HostKeyCallback: gossh.InsecureIgnoreHostKey(),
		Timeout:         10 * time.Second,
	}
	return &Pool{conns: make(map[string]*gossh.Client), cfg: cfg}, nil
}

// Get returns an existing connection or dials a new one.
func (p *Pool) Get(host string) (*gossh.Client, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if c, ok := p.conns[host]; ok {
		// Probe the connection with a no-op to detect stale TCP.
		_, _, err := c.SendRequest("keepalive@openssh.com", true, nil)
		if err == nil {
			return c, nil
		}
		// Stale — reconnect.
		c.Close()
		delete(p.conns, host)
	}

	addr := net.JoinHostPort(host, "22")
	c, err := gossh.Dial("tcp", addr, p.cfg)
	if err != nil {
		return nil, fmt.Errorf("ssh dial %s: %w", host, err)
	}
	p.conns[host] = c
	return c, nil
}

// Close closes all connections.
func (p *Pool) Close() {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, c := range p.conns {
		c.Close()
	}
	p.conns = make(map[string]*gossh.Client)
}
