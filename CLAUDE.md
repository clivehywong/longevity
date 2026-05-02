<!-- CLAUDE.md -->
@AGENTS.md

<!-- Claude-specific instructions below -->

## Claude Code Usage

### Use Subagents to Reduce Context Window

**Always use subagents** for tasks requiring multiple file reads or searches:

- **Explore agent**: Codebase exploration, pattern finding, file searches
- **Plan agent**: Design implementation approaches before coding

**Launch agents in parallel** when tasks are independent (single message, multiple Agent calls).

### When to Use Subagents

- Searching for files/patterns (>3 queries)
- Understanding multi-file features
- Designing implementations
- Any task that would read >5 files

### Memory

- `.claude/memory/` — HPC config, analysis parameters
- `.claude/plans/` — Implementation blueprints

