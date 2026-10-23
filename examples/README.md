# Synthetic examples

Generate the opt-in demonstration with `python scripts/generate_examples.py`. It creates a new missing-file-only `demo-work/` workspace; generated working files are ignored by Git.

The included rename_rules.json and duplicate_rules.json can be loaded from the GUI. On a fresh sample: rename previews five moves, duplicate detection reports one group containing notes_draft.txt and notes_copy.txt, and a backup plan copies five files into a fresh snapshot. expected_preview.json records the deterministic root-file renaming examples. No customer data is included.

## Public snapshot

Version 0.1.1. This repository contains the runnable source, synthetic examples, tests, build scripts and neutral-path real screenshots. Internal acceptance records and previous private history are excluded. [Releases](https://github.com/BigCity-SmallLove/folderpilot-showcase/releases) lists only packages that have completed publication checks.
