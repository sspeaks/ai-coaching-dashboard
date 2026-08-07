package main

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

const (
	secretEnvironment        = "AI_COACHING_PROXY_AUTH_SECRET"
	backendSecretEnvironment = "EVIDENCE_TRUSTED_PROXY_SHARED_SECRET"
	secretHeader             = "X-AI-Coaching-Proxy-Auth"
	defaultListen            = "0.0.0.0:8000"
	defaultBackend           = "127.0.0.1:18000"
)

var backendExecutable = "uvicorn"

func main() {
	secret := os.Getenv(secretEnvironment)
	if len(secret) < 32 {
		log.Fatalf("%s must contain at least 32 characters", secretEnvironment)
	}

	listenAddress := environmentOrDefault("AI_COACHING_GATEWAY_LISTEN_ADDRESS", defaultListen)
	backendAddress := environmentOrDefault("AI_COACHING_GATEWAY_BACKEND_ADDRESS", defaultBackend)

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	backend := exec.Command(
		backendExecutable,
		"evidence_api.app:app",
		"--host",
		hostFromAddress(backendAddress),
		"--port",
		portFromAddress(backendAddress),
		"--no-proxy-headers",
	)
	backend.Env = childEnvironment(os.Environ(), secret)
	backend.Stdout = os.Stdout
	backend.Stderr = os.Stderr
	if err := backend.Start(); err != nil {
		log.Fatalf("start evidence API: %v", err)
	}

	backendDone := make(chan error, 1)
	go func() {
		backendDone <- backend.Wait()
	}()

	backendExited, err := waitForBackend(ctx, backendAddress, backendDone)
	if err != nil {
		cancel()
		if !backendExited {
			if stopErr := stopBackend(backend, backendDone); stopErr != nil {
				log.Printf("stop evidence API after startup failure: %v", stopErr)
			}
		}
		log.Fatal(err)
	}

	target, err := url.Parse("http://" + backendAddress)
	if err != nil {
		log.Fatalf("parse backend address: %v", err)
	}
	server := &http.Server{
		Addr:              listenAddress,
		Handler:           newGateway(secret, target),
		ReadHeaderTimeout: 15 * time.Second,
	}
	serverDone := make(chan error, 1)
	go func() {
		log.Printf("authenticated API gateway listening on %s", listenAddress)
		serverDone <- server.ListenAndServe()
	}()

	var result error
	select {
	case <-ctx.Done():
	case err := <-backendDone:
		backendExited = true
		result = fmt.Errorf("evidence API exited: %w", err)
	case err := <-serverDone:
		if !errors.Is(err, http.ErrServerClosed) {
			result = fmt.Errorf("API gateway exited: %w", err)
		}
	}

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	if err := server.Shutdown(shutdownCtx); err != nil && result == nil {
		result = fmt.Errorf("shut down API gateway: %w", err)
	}
	if !backendExited {
		if err := stopBackend(backend, backendDone); err != nil && result == nil {
			result = fmt.Errorf("stop evidence API: %w", err)
		}
	}
	if result != nil {
		log.Fatal(result)
	}
}

func stopBackend(backend *exec.Cmd, backendDone <-chan error) error {
	if err := backend.Process.Signal(syscall.SIGTERM); err != nil &&
		!errors.Is(err, os.ErrProcessDone) {
		return err
	}
	timer := time.NewTimer(10 * time.Second)
	defer timer.Stop()
	select {
	case err := <-backendDone:
		return err
	case <-timer.C:
		if err := backend.Process.Kill(); err != nil && !errors.Is(err, os.ErrProcessDone) {
			return err
		}
		<-backendDone
		return errors.New("timed out stopping evidence API")
	}
}

func newGateway(secret string, target *url.URL) http.Handler {
	proxy := &httputil.ReverseProxy{
		Rewrite: func(request *httputil.ProxyRequest) {
			request.SetURL(target)
			request.Out.Host = target.Host
			request.Out.Header.Set(secretHeader, secret)
		},
	}
	return http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/api" && !strings.HasPrefix(request.URL.Path, "/api/") {
			http.NotFound(response, request)
			return
		}
		if !validSecret(request.Header.Get(secretHeader), secret) {
			http.Error(response, "authenticated ingress credential required", http.StatusUnauthorized)
			return
		}
		proxy.ServeHTTP(response, request)
	})
}

func validSecret(provided, expected string) bool {
	providedHash := sha256.Sum256([]byte(provided))
	expectedHash := sha256.Sum256([]byte(expected))
	return subtle.ConstantTimeCompare(providedHash[:], expectedHash[:]) == 1
}

func childEnvironment(environment []string, secret string) []string {
	proxyPrefix := secretEnvironment + "="
	backendPrefix := backendSecretEnvironment + "="
	filtered := make([]string, 0, len(environment)+1)
	for _, entry := range environment {
		if !strings.HasPrefix(entry, proxyPrefix) &&
			!strings.HasPrefix(entry, backendPrefix) {
			filtered = append(filtered, entry)
		}
	}
	filtered = append(filtered, backendPrefix+secret)
	return filtered
}

func waitForBackend(
	ctx context.Context,
	address string,
	backendDone <-chan error,
) (bool, error) {
	deadline := time.NewTimer(30 * time.Second)
	defer deadline.Stop()
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		connection, err := net.DialTimeout("tcp", address, 250*time.Millisecond)
		if err == nil {
			_ = connection.Close()
			return false, nil
		}
		select {
		case <-ctx.Done():
			return false, ctx.Err()
		case err := <-backendDone:
			return true, fmt.Errorf("evidence API exited before becoming ready: %w", err)
		case <-deadline.C:
			return false, fmt.Errorf(
				"evidence API did not listen on %s within 30 seconds",
				address,
			)
		case <-ticker.C:
		}
	}
}

func hostFromAddress(address string) string {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		log.Fatalf("invalid backend address %q: %v", address, err)
	}
	return host
}

func portFromAddress(address string) string {
	_, port, err := net.SplitHostPort(address)
	if err != nil {
		log.Fatalf("invalid backend address %q: %v", address, err)
	}
	return port
}

func environmentOrDefault(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
