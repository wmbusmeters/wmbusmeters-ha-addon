# 0002 - Three add-on channels, the test channel has its own store repository

## Status

Accepted

## Context

Users want a stable track and a newest-changes track; after the dotted
version change a third channel was wanted to validate the plumbing
before the edge audience sees it. Home Assistant installs add-ons from
a store repository, and the supervisor clones that repository
anonymously.

## Decision

All channels are sibling directories in this repository:
`wmbusmeters-ha-addon` (stable), `wmbusmeters-ha-addon-edge` (tracks
the wmbusmeters master branch, present since the repo's first lint
workflow pinned it) and `wmbusmeters-ha-addon-test` (added 2026-09-21,
initially identical to edge).

The test channel is published through its own store repository
`wmbusmeters/wmbusmeters-ha-addon-test`: the build workflow's
`update-repo` job checks that repository out, rsyncs the add-on files
into it and pushes them. Edge and stable are published by auto-pushes
into this repository itself. Only the edge directory is linted.

## Consequences

- New channel workflows are created by copying the edge workflow; the
  edge-path copy regression in the test workflow (PR #92) shows that
  this copy step needs test coverage, not care.
- The test store repository must stay public, otherwise the
  supervisor's anonymous clone fails (wmbusmeters#2092).
- Auto-push commits end with `[no ci]`, so CI intentionally skips them.

## Evidence

- `56cbce4` (2023-03-01) points the linter at the edge add-on only.
- `7de2950` (2026-09-21) adds the test channel as a sibling directory.
- `.github/workflows/build_ha_addon_test.yml` contains the
  `update-repo` job against the store repository.
- PR #92 fixes the edge-path regression and adds the workflow tests.

## Alternatives considered

- One repository per channel: rejected, `7de2950` deliberately added
  the test channel as a sibling directory.