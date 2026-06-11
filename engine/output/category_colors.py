"""分类标签颜色：API 与 Dashboard 共用，避免前端硬编码。"""

from __future__ import annotations

DEFAULT_CATEGORY_COLORS: dict[str, str] = {
    "policy": "bg-red-50 text-red-700",
    "industry": "bg-blue-50 text-blue-700",
    "investment": "bg-green-50 text-green-700",
    "finance": "bg-purple-50 text-purple-700",
    "tech_transfer": "bg-cyan-50 text-cyan-700",
    "diplomacy": "bg-amber-50 text-amber-700",
    "elderly_tech": "bg-cyan-50 text-cyan-700",
    "health_services": "bg-green-50 text-green-700",
    "finance_security": "bg-purple-50 text-purple-700",
    "lifestyle": "bg-pink-50 text-pink-700",
    "risk": "bg-orange-50 text-orange-700",
    "case_study": "bg-stone-100 text-stone-600",
    "trade": "bg-blue-50 text-blue-700",
    "uncategorized": "bg-stone-100 text-stone-500",
}

FALLBACK_COLOR = "bg-stone-100 text-stone-500"


def color_for(category_id: str, override: str | None = None) -> str:
    if override:
        return override
    return DEFAULT_CATEGORY_COLORS.get(category_id, FALLBACK_COLOR)
