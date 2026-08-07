package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func TestGatewayRequiresSecretAndPreservesAPIPrefix(t *testing.T) {
	const secret = "0123456789abcdef0123456789abcdef"
	var received *http.Request
	backend := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		received = request.Clone(request.Context())
		response.WriteHeader(http.StatusNoContent)
	}))
	defer backend.Close()
	target, err := url.Parse(backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	gateway := httptest.NewServer(newGateway(secret, target))
	defer gateway.Close()

	for _, provided := range []string{"", "wrong"} {
		request, err := http.NewRequest(http.MethodGet, gateway.URL+"/api/health", nil)
		if err != nil {
			t.Fatal(err)
		}
		request.Header.Set(secretHeader, provided)
		request.Header.Set("X-Auth-Request-Email", "forged@example.invalid")
		response, err := http.DefaultClient.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, response.Body)
		_ = response.Body.Close()
		if response.StatusCode != http.StatusUnauthorized {
			t.Fatalf("secret %q returned %d", provided, response.StatusCode)
		}
	}

	request, err := http.NewRequest(http.MethodGet, gateway.URL+"/api/health?ready=1", nil)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set(secretHeader, secret)
	request.Header.Set("X-Auth-Request-Email", "authenticated@example.invalid")
	request.Header.Set("X-Auth-Request-Groups", "evidence-editors")
	request.Header.Set("X-Forwarded-For", "203.0.113.44")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	_ = response.Body.Close()
	if response.StatusCode != http.StatusNoContent {
		t.Fatalf("authenticated request returned %d", response.StatusCode)
	}
	if received.URL.Path != "/api/health" || received.URL.RawQuery != "ready=1" {
		t.Fatalf("backend received %s?%s", received.URL.Path, received.URL.RawQuery)
	}
	if received.Header.Get(secretHeader) != secret {
		t.Fatal("backend did not receive the validated shared secret")
	}
	if received.Header.Get("X-Auth-Request-Email") != "authenticated@example.invalid" {
		t.Fatal("authenticated identity was not preserved")
	}
	if received.Header.Get("X-Forwarded-For") != "" {
		t.Fatalf("forwarded trust chain reached Uvicorn: %q", received.Header.Get("X-Forwarded-For"))
	}
}

func TestGatewayRejectsNonAPIRoutes(t *testing.T) {
	target, _ := url.Parse("http://127.0.0.1:1")
	request := httptest.NewRequest(http.MethodGet, "/health", nil)
	request.Header.Set(secretHeader, strings.Repeat("x", 32))
	response := httptest.NewRecorder()
	newGateway(strings.Repeat("x", 32), target).ServeHTTP(response, request)
	if response.Code != http.StatusNotFound {
		t.Fatalf("non-API route returned %d", response.Code)
	}
}

func TestChildEnvironmentMapsSecretOnlyToBackendContract(t *testing.T) {
	environment := childEnvironment([]string{
		"PATH=/bin",
		secretEnvironment + "=do-not-inherit",
		backendSecretEnvironment + "=do-not-trust-env-file",
		"EVIDENCE_AUTH_MODE=trusted_proxy",
	}, "shared-ingress-secret-0123456789")
	joined := strings.Join(environment, "\n")
	if strings.Contains(joined, secretEnvironment+"=") {
		t.Fatal("backend child inherited the gateway-only environment name")
	}
	if !strings.Contains(
		joined,
		backendSecretEnvironment+"=shared-ingress-secret-0123456789",
	) {
		t.Fatal("backend did not receive the shared secret under its configured name")
	}
	if strings.Contains(joined, "do-not-trust-env-file") {
		t.Fatal("backend env-file value overrode the gateway credential")
	}
	if !strings.Contains(joined, "EVIDENCE_AUTH_MODE=trusted_proxy") {
		t.Fatal("backend configuration was removed")
	}
}
