"""API 的請求／回應模型。"""
from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[tuple[str, str]] = []  # [(user, assistant), ...]，與 GraphState 同形
    lang: Literal["zh", "en"] = "zh"
    market: Literal["tw", "us"] | None = None  # 明講市場則跳過雙掛牌反問


class AnswerResult(BaseModel):
    answer: str
    sources: list[str]
    ask_market: bool  # True 表示 answer 是反問市場，client 要帶 market 重問
    peer_company: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    status: str
