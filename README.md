# 客服自动回复质量评估流水线

> 测评任务 0109 · 把业务方的模糊要求（"准确、有用、语气好、不能瞎编"）变成一套可运行的评估方案，
> 对 20 条自动回复逐条评分，输出整体得分、指标分布与最差 case 分析。

**线上报告页**：https://cs-reply-eval-report.app.workbuddy.host/
**GitHub 仓库**：https://github.com/SSShuai1999/cs-auto-reply-eval

## 快速开始

```bash
# 无第三方依赖，Python 3.9+ 即可
python3 src/evaluate.py --mode mock      # 跑评估流水线（mock 模式）
python3 src/build_report.py              # 生成 output/report.md
python3 src/build_site.py                # 生成 site/index.html（可视化报告页）

# 真实 LLM API 模式（OpenAI 兼容接口）
export EVAL_LLM_BASE_URL=https://api.openai.com/v1
export EVAL_LLM_API_KEY=sk-xxx
export EVAL_LLM_MODEL=gpt-4o-mini
python3 src/evaluate.py --mode real
```

## 目录结构

```
eval-pipeline/
├── data/                  # 输入：auto_replies.json / human_ref.json / eval_criteria.md
├── scores/mock_scores.json # mock 模式的裁判输出：LLM 按 rubric v1 逐条评分（含理由）
├── src/
│   ├── judge.py           # 指标 rubric 定义 + LLM-as-judge（Real/Mock 两种模式同构）
│   ├── evaluate.py        # 流水线主程序：评分→辅助信号→聚合→人工一致性验证
│   ├── build_report.py    # 生成评估报告 report.md
│   └── build_site.py      # 生成可视化报告页 site/index.html
├── output/                # results.json（全量结构化结果）+ report.md（评估报告）
├── site/index.html        # 可视化报告页（自包含，无外部依赖，可直接部署）
└── screenshots/           # 运行结果截图
```

## 一、指标定义及理由

业务方原话是四个词："准确、有用、语气好、不能瞎编"。一对一映射为四个可自动评估指标，
每个指标 1-5 分（0.5 步进），带评分锚点（完整锚点见 `src/judge.py` 的 `RUBRICS`）：

| 指标 | 对应业务词 | 量化方式 | 权重 | 优先级 |
|---|---|---|---|---|
| **忠实度** | 不能瞎编 | judge 抽取回复中的事实性断言（数字/政策/时效/系统功能/承诺），逐条核对有无依据，按无据断言的数量与风险定分 | 35% | 1 |
| **准确性** | 准确 | judge 判断意图识别是否正确、回答是否切题、信息是否正确 | 30% | 2 |
| **有用性** | 有用 | judge 评估"主动处理动作"是否发生（帮查/帮办/追问关键信息），并用"主动处理 vs 推诿"词法检测交叉验证 | 20% | 3 |
| **语气** | 语气好 | judge 先识别用户情绪（焦急/愤怒/恐惧/中性），再评估共情浓度与场景适配度 | 15% | 4 |

**优先级排序理由**：客服场景下"瞎编"是信任崩塌级事故（如 case_19 虚构系统功能），
且直接决定"能否扩大自动回复覆盖范围"这一业务决策，是一票否决型指标，权重最高；
答错问题是第二严重的事故；有用性决定体验差异、是质量分层指标而非事故指标；
语气影响体感但很少构成事故，也是四项中最容易通过 prompt 调优快速修复的。

**总分 = Σ(指标分 × 权重)**，5 分制。

## 二、评估方法

```
auto_replies.json ──► LLM-as-judge（rubric v1 四指标评分 + 理由）
                           │
human_ref.json ────────────┤（参考回复供 judge 核对事实依据）
                           ▼
              词法辅助信号（主动处理/推诿标记，交叉验证有用性）
                           ▼
              聚合：整体得分 / 指标分布 / 最差 3 条
                           ▼
              人工标注一致性验证（annotator_notes 对照）
                           ▼
        output/results.json + report.md + site/index.html
```

