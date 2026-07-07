---
name: Version bump convention for textread
description: How to increment versions in textread between prompt sessions
type: feedback
---

Use patch version bumps between prompt sessions (0.1.0 → 0.1.1 → 0.1.2), not minor bumps per prompt (never 0.2.0, 0.3.0, etc. for incremental build steps).

**Why:** Prompts 001–007 each bumped the minor version, resulting in 0.7.0 at first publish — misleading for a brand-new project.

**How to apply:** Each prompt that changes code should increment the patch version only. Minor/major bumps are reserved for meaningful public milestones.
