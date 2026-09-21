"""_last_turn_is_market_reask 的判斷：只有真的反問那一輪才該掛上市場消歧模板。

這三個模板（「台股」→…／「美股」→…／「都要」→…）原本無條件寫在 rewrite_question
的 prompt 裡，模型會把「請同時提供台股與美股兩邊的…」當通用句型往外套，害
單一市場的問句被改寫成兩邊都要。掛條件之後，錯掛與漏掛都會讓那組症狀回來，故留檢查。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import _last_turn_is_market_reask
from src.i18n import t

REASK_ZH = t("zh", "ask_market", name="台積電", tw="2330", us="TSM")
REASK_EN = t("en", "ask_market", name="TSMC", tw="2330", us="TSM")
Q = "台積電最新一期財報的毛利率？"


def main() -> None:
    assert _last_turn_is_market_reask([(Q, REASK_ZH)]) is True, "中文反問未被認出"
    assert _last_turn_is_market_reask([(Q, REASK_EN)]) is True, "英文反問未被認出"

    # 只看最後一輪：反問後又問了別的，模板就不該再掛
    assert _last_turn_is_market_reask(
        [(Q, REASK_ZH), ("美股半導體最近如何？", "【已知事實】…")]
    ) is False, "反問已隔一輪，仍被當成反問"

    # 一般對話不得誤觸——這正是 M4／M5 失分的成因
    assert _last_turn_is_market_reask(
        [("台積電最近的新聞在說什麼？", "【已知事實】台積電近期擴產…")]
    ) is False, "一般回覆被誤判為反問"

    # 使用者自己打出反問句不算：撿不回雙掛牌代號就不成立
    assert _last_turn_is_market_reask(
        [("今天天氣如何？", "請問你要看哪一邊？（請點選下方按鈕）")]
    ) is False, "無雙掛牌標的仍被判為反問"

    assert _last_turn_is_market_reask([]) is False, "空歷史應回 False"

    print("OK")


if __name__ == "__main__":
    main()
