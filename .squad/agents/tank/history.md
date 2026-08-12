# Project Context

- **Owner:** Seth Speaks
- **Project:** NixOS-deployable AI coaching dashboard
- **Stack:** Nix flake and NixOS module wrapping the selected web and processing stack
- **Created:** 2026-08-06T18:29:43.244-07:00
- **Research:** `my-barbershop-quartet-records-coaching-sessions-as.md`

## Learnings

- The deliverable must be exposed as a NixOS module, including service configuration, storage, and optional AI-provider settings.
- 2026-08-07T10:32:42.057-07:00: The vid-stream deployment sits behind an untouchable upstream TLS Caddy, so ai-coaching needs a plain-HTTP external-TLS module mode that disables local ACME but preserves secure oauth2-proxy redirect/cookie behavior via loopback-forwarded HTTPS headers.
- 2026-08-07T10:32:42.057-07:00: For ai-coaching packages, following nixos-config's unstable nixpkgs is risky; a local build with `follows = "nixpkgs"` failed in the SciPy dependency build, while keeping the app flake's own nixos-26.05 pin allowed the vid-stream system build to complete.
- 2026-08-07T10:32:42.057-07:00: Seth approved the vid-stream port swap: ai-coaching owns 8080 behind the upstream Caddy, while vid-streamer moves to direct IP port 8081 with firewall access.
- 2026-08-07T10:32:42.057-07:00: Seth chose manual Authentik UI setup with application/provider slug `ai-coaching` and OpenAI-compatible hosted Speakr transcription/text settings.
- 2026-08-07T10:32:42.057-07:00: With ai-coaching `emailDomains = [ "*" ]`, oauth2-proxy allows any authenticated email; Authentik Application binding to `quartet-members` is therefore required as the deployment access gate.
- 2026-08-07T10:32:42.057-07:00: Seth reversed no-role-mapping: map Authentik `quartet-members` to ai-coaching `adminGroups`; keep `editorGroups` empty because ADMIN satisfies editor endpoints.
- 2026-08-10T14:10:31-07:00: Investigated issue #2 GitHub Actions failures. The repeated Quality gates failure was isolated to the nixos-quality job's Nix flake output assertion under the CI Nix installer; refreshed workflow actions, switched CI Nix setup to cachix/install-nix-action with flakes enabled, synced active Squad workflow templates, and made backend CI install non-editable so Python 3.12 validation is reproducible.
📌 Team update (2026-08-10T14:08:35-07:00): GitHub Actions Nix quality now expects flake-capable setup via cachix/install-nix-action@v31; PR #6 merged the CI fix — decided by Tank

## 2026-08-12T14:34:00-07:00 — Reproducible UX screenshot capture harness
Built `apps/web/ux-capture/capture.mjs` and wired `cd apps/web && npm run ux:capture`. The harness starts Vite with `VITE_API_MODE=mock`, freezes render time/randomness, disables motion, captures full-page PNGs at 390x844, 360x800, and 1440x900, and writes a Mouse-readable `manifest.json` under `.squad/files/ux-review/{YYYY-MM-DD}/`.

Added Playwright as a web dev dependency and updated the flake dev shell with `nodejs_24`, `playwright-driver.browsers`, `PLAYWRIGHT_BROWSERS_PATH`, and `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`. The script launches the Chromium executable from the Nix browser store path to avoid Playwright revision mismatches with npm's package. Validation passed: `npm run ux:capture`, `npm run typecheck`, `npm test`, `npm run build`, and `nix eval .#devShells.x86_64-linux.default.drvPath --raw`.

Caveat: outside `nix develop`, callers must provide a usable `PLAYWRIGHT_BROWSERS_PATH` or `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`; otherwise Playwright may not find a browser. Current captured run left in `.squad/files/ux-review/2026-08-12/` for Mouse.

## 2026-08-12T14:38:00-07:00 — Aligned capture states with Trinity mock map
Fixed the web `package.json` tooling dependency to a single exact `playwright` version, `1.61.1`, matching `nixpkgs#playwright-driver.version` and the Nix-provided browser bundle. Updated `apps/web/ux-capture/capture.mjs` to capture Trinity's seven held mock states with user-readable filenames and manifest descriptions: empty first-run, upload idle, upload in progress, processing/transcribing, failed/error, awaiting review, and reviewed/complete.

Re-ran `cd apps/web && npm run ux:capture` with `PLAYWRIGHT_BROWSERS_PATH=$(nix build nixpkgs#playwright-driver.browsers --no-link --print-out-paths)`; it produced 21 non-empty PNGs under `.squad/files/ux-review/2026-08-12/` (7 states × 3 Mouse viewports). Re-ran `npm run typecheck && npm test && npm run build`; all passed.

📌 Team update (2026-08-12T14:25:08.524-07:00): UX screenshot capture now uses npm Playwright 1.61.1 with Nix-provided browser binaries and npm run ux:capture as the entry point — decided by Tank
