# 0001 - Architecture decision records

## Status

Accepted

## Context

The add-on plumbing (three add-on channels, dispatch workflows, version
normalization, the discovery pipeline) lives only in workflow yaml and
git history. Bugs like the dotted version ordering (wmbusmeters#2076)
and the edge-path regression in the test workflow (PR #92) are decisions
whose reasoning was recorded nowhere.

## Decision

Architecture decisions are recorded in this directory as
`NNNN-slug.md`, numbered thematically (0001 is this bootstrap, then
channels, versions, discovery, testing).

Each record uses the sections `## Status`, `## Context`,
`## Decision`, `## Consequences`, `## Evidence` and
`## Alternatives considered`. An accepted record is never edited in
place; a change is a new record with `Superseded by NNNN` noted in the
old one's `## Status`. Rejected ideas are recorded too.

`docs/architecture/` holds mermaid views; the records hold the why, the
views the how. They link, they do not duplicate.

## Consequences

New architectural changes to the add-on plumbing are expected to add a
record. Every `## Evidence` section names only commit hashes, files and
issue/PR numbers.

## Evidence

- This repo's history starts at `13f1451` (2023-02-16); workflow
  decisions since then are only recoverable from commit subjects.
- `README.md` documents installation and the channel names, not the
  reasoning behind them.

## Alternatives considered

- Chronological numbering: rejected, thematic groups are easier to
  navigate.
- A single `ARCHITECTURE.md`: rejected, one decision per file keeps
  supersession clean.