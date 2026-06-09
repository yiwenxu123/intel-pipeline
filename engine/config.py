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
    llm_pre_filter_model: str = "gpt-4o-mini"  # 第一轮：低成本去噪
    llm_scoring_model: str = "gpt-4o"  # 第二轮：高质量评分

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
    # 从 3 天扩大到 7 天，让更多有效条目进入 LLM 筛选流程
    score_window_days: int = 7

    # 日报输出
    report_dir: str = "data/reports"

    # 推送通知（飞书/企业微信 Webhook URL，留空不推送）
    notify_webhook: str = ""

    model_config = {"env_file": ".env", "env_prefix": "INTEL_"}

    def model_post_init(self, __context):
        if not self.db_path:
            self.db_path = f"data/intel-{self.domain}.db"


settings = Settings()
