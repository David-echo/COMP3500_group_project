"""
应用配置 (Configuration)
========================

对应课程 Lecture 6「Architectural design decisions」：
数据库、缓存、密钥这些**基础设施选择**是架构决策，必须集中管理，
不能散落在业务代码里。本文件是唯一读取环境变量的地方。

依赖: pydantic-settings
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---------- 应用 ----------
    app_name: str = "Election Management & Voting System"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # ---------- 安全 ----------
    # 生产环境必须用环境变量覆盖（ADR-005 / README 安全说明）
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    access_token_expire_minutes: int = 120
    jwt_algorithm: str = "HS256"

    # ---------- 数据库 ----------
    # 目标：PostgreSQL 16（见 docs/ADR）
    # 开发回退：SQLite（无 Docker 也能跑通与测试）
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    db_echo: bool = False

    # ---------- 缓存 / 发布订阅 ----------
    # 为空时使用进程内实现（单实例可用）；生产填 redis://localhost:6379/0
    redis_url: str = ""

    # ---------- 业务参数 ----------
    # 每个进行中的选举启动时至少保留多少名未投票选民（便于演示）
    min_available_voters: int = 5
    # SSE 心跳间隔（秒）
    sse_heartbeat_seconds: int = 15

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
