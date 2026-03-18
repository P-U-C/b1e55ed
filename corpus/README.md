# corpus/

The brain's compound learning store. Written by the learning loop as the system accumulates trade history.

## Structure

- `conviction.md` — high-conviction call history and outcomes
- `mistakes.md` — loss analysis and extracted lessons  
- `patterns.md` — technical and behavioral patterns with performance scores
- `sources.md` — alpha source quality ratings
- `theses.md` — active and resolved investment theses

## skills/

Pattern/skill lifecycle managed by `engine/brain/learning.py`:

- `skills-pending/` — patterns under evaluation (need score ≥ +3 to promote)
- `skills-active/` — validated patterns currently used by the brain
- `skills-archived/` — retired patterns (score ≤ -3)

The brain automatically promotes and archives skill files based on realized trade outcomes.
These directories start empty and fill over time as the system trades and learns.
