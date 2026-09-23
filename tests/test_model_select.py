"""模型選單的取值與退回邏輯。

重點是「沒選 / 選了空值」時必須退回預設，否則會拿 None 去建 ChatOllama。
"""
from src import config
from src.app import _model_choices
from src.graph import _model_of


def test_model_of_falls_back_to_default():
    # 沒帶 model 欄位（舊呼叫端）或帶空值，都要退回預設，不能回 None
    assert _model_of({}) == config.LLM_MODEL
    assert _model_of({"model": None}) == config.LLM_MODEL
    assert _model_of({"model": ""}) == config.LLM_MODEL
    assert _model_of({"model": "qwen3.5:4b"}) == "qwen3.5:4b"


def test_model_choices_includes_default_first():
    # 選單一定包含預設模型，且排在第一個——設定漏列時使用者仍選得到
    choices = _model_choices()
    assert config.LLM_MODEL in choices
    assert next(iter(choices)) == config.LLM_MODEL
    assert len(choices) == len(set(choices)), "選單不應有重複項目"


def test_model_choices_dedup(monkeypatch):
    # 設定裡重複列出預設模型時不應出現兩次
    monkeypatch.setattr(config, "LLM_MODEL_CHOICES", [config.LLM_MODEL, config.LLM_MODEL, "qwen3.5:4b"])
    dedup = _model_choices()
    assert list(dedup) == [config.LLM_MODEL, "qwen3.5:4b"]
