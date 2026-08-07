# AI coaching NixOS operations

## Architecture and routing

Caddy is the only public listener. Production requests use this path:

```text
browser -> Caddy -> oauth2-proxy OIDC forward-auth -> API gateway -> FastAPI
browser -> Caddy -> oauth2-proxy OIDC forward-auth -> frontend
Speakr webhook -> Caddy -> signed route -> API gateway -> FastAPI
evidence worker -> extraction gateway -> OpenAI
```

Caddy removes every client-supplied identity, group, forwarded-trust, and
internal hop-auth header. oauth2-proxy uses explicit issuer, client ID, scopes,
verified email claim, groups claim, callback, and loopback trusted-proxy
configuration. Caddy copies only oauth2-proxy's authenticated
`X-Auth-Request-Email` and `X-Auth-Request-Groups` response headers.
When TLS is terminated by an upstream reverse proxy, set
`services.aiCoaching.caddy.externalTls.enable = true` and choose
`services.aiCoaching.caddy.externalTls.httpPort`. The dashboard vhost then
listens as plain HTTP (`http://<domain>:<httpPort>`) and does not request ACME
certificates locally. Caddy still strips client-supplied forwarded headers
before auth, then sends oauth2-proxy explicit HTTPS forwarded headers so
`--reverse-proxy`, secure cookies, and redirects match the public HTTPS URL;
oauth2-proxy continues to trust only loopback because Caddy is its immediate
proxy.

The frontend and FastAPI contracts are both rooted at `/api`; neither Caddy nor
the API gateway strips that prefix. Before proxying an API or signed webhook
request, Caddy injects `X-AI-Coaching-Proxy-Auth` from a root-readable runtime
environment file. The API container starts a small gateway on port 8000 that
requires this credential, canonicalizes the validated header, and forwards the
unchanged `/api/...` path to Uvicorn on container loopback with proxy-header
interpretation disabled. The gateway maps the same credential to the backend's
expected `EVIDENCE_TRUSTED_PROXY_SHARED_SECRET` only in the Uvicorn child
environment, so the application independently verifies the header. Peer
containers can reach the gateway but cannot forge identity without the shared
credential, and they cannot reach Uvicorn directly. The worker receives neither
the Caddy credential nor the API environment file.

`/api/webhooks/speakr` bypasses interactive OIDC but still crosses the
credentialed gateway and then relies on the backend's signed-webhook
verification.

API and worker both mount the host's `dataDir/media` at `/data/media`.
`EVIDENCE_MEDIA_ROOT=/data/media` is forced in both containers, so database
media paths are valid in either process and originals survive replacement,
restart, and upgrade.

Structured ledger extraction is isolated behind the optional extraction gateway
container. The worker speaks the existing `http_json` contract to the gateway
over the private Podman network; only the gateway receives transcript text and
the OpenAI API key. The gateway is a single-process FastAPI/Uvicorn service with
no persistent volume and is expected to use roughly 80-150 MB RSS plus transient
request buffers. Ledger entry `confidence` values are model-self-reported and
uncalibrated; they are not probabilities and must not replace human review.

## Reproducible outputs

```sh
nix flake show
nix build .#evidence-backend
nix build .#web-frontend
nix build .#evidence-api-image
nix build .#evidence-worker-image
nix build .#extraction-gateway-image
nix build .#web-frontend-image
```

The image names embedded in the archives are:

- `ai-coaching/evidence-api:flake`
- `ai-coaching/evidence-worker:flake`
- `ai-coaching/extraction-gateway:flake`
- `ai-coaching/web-frontend:flake`

Inspect them locally:

```sh
nix build .#evidence-api-image --out-link result-api
nix build .#evidence-worker-image --out-link result-worker
nix build .#extraction-gateway-image --out-link result-extraction
nix build .#web-frontend-image --out-link result-frontend
podman load --input ./result-api
podman load --input ./result-worker
podman load --input ./result-extraction
podman load --input ./result-frontend
podman image inspect ai-coaching/evidence-api:flake
```

The NixOS `imageFile` deployment path loads these archives automatically.
Remote alternatives must use exact `name@sha256:<64 hex>` references.

Speakr is read-only in the module and remains unmodified at:

`docker.io/learnedmachine/speakr@sha256:425a39e101ee69abe67e86ad53fec0b4ef7b13caed2ab30f388022beca8fdaf6`

