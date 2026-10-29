"""pytest 共用設定：測試的 log 寫進暫存目錄，不碰正式 data/logs。

src/app.py 在 import 時就會 setup_logging，stub 的假紀錄（如 eval_count=4096）
會混進正式 log，污染回測統計。必須在任何 src 模組 import 前設定。
"""
import os
import tempfile

os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="pytest-logs-")