- **LLM-as-judge**：每个 case 用同一 rubric prompt 评四个指标，强制 JSON 结构化输出（分数 + 一句话理由），
  temperature=0。`RealJudge` 调真实 API（stdlib 实现，无 SDK 依赖）；`MockJudge` 读取离线评分文件——
  mock 数据同样由 LLM 按 rubric 逐条生成，两种模式产出同构数据，可随时切换。
- **可解释性兜底**：LLM 评分可能漂移，因此对"有用性"增加了一个确定性的词法检测
  （`我帮您/帮您查/请提供` 等主动标记 vs `您可以/建议您/请联系/查看详情页` 等推诿标记），
  用来交叉验证 judge 评分——本次 10 条有用性低分 case 中 8 条同时被判为净推诿（8/10 一致）。
- **人工一致性验证**：用 human_ref.json 的 annotator_notes 做三层对照——短板判断是否一致、
  最差 case 是否重合、低分是否有词法信号支撑（详见 report.md 第四节）。

**核心结论**：整体均分 **3.92/5**。忠实度 4.67（基本不瞎编）但有用性仅 2.88（全场最短板）——
普遍"只给通用说明、不帮用户实际处理"。当前质量不建议直接扩大覆盖范围，
建议先修复最差 case 暴露的三类系统性问题（意图识别过粗 / 生成一致性缺失 / 无据断言），复评后再扩大。

## 三、局限性讨论

**哪些 case 可能评不准：**

1. **忠实度无法核实"事实"，只能识别"风险"**。judge 没有真实的商品库、订单系统和政策库，
   case_19 的"购物车补货提醒"功能是否存在，judge 只能标记为"无据断言风险"而无法证伪。
   → 改进：接入已核实的政策/功能白名单做断言比对（RAG 校验），把忠实度从"像不像编的"升级为"与事实库核对"。
2. **有用性含价值观判断，会随 judge 模型/prompt 漂移**。"给规则让用户自助"和"主动帮用户处理"哪种更好，
   不同业务有不同答案（人工标注对 case_09/10 就认为"给规则可接受"）。
   → 改进：把业务的"主动性标准"写成更细的锚点；多 judge 投票或两次采样取均值降方差。
3. **建议类/模糊类 case 主观性最强**（case_14 提建议、case_16 "那两款哪个好"），没有标准答案，
   分数波动最大。
4. **样本量小**（20 条），单条 0.5 分的波动就会改变最差 3 名的排位，分布结论（如"有用性是短板"）
   方向可信，但具体数值不能外推到全量回复。
   → 改进：流水线已支持批量跑，扩大到数百条后结论才稳。
5. **验证方式本身的局限**：本次一致性验证靠 annotator_notes 的关键词命中（13/20 判负，区分度不足）。
   更严谨的做法是请标注员对每条做 1-5 打分，再算流水线分数与人工分数的相关系数（如 Spearman），
   并据此校准 rubric——受限于标注材料形式，本次只做定性 + 重合度验证。
6. **自相矛盾类问题不该靠 LLM 评**。case_11 的流程互斥是确定性问题，
   → 改进：把"同一回复内的流程断言互斥检测"做成独立的规则检查器，不消耗 LLM 也不受漂移影响。

## 四、AI 工具使用情况

本任务全程使用 AI Agent 工具（WorkBuddy）完成，这也是测评鼓励的开发方式：

| 环节 | AI 承担 | 人工承担 |
|---|---|---|
| 需求拆解 | 把"准确/有用/语气好/不瞎编"映射为四指标 + 权重/优先级设计 | 确认优先级排序的业务理由 |
| 逐条评分 | 按 rubric v1 对 20 条 case 逐条打分并写理由（即 mock_scores.json） | 抽查评分与人工标注的一致性 |
| 代码 | judge.py / evaluate.py / build_report.py / build_site.py 全部生成 | 运行验证、修正生成逻辑 |
| 报告 | report.md / index.html / README 起草 | 核对结论与数据一致 |

- 开发过程截图：本 Agent 会话即完整开发过程（需求→评分→代码→运行→报告），可直接截取。
- 运行结果截图：见 `screenshots/`（报告页与终端输出）。
- 线上报告页：见 README 顶部/提交表单中填写的部署地址。
