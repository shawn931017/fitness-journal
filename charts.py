"""趨勢圖：由 Python 的 Plotly 產生圖表定義，瀏覽器端只負責畫出來。"""
import json
from datetime import date, timedelta

import plotly.graph_objects as go
from plotly.subplots import make_subplots

TEAL = "#2f7d6d"
ORANGE = "#d9822b"
GRID = "#e3eae8"
FONT = dict(family='-apple-system, "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif',
            size=12, color="#24302d")


def fmt_num(x):
    return f"{x:g}"


def _base_layout(fig, height):
    fig.update_layout(
        height=height,
        margin=dict(l=44, r=12, t=34, b=30),
        font=FONT,
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        hovermode="closest",
        dragmode=False,  # 手機上捲動頁面時不要被圖表吃掉手勢
        hoverlabel=dict(font=dict(family=FONT["family"], size=13)),
    )
    fig.update_xaxes(type="date", tickformat="%m/%d", gridcolor=GRID, fixedrange=True,
                     showline=True, linecolor="#c9d4d1")
    fig.update_yaxes(gridcolor=GRID, fixedrange=True, zeroline=False)
    for ann in fig.layout.annotations:  # 子圖標題靠左、字小一點
        ann.update(x=0, xanchor="left", font=dict(size=13, color="#4b5a56"))


def _to_dict(fig):
    return json.loads(fig.to_json())


def training_figure(points, per_hand, x_range):
    """points: [{date, weight, reps, progress_kind, progress_text, is_demo}]
    上圖公斤、下圖次數，共用日期軸；進步的點以橘色星號標示。"""
    weight_title = "做組重量（kg，單手）" if per_hand else "做組重量（kg）"
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
                        subplot_titles=(weight_title, "次數（下）"))
    xs = [p["date"] for p in points]
    hover = [
        f"{p['date'][5:].replace('-', '/')}　{fmt_num(p['weight'])} kg × {p['reps']} 下"
        + ("<br>（測試資料）" if p["is_demo"] else "")
        + "<br>點一下看當天全部組別"
        for p in points
    ]

    def marker(kind):
        hit = [p["progress_kind"] == kind for p in points]
        return dict(
            size=[13 if h else 8 for h in hit],
            symbol=["star" if h else "circle" for h in hit],
            color=[ORANGE if h else TEAL for h in hit],
            line=dict(width=1, color="white"),
        )

    fig.add_trace(go.Scatter(
        x=xs, y=[p["weight"] for p in points], customdata=xs, hovertext=hover, hoverinfo="text",
        mode="lines+markers+text", line=dict(color=TEAL, width=2), marker=marker("weight"),
        text=[p["progress_text"] if p["progress_kind"] == "weight" else "" for p in points],
        textposition="top center", textfont=dict(color=ORANGE, size=11),
        cliponaxis=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=xs, y=[p["reps"] for p in points], customdata=xs, hovertext=hover, hoverinfo="text",
        mode="lines+markers+text", line=dict(color=TEAL, width=2), marker=marker("reps"),
        text=[p["progress_text"] if p["progress_kind"] == "reps" else "" for p in points],
        textposition="top center", textfont=dict(color=ORANGE, size=11),
        cliponaxis=False,
    ), row=2, col=1)

    _base_layout(fig, 430)
    fig.update_xaxes(range=x_range)
    _pad_y(fig, [p["weight"] for p in points], row=1)
    _pad_y(fig, [p["reps"] for p in points], row=2, integer=True)
    return _to_dict(fig)


def _pad_y(fig, values, row, integer=False):
    if not values:
        return
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * 0.25, 1 if integer else 2.5)
    fig.update_yaxes(range=[max(0, lo - pad), hi + pad], row=row, col=1)
    if integer:
        fig.update_yaxes(dtick=max(1, round((hi - lo + 2 * pad) / 5)), row=row, col=1)


