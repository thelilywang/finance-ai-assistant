"""unique_sources 依出現順序去重（重複來源共用同一編號位置）。"""
from src.graph import unique_sources


def test_unique_sources_dedup_in_order():
    retrieved = [
        {"source": "docA"},
        {"source": "docB"},
        {"source": "docA"},  # 同一來源第二個 chunk，不應再佔一個編號
        {"source": "docC"},
    ]
    assert unique_sources(retrieved) == ["docA", "docB", "docC"]
    assert unique_sources([]) == []
