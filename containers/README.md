# Reproducible container artifacts

The flake builds the current application source into three Podman/Docker-loadable
OCI archives:

| Flake package | Embedded image reference | Entrypoint |
|---|---|---|
| `evidence-api-image` | `ai-coaching/evidence-api:flake` | Credential-checking gateway, then loopback-only Uvicorn |
| `evidence-worker-image` | `ai-coaching/evidence-worker:flake` | `evidence-worker` |
| `web-frontend-image` | `ai-coaching/web-frontend:flake` | BusyBox HTTP server on port 3000 |

The backend package is built from `pyproject.toml` and the checked-in Python
services. The frontend bundle is built with Vite from `apps/web/package-lock.json`
and is also exported separately as `packages.<system>.web-frontend`.

Build and load from a fresh checkout:

```sh
nix build .#evidence-api-image --out-link result-api
nix build .#evidence-worker-image --out-link result-worker
nix build .#web-frontend-image --out-link result-frontend

podman load --input ./result-api
podman load --input ./result-worker
podman load --input ./result-frontend

podman image exists ai-coaching/evidence-api:flake
podman image exists ai-coaching/evidence-worker:flake
podman image exists ai-coaching/web-frontend:flake
```

Manual loading is useful for inspection but is not required by the NixOS
module: setting both `image` and `imageFile` makes its generated service load
the archive before starting the matching image name.

Registry deployments may replace a local archive with
`registry/name@sha256:<64 hex characters>`. Floating tags are rejected.

Speakr is never rebuilt or repackaged here. It remains exactly:

`docker.io/learnedmachine/speakr@sha256:425a39e101ee69abe67e86ad53fec0b4ef7b13caed2ab30f388022beca8fdaf6`

The API gateway preserves the `/api` path, requires the runtime
`AI_COACHING_PROXY_AUTH_SECRET` hop credential, canonicalizes the validated
header before forwarding, maps it to the backend's
`EVIDENCE_TRUSTED_PROXY_SHARED_SECRET` setting only for the Uvicorn child, and
starts Uvicorn with proxy-header interpretation disabled.
