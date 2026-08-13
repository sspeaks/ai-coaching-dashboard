---
name: "viewport-usability-guard"
description: "Interactive controls must be geometry-tested at phone viewports, not just asserted present in the DOM"
domain: "quality"
confidence: "high"
source: "issue #54 / PR #57 mobile audio control collapse"
---

## Context

A control can be present in the DOM and wired to correct data but unusable on phone because layout collapses or clips it. DOM-presence tests and still screenshots can miss this class.

## Patterns

- Run geometry checks at phone widths, including 390x844 and 360x800.
- Assert rendered width/height, computed visibility, viewport reachability after scrolling, and hit-testability.
- Prefer deterministic geometry assertions over pixel diffs for CI guards.
- Prove the guard fails by temporarily reintroducing the defect, then revert and prove it passes.
- Skip only intentionally collapsed semantics: `[hidden]`, `[aria-hidden="true"]`, `[inert]`, or non-summary content inside closed `<details>`.

## Anti-Patterns

- Treating `toBeInTheDocument()` as evidence that a control is usable.
- Writing a focused assertion for one incident without a broader control-surface sweep.
- Hiding should-be-visible controls with CSS and relying on collapsed-content exceptions.
- Shipping a guard without a fail-then-pass transcript.
