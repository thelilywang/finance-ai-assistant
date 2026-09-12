"""集中設定 logging：stdout 照舊，另外每日一檔寫 JSON Lines 供事後回測。

各服務進入點呼叫一次 `setup_logging("app")` / `setup_logging("mcp")`。
之後各模組用 `logging.getLogger(__name__)` 取得 logger 即可，不需再設定。

耗時等結構化欄位透過 `extra={"fields": {...}}` 傳入，會併進 JSON 那一行：

    log.info("generate 完成", extra={"fields": {"elapsed_ms": 1234, "model": "qwen3.5:9b"}})
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from . import config

# LogRecord 內建屬性，逐一列出才能在 formatter 裡辨識出「呼叫端自己加的欄位」。
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime", "message", "taskName", "fields",
}


class _JsonLinesFormatter(logging.Formatter):
    """一行一筆 JSON。回測時可直接餵 pandas / jq，不必先寫 parser。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            # 用本地時間（容器已設 TZ=Asia/Taipei），與專案其他「今天」的判斷一致
            "ts": dt.datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "fields", None) or {})
        # 相容直接用 extra={"elapsed_ms": ...} 的呼叫
        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _log_name(service: str) -> str:
    """容器內用服務名，容器外再加 -local。

    LOG_DIR 是 bind mount，host 直接跑測試時會寫進容器同一個檔。兩邊連的
    DB 不同（host 沒開 5432，只會連線失敗），混在一起會讓回測把本機測試
    的雜訊當成正式環境數據。
    """
    return service if Path("/.dockerenv").exists() else f"{service}-local"


def _file_handler(service: str) -> logging.Handler:
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    service = _log_name(service)
    # 按日期而非大小輪替：大小輪替的 .1/.2 序號看不出日期，回測要逐檔翻。
    # app 與 mcp-server 是兩個 container，各寫各的檔——共寫一檔在切檔時會互相覆蓋。
    handler = TimedRotatingFileHandler(
        log_dir / f"{service}.log",
        when="midnight",
        backupCount=config.LOG_BACKUP_DAYS,
        encoding="utf-8",
    )
    handler.suffix = "%Y-%m-%d"
    # 預設會產生 app.log.2026-09-13，日期在副檔名之後不利 glob 與排序，改成 app-2026-09-13.log
    handler.namer = lambda name: str(log_dir / f"{service}-{name.rsplit('.', 1)[-1]}.log")
    handler.setFormatter(_JsonLinesFormatter())
    return handler


def setup_logging(service: str) -> None:
    """設定 root logger；重複呼叫只會生效一次。"""
    root = logging.getLogger()
    if any(getattr(h, "_finrag", False) for h in root.handlers):
        return

    root.setLevel(config.LOG_LEVEL)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handlers = [stream]

    try:
        handlers.append(_file_handler(service))
    except OSError as e:
        # 磁碟唯讀或權限不足時不該讓服務起不來，退化成只有 stdout
        stream.handle(logging.LogRecord(
            __name__, logging.WARNING, __file__, 0,
            "logfile 無法建立，僅輸出 stdout：%s", (e,), None,
        ))

    for h in handlers:
        h._finrag = True  # 冪等標記
        root.addHandler(h)

    # 第三方套件的 INFO 量大且與 AI 追蹤無關，壓到 WARNING 免得洗掉自己的紀錄
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_duration(log: logging.Logger, event: str, started: float, **fields) -> None:
    """記一筆耗時。`started` 傳 time.monotonic() 的起點。"""
    log.info(event, extra={"fields": {"elapsed_ms": round((time.monotonic() - started) * 1000), **fields}})