## Fresh-checkout deployment

1. Clone this repository on the NixOS host and validate it:

   ```sh
   git clone <repository-url> /etc/nixos/ai-coaching-dashboard
   cd /etc/nixos/ai-coaching-dashboard
   nix flake check
   ```

2. Add the checkout to the host flake and pass `inputs` to modules:

   ```nix
   {
     inputs = {
       nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
       ai-coaching-dashboard.url = "path:/etc/nixos/ai-coaching-dashboard";
       ai-coaching-dashboard.inputs.nixpkgs.follows = "nixpkgs";
     };

     outputs = inputs@{ nixpkgs, ... }: {
       nixosConfigurations.coaching-host = nixpkgs.lib.nixosSystem {
         system = "x86_64-linux";
         specialArgs = { inherit inputs; };
         modules = [
           ./hardware-configuration.nix
           inputs.ai-coaching-dashboard.nixosModules.aiCoaching
           ./ai-coaching.nix
         ];
       };
     };
   }
   ```

3. Copy `deploy/example-configuration.nix` to the host flake as
   `ai-coaching.nix`, then replace the example domain, issuer, client ID,
   email domain, subnet, and ACME email. It already references the real flake
   image archives; no digest placeholders are required.

4. Populate secrets out-of-band, then build and switch:

   ```sh
   sudo nixos-rebuild build --flake /etc/nixos#coaching-host
   sudo nixos-rebuild switch --flake /etc/nixos#coaching-host
   ```

5. Verify:

   ```sh
   systemctl --no-pager --full status \
     podman-speakr podman-evidence-api podman-evidence-worker \
     podman-web-frontend oauth2-proxy caddy postgresql
   curl -I https://coaching.example.org/
   curl -I https://coaching.example.org/api/health
   ```

6. Complete the one-time Speakr bootstrap described below before submitting
   recordings.

## Secrets

Create `/var/lib/ai-coaching/secrets` as root and use mode `0400` for files:

| File | Runtime content |
|---|---|
| `oidc-client-secret` | OIDC client secret |
| `oauth2-proxy-cookie-secret` | `openssl rand -base64 32` output |
| `postgresql-evidence-password` | PostgreSQL role password |
| `proxy-auth.env` | Exactly `AI_COACHING_PROXY_AUTH_SECRET=<at least 32 random characters>`; loaded only by Caddy and the API gateway |
| `speakr.env` | First-boot `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, stable `SECRET_KEY`, and Speakr-supported transcription/text-model credentials |
| `evidence-api.env` | `EVIDENCE_DATABASE_URL`, the user-bound `EVIDENCE_SPEAKR_API_TOKEN`, and `EVIDENCE_SPEAKR_WEBHOOK_SECRET` |
| `evidence-worker.env` | `EVIDENCE_DATABASE_URL`, the same user-bound `EVIDENCE_SPEAKR_API_TOKEN`, and—when extraction is enabled—`EVIDENCE_EXTRACTION_API_KEY` |
| `extraction-gateway.env` | `EXTRACTION_GATEWAY_OPENAI_API_KEY` and `EXTRACTION_GATEWAY_INBOUND_API_KEY`; the inbound key must equal the worker's `EVIDENCE_EXTRACTION_API_KEY` |

Do not put values in Nix expressions. The module sets non-secret production
contract values (auth mode, exact trusted email/group headers, loopback-only
trusted proxy networks, role groups, media root, and Speakr network URL)
directly and they override conflicting env-file values.

To enable structured extraction, configure the gateway image and keep the shared
bearer token in both secret env files:

```nix
services.aiCoaching.extractionGateway = {
  enable = true;
  image = "ai-coaching/extraction-gateway:flake";
  imageFile = inputs.ai-coaching-dashboard.packages.${pkgs.stdenv.hostPlatform.system}.extraction-gateway-image;
};
```

The module then sets the worker's non-secret routing values:

```text
EVIDENCE_EXTRACTION_PROVIDER=http_json
EVIDENCE_EXTRACTION_ENDPOINT=http://extraction-gateway:8080/
```

Set these secrets out-of-band:

```text
# evidence-worker.env
EVIDENCE_EXTRACTION_API_KEY=<shared-random-token>

