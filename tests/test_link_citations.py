"""最小 self-check：_link_citations 容錯標籤與數字間空格、url 為 None 不替換。
執行：python tests/test_link_citations.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app import _link_citations

# 中文標籤，模型輸出多了空格 "[來源 1]"
result = _link_citations("根據[來源 1]所述...", "來源", "zh", ["https://a.com"])
assert result == "根據[來源1](https://a.com)所述...", result

# 英文標籤 "[Source 2]"
result = _link_citations("see [Source 2] for detail", "Source ", "en", [None, "https://b.com"])
assert result == "see [Source 2](https://b.com) for detail", result

# url 為 None（幻覺編號或無連結來源）不替換
result = _link_citations("[來源1] and [來源2]", "來源", "zh", [None, "https://c.com"])
assert result == "[來源1] and [來源2](https://c.com)", result

print("_link_citations self-check OK")
