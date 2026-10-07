"""bench_adr_premium.cites_premium / cites_eps_equiv / _parse_block 的數值比對邏輯。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_adr_premium import _parse_block, cites_eps_equiv, cites_premium  # noqa: E402


def test_cites_premium_exact_phrase():
    assert cites_premium("ADR 換算後價格約為 3,071.09 元，高於台股現價 19.03%", 19.03)


def test_cites_premium_rounded():
    assert cites_premium("ADR 換算價高於台股約 19%", 19.03)


def test_cites_premium_different_wording():
    assert cites_premium("美股溢價明顯：ADR 價格換算後比台股高出約 19%", 19.05)


def test_cites_premium_unrelated_percentages():
    assert not cites_premium("台股跌幅 0.19%，ADR 跌幅 0.72%，毛利率 67.5%", 19.03)


def test_cites_premium_discount_takes_abs():
    assert cites_premium("ADR 低於台股 3.2%", -3.21)


def test_cites_premium_none_premium_pct():
    assert not cites_premium("高於台股現價 19.03%", None)


def test_cites_eps_equiv_rounded_up():
    assert cites_eps_equiv("換算後約 27.4 元", 27.41)


def test_cites_eps_equiv_rounded_down():
    assert cites_eps_equiv("換算後約 27.5 元", 27.46)


def test_cites_eps_equiv_self_converted_wrong():
    assert not cites_eps_equiv("台股 EPS 27.25 元，ADR 4.31 美元", 27.41)


def test_cites_eps_equiv_none_eps_equiv():
    assert not cites_eps_equiv("27.4", None)


def test_parse_block_full():
    text = (
        "ADR premium vs 2330: +19.03%\n"
        "TSM EPS per 2330 share: 4.31 / 5 × 31.8 = 27.41 TWD "
        "(vs 2330 27.25 TWD, +0.59%)"
    )
    assert _parse_block(text) == (19.03, 27.41)


def test_parse_block_price_line_not_taken_as_eps_equiv():
    # 新版區塊的股價行也含「= 2840.36 TWD」，eps_equiv 必須取 EPS 換算行的 27.41
    text = (
        "ADR ratio: 1 TSM = 5 shares of 2330 (ADR figure → per 2330 share: ÷ 5, then × USD/TWD)\n"
        "TSM price per 2330 share: 446.57 / 5 × 31.802 = 2840.36 TWD (share price, not EPS)\n"
        "ADR premium vs 2330: +14.53%\n"
        "latest reported EPS (reported 2026-07-16): 2330 27.25 TWD / TSM 4.31 USD\n"
        "TSM EPS per 2330 share: 4.31 / 5 × 31.802 = 27.41 TWD (vs 2330 27.25 TWD, +0.60%)"
    )
    assert _parse_block(text) == (14.53, 27.41)


def test_parse_block_premium_only():
    assert _parse_block("ADR premium vs 2330: +19.03%") == (19.03, None)


def test_parse_block_none():
    assert _parse_block(None) == (None, None)
