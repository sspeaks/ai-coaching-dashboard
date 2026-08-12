# Squad Team

> ai-coaching-dashboard

## Coordinator

| Name | Role | Notes |
|------|------|-------|
| Squad | Coordinator | Routes work, enforces handoffs and reviewer gates. |

## Members

| Name | Role | Charter | Status |
|------|------|---------|--------|
| Morpheus | Lead Architect & Product Owner | `.squad/agents/morpheus/charter.md` | Active |
| Neo | Audio/AI Backend Engineer | `.squad/agents/neo/charter.md` | Active |
| Trinity | Frontend Engineer | `.squad/agents/trinity/charter.md` | Active |
| Tank | NixOS/Platform Engineer | `.squad/agents/tank/charter.md` | Active |
| Switch | Quality & Evaluation Engineer | `.squad/agents/switch/charter.md` | Active |
| Mouse | UX Review Engineer | `.squad/agents/mouse/charter.md` | Active |
| Link | Frontend Engineer (UX Remediation) | `.squad/agents/link/charter.md` | Active |
| Scribe | Session Logger | `.squad/agents/scribe/charter.md` | Active |
| Ralph | Work Monitor | `.squad/agents/ralph/charter.md` | Active |
| Rai | RAI Reviewer | `.squad/agents/Rai/charter.md` | Active |
| Fact Checker | Fact Checker | `.squad/agents/fact-checker/charter.md` | Active |

## Project Context

- **Project:** ai-coaching-dashboard
- **Created:** 2026-08-07
- **Owner:** Seth Speaks
- **Goal:** Turn long barbershop coaching recordings into source-grounded coach notes with critical timestamps through a web upload workflow.
- **Delivery:** Prefer a local-first web application with a processing backend and optional AI APIs, packaged as a NixOS module. If an existing product fully satisfies the workflow, deliver a verified usage guide instead.
- **Research:** `my-barbershop-quartet-records-coaching-sessions-as.md`
- **Key constraints:** Preserve source evidence, avoid claims about sung or overlapping audio, support consent and privacy, and keep deployment reproducible.
