"""从 output/results.json 生成 site/index.html（自包含可视化报告页，无外部依赖）。

用法：python3 src/build_site.py
"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

METRIC_COLORS = {
    "faithfulness": "#6366f1",
    "accuracy": "#0ea5e9",
    "helpfulness": "#f59e0b",
    "tone": "#10b981",
}

WORST_ANALYSIS = {
    "case_20": "用户说「搞不懂退货流程」，回复却把同一份流程原样复述——提供的是用户已声明无效的信息。根因是意图识别粒度过粗：只匹配了问题主题，没识别出这是抱怨/求助而非咨询。",
    "case_11": "同一回复内给出两条互斥路径（「换货=先退再买」与「发起换货申请」），且「换货=先退再买」属无据自创规则。根因是多商品场景触发流程拼接，缺内部一致性自检。",
    "case_19": "声称「加入购物车后系统自动提醒补货」——对系统功能的无据断言，若功能不存在即为典型编造，用户会基于不存在的功能产生预期，风险极高。",
}


def esc(s):
    return html.escape(str(s))


def score_cls(v):
    if v >= 4.5:
        return "s-good"
    if v >= 4.0:
        return "s-ok"
    if v >= 3.0:
        return "s-mid"
    return "s-bad"


def build():
    with open(ROOT / "output" / "results.json", encoding="utf-8") as f:
        data = json.load(f)

    agg = data["aggregate"]
    cases = sorted(data["cases"], key=lambda x: x["overall"])
    val = data["validation"]

    # 指标卡
    metric_cards = ""
    for k, pm in agg["per_metric"].items():
        color = METRIC_COLORS[k]
        pct = pm["mean"] / 5 * 100
        dist = pm["distribution"]
        segs = ""
        total = sum(dist.values())
        seg_colors = ["#ef4444", "#fb923c", "#facc15", "#4ade80", "#22c55e"]
        for i, (b, n) in enumerate(dist.items()):
            w = n / total * 100
            segs += f'<div class="seg" style="width:{w:.1f}%;background:{seg_colors[i]}" title="{esc(b)}: {n}条"></div>'
        metric_cards += f"""
        <div class="card metric-card">
          <div class="metric-head"><span class="dot" style="background:{color}"></span>{esc(pm['name'])}<span class="weight">权重 {pm['weight']:.0%}</span></div>
          <div class="metric-score">{pm['mean']:.2f}<span class="of5">/5</span></div>
          <div class="bar"><div class="bar-fill" style="width:{pct:.0f}%;background:{color}"></div></div>
          <div class="range">区间 {pm['min']} – {pm['max']}</div>
          <div class="dist">{segs}</div>
          <div class="dist-legend">红→绿：低分段 → 高分段分布</div>
        </div>"""

    # 最差 3
    worst_cards = ""
    for cid in data["worst3"]:
        c = next(x for x in data["cases"] if x["id"] == cid)
        chips = "".join(
            f'<span class="chip {score_cls(c["scores"][m]["score"])}">{n} {c["scores"][m]["score"]}</span>'
            for m, n in [("faithfulness", "忠实"), ("accuracy", "准确"), ("helpfulness", "有用"), ("tone", "语气")]
        )
        worst_cards += f"""
        <div class="card worst-card">
          <div class="worst-head"><span class="cid">{cid}</span><span class="overall {score_cls(c['overall'])}">总分 {c['overall']}</span></div>
          <div class="q">用户：{esc(c['user_question'])}</div>
          <div class="chips">{chips}</div>
          <p class="analysis">{esc(WORST_ANALYSIS[cid])}</p>
          <p class="human">人工标注：{esc(c['human_note'])}</p>
        </div>"""

    # 全量表
    rows = ""
    for c in cases:
        cells = "".join(
            f'<td class="{score_cls(c["scores"][m]["score"])}">{c["scores"][m]["score"]}</td>'
            for m in ["faithfulness", "accuracy", "helpfulness", "tone"]
        )
        rows += f"""<tr><td>{c['id']}</td><td class="{score_cls(c['overall'])}"><b>{c['overall']}</b></td>{cells}<td class="qcell">{esc(c['user_question'])}</td></tr>"""

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>客服自动回复质量评估报告</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; background:#f6f7f9; color:#1f2329; line-height:1.6; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:40px 24px 64px; }}
  header {{ margin-bottom:28px; }}
  h1 {{ font-size:26px; margin-bottom:6px; }}
  .sub {{ color:#646a73; font-size:14px; }}
  .hero {{ display:flex; gap:24px; align-items:stretch; margin:24px 0; flex-wrap:wrap; }}
  .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:20px 24px; }}
  .hero-main {{ flex:1; min-width:280px; display:flex; align-items:center; gap:28px; }}
  .big-score {{ font-size:56px; font-weight:700; color:#f59e0b; line-height:1; }}
  .big-score small {{ font-size:20px; color:#9ca3af; font-weight:400; }}
  .verdict {{ flex:1; font-size:14px; color:#374151; }}
  .verdict b {{ color:#b45309; }}
  h2 {{ font-size:19px; margin:34px 0 14px; padding-left:10px; border-left:4px solid #6366f1; }}
  .grid4 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:16px; }}
  .metric-head {{ font-size:14px; font-weight:600; display:flex; align-items:center; gap:8px; }}
  .dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
  .weight {{ margin-left:auto; font-size:12px; color:#9ca3af; font-weight:400; }}
  .metric-score {{ font-size:32px; font-weight:700; margin:8px 0 6px; }}
  .of5 {{ font-size:14px; color:#9ca3af; font-weight:400; }}
  .bar {{ height:8px; background:#f0f1f3; border-radius:4px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:4px; }}
  .range {{ font-size:12px; color:#9ca3af; margin:6px 0 10px; }}
  .dist {{ display:flex; height:10px; border-radius:5px; overflow:hidden; }}
  .seg {{ height:100%; }}
  .dist-legend {{ font-size:11px; color:#b0b4ba; margin-top:6px; }}
  .grid3 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }}
  .worst-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }}
  .cid {{ font-weight:700; font-family:ui-monospace,monospace; }}
  .overall {{ font-weight:700; }}
  .q {{ font-size:13px; color:#646a73; margin-bottom:8px; }}
  .chips {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }}
  .chip {{ font-size:12px; padding:2px 8px; border-radius:10px; background:#f3f4f6; }}
  .analysis {{ font-size:13px; color:#374151; margin-bottom:8px; }}
  .human {{ font-size:12px; color:#9ca3af; border-top:1px dashed #e5e7eb; padding-top:8px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:12px; overflow:hidden; font-size:13px; }}
  th,td {{ padding:8px 10px; text-align:left; border-bottom:1px solid #f0f1f3; }}
  th {{ background:#fafbfc; color:#646a73; font-weight:600; }}
  .qcell {{ color:#646a73; }}
  .s-good {{ color:#16a34a; }} .s-ok {{ color:#65a30d; }} .s-mid {{ color:#d97706; }} .s-bad {{ color:#dc2626; }}
  .val-card {{ font-size:14px; color:#374151; }}
  .val-card li {{ margin:6px 0 6px 18px; }}
  footer {{ margin-top:36px; font-size:12px; color:#9ca3af; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>客服自动回复质量评估报告</h1>
    <div class="sub">评估对象：20 组「用户问题 + 自动回复」 · 模式：{esc(data['mode'])}（rubric {esc(data['rubric_version'])}，LLM-as-judge） · 四指标加权总分</div>
  </header>

  <div class="hero">
    <div class="card hero-main">
      <div class="big-score">{agg['overall_mean']}<small> /5</small></div>
      <div class="verdict">
        整体处于「可用但不及格」区间。忠实度 4.67 说明基本不瞎编、底线可用；
        但<b>有用性仅 2.88，为全场最短板</b>——普遍只给通用说明、不帮用户实际处理。
        建议先修复最差 case 暴露的三类系统性问题，复评达标后再扩大覆盖范围。
      </div>
    </div>
  </div>

  <h2>各指标得分与分布</h2>
  <div class="grid4">{metric_cards}</div>

  <h2>最差 3 条 case 及分析</h2>
  <div class="grid3">{worst_cards}</div>

  <h2>与人工标注的一致性验证</h2>
  <div class="card val-card">
    <ul>
      <li><b>短板判断一致</b>：人工标注 13/20 条提到「没有帮用户处理 / 把责任推给用户」；本流水线四指标中有用性均值最低（2.88）——两者独立得出同一结论。</li>
      <li><b>词法信号交叉验证</b>：有用性低分（≤2.5）的 10 条中，{esc(val['helpfulness_signal_consistency'])} 同时被「主动处理 vs 推诿」词法检测判为净推诿，judge 评分有可解释信号支撑。</li>
      <li><b>最差 case 重合</b>：总分后 5 名 {esc('、'.join(val['pipeline_bottom5']))} 中，case_01、case_20 也是人工措辞最严厉的两条。</li>
    </ul>
  </div>

  <h2>20 条全量得分（按总分升序）</h2>
  <table>
    <thead><tr><th>case</th><th>总分</th><th>忠实度</th><th>准确性</th><th>有用性</th><th>语气</th><th>用户问题</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>

  <footer>评估流水线：LLM-as-judge（rubric v1，4 指标 1-5 分锚点评分）+ 词法辅助信号交叉验证 · 完整逐条评分理由见 results.json</footer>
</div>
</body>
</html>"""

    out = ROOT / "site" / "index.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"已写出: {out}")


if __name__ == "__main__":
    build()
