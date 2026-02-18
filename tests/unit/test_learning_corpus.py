from __future__ import annotations

from pathlib import Path

from engine.brain.learning import LearningLoop
from engine.core.database import Database


def test_skill_promotion_and_archival(test_config, temp_dir, monkeypatch):
    monkeypatch.chdir(temp_dir)

    # Create corpus skill files.
    pending = Path("corpus/skills/skills-pending")
    active = Path("corpus/skills/skills-active")
    pending.mkdir(parents=True, exist_ok=True)
    active.mkdir(parents=True, exist_ok=True)

    (pending / "skill_a.md").write_text("---\nscore: 3\n---\n", encoding="utf-8")
    (active / "skill_b.md").write_text("---\nscore: -3\n---\n", encoding="utf-8")

    db = Database(temp_dir / "brain.db")
    loop = LearningLoop(db=db, config=test_config)

    fb = loop.update_corpus()

    assert "skill_a" in fb.skills_promoted
    assert "skill_b" in fb.skills_archived

    assert (Path("corpus/skills/skills-active") / "skill_a.md").exists()
    assert (Path("corpus/skills/skills-archived") / "skill_b.md").exists()
