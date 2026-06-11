"""分类颜色模块测试。"""

from __future__ import annotations

from engine.output.category_colors import FALLBACK_COLOR, color_for


def test_color_for_known_category():
    assert "red" in color_for("policy")


def test_color_for_override():
    custom = "bg-pink-50 text-pink-700"
    assert color_for("unknown", override=custom) == custom


def test_color_for_unknown_fallback():
    assert color_for("nonexistent_id_xyz") == FALLBACK_COLOR
