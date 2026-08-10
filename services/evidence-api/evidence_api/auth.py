import hmac
from dataclasses import dataclass
from enum import IntEnum
from ipaddress import IPv6Address, ip_address, ip_network

from fastapi import Depends, HTTPException, Request, status


class Role(IntEnum):
    VIEWER = 1
    EDITOR = 2
    ADMIN = 3


@dataclass(frozen=True)
class Principal:
    subject: str
    username: str
    role: Role


def require_principal(request: Request) -> Principal:
    settings = request.app.state.settings
    if settings.auth_mode == "development":
        # Dev-mode identity is not backed by any credential at all, so it
        # must never be reachable except from the local machine itself.
        # This is explicit and independent of network topology/deployment
        # config: even if EVIDENCE_AUTH_MODE were accidentally left as
        # "development" behind a real proxy, only loopback callers could
        # exploit it.
        if not _is_loopback(request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "development_auth_requires_loopback",
                    "message": (
                        "development auth mode only accepts connections "
                        "from loopback"
                    ),
                },
            )
        return Principal(
            settings.development_user,
            settings.development_user,
            Role[settings.development_role.upper()],
        )

    # Fail closed, in this exact order:
    #   1. A credential-backed shared secret must be configured for this
    #      deployment AND presented by the caller on every request. This is
    #      independent of identity headers and of network position: a peer
    #      container that merely shares a network with this service (and so
    #      could otherwise reach it directly and forge identity headers)
    #      cannot authenticate without also holding this secret. Comparison
    #      is constant-time to avoid leaking the secret via response timing.
    #      A request is rejected the same way whether the secret is simply
    #      unconfigured, missing from the request, or wrong -- the caller
    #      cannot distinguish "misconfigured server" from "wrong secret".
    configured_secret = settings.trusted_proxy_shared_secret or ""
    provided_secret = request.headers.get(settings.trusted_proxy_secret_header, "")
    if not configured_secret or not hmac.compare_digest(
        provided_secret, configured_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "proxy_secret_required",
                "message": (
                    "a valid credential-backed proxy secret header is required"
                ),
            },
        )

    #   2. The connection must additionally originate from an explicitly
    #      trusted network (loopback by default; see config.py). This is
    #      belt-and-suspenders alongside the shared secret, not a substitute
    #      for it: client-supplied "X-Forwarded-For"-style headers are never
    #      consulted here, only the actual peer socket address, so this
    #      check cannot be spoofed by rewriting request headers.
    if not _client_ip_is_trusted(request, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "untrusted_proxy",
                "message": "identity headers were not received from a trusted proxy",
            },
        )

    #   3. Only now do we trust the identity headers themselves.
    subject = request.headers.get(settings.trusted_email_header)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "authentication_required",
                "message": "authenticated proxy identity header is missing",
            },
        )
    username = _display_username(
        subject,
        request.headers.get(settings.trusted_username_header),
        request.headers.get(settings.trusted_user_header),
    )
    groups = {
        item.strip().casefold()
        for item in request.headers.get(settings.trusted_groups_header, "").split(",")
        if item.strip()
    }
    admin_groups = _configured_groups(settings.admin_groups)
    editor_groups = _configured_groups(settings.editor_groups)
    role = (
        Role.ADMIN
        if groups & admin_groups
        else Role.EDITOR
        if groups & editor_groups
        else Role.VIEWER
    )
    return Principal(subject.strip(), username, role)


def require_editor(
    principal: Principal = Depends(require_principal),
) -> Principal:
    return _require_role(principal, Role.EDITOR)


def require_admin(
    principal: Principal = Depends(require_principal),
) -> Principal:
    return _require_role(principal, Role.ADMIN)


def _configured_groups(value: str) -> set[str]:
    return {item.strip().casefold() for item in value.split(",") if item.strip()}


def _display_username(subject: str, *candidates: str | None) -> str:
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()
    clean_subject = subject.strip()
    if "@" in clean_subject:
        return clean_subject.split("@", 1)[0]
    return clean_subject


def _client_ip(request: Request):
    client_host = request.client.host if request.client else ""
    try:
        candidate = ip_address(client_host)
    except ValueError:
        return None
    if isinstance(candidate, IPv6Address) and candidate.ipv4_mapped is not None:
        # Normalize IPv4-mapped IPv6 addresses (e.g. "::ffff:127.0.0.1"), a
        # representation dual-stack sockets may use for what is actually a
        # plain IPv4 loopback/proxy connection, so it is not spuriously
        # rejected by an IPv4-only trusted-network entry.
        return candidate.ipv4_mapped
    return candidate


def _is_loopback(request: Request) -> bool:
    client_ip = _client_ip(request)
    return client_ip is not None and client_ip.is_loopback


def _client_ip_is_trusted(request: Request, settings) -> bool:
    client_ip = _client_ip(request)
    if client_ip is None:
        return False
    trusted_networks = [
        ip_network(item.strip(), strict=False)
        for item in settings.trusted_proxy_networks.split(",")
        if item.strip()
    ]
    return any(client_ip in network for network in trusted_networks)


def _require_role(principal: Principal, role: Role) -> Principal:
    if principal.role < role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "insufficient_role",
                "message": f"{role.name.lower()} role is required",
            },
        )
    return principal
