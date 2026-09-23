"""_link_citations 的自我檢查：半形與全形引用標記都要轉成連結。"""
from src.app import _link_citations

URLS = ["http://a", "http://b"]


def test_link_citations_halfwidth():
    # 1: 半形（prompt 寫的形式）
    out = _link_citations("營收成長 [來源1]，動能延續 [來源2]。", "來源", "zh", URLS)
    assert out == "營收成長 [[來源1]](http://a)，動能延續 [[來源2]](http://b)。", out


def test_link_citations_fullwidth():
    # 2: 全形（模型實測輸出的形式）——2026-09-19 前這裡轉換數為 0
    out = _link_citations("營收成長【來源1】，動能延續【來源2】。", "來源", "zh", URLS)
    assert out == "營收成長[[來源1]](http://a)，動能延續[[來源2]](http://b)。", out


def test_link_citations_out_of_range_removed():
    # 3: 越界編號整段移除，半形與全形一致
    assert _link_citations("推論 [來源9]。", "來源", "zh", URLS) == "推論 。"
    assert _link_citations("推論【來源9】。", "來源", "zh", URLS) == "推論。"


def test_link_citations_none_url_kept_as_text():
    # 4: url 為 None 的來源保留純文字，不轉連結也不被當成越界刪掉
    out = _link_citations("事實【來源2】。", "來源", "zh", ["http://a", None])
    assert out == "事實【來源2】。", out


def test_link_citations_english_label_spacing():
    # 5: 英文 label（尾端空格）與數字間的空格都要容錯
    out = _link_citations("Growth [Source 1] and [Source2].", "Source ", "en", URLS)
    assert out == "Growth [[Source 1]](http://a) and [[Source 2]](http://b).", out
