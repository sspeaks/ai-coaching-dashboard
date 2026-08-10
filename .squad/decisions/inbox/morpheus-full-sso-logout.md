### 2026-08-10: Dashboard sign-out performs full Authentik SSO logout
**By:** Morpheus
**What:** The dashboard's Sign out control should clear the oauth2-proxy application cookie and trigger the upstream OIDC end-session endpoint, then land on an unauthenticated `/signed-out` page.
**Why:** This is a private coaching archive likely used from shared household or rehearsal devices. App-only logout leaves the Authentik browser session live, so the next protected route silently recreates the dashboard session and violates the user's expectation that sign-out protects the archive.
