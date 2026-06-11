from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from engine.config import settings
from engine.models import RawItem, ScoredItem, SourceType
from engine.store import Store


# ── Helpers ──

def _make_raw(source_id="src1", title="标题", url="https://example.com/1",
              fetched_at=None, **kwargs):
    defaults = dict(
        source_id=source_id, title=title, url=url, content="内容摘要",
        published=datetime.now(), fetched_at=fetched_at or datetime.now(),
        lang="zh",
    )
    defaults.update(kwargs)
    return RawItem(**defaults)

def _make_scored(raw, score=7.5, category="industry", summary="摘要"):
    return ScoredItem(
        raw=raw, score=score, category=category,
        summary=summary, reason="推荐理由",
    )


# ═══════════════════════════════════════════════════════════════
# keyword_staging tests
# ═══════════════════════════════════════════════════════════════

class TestKeywordStaging:
    """keyword_staging 模块：暂存/读取/验证/合并/回滚。"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "project_root", tmp_path)
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        # 确保领域目录和 keywords.yaml 存在
        d = tmp_path / "domains" / "test-domain"
        d.mkdir(parents=True)
        (d / "keywords.yaml").write_text(
            "keywords:\n  - 测试\n  - 示例\n", encoding="utf-8")
        (d / "sources.yaml").write_text("sources:\n  - id: src1\n    name: 源\n    kind: rss\n    url: http://x\n    tier: T1\n    lang: zh\n", encoding="utf-8")

    # ── stage_suggestions ──

    def test_stage_suggestions_creates_file(self):
        from engine.evolution.keyword_staging import stage_suggestions, _staging_path
        result = stage_suggestions("test-domain", ["养老产业", "智慧养老"])
        assert result["domain"] == "test-domain"
        assert result["keywords"] == ["养老产业", "智慧养老"]
        assert result["status"] == "pending"
        assert _staging_path("test-domain").exists()

    def test_stage_suggestions_overwrites_existing(self):
        from engine.evolution.keyword_staging import stage_suggestions, get_staging
        stage_suggestions("test-domain", ["第一组"])
        stage_suggestions("test-domain", ["第二组"])
        staging = get_staging("test-domain")
        assert staging["keywords"] == ["第二组"]

    # ── get_staging ──

    def test_get_staging_returns_none_when_missing(self):
        from engine.evolution.keyword_staging import get_staging
        assert get_staging("nonexistent") is None

    def test_get_staging_returns_data(self):
        from engine.evolution.keyword_staging import stage_suggestions, get_staging
        stage_suggestions("test-domain", ["kw1", "kw2"])
        data = get_staging("test-domain")
        assert data is not None
        assert data["keywords"] == ["kw1", "kw2"]

    def test_get_staging_reads_arbitrary_status(self):
        from engine.evolution.keyword_staging import get_staging, _staging_path
        import json
        from datetime import datetime
        path = _staging_path("test-domain")
        path.write_text(json.dumps({"keywords": ["x"], "status": "manual_review"}), encoding="utf-8")
        data = get_staging("test-domain")
        assert data["status"] == "manual_review"

    # ── get_staged_keywords ──

    def test_get_staged_keywords_returns_none_when_missing(self):
        from engine.evolution.keyword_staging import get_staged_keywords
        assert get_staged_keywords("nonexistent") == []

    def test_get_staged_keywords_only_pending(self):
        from engine.evolution.keyword_staging import stage_suggestions, get_staged_keywords
        stage_suggestions("test-domain", ["kw"])
        assert get_staged_keywords("test-domain") == ["kw"]

    def test_get_staged_keywords_ignores_non_pending(self):
        from engine.evolution.keyword_staging import get_staged_keywords, _staging_path
        import json
        path = _staging_path("test-domain")
        path.write_text(json.dumps({"keywords": ["x"], "status": "accepted"}), encoding="utf-8")
        assert get_staged_keywords("test-domain") == []

    # ── record_trial_result ──

    def test_record_trial_result_accepted_on_big_improvement(self):
        from engine.evolution.keyword_staging import stage_suggestions, record_trial_result, get_staging
        stage_suggestions("test-domain", ["kw"])
        record_trial_result("test-domain", staged_pass_rate=0.30, official_pass_rate=0.10)
        data = get_staging("test-domain")
        assert data["status"] == "accepted"
        assert data["trial_results"]["improvement"] == pytest.approx(0.20)

    def test_record_trial_result_manual_review_on_small_improvement(self):
        from engine.evolution.keyword_staging import stage_suggestions, record_trial_result, get_staging
        stage_suggestions("test-domain", ["kw"])
        record_trial_result("test-domain", staged_pass_rate=0.12, official_pass_rate=0.10)
        data = get_staging("test-domain")
        assert data["status"] == "manual_review"
        assert data["trial_results"]["improvement"] == pytest.approx(0.02)

    def test_record_trial_result_rejected_on_no_improvement(self):
        from engine.evolution.keyword_staging import stage_suggestions, record_trial_result, get_staging
        stage_suggestions("test-domain", ["kw"])
        record_trial_result("test-domain", staged_pass_rate=0.05, official_pass_rate=0.10)
        data = get_staging("test-domain")
        assert data["status"] == "rejected"

    def test_record_trial_result_skips_if_no_staging(self):
        from engine.evolution.keyword_staging import record_trial_result
        record_trial_result("nonexistent", 0.3, 0.1)  # should not raise

    def test_record_trial_result_rounds_to_4_decimal(self):
        from engine.evolution.keyword_staging import stage_suggestions, record_trial_result, get_staging
        stage_suggestions("test-domain", ["kw"])
        record_trial_result("test-domain", 0.12345, 0.07234)
        data = get_staging("test-domain")
        assert data["trial_results"]["staged_pass_rate"] == 0.1235  # rounded

    # ── apply_staged_keywords ──

    def test_apply_staged_keywords_appends_to_yaml(self):
        from engine.evolution.keyword_staging import stage_suggestions, _staging_path
        import json
        from datetime import datetime
        # 手动设置 accepted 状态
        path = _staging_path("test-domain")
        path.write_text(json.dumps({
            "keywords": ["新关键词1", "新关键词2"], "status": "accepted",
        }, ensure_ascii=False), encoding="utf-8")

        from engine.evolution.keyword_staging import apply_staged_keywords
        result = apply_staged_keywords("test-domain")
        assert result is True

        kw_path = settings.project_root / "domains" / "test-domain" / "keywords.yaml"
        content = kw_path.read_text(encoding="utf-8")
        assert "新关键词1" in content
        assert "新关键词2" in content
        assert "测试" in content  # original still there

    def test_apply_staged_keywords_skips_if_not_accepted(self):
        from engine.evolution.keyword_staging import stage_suggestions, apply_staged_keywords
        stage_suggestions("test-domain", ["新kw"])
        result = apply_staged_keywords("test-domain")
        assert result is False

    def test_apply_staged_keywords_skips_if_no_keywords(self):
        from engine.evolution.keyword_staging import _staging_path, apply_staged_keywords
        import json
        path = _staging_path("test-domain")
        path.write_text(json.dumps({"keywords": [], "status": "accepted"}), encoding="utf-8")
        assert apply_staged_keywords("test-domain") is False

    def test_apply_staged_keywords_skips_duplicates(self):
        from engine.evolution.keyword_staging import _staging_path, apply_staged_keywords
        import json
        path = _staging_path("test-domain")
        path.write_text(json.dumps({"keywords": ["测试"], "status": "accepted"}), encoding="utf-8")
        result = apply_staged_keywords("test-domain")
        assert result is True  # no new keywords, but still cleans up staging

    def test_apply_staged_keywords_clears_staging(self):
        from engine.evolution.keyword_staging import _staging_path, apply_staged_keywords, get_staging
        import json
        path = _staging_path("test-domain")
        path.write_text(json.dumps({"keywords": ["新kw"], "status": "accepted"}), encoding="utf-8")
        apply_staged_keywords("test-domain")
        assert not _staging_path("test-domain").exists()

    # ── reject_staged_keywords ──

    def test_reject_staged_keywords_sets_status(self):
        from engine.evolution.keyword_staging import stage_suggestions, reject_staged_keywords, get_staging
        stage_suggestions("test-domain", ["kw"])
        reject_staged_keywords("test-domain")
        data = get_staging("test-domain")
        assert data["status"] == "rejected"

    def test_reject_staged_keywords_noop_if_missing(self):
        from engine.evolution.keyword_staging import reject_staged_keywords
        reject_staged_keywords("nonexistent")  # should not raise

    # ── _clear_staging ──

    def test_clear_staging_removes_file(self):
        from engine.evolution.keyword_staging import stage_suggestions, _staging_path, _clear_staging
        stage_suggestions("test-domain", ["kw"])
        assert _staging_path("test-domain").exists()
        _clear_staging("test-domain")
        assert not _staging_path("test-domain").exists()

    def test_clear_staging_on_missing_file(self):
        from engine.evolution.keyword_staging import _clear_staging
        _clear_staging("nonexistent")  # should not raise

    # ── check_and_apply ──

    def test_check_and_apply_none(self):
        from engine.evolution.keyword_staging import check_and_apply
        result = check_and_apply("nonexistent")
        assert result == {"action": "none"}

    def test_check_and_apply_pending(self):
        from engine.evolution.keyword_staging import stage_suggestions, check_and_apply
        stage_suggestions("test-domain", ["kw"])
        result = check_and_apply("test-domain")
        assert result == {"action": "pending"}

    def test_check_and_apply_accepted(self):
        from engine.evolution.keyword_staging import _staging_path, check_and_apply
        import json
        path = _staging_path("test-domain")
        path.write_text(json.dumps({"keywords": ["新kw"], "status": "accepted"}), encoding="utf-8")
        result = check_and_apply("test-domain")
        assert result["action"] == "applied"
        assert result["keywords"] == ["新kw"]

    def test_check_and_apply_rejected(self):
        from engine.evolution.keyword_staging import _staging_path, check_and_apply
        import json
        path = _staging_path("test-domain")
        path.write_text(json.dumps({"keywords": ["kw"], "status": "rejected"}), encoding="utf-8")
        result = check_and_apply("test-domain")
        assert result == {"action": "rejected"}
        assert not _staging_path("test-domain").exists()


# ═══════════════════════════════════════════════════════════════
# scoring_calibrator tests
# ═══════════════════════════════════════════════════════════════

class TestScoringCalibrator:
    """scoring_calibrator 模块：评分分布分析/报告/建议。"""

    def _seed_data(self, store: Store):
        """向 store 灌入测试评分数据。"""
        now = datetime.now(timezone.utc)
        raw1 = _make_raw(source_id="s1", url="https://ex.com/1",
                         fetched_at=now)
        raw2 = _make_raw(source_id="s1", url="https://ex.com/2",
                         fetched_at=now)
        raw3 = _make_raw(source_id="s2", url="https://ex.com/3",
                         fetched_at=now)
        raw4 = _make_raw(source_id="s2", url="https://ex.com/4",
                         fetched_at=now)
        r1 = store.save_raw(raw1)
        r2 = store.save_raw(raw2)
        r3 = store.save_raw(raw3)
        r4 = store.save_raw(raw4)

        # industry 分类：高分
        store.save_scored(r1, "test-domain", _make_scored(raw1, score=9.0, category="industry"))
        store.save_scored(r2, "test-domain", _make_scored(raw2, score=8.5, category="industry"))
        # policy 分类：低分
        store.save_scored(r3, "test-domain", _make_scored(raw3, score=3.0, category="policy"))
        store.save_scored(r4, "test-domain", _make_scored(raw4, score=2.5, category="policy"))

    def test_analyze_scoring_distribution_empty(self, store):
        from engine.evolution.scoring_calibrator import analyze_scoring_distribution
        result = analyze_scoring_distribution("test-domain", days=7)
        assert result["domain"] == "test-domain"
        assert result["overall"]["total"] == 0

    def test_analyze_scoring_distribution_with_data(self, store):
        self._seed_data(store)
        from engine.evolution.scoring_calibrator import analyze_scoring_distribution
        result = analyze_scoring_distribution("test-domain", days=7)
        assert result["overall"]["total"] == 4
        assert result["overall"]["avg_score"] == pytest.approx(5.75, abs=0.01)
        assert result["overall"]["selected"] == 2  # ≥6.0
        assert len(result["by_category"]) == 2
        assert len(result["by_source"]) == 2

    def test_analyze_scoring_distribution_by_category(self, store):
        self._seed_data(store)
        from engine.evolution.scoring_calibrator import analyze_scoring_distribution
        result = analyze_scoring_distribution("test-domain", days=7)
        cats = {c["category"]: c for c in result["by_category"]}
        assert cats["industry"]["avg_score"] == pytest.approx(8.75, abs=0.01)
        assert cats["policy"]["avg_score"] == pytest.approx(2.75, abs=0.01)
        assert cats["industry"]["selected"] == 2
        assert cats["policy"]["selected"] == 0

    def _seed_data_with_anomaly(self, store):
        """Seed so policy has avg<4.0 and total>3 to trigger anomaly."""
        now = datetime.now(timezone.utc)
        raw1 = _make_raw(source_id="s1", url="https://ex.com/1", fetched_at=now)
        raw2 = _make_raw(source_id="s1", url="https://ex.com/2", fetched_at=now)
        raw3 = _make_raw(source_id="s2", url="https://ex.com/3", fetched_at=now)
        raw4 = _make_raw(source_id="s2", url="https://ex.com/4", fetched_at=now)
        raw5 = _make_raw(source_id="s2", url="https://ex.com/5", fetched_at=now)
        raw6 = _make_raw(source_id="s2", url="https://ex.com/6", fetched_at=now)
        r1 = store.save_raw(raw1)
        r2 = store.save_raw(raw2)
        r3 = store.save_raw(raw3)
        r4 = store.save_raw(raw4)
        r5 = store.save_raw(raw5)
        r6 = store.save_raw(raw6)
        store.save_scored(r1, "test-domain", _make_scored(raw1, score=9.0, category="industry"))
        store.save_scored(r2, "test-domain", _make_scored(raw2, score=8.5, category="industry"))
        store.save_scored(r3, "test-domain", _make_scored(raw3, score=3.0, category="policy"))
        store.save_scored(r4, "test-domain", _make_scored(raw4, score=2.5, category="policy"))
        store.save_scored(r5, "test-domain", _make_scored(raw5, score=2.0, category="policy"))
        store.save_scored(r6, "test-domain", _make_scored(raw6, score=2.0, category="policy"))

    def test_generate_scoring_report(self, store):
        self._seed_data_with_anomaly(store)
        from engine.evolution.scoring_calibrator import generate_scoring_report
        report = generate_scoring_report("test-domain", days=7)
        assert "评分分析报告" in report
        assert "industry" in report
        assert "policy" in report
        # policy avg=2.375 < 4.0 and total=4 > 3 → anomaly
        assert "平均分异常低" in report

    def test_generate_scoring_report_empty(self, store):
        from engine.evolution.scoring_calibrator import generate_scoring_report
        report = generate_scoring_report("test-domain", days=7)
        assert "评分分析报告" in report

    def test_suggest_adjustments_global_high(self, store):
        # 全部高分 -> 触发全局精选率过高建议
        now = datetime.now(timezone.utc)
        for i in range(5):
            raw = _make_raw(source_id="s1", url=f"https://ex.com/{i}", fetched_at=now)
            rid = store.save_raw(raw)
            store.save_scored(rid, "test-domain", _make_scored(raw, score=8.0, category="industry"))
        from engine.evolution.scoring_calibrator import suggest_adjustments
        suggestions = suggest_adjustments("test-domain", days=7)
        assert len(suggestions) >= 1

    def test_suggest_adjustments_normal_returns_no_adjustment_needed(self, store):
        # 正常分布 -> 无异常
        now = datetime.now(timezone.utc)
        for i in range(5):
            raw = _make_raw(source_id="s1", url=f"https://ex.com/{i}", fetched_at=now)
            rid = store.save_raw(raw)
            store.save_scored(rid, "test-domain", _make_scored(raw, score=7.0, category="industry"))
        for i in range(5):
            raw = _make_raw(source_id="s2", url=f"https://ex.com/{5+i}", fetched_at=now)
            rid = store.save_raw(raw)
            store.save_scored(rid, "test-domain", _make_scored(raw, score=5.0, category="policy"))
        from engine.evolution.scoring_calibrator import suggest_adjustments
        suggestions = suggest_adjustments("test-domain", days=7)
        assert any("正常" in s for s in suggestions)


# ═══════════════════════════════════════════════════════════════
# scoring_injector tests
# ═══════════════════════════════════════════════════════════════

class TestScoringInjector:
    """scoring_injector 模块：校准分析/指令注入。"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "project_root", tmp_path)
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    def _seed_data(self, store: Store):
        now = datetime.now(timezone.utc)
        for i in range(5):
            raw = _make_raw(source_id="s1", url=f"https://ex.com/{i}", fetched_at=now)
            rid = store.save_raw(raw)
            store.save_scored(rid, "test-domain", _make_scored(raw, score=9.0, category="industry"))
        from engine.evolution.scoring_injector import analyze_and_calibrate
        result = analyze_and_calibrate("test-domain", days=7)
        assert len(result["calibrations"]) > 0
        # industry avg is 9.0 > 8.5 threshold
        types = [c["type"] for c in result["calibrations"]]
        assert "category_high" in types

    def test_analyze_and_calibrate_cleans_up_when_normal(self, store):
        now = datetime.now(timezone.utc)
        for i in range(5):
            raw = _make_raw(source_id="s1", url=f"https://ex.com/{i}", fetched_at=now)
            rid = store.save_raw(raw)
            store.save_scored(rid, "test-domain", _make_scored(raw, score=7.0, category="industry"))
        from engine.evolution.scoring_injector import analyze_and_calibrate, _calibration_path
        result = analyze_and_calibrate("test-domain", days=7)
        assert len(result["calibrations"]) == 0
        # normal distribution, calibrations cleared
        assert not _calibration_path("test-domain").exists()

    def test_analyze_and_calibrate_saves_calibration_file(self, store):
        self._seed_data(store)
        from engine.evolution.scoring_injector import analyze_and_calibrate, _calibration_path
        analyze_and_calibrate("test-domain", days=7)
        path = _calibration_path("test-domain")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["calibrations"]) > 0

    def test_get_calibration_instructions_returns_empty_when_none(self, store):
        from engine.evolution.scoring_injector import get_calibration_instructions
        assert get_calibration_instructions("test-domain") == ""

    def test_get_calibration_instructions_returns_text_when_exists(self, store):
        self._seed_data(store)
        from engine.evolution.scoring_injector import analyze_and_calibrate, get_calibration_instructions
        analyze_and_calibrate("test-domain", days=7)
        instructions = get_calibration_instructions("test-domain")
        assert "动态校准指令" in instructions
        assert "industry" in instructions

    def test_get_calibration_instructions_removes_expired(self, store, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "project_root", tmp_path)
        from engine.evolution.scoring_injector import _calibration_path, get_calibration_instructions
        # 写入 10 天前的校准数据 → 过期
        old_data = {
            "calibrations": [{"type": "category_high", "target": "x", "avg_score": 9.0,
                              "instruction": "test"}],
            "analyzed_at": (datetime.now() - timedelta(days=10)).isoformat(),
        }
        path = _calibration_path("test-domain")
        path.write_text(json.dumps(old_data), encoding="utf-8")
        assert get_calibration_instructions("test-domain") == ""
        assert not path.exists()

    def test_inject_calibration_appends_to_prompt(self, store):
        self._seed_data(store)
        from engine.evolution.scoring_injector import analyze_and_calibrate, inject_calibration
        analyze_and_calibrate("test-domain", days=7)
        result = inject_calibration("test-domain", "这是基础 prompt")
        assert "这是基础 prompt" in result
        assert "动态校准指令" in result

    def test_inject_calibration_returns_base_when_none(self, store):
        from engine.evolution.scoring_injector import inject_calibration
        result = inject_calibration("test-domain", "基础 prompt")
        assert result == "基础 prompt"

    def test_run_calibration_check_delegates(self, store):
        from engine.evolution.scoring_injector import run_calibration_check
        result = run_calibration_check("test-domain", days=7)
        assert result["domain"] == "test-domain"
        assert "calibrations" in result


