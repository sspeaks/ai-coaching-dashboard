# Decision: Caddy route block must enforce forward_auth before try_files

**By:** Morpheus
**Date:** 2026-08-11
**Issue:** #28

## Decision

The Caddy `staticRoot` frontend handler must wrap its directives in a `route {}` block to enforce written order: `forward_auth` before `try_files`.

## Root cause (confirmed via host logs)

Caddy's standard directive ordering executes `try_files` (a rewrite) before `forward_auth`. When an unauthenticated user requests `/`, Caddy rewrites it to `/index.html` before forward_auth captures `{uri}` for the `rd` parameter. oauth2-proxy then redirects users to `/index.html` after login instead of their original path `/`.

Evidence: host logs show every login produces `GET "/oauth2/start?rd=https://streams.sspeaks.net/index.html"` regardless of client device.

## Fix

- `nix/proxy.nix`: Wrap frontend handler in `route {}` to preserve written order.
- `apps/web/src/App.tsx`: Add `/index.html` as a known alias for feedback (defense-in-depth).
- Catch-all for genuinely unknown paths (issue #17) is preserved.

## Standing rule

Any Caddy handler that combines `try_files` with `forward_auth` must use a `route {}` block to prevent path rewriting from corrupting the authentication redirect target.