def nutrition_figure(estimates, daily_rows, start, end, day_targets, comparisons):
    """每日估算熱量與蛋白質（長條）＋當天目標（橘色虛線，體重變了目標也跟著變）。
    沒寫飲食的日子不畫；含未知食物的日子用淡色，代表數值偏低。
    增重、減重畫一條目標線；維持畫上下兩條，中間是目標範圍。"""
    xs, kcal, protein, colors, hover = [], [], [], [], []
    k_line, k_low, k_high, p_line = [], [], [], []
    d = start
    while d <= end:
        key = d.isoformat()
        est = estimates.get(key)
        tg = day_targets[key]
        cmp = comparisons.get(key)
        xs.append(key)
        maintain = tg["mode"] == "maintain"
        k_line.append(tg["kcal"] if tg["kcal"] and not maintain else None)
        k_low.append(tg["kcal_low"] if maintain else None)
        k_high.append(tg["kcal_high"] if maintain else None)
        p_line.append(tg["protein"])
        if est and est["items"]:
            t = est["total"]
            partial = bool(est["unknown"])
            kcal.append(round(t["kcal"]))
            protein.append(round(t["protein"], 1))
            colors.append("#9cc5bb" if partial else TEAL)
            row = daily_rows.get(key)
            verdict = ""
            if cmp and not cmp["in_progress"]:
                parts = [f"{label}{cmp[k]['text']}" for k, label in (("kcal", "熱量"), ("protein", "蛋白質"))
                         if cmp[k]["state"] != "none"]
                verdict = f"<br>{tg['mode_label']}：" + "；".join(parts) if parts else ""
            hover.append(
                f"{key[5:].replace('-', '/')}　約 {round(t['kcal'])} kcal<br>"
                f"碳水 {t['carb']:.0f} g・蛋白質 {t['protein']:.0f} g・脂肪 {t['fat']:.0f} g"
                + verdict
                + (f"<br>另有 {len(est['unknown'])} 項查不到，實際應更高" if partial else "")
                + ("<br>（測試資料）" if row and row["is_demo"] else "")
            )
        else:
            kcal.append(None)
            protein.append(None)
            colors.append(TEAL)
            hover.append("")
        d += timedelta(days=1)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.14,
                        subplot_titles=("每日熱量（kcal，估算）", "每日蛋白質（g，估算）"))
    for row, ys in ((1, kcal), (2, protein)):
        fig.add_trace(go.Bar(x=xs, y=ys, customdata=xs, hovertext=hover, hoverinfo="text",
                             marker=dict(color=colors)), row=row, col=1)
    # 目標線畫到最後一天的右緣，看起來像階梯
    line_x = xs + [(end + timedelta(days=1)).isoformat()]
    dash = dict(color=ORANGE, width=1.5, dash="dash", shape="hv")
    for ys, row in ((k_line, 1), (k_low, 1), (k_high, 1), (p_line, 2)):
        if any(v is not None for v in ys):
            fig.add_trace(go.Scatter(x=line_x, y=ys + [ys[-1]], mode="lines", line=dash, hoverinfo="skip",
                                     connectgaps=False), row=row, col=1)
    _base_layout(fig, 400)
    fig.update_layout(bargap=0.25)
    fig.update_xaxes(range=[(start - timedelta(days=1)).isoformat(), (end + timedelta(days=1)).isoformat()])

    last = day_targets[end.isoformat()]
    labels = []
    if last["kcal"]:
        if last["mode"] == "maintain":
            labels.append((1, last["kcal_high"], f"範圍 {last['kcal_low']}–{last['kcal_high']}"))
        else:
            labels.append((1, last["kcal"], f"{'至少' if last['mode'] == 'gain' else '上限'} {last['kcal']}"))
    if last["protein"]:
        labels.append((2, last["protein"], f"至少 {last['protein']} g"))
    for row, y, text in labels:
        fig.add_annotation(x=xs[0], y=y, text=text, showarrow=False, xanchor="left", yanchor="bottom",
                           font=dict(color=ORANGE, size=11), row=row, col=1)
    # y 軸要包含目標線
    for row, bars, lines in ((1, kcal, k_line + k_high), (2, protein, p_line)):
        vals = [v for v in bars + lines if v is not None]
        if vals:
            fig.update_yaxes(range=[0, max(vals) * 1.12], row=row, col=1)
    return _to_dict(fig)


def body_weight_figure(daily_rows, start, end, target):
    """體重另圖顯示；沒量的日期是 None，線會斷開（留白，不補點）。"""
    xs, ys, hover = [], [], []
    d = start
    while d <= end:
        key = d.isoformat()
        row = daily_rows.get(key)
        bw = row["body_weight"] if row else None
        xs.append(key)
        ys.append(bw)
        hover.append(
            f"{key[5:].replace('-', '/')}　{fmt_num(bw)} kg" + ("<br>（測試資料）" if row and row["is_demo"] else "")
            if bw is not None else ""
        )
        d += timedelta(days=1)

    fig = go.Figure(go.Scatter(
        x=xs, y=ys, customdata=xs, hovertext=hover, hoverinfo="text",
        mode="lines+markers", connectgaps=False,
        line=dict(color=TEAL, width=2), marker=dict(size=7, color=TEAL),
    ))
    _base_layout(fig, 260)
    fig.update_layout(margin=dict(t=36),
                      title=dict(text="體重（kg）", x=0.01, xanchor="left", font=dict(size=13, color="#4b5a56")))
    fig.add_hline(y=target, line=dict(color=ORANGE, width=1.5, dash="dash"),
                  annotation_text=f"目標 {fmt_num(target)} kg", annotation_position="top left",
                  annotation_font=dict(color=ORANGE, size=11))
    measured = [y for y in ys if y is not None]
    if measured:
        lo, hi = min(measured + [target]), max(measured + [target])
        fig.update_yaxes(range=[lo - 1.5, hi + 1.5])
    fig.update_xaxes(range=[start.isoformat(), (end + timedelta(days=1)).isoformat()])
    return _to_dict(fig)
