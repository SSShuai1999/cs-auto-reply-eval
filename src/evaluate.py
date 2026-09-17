"""评估流水线主程序。

用法：
    python3 src/evaluate.py [--mode mock|real]

流程：
    1. 加载 data/auto_replies.json（20 条用户问题+自动回复）
    2. 逐条调用 judge（mock / real）按 rubric v1 四指标评分
    3. 计算辅助信号：主动处理 vs 推诿的词法检测（与 judge 有用性评分交叉验证）
    4. 聚合：整体得分、各指标均值与分布、最差 3 条
    5. 与 data/human_ref.json 人工标注做一致性验证
    6. 输出 output/results.json + output/report.md
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from judge import RUBRICS, get_judge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# 辅助信号词表（可解释、可审计的词法检测，仅用于交叉验证，不计入总分）
PROACTIVE_MARKERS = ["我帮您", "帮您查", "帮您处理", "帮您操作", "我来", "请提供", "请告诉我"]
DEFLECTION_MARKERS = ["您可以", "建议您", "请查看", "请联系", "自行", "耐心等待", "查看商品详情页"]

# 人工标注中明确表达负面评价的措辞（用于一致性验证）
NEGATIVE_NOTE_PATTERNS = [
    "推卸", "推给", "没有体现", "没有帮", "答非所问", "正确但没用",
    "操作负担", "力度不够", "安抚不够", "把判断责任", "让用户自己", "把用户推走",
]


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def lexical_signals(reply: str) -> dict:
    """主动处理 / 推诿标记计数（辅助信号）。"""
    proactive = [m for m in PROACTIVE_MARKERS if m in reply]
    deflection = [m for m in DEFLECTION_MARKERS if m in reply]
    return {
        "proactive_hits": proactive,
        "deflection_hits": deflection,
        "net_proactive": len(proactive) - len(deflection),
    }


def bucket(score: float) -> str:
    if score < 2:
        return "[1,2) 差"
    if score < 3:
        return "[2,3) 较差"
    if score < 4:
        return "[3,4) 中等"
    if score < 4.5:
        return "[4,4.5) 良好"
    return "[4.5,5] 优秀"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="mock", choices=["mock", "real"])
    args = parser.parse_args()

    cases = load_json(ROOT / "data" / "auto_replies.json")
    human_refs = {r["id"]: r for r in load_json(ROOT / "data" / "human_ref.json")}
    judge = get_judge(args.mode, str(ROOT / "scores" / "mock_scores.json"))

    weights = {k: v["weight"] for k, v in RUBRICS.items()}

    results = []
    for case in cases:
        ref = human_refs.get(case["id"], {})
        scores = judge.score(case, ref.get("human_reference", ""))
        metric_scores = {m: float(s["score"]) for m, s in scores.items()}
        overall = round(sum(metric_scores[m] * weights[m] for m in weights), 2)
        results.append({
            "id": case["id"],
            "user_question": case["user_question"],
            "auto_reply": case["auto_reply"],
            "scores": scores,
            "overall": overall,
            "signals": lexical_signals(case["auto_reply"]),
            "human_note": ref.get("annotator_notes", ""),
            "human_reference": ref.get("human_reference", ""),
        })

    # ---- 聚合 ----
    metrics = list(RUBRICS.keys())
    agg = {
        "overall_mean": round(statistics.mean(r["overall"] for r in results), 2),
        "overall_median": round(statistics.median(r["overall"] for r in results), 2),
        "per_metric": {},
    }
    for m in metrics:
        vals = [r["scores"][m]["score"] for r in results]
        dist = {}
        for v in vals:
            dist[bucket(v)] = dist.get(bucket(v), 0) + 1
        agg["per_metric"][m] = {
            "name": RUBRICS[m]["name"],
            "weight": weights[m],
            "mean": round(statistics.mean(vals), 2),
            "min": min(vals),
            "max": max(vals),
            "distribution": dict(sorted(dist.items())),
        }

    worst3 = sorted(results, key=lambda r: r["overall"])[:3]
    best3 = sorted(results, key=lambda r: r["overall"], reverse=True)[:3]

    # ---- 与人工标注的一致性验证 ----
    # 方法：人工 annotator_notes 中含明确负面措辞的 case 视为"人工判负"，
    # 与本流水线总分后 5 名对比重合度；同时词法辅助信号与有用性评分做相关性抽查。
    human_negative = {
        r["id"] for r in results
        if any(p in r["human_note"] for p in NEGATIVE_NOTE_PATTERNS)
    }
    bottom5 = {r["id"] for r in sorted(results, key=lambda r: r["overall"])[:5]}
    overlap = sorted(human_negative & bottom5)
    # 有用性低分（<=2.5）case 与词法"推诿>主动"信号的一致率
    low_help = [r for r in results if r["scores"]["helpfulness"]["score"] <= 2.5]
    low_help_with_deflection = [r for r in low_help if r["signals"]["net_proactive"] < 0]
    validation = {
        "human_negative_cases": sorted(human_negative),
        "pipeline_bottom5": sorted(bottom5),
        "overlap": overlap,
        "overlap_ratio": f"{len(overlap)}/5",
        "low_helpfulness_cases": [r["id"] for r in low_help],
        "low_help_with_net_deflection": [r["id"] for r in low_help_with_deflection],
        "helpfulness_signal_consistency": f"{len(low_help_with_deflection)}/{len(low_help)}",
    }

    output = {
        "mode": args.mode,
        "rubric_version": "v1",
        "weights": weights,
        "aggregate": agg,
        "worst3": [r["id"] for r in worst3],
        "best3": [r["id"] for r in best3],
        "validation": validation,
        "cases": results,
    }
    out_path = ROOT / "output" / "results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"模式: {args.mode} | case 数: {len(results)}")
    print(f"整体均分: {agg['overall_mean']} / 5（中位 {agg['overall_median']}）")
    for m in metrics:
        pm = agg["per_metric"][m]
        print(f"  {pm['name']:<12} 均值 {pm['mean']:.2f}  区间 [{pm['min']}, {pm['max']}]  权重 {weights[m]}")
    print(f"最差 3 条: {[r['id'] for r in worst3]} -> {[r['overall'] for r in worst3]}")
    print(f"最好 3 条: {[r['id'] for r in best3]} -> {[r['overall'] for r in best3]}")
    print(f"人工判负 case: {sorted(human_negative)}")
    print(f"流水线后 5 名与人工判负重合: {overlap}（{validation['overlap_ratio']}）")
    print(f"已写出: {out_path}")


if __name__ == "__main__":
    main()
