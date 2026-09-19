"""最小 self-check：股價圖的財報日標記。
不連 yfinance——這個 bug 與資料無關，純粹是 plotly 對「字串日期 x 軸」的行為。
執行：python tests/test_chart_earnings_marker.py
"""
import sys
from pathlib import Path

import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

passed = 0

# price_chart 的 x 軸是 ISO 字串（kaleido 的 orjson 不吃 pandas Timestamp，見 charts.py）
fig = go.Figure(go.Scatter(x=["2026-03-18", "2026-09-18"], y=[1.0, 2.0], mode="lines"))

# add_vline 帶 annotation_text 會把線的 x 端點丟進 sum() 求平均來擺標註，字串就炸
# TypeError: unsupported operand type(s) for +: 'int' and 'str'。
# 這條釘住「為什麼不能用回 add_vline」——哪天 plotly 修了，這題會 FAIL 提醒我們簡化。
try:
    go.Figure(fig).add_vline(x="2026-10-15", annotation_text="下次財報")
    raise AssertionError("add_vline 竟然沒炸——plotly 可能已修正，可考慮簡化 charts.py")
except TypeError as e:
    assert "unsupported operand" in str(e)
passed += 1

# 實際採用的寫法：shape + annotation 分開，自己指定位置，不經過那段平均
x = "2026-10-15"
fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, yref="paper",
              line=dict(color="#898781", dash="dash"))
fig.add_annotation(x=x, y=1, yref="paper", text="下次財報", showarrow=False,
                   yanchor="bottom", font=dict(color="#898781"))
assert len(fig.layout.shapes) == 1 and fig.layout.shapes[0].x0 == x
assert len(fig.layout.annotations) == 1 and fig.layout.annotations[0].text == "下次財報"
passed += 1

# 圖仍可序列化（PDF 匯出走 kaleido，序列化失敗會在那裡才爆）
assert "下次財報" in fig.to_json()
passed += 1

print(f"chart earnings marker self-check OK（{passed} passed）")
