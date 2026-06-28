# Local group chat setup

This fork includes local fixes for Odysseus group chat behavior.

## Intended Ida/Kody workflow

- Group mode: Sequential
- Participant order: Ida first, Kody second
- Ida handles strategy, planning, routing, and defaults Kody to SKIP
- Kody only acts when Ida routes REVIEW, IMPLEMENT, or WAIT
- Kody outputs exactly `<KODY_SILENT_SKIP>` when skipped

## Local behavior fixes

- Group parent chat remains stable when clicking away
- Internal participant sessions are hidden from the sidebar
- Sequential mode preserves participant order
- Duplicate/overlapping group sends are blocked
- Fake tool-call output is discouraged
- Internal group participant sessions are archived on creation by the backend

## Important

Do not use Parallel mode for Ida/Kody routing. Parallel mode lets both participants respond independently, which defeats Ida's routing role.
