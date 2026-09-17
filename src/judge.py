"""LLM-as-judge 评估器：指标 rubric 定义 + 真实/ mock 两种评判模式。

- RealJudge：调用 OpenAI 兼容接口（仅需环境变量，stdlib 实现，无第三方依赖）
- MockJudge：读取 scores/mock_scores.json（由 LLM 按同一 rubric 离线生成）

两种模式产出同构数据：{metric: {score: float(1-5, 0.5步进), reason: str}}
"""

import json
import os
import urllib.request

# ---------------------------------------------------------------------------
# 指标定义（rubric v1）
# 业务方原话：回复要"准确"、"有用"、"语气好"、"不能瞎编"
# 四个词一对一映射为四个可自动评估指标，每个指标 1-5 分（0.5 步进），锚点如下。
# ---------------------------------------------------------------------------

RUBRICS = {
    "faithfulness": {
        "name": "忠实度（不瞎编）",
        "business_word": "不能瞎编",
        "definition": "回复中的具体断言（数字、政策、时效、系统功能、承诺）是否都有据可依。",
        "quantification": "LLM judge 抽取回复中的事实性断言，逐条核对是否有依据（参考回复/通用业务常识），按无据断言的数量与风险定分。",
        "anchors": {
            5: "零编造：所有具体断言均有依据或为明显合理的通用建议",
            4: "有低风险无据断言（如善意的模糊承诺），不影响用户决策",
            3: "存在可能影响用户决策的无据断言（如虚构系统功能、自创规则、自相矛盾）",
            2: "多处无据断言或一处高风险编造（如虚构赔偿金额、错误政策）",
            1: "核心答案本身就是编造的",
        },
        "weight": 0.35,
        "priority": 1,
        "priority_reason": "客服场景下编造是信任崩塌级事故，且直接决定'能否扩大自动回复覆盖范围'这一业务决策，是一票否决型指标。",
    },
    "accuracy": {
        "name": "准确性",
        "business_word": "准确",
        "definition": "是否正确识别用户意图并给出方向正确的回答（不答非所问、信息本身正确）。",
        "quantification": "LLM judge 对照用户问题判断：意图识别是否正确、回答是否切题、信息是否正确，按 rubric 锚点定分。",
        "anchors": {
            5: "意图识别正确，回答切题且信息正确完整",
            4: "方向正确但有偏差（如只答了通用规则未答具体对象、重点排序失当）",
            3: "部分答非所问，或关键信息有误但方向可救",
            2: "明显答非所问，回答的不是用户问的问题",
            1: "完全理解错意图或给出错误指引",
        },
        "weight": 0.30,
        "priority": 2,
        "priority_reason": "在不编造的前提下，答错问题是第二严重的事故，直接决定回复是否有效。",
    },
    "helpfulness": {
        "name": "有用性",
        "business_word": "有用",
        "definition": "是否给出可执行的下一步、是否主动帮用户解决问题（而非把操作/判断责任推给用户），多意图是否全覆盖。",
        "quantification": "LLM judge 评估'主动处理动作'是否发生（帮查/帮办/追问关键信息），结合辅助信号——主动处理标记与推诿标记的词法检测交叉验证。",
        "anchors": {
            5: "直接替用户完成核心动作或给出立即可执行的完整方案",
            4: "方案完整可执行，但缺一步确认/追问",
            3: "给了方向但关键动作仍需用户自助完成",
            2: "核心诉求未解决，主要把责任推给用户自己查/自己试",
            1: "没有提供任何有效帮助，甚至重复用户已表示无效的信息",
        },
        "weight": 0.20,
        "priority": 3,
        "priority_reason": "在答对的前提下，'有用'决定体验差异，是质量分层指标而非事故指标。",
    },
    "tone": {
        "name": "语气",
        "business_word": "语气好",
        "definition": "是否礼貌、有共情（尤其负面情绪场景）、不推诿、不混入对用户无意义的内部话术。",
        "quantification": "LLM judge 先识别用户情绪（焦急/愤怒/恐惧/中性），再评估回复的共情浓度与场景适配度。",
        "anchors": {
            5: "情绪识别准确，共情充分，表达自然",
            4: "有道歉/感谢且场景适配，个别话术瑕疵",
            3: "礼貌但流程化，负面情绪场景无安抚",
            2: "冷漠、推诿或明显模板感",
            1: "冒犯、指责用户或激化矛盾",
        },
        "weight": 0.15,
        "priority": 4,
        "priority_reason": "语气影响体感但很少构成事故，且是四项中最容易通过 prompt 调优快速修复的。",
    },
}

JUDGE_OUTPUT_SCHEMA = """{
  "faithfulness": {"score": <1-5, 0.5步进>, "reason": "<一句话中文理由>"},
  "accuracy":     {"score": <1-5, 0.5步进>, "reason": "<一句话中文理由>"},
  "helpfulness":  {"score": <1-5, 0.5步进>, "reason": "<一句话中文理由>"},
  "tone":         {"score": <1-5, 0.5步进>, "reason": "<一句话中文理由>"}
}"""


def build_prompt(case: dict, reference: str = "") -> str:
    """构造 judge prompt（真实模式使用；mock 模式的离线评分也用同一 prompt 结构）。"""
    rubric_text = "\n".join(
        f"### {m['name']}（对应业务要求：{m['business_word']}）\n"
        f"定义：{m['definition']}\n"
        + "\n".join(f"  {k}分：{v}" for k, v in m["anchors"].items())
        for m in RUBRICS.values()
    )
    ref_block = f"\n【人工参考回复】（仅供核对事实依据，不作为语气/主动性的唯一标准）\n{reference}\n" if reference else ""
    return f"""你是客服自动回复质量评估专家。请按以下 rubric 对一条自动回复评分。

{rubric_text}

【用户问题】
{case["user_question"]}

【自动回复】
{case["auto_reply"]}
{ref_block}
只输出 JSON，不要输出任何其他内容。输出格式：
{JUDGE_OUTPUT_SCHEMA}"""


class MockJudge:
    """mock 模式：读取离线评分文件（由 LLM 按同一 rubric 预先生成）。"""

    def __init__(self, scores_path: str):
        with open(scores_path, encoding="utf-8") as f:
            data = json.load(f)
        self._scores = {c["id"]: c["scores"] for c in data["cases"]}

    def score(self, case: dict, reference: str = "") -> dict:
        if case["id"] not in self._scores:
            raise KeyError(f"mock 评分缺失: {case['id']}")
        return self._scores[case["id"]]


class RealJudge:
    """真实模式：调用 OpenAI 兼容的 chat completions 接口（stdlib 实现，无第三方依赖）。

    环境变量：
      EVAL_LLM_BASE_URL  如 https://api.openai.com/v1
      EVAL_LLM_API_KEY
      EVAL_LLM_MODEL     如 gpt-4o-mini
    """

    def __init__(self):
        self.base_url = os.environ["EVAL_LLM_BASE_URL"].rstrip("/")
        self.api_key = os.environ["EVAL_LLM_API_KEY"]
        self.model = os.environ["EVAL_LLM_MODEL"]

    def score(self, case: dict, reference: str = "") -> dict:
        prompt = build_prompt(case, reference)
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)


def get_judge(mode: str, scores_path: str = "scores/mock_scores.json"):
    if mode == "mock":
        return MockJudge(scores_path)
    if mode == "real":
        return RealJudge()
    raise ValueError(f"未知模式: {mode}（可选 mock / real）")
