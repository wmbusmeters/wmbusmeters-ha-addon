# 0005 - The channel plumbing is tested by executing the real workflow run blocks

## Status

Proposed (PR #92)

## Context

Channel plumbing bugs (wrong sed paths in a copied workflow) only
surface in production auto-pushes, and auto-push commits end with
`[no ci]` so they never run CI anyway. The edge-path regression in the
test workflow sat in the repository unnoticed until it was diagnosed by
hand in wmbusmeters#2092.

## Decision

`tests/test_workflows.py` extracts the real version/sed/rsync run
blocks from the build workflows, substitutes the dispatch payload
expression with an environment variable, and executes them against
sandboxed copies of the three add-on directories. It validates the
version normalization and increments, the store rsync (including
removal of the unpacked artifact directory before committing), the
config/CHANGELOG consistency and the workflow wiring. A `Tests`
workflow runs the harness on every push to and pull request against
`main`.

## Consequences

- A wrong sed path or version step now fails in CI instead of in an
  auto-push.
- The harness parses the workflow yaml with PyYAML, so workflow changes
  can require harness updates (the unquoted `on:` key arrives as
  boolean True and is handled explicitly).

## Evidence

- PR #92: `tests/test_workflows.py`, `.github/workflows/tests.yml`,
  and the `rm -rf artifact` fix in the store `update-repo` job.
- Negative probe: reintroducing the edge-path regression makes the
  harness fail with five checks.

## Alternatives considered

- actionlint or yaml-lint only: rejected, they catch syntax, not wrong
  file paths inside run blocks.
- Shell-based tests mirroring the workflows: rejected, duplicating the
  logic invites the same copy drift the harness exists to catch.