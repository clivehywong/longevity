# Documentation Sources and Archive Policy

This repository accumulated operational knowledge in several places. This page defines how to treat those sources during future cleanup.

## Preferred order of truth

1. Current executable scripts in `script/`
2. Current app code in `neuconn_app/`
3. Maintained docs under `docs/user/` and `docs/developer/`
4. Historical notes in `docs/archive/` and legacy markdown files

## What belongs in maintained docs

- repeatable workflows
- stable path and state conventions
- architecture and folder-structure explanations
- parameter guidance that still matches code
- troubleshooting patterns that generalize beyond a single subject or run

## What belongs in archive

- one-off run logs
- dated status reports
- incident notes tied to a specific subject
- duplicate "final/fix/complete" writeups for the same topic
- implementation summaries that are no longer current

## How to use legacy script markdown

`script/*.md` files can still be mined for:

- rationale behind defaults
- old troubleshooting patterns worth generalizing
- atlas or workflow assumptions that are not obvious from code

Do not make them the primary navigation path for users unless they have been rewritten into the maintained hierarchy.
