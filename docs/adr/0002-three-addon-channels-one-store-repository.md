# 0002 - Three add-on channels, one store repository

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

There is one store repository, and it is this one. Users add this
repository as their add-on store and install stable, edge or test from
it. Every channel is published here by auto-pushes: the build
workflow's `update-repo` job checks this repository out, unpacks the
built add-on files and commits the channel's config.json and
CHANGELOG.md. Edge has done this since the beginning; the test channel
is published here like edge (PR #94). Only the edge directory is
linted.

## Consequences

- New channel workflows are created by copying the edge workflow; the
  edge-path copy regression in the test workflow (PR #92) shows that
  this copy step needs test coverage, not care.
- A wrong publish target fails the build with `Not Found`
  (run 35847836048, wmbusmeters#2092); the workflow tests pin the test
  `update-repo` job to this repository (PR #94).
- Auto-push commits end with `[no ci]`, so CI intentionally skips them.

## Evidence

- `56cbce4` (2023-03-01) points the linter at the edge add-on only.
- `7de2950` (2026-09-21) adds the test channel as a sibling directory;
  its original build workflow commits the test channel to this
  repository, like the edge workflow.
- wmbusmeters#2092 announced the URL
  `https://github.com/wmbusmeters/wmbusmeters-ha-addon-test`, but no
  such repository exists; PR #92's checkout of it fails with
  `Not Found` (run 35847836048).
- PR #94 restores the test `update-repo` job to commit to this
  repository; `tests/test_workflows.py` pins it.

## Alternatives considered

- One repository per channel: rejected, `7de2950` deliberately added
  the test channel as a sibling directory.
- A separate store repository for the test channel
  (`wmbusmeters/wmbusmeters-ha-addon-test`, announced in
  wmbusmeters#2092): not viable, the repository does not exist and the
  checkout of it broke the build; removed in PR #94.