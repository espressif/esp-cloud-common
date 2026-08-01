# CLAUDE.md

Session guidance for Claude Code working in this repo.

## What this is

`esp-cloud-common` is a shared library repo for Espressif cloud infrastructure. Multiple products consume it. Changes here are potentially breaking for every downstream consumer — treat them accordingly.

## Rules

- Never introduce product-specific code. If a module's name, variables, or behavior hardcode something only one product cares about, it belongs in that product's repo, not here.
- Every module has its own README with a full usage example, inputs, and outputs.
- Breaking changes require a new tag. Never silently change behavior on `main`.
- Downstream consumers should pin to tags, not `main`. If you're tempted to use `main`, write a tag first.

## Read

Any consumer repo's design spec explains why a given module exists here.
