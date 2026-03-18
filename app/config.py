from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


def _env(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        # Fallback: try to load .env relative to the project root
        # (helps when main.py wasn't executed from the expected cwd / shell is quirky)
        try:
            project_root_env = Path(__file__).resolve().parents[1] / ".env"
            if project_root_env.exists():
                load_dotenv(dotenv_path=project_root_env, override=True, encoding="utf-8")
            load_dotenv(override=True, encoding="utf-8")
        except Exception:
            pass
        v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(
            "Missing required env var: "
            f"{name}\n\n"
            "Create file .env in the project root (next to main.py), for example:\n"
            "BOT_TOKEN=123456:ABCDEF\n"
            "OWNER_ADMIN_ID=123456789\n"
            "ADMIN_IDS=111111111,222222222\n"
            "CRYPTOBOT_API_KEY=your_api_key_here\n"
        )
    return v


def _env_int(name: str, default: int | None = None) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        if default is None:
            raise RuntimeError(f"Missing env var: {name}")
        return default
    return int(v)


def _parse_int_list(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        out.append(int(p))
    return out


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_admin_id: int
    admin_ids: list[int]
    cryptobot_api_key: str
    reviews_url: str | None
    auto_withdraw: bool
    watcher_interval_sec: int

    @property
    def all_admin_ids(self) -> set[int]:
        return {self.owner_admin_id, *self.admin_ids}


def load_config() -> Config:
    bot_token = _env("BOT_TOKEN")
    owner_admin_id = _env_int("OWNER_ADMIN_ID")
    admin_ids = _parse_int_list(os.getenv("ADMIN_IDS", ""))
    cryptobot_api_key = _env("CRYPTOBOT_API_KEY", "")
    reviews_url = os.getenv("REVIEWS_URL") or None
    auto_withdraw = os.getenv("AUTO_WITHDRAW", "0").strip() in {"1", "true", "True", "yes", "YES"}
    watcher_interval_sec = _env_int("WATCHER_INTERVAL_SEC", 10)
    return Config(
        bot_token=bot_token,
        owner_admin_id=owner_admin_id,
        admin_ids=admin_ids,
        cryptobot_api_key=cryptobot_api_key,
        reviews_url=reviews_url,
        auto_withdraw=auto_withdraw,
        watcher_interval_sec=watcher_interval_sec,
    )


def is_admin(user_id: int, cfg: Config) -> bool:
    return user_id in cfg.all_admin_ids


def admin_only_ids(cfg: Config) -> Iterable[int]:
    return cfg.all_admin_ids