# extraction-gateway.env
EXTRACTION_GATEWAY_OPENAI_API_KEY=<openai-api-key>
EXTRACTION_GATEWAY_INBOUND_API_KEY=<same-shared-random-token>
EXTRACTION_GATEWAY_OPENAI_MODEL=gpt-4o
EXTRACTION_GATEWAY_OPENAI_BASE_URL=https://api.openai.com/v1
EXTRACTION_GATEWAY_REQUEST_TIMEOUT_SECONDS=120
```

## Authentik UI setup

Create this manually in the Authentik admin UI; do not use the Authentik API.
For the `streams.sspeaks.net` deployment, use the slug `ai-coaching` so the
issuer URL is exactly:

```text
https://auth.sspeaks.net/application/o/ai-coaching/
```

1. Go to **Applications → Providers → Create**.
2. Provider type: **OAuth2/OpenID Provider**.
3. Name: `AI Coaching Dashboard`.
4. Authorization flow: Authentik's default explicit consent or default
   authorization flow.
5. Client type: **Confidential**.
6. Client ID: `ai-coaching` if the UI allows setting it; otherwise copy the
   generated **Client ID** from the provider detail page and set
   `services.aiCoaching.oidc.clientID` to that value in the host config.
7. Copy the generated **Client Secret** from the same provider page into the
   deployment secret named `ai-coaching-oidc-client-secret`.
8. Redirect URIs / redirect URI regex:

   ```text
   https://streams.sspeaks.net/oauth2/callback
   ```

9. Signing key / algorithm: use Authentik's default RSA signing key with
   **RS256**.
10. Subject mode: **Based on the User's ID**.
11. Scope mappings: include `openid`, `email`, `profile`, and an explicit
    `groups` mapping. The Nix config requests these scopes and sets
    `groupsClaim = "groups"`, so oauth2-proxy will copy the received
    `groups` claim into `X-Auth-Request-Groups` for the backend.
12. Create the explicit groups scope mapping if it is not already present:
    go to **Customization → Property Mappings → Create → OAuth2/OpenID Scope
    Mapping** and set:

    ```text
    Name: AI Coaching groups
    Scope name: groups
    Description: Group names for AI Coaching Dashboard RBAC
    Expression:
    return {
        "groups": [group.name for group in request.user.groups.all()],
    }
    ```

    Add this mapping to the provider's Scope mappings. Authentik's built-in
    `profile` mapping also commonly emits `groups` as group names, but this
    explicit mapping makes the deployment contract unambiguous.
13. Go to **Applications → Applications → Create**.
14. Name: `AI Coaching Dashboard`.
15. Slug: `ai-coaching`.
16. Provider: select the provider created above.
17. Security-critical access gate: bind the Application to the existing
    Authentik `quartet-members` group (or an equivalent allow policy) so only
    that group can launch the app. The Nix config intentionally sets
    `emailDomains = [ "*" ]`, which oauth2-proxy documents as "authenticate
    any email", so dashboard access is otherwise as broad as whatever
    Authentik will authenticate. This binding is an access gate only; it is
    also the dashboard admin role source: Nix maps `quartet-members` to
    `adminGroups`, and admins satisfy editor-only endpoints such as creating
    sessions and uploading media. Confirm Authentik emits the plain group name
    `quartet-members` in the `groups` claim (not a UUID, path, or DN).

Create the hop credential without printing it:

```sh
sudo sh -c 'umask 077; printf "AI_COACHING_PROXY_AUTH_SECRET=%s\n" \
  "$(openssl rand -hex 32)" > /var/lib/ai-coaching/secrets/proxy-auth.env'
```

Restart both consumers whenever that file is rotated:

```sh
sudo systemctl restart caddy podman-evidence-api
```

## Fresh-host Speakr bootstrap

Speakr is intentionally not routed through the public Caddy virtual host. Its
published port is `127.0.0.1:8899`, so bootstrap it through host-local access
or an SSH tunnel:

```sh
ssh -N -L 8899:127.0.0.1:8899 <operator>@<coaching-host>
```

Before the first `podman-speakr` start, place the initial account and provider
settings in root-owned `speakr.env`:

```text
ADMIN_USERNAME=<initial-admin-name>
ADMIN_EMAIL=<initial-admin-address>
ADMIN_PASSWORD=<strong-unique-password>
SECRET_KEY=<stable-random-secret>
TEXT_MODEL_BASE_URL=https://api.openai.com/v1
TEXT_MODEL_API_KEY=<OpenAI API key>
TEXT_MODEL_NAME=gpt-4.1-mini
TRANSCRIPTION_API_KEY=<OpenAI API key>
TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
```

Use Speakr's documented `ASR_BASE_URL` settings instead of the transcription
API variables when operating a self-hosted ASR service. Apply mode `0400`,
restart `podman-speakr`, browse to `http://127.0.0.1:8899` through the tunnel,
and sign in with the initial account. The first account created from these
variables is the administrator.

