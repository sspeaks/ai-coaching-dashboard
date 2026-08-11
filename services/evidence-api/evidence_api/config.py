from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EVIDENCE_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["production", "development", "test"] = "production"
    database_url: str = "sqlite:///./evidence.db"
    media_root: Path = Path("./data/media")
    max_upload_bytes: int = 5 * 1024 * 1024 * 1024
    auth_mode: Literal["trusted_proxy", "development"] = "trusted_proxy"
    # These header names must match what the deployment's edge proxy actually
    # forwards (e.g. oauth2-proxy's forward_auth response headers copied by
    # Caddy), not whatever a client could set. The historical defaults below
    # matched headers the edge is expected to strip from client input, which
    # would have silently deadlocked authentication; they now match the
    # documented NixOS deployment (see nix/containers.nix).
    trusted_email_header: str = "x-auth-request-email"
    trusted_username_header: str = "x-auth-request-preferred-username"
    trusted_user_header: str = "x-auth-request-user"
    trusted_groups_header: str = "x-auth-request-groups"
    # A credential-backed hop secret the edge/gateway must present on every
    # request in addition to identity headers. This is independent
    # defense-in-depth inside the application itself: even if a peer
    # container on the same private network reaches this service directly
    # and forges identity headers, it cannot authenticate without this
    # secret. Required whenever auth_mode is trusted_proxy; never logged.
    trusted_proxy_secret_header: str = "x-ai-coaching-proxy-auth"
    trusted_proxy_shared_secret: str | None = None
    # Loopback-only by default: the only topology in which a proxy-forwarded
    # request should ever reach this process directly. Broader private
    # ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) are deliberately not
    # trusted by default because any peer container on those networks could
    # otherwise reach this service and spoof identity headers.
    trusted_proxy_networks: str = "127.0.0.1/32,::1/128"
    admin_groups: str = "evidence-admins"
    editor_groups: str = "evidence-editors"
    development_user: str = "local-developer@example.invalid"
    development_role: Literal["admin", "editor", "viewer"] = "admin"

    speakr_base_url: str | None = None
    speakr_api_token: str | None = None
    speakr_webhook_secret: str | None = None
    speakr_timeout_seconds: float = 60
    speakr_verify_tls: bool = True
    webhook_freshness_seconds: int = 300

    extraction_provider: Literal["disabled", "http_json"] = "disabled"
    extraction_endpoint: str | None = None
    extraction_api_key: str | None = None
    summary_max_themes: int = 25
    # The gateway extracts a long session one window at a time, so a single
    # call to it covers several sequential model requests.
    extraction_timeout_seconds: float = 900

    worker_poll_seconds: float = 5
    worker_transcription_poll_seconds: float = 15
    # Must exceed extraction_timeout_seconds, or a still-running extraction
    # looks abandoned and a second worker picks the job up alongside the first.
    worker_job_lease_seconds: int = 1200
    reconciliation_interval_seconds: int = 3600
    worker_max_attempts: int = 3

    @property
    def summary_endpoint(self) -> str | None:
        """Derived so summaries need no separate endpoint configuration."""

        if not self.extraction_endpoint:
            return None
        return self.extraction_endpoint.rstrip("/") + "/summarize"

    @property
    def consolidation_endpoint(self) -> str | None:
        """Derived so consolidation needs no separate endpoint configuration."""

        if not self.extraction_endpoint:
            return None
        return self.extraction_endpoint.rstrip("/") + "/consolidate"

    @model_validator(mode="after")
    def secure_development_auth(self) -> "Settings":
        if self.auth_mode == "development" and self.environment == "production":
            raise ValueError("development auth cannot be enabled in production")
        if self.auth_mode == "trusted_proxy":
            # A missing secret is intentionally NOT a construction-time
            # error: Settings() is built at module import (see
            # evidence_api.app's module-level `app = create_app()`), which
            # must keep working for tooling/tests that never serve traffic.
            # Instead, `auth.require_principal` fails every request closed
            # (401) whenever no secret is configured. We do validate the
            # shape of a *configured* secret here, since that only runs when
            # an operator has actually supplied one.
            if (
                self.trusted_proxy_shared_secret is not None
                and len(self.trusted_proxy_shared_secret) < 32
            ):
                raise ValueError(
                    "trusted_proxy_shared_secret must contain at least 32 characters"
                )
            if not self.trusted_proxy_secret_header.strip():
                raise ValueError("trusted_proxy_secret_header cannot be empty")
        if self.webhook_freshness_seconds < 1:
            raise ValueError("webhook_freshness_seconds must be positive")
        if self.worker_transcription_poll_seconds < 0:
            raise ValueError("worker_transcription_poll_seconds cannot be negative")
        if self.worker_job_lease_seconds < 1:
            raise ValueError("worker_job_lease_seconds must be positive")
        if self.worker_job_lease_seconds <= self.extraction_timeout_seconds:
            raise ValueError(
                "worker_job_lease_seconds must exceed extraction_timeout_seconds "
                "so a running extraction is never treated as abandoned"
            )
        for value in self.trusted_proxy_networks.split(","):
            if value.strip():
                ip_network(value.strip(), strict=False)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
