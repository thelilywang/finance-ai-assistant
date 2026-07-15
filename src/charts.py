"""決策卡圖表（plotly，真資料）與 PDF 報告匯出，全部失敗回 None 不 raise。

配色依 dataviz skill 驗證通過：估值/股價藍 #2a78d6、beat 綠 #0ca30c、miss 紅 #d03b3b。
"""
from __future__ import annotations

import sys

from .market import to_symbol

BLUE = "#2a78d6"
GREEN = "#0ca30c"
RED = "#d03b3b"
INK_MUTED = "#898781"
GRID = "#e1e0d9"

# ponytail: 圖表固定淺色版面（PDF 也是白底），不做深色主題
_LAYOUT = dict(
    template="plotly_white",
    font=dict(family='system-ui, "PingFang TC", sans-serif', color="#0b0b0b"),
    plot_bgcolor="#fcfcfb",
    paper_bgcolor="#fcfcfb",
    margin=dict(l=50, r=30, t=50, b=40),
)


def price_chart(company: str):
    """近 6 個月收盤價線圖；calendar 有下次財報日且在圖表範圍附近就加垂直標記。"""
    try:
        import plotly.graph_objects as go  # 延遲 import
        import yfinance

        ticker = yfinance.Ticker(to_symbol(company))
        hist = ticker.history(period="6mo")
        if hist.empty:
            return None

        fig = go.Figure(go.Scatter(
            # ponytail: kaleido 的 orjson 不吃 pandas Timestamp，轉 ISO 字串（plotly 仍視為日期軸）
            x=hist.index.strftime("%Y-%m-%d").tolist(), y=hist["Close"].tolist(), mode="lines",
            line=dict(color=BLUE, width=2), name="收盤價",
            hovertemplate="%{x|%Y-%m-%d}<br>收盤 %{y:.2f}<extra></extra>",
        ))
        fig.update_layout(
            title=f"{company.upper()} 股價走勢（6 個月）", showlegend=False, **_LAYOUT,
        )
        fig.update_xaxes(gridcolor=GRID)
        fig.update_yaxes(gridcolor=GRID)

        try:  # 下次財報日標記，拿不到就略過
            import datetime as dt

            date = (ticker.calendar or {}).get("Earnings Date", [None])[0]
            last = hist.index[-1].date()
            # ponytail: 只標「已過去～未來 45 天內」的財報日，太遠會把 x 軸拉爆
            if date and hist.index[0].date() <= date <= last + dt.timedelta(days=45):
                fig.add_vline(
                    x=date.isoformat(), line_dash="dash", line_color=INK_MUTED,
                    annotation_text="下次財報", annotation_font_color=INK_MUTED,
                )
        except Exception as e:  # noqa: BLE001
            print(f"[charts] 財報日標記略過：{e}")

        return fig
    except Exception as e:  # noqa: BLE001
        print(f"[charts] 股價圖生成失敗：{e}")
        return None


def eps_chart(company: str):
    """近 8 季 EPS 預估 vs 實際 grouped bar，實際 beat 綠 / miss 紅。"""
    try:
        import plotly.graph_objects as go  # 延遲 import
        import yfinance

        df = yfinance.Ticker(to_symbol(company)).earnings_dates
        df = df[df["Reported EPS"].notna()].head(8).iloc[::-1]  # 舊到新
        if df.empty:
            return None

        quarters = [idx.date().isoformat() for idx in df.index]
        est, actual = df["EPS Estimate"], df["Reported EPS"]
        colors = [GREEN if a >= e else RED for a, e in zip(actual, est)]

        fig = go.Figure([
            go.Bar(x=quarters, y=est, name="預估 EPS", marker_color=BLUE,
                   hovertemplate="%{x}<br>預估 %{y:.2f}<extra></extra>"),
            go.Bar(x=quarters, y=actual, name="實際 EPS（綠=beat／紅=miss）",
                   marker_color=colors,
                   hovertemplate="%{x}<br>實際 %{y:.2f}<extra></extra>"),
        ])
        fig.update_layout(
            title=f"{company.upper()} EPS 預估 vs 實際（近 8 季）",
            barmode="group", bargroupgap=0.05,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            **{**_LAYOUT, "margin": dict(l=50, r=30, t=90, b=40)},  # legend 在標題下，需較高上邊距
        )
        fig.update_yaxes(gridcolor=GRID)
        return fig
    except Exception as e:  # noqa: BLE001
        print(f"[charts] EPS 圖生成失敗：{e}")
        return None


# ponytail: 依序找得到的 Chrome 系瀏覽器就用；kaleido 轉 PNG 也靠 Chrome，能畫圖就能印 PDF
_CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


def report_pdf(report_md: str, figures: list) -> bytes | None:
    """markdown 報告 + 圖表 → PDF bytes；任一步失敗回 None（呼叫端退回 .md）。

    用 Chrome headless --print-to-pdf 渲染（weasyprint 需要 brew pango，
    在 Intel Homebrew + arm64 Python 環境載不起來，瀏覽器渲染反而零依賴且中文最穩）。
    """
    try:
        import base64
        import os
        import subprocess
        import tempfile

        import markdown

        chrome = next((p for p in _CHROME_PATHS if os.path.exists(p)), None)
        if chrome is None:
            print("[charts] 找不到 Chrome/Chromium/Edge，PDF 退回 .md")
            return None

        body = markdown.markdown(report_md, extensions=["tables"])
        for fig in figures:
            png = fig.to_image(format="png", scale=2)  # kaleido
            b64 = base64.b64encode(png).decode()
            body += f'<img src="data:image/png;base64,{b64}">'

        html = (
            '<meta charset="utf-8"><style>'
            'body { font-family: "PingFang TC", sans-serif; font-size: 11pt; line-height: 1.6; }'
            "h1 { font-size: 16pt; } h2 { font-size: 13pt; }"
            "img { width: 100%; margin: 12pt 0; }"
            "</style>"
            f"<body>{body}</body>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "report.html")
            out = os.path.join(tmp, "report.pdf")
            with open(src, "w", encoding="utf-8") as f:
                f.write(html)
            subprocess.run(
                [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                 f"--print-to-pdf={out}", src],
                check=True, capture_output=True, timeout=60,
            )
            with open(out, "rb") as f:
                return f.read()
    except Exception as e:  # noqa: BLE001
        print(f"[charts] PDF 生成失敗，退回 .md：{e}")
        return None


if __name__ == "__main__":
    company = sys.argv[1] if len(sys.argv) > 1 else "ASML"
    figs = []
    for name, fn in (("price", price_chart), ("eps", eps_chart)):
        fig = fn(company)
        print(f"{name}_chart: {'None' if fig is None else f'{len(fig.data)} trace(s)'}")
        if fig is not None:
            figs.append(fig)
    pdf = report_pdf(f"# {company} 測試報告\n\n中文顯示測試。", figs)
    print(f"report_pdf: {'None' if pdf is None else f'{len(pdf)} bytes'}")
