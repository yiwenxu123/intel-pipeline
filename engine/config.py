"""全局配置，通过环境变量或 .env 加载。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 项目根目录
    project_root: Path = Path(__file__).parent.parent

    # LLM 配置
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_pre_filter_model: str = "gpt-4o-mini"  # DEPRECATED: 保留兼容旧 .env
    llm_scoring_model: str = "gpt-4o"  # 评分 + 简报提炼

    # 当前加载的领域
    domain: str = "elderly-care"

    # 数据库
    db_path: str = ""  # 空值时自动按领域生成 data/intel-{domain}.db

    # API 服务
    api_host: str = "0.0.0.0"
    api_port: int = 8900

    # 新鲜度过滤（天数，超过此天数的条目直接丢弃）
    freshness_days: int = 3

    # LLM 筛选窗口（只对最近 N 天的未评分条目跑 LLM）
    # 从 7 天扩大到 14 天，让更多有效条目进入 LLM 筛选流程
    score_window_days: int = 14

    # 日报输出
    report_dir: str = "data/reports"

    # 推送通知（飞书/企业微信 Webhook URL，留空不推送）
    notify_webhook: str = ""

    # pipe 采集失败告警：失败信源数 ≥ 此阈值时推送（独立于日报推送）
    pipe_alert_error_threshold: int = 3

    # 待评分堆积预警：窗口内未评分条目超过此数时在日志/Dashboard 标红
    unscored_warn_threshold: int = 100

    # DEPRECATED: LLM 预筛已废弃；设为极大值等同关闭
    pre_filter_backlog_threshold: int = 999999

    # 规则预筛：零成本去噪，被拒条目 score=0 入库
    rule_prefilter_enabled: bool = True

    # LLM 成本估算（元/百万 tokens，用于 Dashboard ROI 展示）
    llm_cost_per_1m_input: float = 2.0
    llm_cost_per_1m_output: float = 8.0

    # 暂停自动采集的领域（逗号分隔）；手动 CLI 仍可执行，scheduler 跳过
    paused_domains: str = "china-africa"

    # 评分前正文补全：原文短于此阈值时抓取全文
    enrich_min_content_length: int = 200
    score_input_max_chars: int = 3000

    # 低输入评分封顶（正文+全文不足 low_input_threshold 且无标题事实锚点）
    low_input_threshold: int = 80
    low_input_max_score: float = 6.5

    # 精选后是否运行简报提炼（headline/lead/takeaway）
    briefing_enabled: bool = True

    # API 写操作 Token（留空则不校验 POST，仅建议内网使用）
    api_token: str = ""

    model_config = {"env_file": ".env", "env_prefix": "INTEL_"}

    def model_post_init(self, __context):
        if not self.db_path:
            self.db_path = f"data/intel-{self.domain}.db"

    def get_paused_domains(self) -> frozenset[str]:
        return frozenset(
            d.strip() for d in self.paused_domains.split(",") if d.strip()
        )

    def is_domain_paused(self, domain: str) -> bool:
        return domain in self.get_paused_domains()


settings = Settings()
