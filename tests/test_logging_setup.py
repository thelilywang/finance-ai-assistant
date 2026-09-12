"""自檢 logging：JSON Lines 格式、按日期分檔的檔名、冪等設定。

執行：PYTHONDONTWRITEBYTECODE=1 python tests/test_logging_setup.py
"""
import datetime as dt
import json
import logging
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, logging_setup

original_dir = config.LOG_DIR
original_handlers = logging.getLogger().handlers[:]
original_level = logging.getLogger().level

try:
    with tempfile.TemporaryDirectory() as tmp:
        config.LOG_DIR = tmp
        logging.getLogger().handlers = []

        logging_setup.setup_logging("app")
        handler_count = len(logging.getLogger().handlers)
        assert handler_count == 2, f"應有 stream + file 兩個 handler，實際 {handler_count}"

        # 重複呼叫不得重複掛 handler（app.py 是模組載入即執行，可能被載入多次）
        logging_setup.setup_logging("app")
        assert len(logging.getLogger().handlers) == handler_count

        log = logging.getLogger("graph")
        log.info("測試事件", extra={"fields": {"elapsed_ms": 42, "node": "generate"}})
        logging_setup.log_duration(log, "耗時事件", time.monotonic(), node="agent")

        logfile = Path(tmp) / "app.log"
        assert logfile.exists(), "logfile 未建立"
        lines = [l for l in logfile.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2, f"應寫入 2 行，實際 {len(lines)}"

        first = json.loads(lines[0])  # 每行都必須是合法 JSON，回測才能直接餵 pandas/jq
        assert first["message"] == "測試事件"
        assert first["level"] == "INFO"
        assert first["logger"] == "graph"
        assert first["elapsed_ms"] == 42
        assert first["node"] == "generate"
        dt.datetime.fromisoformat(first["ts"])  # 時間戳必須可解析，否則無法算耗時

        second = json.loads(lines[1])
        assert isinstance(second["elapsed_ms"], int)
        assert second["node"] == "agent"

        # 中文不得被轉成 \uXXXX，否則 log 難以直接閱讀
        assert "測試事件" in lines[0]

        # 按日期分檔：切檔後的檔名要帶日期且仍是 .log，方便 glob 與排序
        file_handler = next(h for h in logging.getLogger().handlers
                            if hasattr(h, "namer"))
        rotated = file_handler.namer(str(Path(tmp) / "app.log.2026-09-13"))
        assert Path(rotated).name == "app-2026-09-13.log", rotated

        # 例外要記進 exc 欄位
        logging.getLogger().handlers[1].flush()
        try:
            raise ValueError("boom")
        except ValueError:
            log.error("出錯", exc_info=True)
        last = json.loads(logfile.read_text(encoding="utf-8").splitlines()[-1])
        assert "ValueError: boom" in last["exc"]

        for h in logging.getLogger().handlers:
            h.close()

finally:
    config.LOG_DIR = original_dir
    logging.getLogger().handlers = original_handlers
    logging.getLogger().setLevel(original_level)

print("logging_setup self-check OK")