Create the integration credential while signed in as the account that should
own dashboard-created recordings:

1. Open **Account Settings → API Tokens**.
2. Create a descriptively named token such as `ai-coaching-evidence`.
3. Choose the operator's expiration policy and copy the token immediately; it
   is shown only once and has the same access as that user.
4. Store it as `EVIDENCE_SPEAKR_API_TOKEN` in both `evidence-api.env` and
   `evidence-worker.env`. Never put it in browser code or Nix.
5. Restart `podman-evidence-api` and `podman-evidence-worker`.

In **Account Settings → Webhooks**, create a webhook targeting
`https://<dashboard-domain>/api/webhooks/speakr`, select the recording lifecycle
events needed by the dashboard, and copy the generated HMAC secret into
`evidence-api.env` as `EVIDENCE_SPEAKR_WEBHOOK_SECRET`. Restart the API, then
use Speakr's webhook **Test** action and confirm a successful delivery.

After configuring working Speakr transcription and evidence extraction
providers, perform a synthetic end-to-end check:

```sh
ffmpeg -f lavfi -i 'sine=frequency=440:sample_rate=16000' -t 8 synthetic.wav
sudo journalctl -f \
  -u podman-speakr -u podman-evidence-api -u podman-evidence-worker
```

In a separate authenticated browser session, upload `synthetic.wav` through
the dashboard. Verify that the job advances through transcription and
extraction, the recording appears under the token-owning Speakr account, the
dashboard reaches its completed state, and authenticated playback plus the
evidence ledger work. Delete the synthetic recording through the normal
two-step dashboard flow afterward.

## Backup and restore

### Exclusive lock

Backup and restore both acquire the same non-blocking, exclusive host-level
lock (`dataDir/.ai-coaching-backup-restore.lock`, held with `flock -n`) as
their very first action, before either one inspects or changes any service
state. If the lock is already held, the contending command aborts immediately
with exit code 3 and a clear "another ai-coaching backup or restore operation
holds ... ; aborting" message. There is no blocking/waiting mode: contention
always fails fast and predictably rather than queueing.

### Backup

`ai-coaching-backup.timer` acquires the lock, records which writer services
are active, stops Speakr, the evidence API, and the evidence worker, verifies
every writer is inactive, and only then stages and archives:

- `dataDir/media` (authoritative original media shared by API and worker)
- `dataDir/speakr`
- `dataDir/evidence-worker`
- a custom-format PostgreSQL dump when PostgreSQL is locally managed (backup
  fails if the dump would be empty)

Before packing the archive, backup writes a `MANIFEST.sha256` covering every
staged file. After archiving, it writes a companion `<archive>.tar.gz.sha256`
checksum of the whole archive. Both are required inputs to restore's
validation phase below, and both are pruned together with their archive
during retention cleanup.

Run and inspect a backup:

```sh
sudo systemctl start ai-coaching-backup.service
sudo journalctl -u ai-coaching-backup.service --no-pager
tar -tzf /var/lib/ai-coaching/backups/<timestamp>.tar.gz
```

### Restore

Restore is manual:

```sh
sudo ai-coaching-restore /var/lib/ai-coaching/backups/<timestamp>.tar.gz
```

Restore acquires the exclusive lock first, then validates the archive
**before touching any live service state or data**: gzip integrity, the
archive-level sha256 checksum, tar member path safety, extraction to a
private staging directory, the `MANIFEST.sha256` contents of every staged
file, and (when PostgreSQL is enabled) that the archive contains the required
database dump and that the dump passes `pg_restore --list` structural
validation. Any validation failure aborts before writers are stopped and
before any data is modified.

