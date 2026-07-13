"""最小 self-check：unique_sources 依出現順序去重（重複來源共用同一編號位置）。
執行：python tests/test_unique_sources.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import unique_sources

retrieved = [
    {"source": "docA"},
    {"source": "docB"},
    {"source": "docA"},  # 同一來源第二個 chunk，不應再佔一個編號
    {"source": "docC"},
]
assert unique_sources(retrieved) == ["docA", "docB", "docC"]
assert unique_sources([]) == []

print("unique_sources self-check OK")
