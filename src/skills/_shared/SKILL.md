---
name: _shared
description: Shared references for all Demiurgos narrative skills. Not invokable directly.
---

# Demiurgos Shared References

This directory contains shared conventions and contracts that all narrative skills reference.

## Contents

- `persistence-contract.md` — Artifact storage conventions (Engram, openspec, hybrid)
- `narrative-phase-common.md` — Common fields across all narrative phases
- `narrative-conventions.md` — Narrative conventions for the Vibrantes universe
- `skill-resolver.md` — How the orchestrator resolves and injects skills

## Usage

Skills reference these files for consistent behavior. The orchestrator resolves and caches compact rules from the skill registry and injects them into sub-agent prompts.
