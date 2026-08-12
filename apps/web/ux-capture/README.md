# UX screenshot capture

Runs the Vite web app in `VITE_API_MODE=mock` and captures full-page screenshots for Mouse's screenshot-only UX review.

## Run

```sh
nix develop
cd apps/web
npm install
npm run ux:capture
```

Output is written to `.squad/files/ux-review/{YYYY-MM-DD}/{viewport}/{state-name}.png` with a `manifest.json` next to the viewport folders. The command exits non-zero if the app cannot start, a state cannot render, or a PNG is empty.

The PNG screenshots are gitignored because they are large, regenerable binaries that churn on every UI change. Regenerate them locally with `npm run ux:capture` before a UX review; a fresh clone may only contain the tracked text artifacts (`manifest.json` and Mouse's `REVIEW.md`).

## Reproducibility

The dev shell declares Nix's `playwright-driver.browsers` and exports `PLAYWRIGHT_BROWSERS_PATH` plus `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`, so Playwright uses Nix-provided browser binaries instead of downloading global mutable browsers. It also provides a fontconfig file with Noto, Liberation, DejaVu, CJK, and emoji fonts; missing fonts can make screenshots look blank or tofu-filled even when the browser launches. The script freezes browser `Date`, stubs `Math.random`, requests reduced motion, waits for fonts, and disables CSS animations/transitions before capture.

## Browser launch failures

Run captures from `nix develop` so the npm `playwright` driver (`1.61.1`) matches the Nix `playwright-driver.browsers` bundle (`1.61.1`). If Chromium fails to launch, check:

- `echo "$PLAYWRIGHT_BROWSERS_PATH"` points at an existing Nix store path.
- `echo "$PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"` prints `1`.
- `nix eval --raw nixpkgs#playwright-driver.version` matches `apps/web/package.json`.

Do not fix NixOS launch errors with `npx playwright install`; those downloaded binaries are not reproducible and may be linked for non-NixOS systems.

## Add a new state

Edit `apps/web/ux-capture/capture.mjs` and add an entry to the sorted `states` array with:

- `file`: a plain-language, numbered PNG name.
- `description`: one sentence saying how Mouse could reach the state.
- `run(page)`: Playwright actions that navigate from a fresh mock-mode page to the state and wait for visible text before the screenshot.
