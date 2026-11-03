# 0003 - Dotted version scheme 3.0.0.N for continuous builds

## Status

Accepted

## Context

Home Assistant's update entity orders versions with awesomeversion.
For legacy continuous versions like `3.0.0-87` it silently returns
False when comparing numeric-only prerelease identifiers (it does not
throw), so the entity showed "Up to date" while a newer build was
installed (wmbusmeters#2076). The supervisor's own `version != latest`
check showed the update, which made the bug confusing to diagnose.

## Decision

Continuous edge builds use a dotted scheme: the dispatched tag
`3.0.0-N` is normalized to `3.0.0.N` in the build workflows, and the
on-push workflow increments the dotted build number. Exact tags that
are not purely numeric prereleases (e.g. `3.0.0-RC1`) pass through
unchanged. The dispatching workflow in the wmbusmeters repository that
produces `3.0.0-N` is left untouched.

## Consequences

- The first dotted version orders above every legacy form, so existing
  installations migrate cleanly without a forced downgrade.
- Both orderings now agree: supervisor string compare and HA core
  awesomeversion compare report the same update state.

## Evidence

- `1ae268f` (2026-09-22) introduces the normalization, merged as
  PR #91 (`55f9b48`).
- awesomeversion comparison matrix for `3.0.0-87` vs `3.0.0-54`
  (False), `3.0.0.87` ordering, and the rejected alternatives is
  recorded in the PR #91 discussion.
- `.github/workflows/build_ha_addon_edge.yml` normalization step and
  `.github/workflows/build_ha_addon_on_pr.yml` increment step; tested
  by `tests/test_workflows.py` (PR #92).

## Alternatives considered

- Suffixes like `3.0.0-rcN` or `3.0.0-bN`: rejected, they do not order
  against the already-installed legacy `3.0.0-N` versions and would
  pin migrating users to a broken scheme.
- Build metadata `3.0.0+rN`: rejected, awesomeversion ignores build
  metadata when ordering.