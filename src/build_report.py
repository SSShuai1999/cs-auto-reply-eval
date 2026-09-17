"""从 output/results.json 生成 output/report.md（评估报告）。

用法：python3 src/build_report.py
最差 3 条的深度分析写在 ANALYSIS_NOTES 中（人工撰写，键为 case id）。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ANALYSIS_NOTES = {
    "case_20": {
        "title": "答非所问：用户说'搞不懂流程'，回复把流程原样复述一遍",
        "analysis": (
            "用户明确表达'退货流程太复杂了搞半天都不知道怎么操作'，诉求是**被带着操作**，"
            "而自动回复恰恰把用户说看不懂的同一份流程又复述了一遍——提供的是用户已声明无效的信息，"
            "有用性全场最低（1.5）。人工参考的正确做法是追问'卡在哪一步'再针对性指导。\n\n"
            "**根因**：回复生成只看'问题主题'（退货流程）而没有识别'消息类型'（抱怨/求助而非询问）。"
            "这是意图识别粒度过粗导致的答非所问，属于准确性事故（2.0）。"
        ),
        "fix": "在意图分类中增加'抱怨/求助 vs 信息咨询'的区分；对抱怨类消息强制走'追问具体卡点'策略，禁止直接复述通用流程。",
    },
    "case_11": {
        "title": "自相矛盾：先说'换货=先退货再下单'，又说'发起换货申请'",
        "analysis": (
            "同一回复内给出两条互斥的处理路径（'换货需要先退货再重新下单'与'请分别发起两件商品的换货申请'），"
            "用户无法判断该走哪条。'换货=先退再买'是模型的无据自创规则，忠实度被扣到 3.5——"
            "这是 20 条中唯一的自相矛盾 case。\n\n"
            "**根因**：多商品场景（两件衣服一大小）触发了流程拼接，模型把两套话术揉进了一条回复。"
            "另外，两件商品分别换什么尺码是处理此事的必要信息，回复没有追问。"
        ),
        "fix": "上线前对回复做'内部一致性自检'（同一回复中的流程断言是否互斥）；多商品/多对象场景强制先追问关键信息再给方案。",
    },
    "case_19": {
        "title": "无据功能断言：'加入购物车，补货时系统会自动提醒您'",
        "analysis": (
            "用户问'什么时候补货'，回复未查询具体商品，且声称'加入购物车后系统会自动提醒补货'——"
            "这是一个对系统功能的具体断言，若该功能不存在就是典型'瞎编'（忠实度 3.5，并列全场最低）。"
            "这类编造在客服场景风险极高：用户会基于不存在的功能产生预期，后续必然投诉。\n\n"
            "**根因**：模型用'听起来合理'的行业常见功能填充答案，而非基于已核实的产品能力作答。"
        ),
        "fix": "为自动回复接入'产品能力白名单'（已核实的功能/政策库），生成时只允许引用白名单内的功能断言；白名单外的一律降级为'我帮您确认'。",
    },
}


def main():
    with open(ROOT / "output" / "results.json", encoding="utf-8") as f:
        data = json.load(f)

    agg = data["aggregate"]
    cases = {c["id"]: c for c in data["cases"]}
    worst3 = data["worst3"]
    val = data["validation"]

    lines = []
    a = lines.append

    a("# 客服自动回复质量评估报告")
    a("")
    a(f"- 评估对象：`data/auto_replies.json`，20 组「用户问题 + 自动回复」")
    a(f"- 评估模式：`{data['mode']}`（rubric {data['rubric_version']}，mock 与真实 LLM API 同构）")
    a(f"- 指标与权重：" + "、".join(
        f"{pm['name']}（{pm['weight']:.0%}）" for pm in agg['per_metric'].values()))
    a("")
    a("---")
    a("")
    a("## 一、整体结论")
    a("")
    a(f"**整体均分 {agg['overall_mean']} / 5**（中位数 {agg['overall_median']}）——处于「可用但不及格」区间。")
    a("")
    a("| 指标 | 均值 | 最低 | 最高 | 权重 | 判断 |")
    a("|---|---|---|---|---|---|")
    verdict = {
        "faithfulness": "整体可信，但有 2 条硬伤（自相矛盾/无据功能断言）",
        "accuracy": "方向基本对，但有答非所问个例",
        "helpfulness": "**全场最短板**：普遍把操作责任推给用户",
        "tone": "合格但平庸，负面情绪场景安抚不足",
    }
    for k, pm in agg["per_metric"].items():
        a(f"| {pm['name']} | **{pm['mean']:.2f}** | {pm['min']} | {pm['max']} | {pm['weight']:.0%} | {verdict[k]} |")
    a("")
    a("**对业务决策的直接回答**（评估结果用于决定是否扩大自动回复覆盖范围）：")
    a("")
    a("> 当前质量**不建议直接扩大覆盖**。忠实度（4.67）说明回复基本不瞎编，底线可用；"
      "但有用性仅 2.88，最典型的问题是「只给通用说明、不帮用户实际处理」——"
      "这类回复不会引发事故，但会持续消耗用户耐心。建议先修复最差 case 暴露的三类系统性问题"
      "（见第三节），复评达标后再扩大。")
    a("")
    a("---")
    a("")
    a("## 二、各指标得分分布")
    a("")
    for k, pm in agg["per_metric"].items():
        a(f"### {pm['name']}（均值 {pm['mean']:.2f}）")
        a("")
        a("| 分数段 | case 数 |")
        a("|---|---|")
        for b, n in pm["distribution"].items():
            a(f"| {b} | {n} |")
        a("")
    a("---")
    a("")
    a("## 三、最差 3 条 case 及分析")
    a("")
    for cid in worst3:
        c = cases[cid]
        note = ANALYSIS_NOTES[cid]
        a(f"### {cid}（总分 {c['overall']}）—— {note['title']}")
        a("")
        a(f"- **用户问题**：{c['user_question']}")
        a(f"- **自动回复**：{c['auto_reply']}")
        a(f"- **分项得分**：忠实度 {c['scores']['faithfulness']['score']} / "
          f"准确性 {c['scores']['accuracy']['score']} / "
          f"有用性 {c['scores']['helpfulness']['score']} / "
          f"语气 {c['scores']['tone']['score']}")
        a(f"- **人工标注**：{c['human_note']}")
        a("")
        a(note["analysis"])
        a("")
        a(f"**改进建议**：{note['fix']}")
        a("")
    a("三条最差 case 恰好暴露三类不同性质的问题：**意图识别过粗**（case_20）、"
      "**生成一致性缺失**（case_11）、**无据断言**（case_19）。都是系统性问题，修复收益会外溢到全量回复。")
    a("")
    a("---")
    a("")
    a("## 四、与人工标注的一致性验证")
    a("")
    a("用 `human_ref.json` 的 annotator_notes 验证评估方法是否靠谱：")
    a("")
    a(f"1. **短板判断一致**：人工标注 13/20 条提到「没有帮用户处理 / 把责任推给用户」类问题；"
      f"本流水线四指标中有用性均值最低（2.88），两者独立得出同一结论——**缺乏主动处理是该自动回复系统的最大短板**。")
    a(f"2. **词法信号交叉验证**：有用性低分（≤2.5）的 10 条 case 中，{val['helpfulness_signal_consistency'].split('/')[0]} 条"
      f"同时被「主动处理 vs 推诿」词法检测判定为净推诿（一致率 {val['helpfulness_signal_consistency']}），"
      "说明 judge 的有用性评分有可解释的信号支撑，不是拍脑袋。")
    a(f"3. **最差 case 重合**：流水线总分后 5 名 {val['pipeline_bottom5']} 中，"
      f"case_01（推卸责任）与 case_20（答非所问）也是人工措辞最严厉的两条。")
    a("")
    a("---")
    a("")
    a("## 五、20 条全量得分")
    a("")
    a("| case | 总分 | 忠实度 | 准确性 | 有用性 | 语气 | 用户问题 |")
    a("|---|---|---|---|---|---|---|")
    for c in sorted(data["cases"], key=lambda x: x["overall"]):
        a(f"| {c['id']} | **{c['overall']}** | {c['scores']['faithfulness']['score']} | "
          f"{c['scores']['accuracy']['score']} | {c['scores']['helpfulness']['score']} | "
          f"{c['scores']['tone']['score']} | {c['user_question'][:18]}… |")
    a("")
    a(f"> 完整逐条理由见 `output/results.json`（每条含四指标评分理由、词法信号、人工标注对照）。")

    out = ROOT / "output" / "report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已写出: {out}")


if __name__ == "__main__":
    main()