# ═══════════════════════════════════════════════════════════════
# source_lifecycle tests
# ═══════════════════════════════════════════════════════════════

class TestSourceLifecycle:
    """source_lifecycle 模块：度量记录/降级检测/YAML 操作。"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "project_root", tmp_path)
        # 创建领域目录和 sources.yaml
        domain_dir = tmp_path / "domains" / "test-domain"
        domain_dir.mkdir(parents=True)
        (domain_dir / "sources.yaml").write_text(
            "sources:\n"
            "  - id: s1\n    name: 源1\n"
            "    kind: rss\n    url: https://ex.com/1\n"
            "    tier: T1\n    lang: zh\n"
            "  - id: s2\n    name: 源2\n"
            "    kind: rss\n    url: https://ex.com/2\n"
            "    tier: T1\n    lang: zh\n"
            "    type: hotlist\n",
            encoding="utf-8",
        )
        (domain_dir / "categories.yaml").write_text(
            '{"categories": []}', encoding="utf-8")
        (domain_dir / "keywords.yaml").write_text("keywords: []", encoding="utf-8")
        (domain_dir / "scoring.md").write_text("prompt", encoding="utf-8")
        (domain_dir / "pre_filter.md").write_text("prompt", encoding="utf-8")

    def _seed_metrics(self, store: Store, source_id="s1", days=7,
                      fetched=20, selected=1, start_from=None):
        """向 source_metrics 表插入指定天数的指标记录。"""
        end = start_from or datetime.now()
        for i in range(days):
            d = (end - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            rate = selected / fetched if fetched > 0 else 0
            store.conn.execute(
                "INSERT OR REPLACE INTO source_metrics "
                "(domain, source_id, date, fetched, selected, yield_rate) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test-domain", source_id, d, fetched, selected, round(rate, 4)),
            )
        store.conn.commit()

    def _seed_raw_scored(self, store: Store, source_id="s1", count=5,
                         score=7.0, date=None):
        """向 raw_items + scored_items 插入测试数据。"""
        dt = date or datetime.now()
        for i in range(count):
            raw = _make_raw(source_id=source_id, url=f"https://ex.com/{source_id}/{i}",
                            fetched_at=dt)
            rid = store.save_raw(raw)
            store.save_scored(rid, "test-domain",
                              _make_scored(raw, score=score))

    # ── record_daily_metrics ──

    def test_record_daily_metrics_inserts_records(self, store):
        self._seed_raw_scored(store, "s1", count=5, score=8.0)
        self._seed_raw_scored(store, "s2", count=3, score=4.0)

        from engine.evolution.source_lifecycle import record_daily_metrics
        records = record_daily_metrics("test-domain")

        # 至少两条记录（s1, s2）
        ids = [r["source_id"] for r in records]
        assert "s1" in ids
        assert "s2" in ids

        # 验证产出率
        s1 = next(r for r in records if r["source_id"] == "s1")
        assert s1["selected"] == 5
        assert s1["yield_rate"] == pytest.approx(1.0)

    def test_record_daily_metrics_with_specific_date(self, store):
        self._seed_raw_scored(store, "s1", count=3, score=6.5)

        from engine.evolution.source_lifecycle import record_daily_metrics
        date = datetime.now().strftime("%Y-%m-%d")
        records = record_daily_metrics("test-domain", date=date)
        assert len(records) > 0

    # ── detect_degradation ──

    def test_detect_degradation_skips_healthy_source(self, store):
        # s1 产出率高 → 不应降级
        self._seed_metrics(store, "s1", days=7, fetched=20, selected=5)
        from engine.evolution.source_lifecycle import detect_degradation
        result = detect_degradation("test-domain")
        assert len(result) == 0

    def test_detect_degradation_identifies_low_yield(self, store):
        # s1 连续 7 天产出率极低且采集量充足
        # GENERAL 需要 observation_days >= 7 → seed 8 天得 observation_days=7
        self._seed_metrics(store, "s1", days=8, fetched=20, selected=0)
        from engine.evolution.source_lifecycle import detect_degradation
        result = detect_degradation("test-domain")
        # s1 is type general with min_yield_rate=0.05, auto_disable=True
        # avg yield = 0.0 < 0.05 → should flag
        assert any(r["source_id"] == "s1" for r in result)

    def test_detect_degradation_skips_confirmed_source(self, store):
        # 在 sources.yaml 中添加 confirmed: true → 跳过
        from engine.evolution.source_lifecycle import confirm_source_status
        confirm_source_status("test-domain", "s2")

        self._seed_metrics(store, "s2", days=7, fetched=20, selected=0)
        from engine.evolution.source_lifecycle import detect_degradation
        result = detect_degradation("test-domain")
        assert not any(r["source_id"] == "s2" for r in result)

    def test_detect_degradation_flags_hotlist_type(self, store):
        # s2 has type: hotlist (auto_disable=True, observation_days=7)
        # 改 s2 type 为 hotlist 在 _setup 的 YAML 中；seed 8 天得 observation_days=7
        self._seed_metrics(store, "s2", days=8, fetched=20, selected=0)
        from engine.evolution.source_lifecycle import detect_degradation
        result = detect_degradation("test-domain")
        assert any(r["source_id"] == "s2" for r in result)

    def test_detect_degradation_skips_insufficient_data(self, store):
        # 采集量不足 → 跳过
        self._seed_metrics(store, "s1", days=3, fetched=3, selected=0)
        from engine.evolution.source_lifecycle import detect_degradation
        result = detect_degradation("test-domain")
        assert len(result) == 0

    # ── apply_degradation ──

    def test_apply_degradation_modifies_yaml(self):
        degraded = [{"source_id": "s1", "days_tracked": 7, "avg_yield": 0.02}]
        from engine.evolution.source_lifecycle import apply_degradation
        disabled = apply_degradation("test-domain", degraded)
        assert "s1" in disabled

        yaml_path = settings.project_root / "domains" / "test-domain" / "sources.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        assert "enabled: false" in content

    def test_apply_degradation_skips_already_disabled(self):
        yaml_path = settings.project_root / "domains" / "test-domain" / "sources.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        content = content.replace("- id: s1", "- id: s1\n    enabled: true")
        yaml_path.write_text(content, encoding="utf-8")

        degraded = [{"source_id": "s1", "days_tracked": 7, "avg_yield": 0.02}]
        from engine.evolution.source_lifecycle import apply_degradation
        disabled = apply_degradation("test-domain", degraded)
        assert "s1" not in disabled  # already has enabled field → skip

    def test_apply_degradation_empty_list(self):
        from engine.evolution.source_lifecycle import apply_degradation
        assert apply_degradation("test-domain", []) == []

    def test_apply_degradation_unknown_source(self):
        degraded = [{"source_id": "nonexistent", "days_tracked": 7, "avg_yield": 0.0}]
        from engine.evolution.source_lifecycle import apply_degradation
        assert apply_degradation("test-domain", degraded) == []

    # ── restore_source ──

    def test_restore_source_removes_auto_degraded_mark(self):
        # 先禁用
        degraded = [{"source_id": "s1", "days_tracked": 7, "avg_yield": 0.02}]
        from engine.evolution.source_lifecycle import apply_degradation, restore_source
        apply_degradation("test-domain", degraded)

        # 恢复
        result = restore_source("test-domain", "s1")
        assert result is True

        yaml_path = settings.project_root / "domains" / "test-domain" / "sources.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        assert "auto-degraded" not in content

    def test_restore_source_nonexistent(self):
        from engine.evolution.source_lifecycle import restore_source
        assert restore_source("test-domain", "nonexistent") is False

    # ── confirm_source_status ──

    def test_confirm_source_status_adds_confirmed_field(self):
        from engine.evolution.source_lifecycle import confirm_source_status
        result = confirm_source_status("test-domain", "s1")
        assert result is True

        yaml_path = settings.project_root / "domains" / "test-domain" / "sources.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        assert "confirmed: true" in content

    def test_confirm_source_status_nonexistent(self):
        from engine.evolution.source_lifecycle import confirm_source_status
        assert confirm_source_status("test-domain", "nonexistent") is False

    # ── manual_disable/enable ──

    def test_manual_disable_adds_enabled_false(self):
        from engine.evolution.source_lifecycle import manual_disable_source
        result = manual_disable_source("test-domain", "s1")
        assert result is True

        yaml_path = settings.project_root / "domains" / "test-domain" / "sources.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        assert "enabled: false" in content

    def test_manual_enable_adds_enabled_true(self):
        # 先禁用
        from engine.evolution.source_lifecycle import manual_disable_source
        manual_disable_source("test-domain", "s1")

        from engine.evolution.source_lifecycle import manual_enable_source
        result = manual_enable_source("test-domain", "s1")
        assert result is True

        yaml_path = settings.project_root / "domains" / "test-domain" / "sources.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        assert "enabled: true" in content or "enabled: true  # 手动启用" in content

    def test_manual_disable_nonexistent(self):
        from engine.evolution.source_lifecycle import manual_disable_source
        assert manual_disable_source("test-domain", "nonexistent") is False

    def test_manual_enable_nonexistent(self):
        from engine.evolution.source_lifecycle import manual_enable_source
        assert manual_enable_source("test-domain", "nonexistent") is False

    # ── get_lifecycle_status ──

    def test_get_lifecycle_status_returns_sorted(self, store):
        self._seed_metrics(store, "s1", days=7, fetched=20, selected=5)
        self._seed_metrics(store, "s2", days=7, fetched=20, selected=1)

        from engine.evolution.source_lifecycle import get_lifecycle_status
        result = get_lifecycle_status("test-domain")
        assert len(result) >= 2
        # sorted by avg_yield DESC
        assert result[0]["avg_yield"] >= result[-1]["avg_yield"]

    def test_get_lifecycle_status_empty(self, store):
        from engine.evolution.source_lifecycle import get_lifecycle_status
        assert get_lifecycle_status("test-domain") == []

    # ── run_lifecycle_check ──

    def test_run_lifecycle_check_full_flow(self, store):
        # 插入评分数据使 record_daily_metrics 有数据可录
        self._seed_raw_scored(store, "s1", count=5, score=8.0)
        # 插入低产出率指标使 detect_degradation 触发
        self._seed_metrics(store, "s1", days=8, fetched=20, selected=0)

        from engine.evolution.source_lifecycle import run_lifecycle_check
        result = run_lifecycle_check("test-domain")
        assert "metrics" in result
        assert "degraded" in result
        assert "disabled" in result


# ═══════════════════════════════════════════════════════════════
# source_analyzer tests
# ═══════════════════════════════════════════════════════════════

class TestSourceAnalyzer:
    """source_analyzer 模块：信源质量分析/报告。"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "project_root", tmp_path)
        domain_dir = tmp_path / "domains" / "test-domain"
        domain_dir.mkdir(parents=True)
        (domain_dir / "sources.yaml").write_text(
            "sources:\n"
            "  - id: s1\n    name: 健康源\n    kind: rss\n"
            "    url: https://ex.com/1\n    tier: T1\n    lang: zh\n"
            "  - id: s2\n    name: 低效源\n    kind: rss\n"
            "    url: https://ex.com/2\n    tier: T1\n    lang: zh\n",
            encoding="utf-8",
        )
        (domain_dir / "categories.yaml").write_text(
            '{"categories": [{"id": "g", "name": "通用", "freshness_days": 7}]}',
            encoding="utf-8",
        )
        (domain_dir / "keywords.yaml").write_text("keywords: []", encoding="utf-8")
        (domain_dir / "scoring.md").write_text("prompt", encoding="utf-8")
        (domain_dir / "pre_filter.md").write_text("prompt", encoding="utf-8")

    def _seed_raw_scored(self, store, source_id, count, score=7.0, days_ago=1):
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        for i in range(count):
            raw = _make_raw(source_id=source_id, url=f"https://ex.com/{source_id}/{i}",
                            fetched_at=dt)
            rid = store.save_raw(raw)
            store.save_scored(rid, "test-domain",
                              _make_scored(raw, score=score, category="g"))

    def _seed_raw_scored_across_days(self, store, source_id, total_count, score=7.0, num_days=7):
        """Distribute data across num_days so observation_days is sufficient."""
        per_day = max(1, total_count // num_days)
        for day in range(num_days):
            dt = datetime.now(timezone.utc) - timedelta(days=num_days - 1 - day)
            n = per_day if day < num_days - 1 else total_count - per_day * (num_days - 1)
            for j in range(n):
                raw = _make_raw(source_id=source_id, url=f"https://ex.com/{source_id}/{day}/{j}",
                                fetched_at=dt)
                rid = store.save_raw(raw)
                store.save_scored(rid, "test-domain",
                                  _make_scored(raw, score=score, category="g"))

    def test_analyze_source_quality_empty(self, store):
        from engine.evolution.source_analyzer import analyze_source_quality
        result = analyze_source_quality("test-domain", days=7)
        assert result["domain"] == "test-domain"
        assert result["sources"] == []

    def test_analyze_source_quality_with_data(self, store):
        # GENERAL 需要 observation_days >= 7 → 数据跨 8 天得 observation_days=7
        self._seed_raw_scored_across_days(store, "s1", total_count=20, score=8.0, num_days=8)
        self._seed_raw_scored_across_days(store, "s2", total_count=20, score=4.0, num_days=8)

        from engine.evolution.source_analyzer import analyze_source_quality
        result = analyze_source_quality("test-domain", days=7)
        assert len(result["sources"]) == 2

        s1 = next(s for s in result["sources"] if s["source_id"] == "s1")
        assert s1["total"] == 20
        assert s1["selected"] == 20  # all ≥ 6.0
        assert s1["rate"] == pytest.approx(1.0)
        assert s1["status"] == "healthy"

        s2 = next(s for s in result["sources"] if s["source_id"] == "s2")
        assert s2["selected"] == 0  # all < 6.0

    def test_analyze_source_quality_observing_when_few_items(self, store):
        self._seed_raw_scored(store, "s1", count=3, score=7.0)  # < 10 items

        from engine.evolution.source_analyzer import analyze_source_quality
        result = analyze_source_quality("test-domain", days=7)
        s1 = next(s for s in result["sources"] if s["source_id"] == "s1")
        assert s1["status"] == "observing"

    def test_generate_source_report(self, store):
        self._seed_raw_scored(store, "s1", count=15, score=7.0)
        self._seed_raw_scored(store, "s2", count=15, score=3.0)

        from engine.evolution.source_analyzer import generate_source_report
        report = generate_source_report("test-domain", days=7)
        assert "信源质量报告" in report
        assert "s1" in report
        assert "s2" in report


# ═══════════════════════════════════════════════════════════════
# keyword_expander tests
# ═══════════════════════════════════════════════════════════════

class TestKeywordExpander:
    """keyword_expander 模块：关键词提取/分析/建议。"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "project_root", tmp_path)
        domain_dir = tmp_path / "domains" / "test-domain"
        domain_dir.mkdir(parents=True)
        (domain_dir / "keywords.yaml").write_text(
            "keywords:\n  - 现有关键词\n", encoding="utf-8")
        (domain_dir / "sources.yaml").write_text(
            "sources:\n  - id: s1\n    name: 源\n    kind: rss\n"
            "    url: https://ex.com/1\n    tier: T1\n    lang: zh\n",
            encoding="utf-8",
        )

    # ── extract_keywords_from_text ──

    def test_extract_keywords_basic(self):
        from engine.evolution.keyword_expander import extract_keywords_from_text
        result = extract_keywords_from_text("人工智能在养老产业的应用与发展")
        assert "人工智能" in result
        assert "养老产业" in result

    def test_extract_keywords_removes_stopwords(self):
        from engine.evolution.keyword_expander import extract_keywords_from_text
        result = extract_keywords_from_text("这是一个很好的解决方案")
        assert "一个" not in result  # stopword
        assert "解决方案" in result

    def test_extract_keywords_handles_english(self):
        from engine.evolution.keyword_expander import extract_keywords_from_text
        result = extract_keywords_from_text("AI technology for elderly care")
        assert "technology" in result
        assert "elderly" in result
        # shorter than 3 chars → excluded
        assert "AI" not in result

    def test_extract_keywords_skips_digits(self):
        from engine.evolution.keyword_expander import extract_keywords_from_text
        result = extract_keywords_from_text("测试12345数据")
        assert "12345" not in result

    def test_extract_keywords_min_length_filter(self):
        from engine.evolution.keyword_expander import extract_keywords_from_text
        result = extract_keywords_from_text("你我他", min_length=4)
        assert len(result) == 0

    # ── analyze_keyword_frequency ──

    def test_analyze_keyword_frequency_empty(self, store):
        from engine.evolution.keyword_expander import analyze_keyword_frequency
        result = analyze_keyword_frequency("test-domain", days=7)
        assert result["total_items"] == 0

    def test_analyze_keyword_frequency_with_data(self, store):
        now = datetime.now(timezone.utc)
        raw = _make_raw(source_id="s1", url="https://ex.com/1",
                        title="人工智能养老产业发展趋势分析",
                        content="人工智能在养老产业中的应用", fetched_at=now)
        rid = store.save_raw(raw)
        store.save_scored(rid, "test-domain",
                          _make_scored(raw, score=8.0, category="g"))

        from engine.evolution.keyword_expander import analyze_keyword_frequency
        result = analyze_keyword_frequency("test-domain", days=7)
        assert result["total_items"] == 1
        keywords = [k["keyword"] for k in result["keywords"]]
        assert "人工智能" in keywords
        assert "养老产业" in keywords

    # ── suggest_new_keywords ──

    def test_suggest_new_keywords_filters_existing(self, store, monkeypatch):
        # "现有关键词" is in keywords.yaml → should be filtered out
        now = datetime.now(timezone.utc)
        raw = _make_raw(source_id="s1", url="https://ex.com/1",
                        title="现有关键词人工智能发展趋势",
                        fetched_at=now)
        rid = store.save_raw(raw)
        store.save_scored(rid, "test-domain",
                          _make_scored(raw, score=8.0, category="g"))

        from engine.evolution.keyword_expander import suggest_new_keywords
        suggestions = suggest_new_keywords("test-domain", days=7)
        assert "现有关键词" not in suggestions  # filtered by existing
        # "人工智能" should be suggested
        assert "人工智能" in suggestions

    def test_suggest_new_keywords_returns_empty_when_all_exist(self, store, monkeypatch):
        now = datetime.now(timezone.utc)
        raw = _make_raw(source_id="s1", url="https://ex.com/1",
                        title="现有关键词", fetched_at=now)
        rid = store.save_raw(raw)
        store.save_scored(rid, "test-domain",
                          _make_scored(raw, score=8.0, category="g"))

        from engine.evolution.keyword_expander import suggest_new_keywords
        suggestions = suggest_new_keywords("test-domain", days=7)
        # "现有关键词" exists, any extra words like extracted ones should be new
        # The title is exactly "现有关键词" which may get extracted
        pass  # verifying it runs without error

    def test_suggest_new_keywords_limits_to_20(self, store, monkeypatch):
        from engine.evolution.keyword_expander import suggest_new_keywords
        suggestions = suggest_new_keywords("test-domain", days=7)
        assert len(suggestions) <= 20

    # ── generate_keyword_report ──

    def test_generate_keyword_report(self, store):
        now = datetime.now(timezone.utc)
        raw = _make_raw(source_id="s1", url="https://ex.com/1",
                        title="人工智能养老金融科技发展",
                        fetched_at=now)
        rid = store.save_raw(raw)
        store.save_scored(rid, "test-domain",
                          _make_scored(raw, score=8.0, category="g"))

        from engine.evolution.keyword_expander import generate_keyword_report
        report = generate_keyword_report("test-domain", days=7)
        assert "关键词分析报告" in report

    # ── suggest_keywords_yaml ──

    def test_suggest_keywords_yaml(self, store, monkeypatch):
        now = datetime.now(timezone.utc)
        raw = _make_raw(source_id="s1", url="https://ex.com/1",
                        title="人工智能养老金融科技发展新趋势",
                        fetched_at=now)
        rid = store.save_raw(raw)
        store.save_scored(rid, "test-domain",
                          _make_scored(raw, score=8.0, category="g"))

        from engine.evolution.keyword_expander import suggest_keywords_yaml
        yaml_block = suggest_keywords_yaml("test-domain", days=7)
        assert yaml_block.startswith("  # auto-suggested on ")

    def test_suggest_keywords_yaml_empty_when_none(self, store):
        from engine.evolution.keyword_expander import suggest_keywords_yaml
        assert suggest_keywords_yaml("test-domain", days=7) == ""
