"""最小 self-check：模型選單的取值與退回邏輯。

重點是「沒選 / 選了空值」時必須退回預設，否則會拿 None 去建 ChatOllama。
執行：python tests/test_model_select.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.app import _model_choices
from src.graph import _model_of

# 沒帶 model 欄位（舊呼叫端）或帶空值，都要退回預設，不能回 None
assert _model_of({}) == config.LLM_MODEL
assert _model_of({"model": None}) == config.LLM_MODEL
assert _model_of({"model": ""}) == config.LLM_MODEL
assert _model_of({"model": "qwen3.5:4b"}) == "qwen3.5:4b"

# 選單一定包含預設模型，且排在第一個——設定漏列時使用者仍選得到
choices = _model_choices()
assert config.LLM_MODEL in choices
assert next(iter(choices)) == config.LLM_MODEL
assert len(choices) == len(set(choices)), "選單不應有重複項目"

# 設定裡重複列出預設模型時不應出現兩次
original = config.LLM_MODEL_CHOICES
try:
    config.LLM_MODEL_CHOICES = [config.LLM_MODEL, config.LLM_MODEL, "qwen3.5:4b"]
    dedup = _model_choices()
    assert list(dedup) == [config.LLM_MODEL, "qwen3.5:4b"]
finally:
    config.LLM_MODEL_CHOICES = original

print("model select self-check OK")
