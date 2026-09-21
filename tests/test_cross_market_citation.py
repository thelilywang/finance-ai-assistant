"""check_answer_format 的跨市場引用偵測（rule: cross_market_citation）。

正常流程走不到這條規則：市場不明的雙掛牌由 resolve_market 反問使用者，問句講了
市場則由 similarity_search 的 market 過濾擋在檢索外。這條是那兩層失效時的可觀測性
（來源 market 為 NULL、或 both 路徑），平時不該觸發，壞掉也無聲無息——故留自檢。

執行：docker exec finance_ai_assistant_app python tests/test_cross_market_citation.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import check_answer_format

FIELDS = ["conclusion"]


def rules(answer, source_markets=None, market=None):
    return {v["rule"]: v.get("detail") for v in check_answer_format(
        answer, FIELDS, len(source_markets or []), "zh",
        source_markets=source_markets, market=market)}


def demo():
    # 問美股、引用台股來源 → 要抓到，且指出是第幾號
    got = rules("根據[來源2]，台股加權指數上漲。", ["us", "tw"], "us")
    assert got.get("cross_market_citation") == {"market": "us", "cited": [2]}, got

    # 同市場引用不得誤報
    assert "cross_market_citation" not in rules(
        "根據[來源1]，輝瑞營收成長。", ["us", "us"], "us")

    # 市場不明（NULL）的來源不算違規：市場新聞本來就常沒標，報了只是雜訊
    assert "cross_market_citation" not in rules(
        "根據[來源2]說明。", ["us", None], "us")

    # 問句沒市場時整條規則不啟用——沒有基準可比，硬比會把不限市場的查詢全報成違規
    assert "cross_market_citation" not in rules(
        "根據[來源2]，台股上漲。", ["us", "tw"], None)
    assert "cross_market_citation" not in rules(
        "根據[來源2]，台股上漲。", ["us", "tw"], "both")

    # 全形【】也要認：中文語境實測模型會輸出全形，只認半形等於對真實輸出半盲
    assert rules("根據【來源2】，台股上漲。", ["us", "tw"], "us").get(
        "cross_market_citation") == {"market": "us", "cited": [2]}

    # 超出範圍的編號由 citation_out_of_range 負責，不該在這條重複報
    got = rules("根據[來源9]。", ["us", "tw"], "us")
    assert "cross_market_citation" not in got
    assert got.get("citation_out_of_range") == [9]

    print("OK")


if __name__ == "__main__":
    demo()