Only after validation succeeds does restore prompt for confirmation. Before
stopping any writer or creating the marker, it durably records the original
existence/absence plus the live, moved-aside, staged, and recovery paths for
all three managed directories. It also validates that the PostgreSQL password
file works, the local peer-admin connection is available, and the configured
application role owns the target database. Restore then quiesces writers,
saves the exact active writer set, and takes a custom-format snapshot of the
current PostgreSQL database for operator rollback. It then creates
`dataDir/.ai-coaching-restore-in-progress`, fsyncs the marker and its parent
directory, and only then mutates live filesystem or PostgreSQL state. The
marker points to a persistent `dataDir/.restore-recovery-*` directory
containing the validated staged restore, the pre-restore PostgreSQL snapshot,
the saved writer set, and the filesystem and database rollback ledgers.

Speakr, the evidence API, and the evidence worker all have a systemd
`ConditionPathExists=!dataDir/.ai-coaching-restore-in-progress` startup
condition. Therefore a killed restore, host crash, or reboot cannot start a
writer while recovery is incomplete. Backup also refuses to run while the
marker exists. Do not delete the marker or start writers by bypassing the
condition.

Filesystem recovery always uses those recorded paths and original states; it
never re-infers them after a reboot. If `systemd-tmpfiles` recreates an
originally absent directory while the marker blocks writers, resume moves that
post-marker path into recovery storage before proceeding, and rollback removes
it so the original absence is restored. Existing directories move to
`*.pre-restore-<restore-id>` before staged content moves into place. If the
second move fails, the original is immediately moved back.

PostgreSQL restore is a replacement rather than a `pg_restore --clean` merge.
While writers remain quiesced, restore creates an empty temporary database
from `template0`, restores the dump there with a single transaction, and then
copies the target database owner, ACLs, connection limit, and database/role
settings before atomically renaming the old and replacement databases.
Metadata identifiers and values are quoted by PostgreSQL/psql rather than
assembled by the shell. Every metadata query and generated SQL command runs
with `ON_ERROR_STOP`; any extraction or application error leaves the durable
marker in place and writers fail-stopped. The displaced database is dropped
only after the name swap commits. Explicit rollback uses the same
empty-database replacement path for the pre-restore snapshot, so objects that
exist only in the failed target restore cannot survive rollback. Object
ownership and grants are restored from the custom-format dump.

`nix flake check path:.` includes a real PostgreSQL restore/rollback check in
addition to fault-injection fakes. It verifies old-only/new-only object
replacement, owner and database ACL preservation, quoted database/role
settings, fail-stop behavior on real SQL errors, and rollback recovery.

If any post-marker stage fails, writers remain stopped and the marker remains
durable even if the command was killed without running shell traps. Choose one
explicit recovery action:

```sh
# Continue the validated staged restore. Safe after a reboot or repeated
# interruption; directory swaps and PostgreSQL restore are resumed/reapplied.
sudo ai-coaching-restore --resume

# Restore original directory existence/content and the pre-restore PostgreSQL
# snapshot, then clear the marker.
sudo ai-coaching-restore --rollback
```

Both commands reacquire the exclusive lock, verify every writer is inactive,
and use the recovery directory named by the marker. They clear and fsync the
marker only after the selected filesystem and PostgreSQL operation succeeds.
Only then do they restart exactly the writer set saved before the original
restore and verify it is active. If recovery fails, the marker stays in place
and writers remain fail-stopped; fix the reported storage or PostgreSQL error
and rerun the same recovery command.

A normal successful restore follows the same completion rule: restored
filesystem contents are flushed, PostgreSQL has committed, the marker is
removed and its parent fsynced, and only then are the previously active
writers restarted.

Replicate `dataDir/backups` off-host with separate backup infrastructure.

## Retention

Originals are never automatically deleted. The deletion command accepts only
a relative path under `dataDir/media`. Its packaged helper opens the data,
media, parent, quarantine, and audit locations with descriptor-relative
no-follow operations. Rename and recursive purge remain relative to those
opened descriptors, so symlinks, parent traversal, and concurrent ancestor
replacement cannot redirect a root-run deletion to host paths.

```sh
sudo ai-coaching-delete-recording --yes <relative-path-under-dataDir/media>
sudo ai-coaching-purge-quarantine
```

Purge separately requires typing `purge`, includes hidden entries, and appends
both stages to `dataDir/deletion-audit.log`.

## Upgrade and rollback

Run `sudo systemctl start ai-coaching-backup.service` before upgrades. Update
the pinned flake input, run `nix flake check`, then use
`nixos-rebuild switch`. NixOS generations roll back configuration and image
references, but database schema changes require a compatible application/data
rollback.
