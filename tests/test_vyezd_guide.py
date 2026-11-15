from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "VYEZD.md"


def test_guide_covers_every_step_of_part_a():
    text = GUIDE.read_text(encoding="utf-8")
    for step in ("12.7", "12.8", "12.9", "12.10", "12.11", "12.12", "12.13", "12.16", "12.6"):
        assert step in text, step
    assert text.count("- [ ]") > 40

