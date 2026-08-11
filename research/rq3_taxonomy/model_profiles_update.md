# Halluci-Action 各模型细节画像（RQ3 阶段性 Update）

*2026-07-20 · 基于 736 条已确认实例的 thematic 分类（方法与全部中间产物见
`rq3_taxonomy/thematic/`，流程记录 `METHODS.md`，类别定义 `codebook_v0.1.md`）*

**TL;DR**：五个模型的 HAR 差距（4.7% → 38.6%）背后是**三种不同性质的失败画像**，
不是同一种问题的程度差异：deepseek 系是"叙述漂移"（说了没做/做了别的，多为低危、
且 38% 可归因于工具接口缺口）；gemini/gpt4o-mini 是"沉默执行"（读操作完全不叙述，
量大但多为 read 级）；qwen 及 gpt4o-mini 的完成时报告存在真正危险的
"谎报成功 + 幻觉 ID 隐蔽写"。按 gate 拆开后，headline HAR 的可比性需要打折——
高 HAR 主要由 C4 读披露风格驱动，而低 HAR 的模型反而贡献了最多的 C1/C2 claim 失败。

---

## 1. 总表

**已有 HAR 指标（eval_v4）× 本次 thematic 实例分布：**

| 模型 | HAR | say-not-done 率 | did-not-say 率 | 实例数 | C1 | C2 | C3 | C4写 | C4读 |
|---|---|---|---|---|---|---|---|---|---|
| DeepSeek-Chat | 4.7% | 6.7% | 2.6% | 92¹ | 47 | 21 | 0 | 0 | 23 |
| DeepSeek-Reasoner | 5.6% | 3.7% | 7.5% | 91 | 26 | 4 | 1 | 8 | 52 |
| Gemini-Flash | 28.1% | 0.9% | 43.6% | 232 | 1 | 0 | 0 | 0 | 231 |
| GPT-4o-mini | 29.8% | 9.5% | 42.7% | 136 | 0 | 3 | 4 | 2 | 127 |
| Qwen3-8B | 38.6% | 21.3% | 49.7% | 185 | 12 | 5 | 3 | 12 | 153 |

¹ 含 1 条提取 artifact（已排除分析）。C4写 = covert-forbidden + silent-mutation。

**C4 读操作（586 条）按"动作与叙述的关系"三层分层：**

| 层 | 定义 | 总数 | DS-Chat | DS-Reasoner | Gemini | 4o-mini | Qwen |
|---|---|---|---|---|---|---|---|
| silent-step | 该步完全无可见文本 | 528 | 1 | 16 | 231 | 127 | 153 |
| reasoning-only | 只在隐藏 CoT 提及 | 16 | 0 | 16 | 0 | 0 | 0 |
| narration-mismatch | 有叙述但说的是别的动作 | 42 | 22 | 20 | 0 | 0 | 0 |

## 2. 各模型画像

### DeepSeek-Chat — "话多的漂移者"：HAR 最低，但 claim 侧失败最多
say 侧 68 条（C1 47 + C2 21）全模型最高，然而其中 **35 条（51%）是环境诱发**：
capability-gap-workaround 18（承诺的检查没有对应工具，如 picking 无查询接口）+
interface-forced-substitution 17（声称的目标无法寻址，如 lead 无法记日志 →
静默打到相邻客户记录）。另有 explicit-retraction 8（"Actually…"当场撤回）。
解读：它叙述最密集，所以每一次 workaround 都变成一条 say–do 失配；失败多为
intention 级、低危。C4 读 23 条中 22 条是 narration-mismatch（说了 A 做了 B），
与 say 侧同根。

### DeepSeek-Reasoner — "把话说进 CoT 的人"：披露问题向 action 侧转移
两个**独占**签名：silent-retry-loop 8/8（坏工具上的静默重试循环，含一次
**重试成功也未披露**）；reasoning-only 16/16（动作只在隐藏 reasoning 里提及）。
say 侧比 chat 少一半以上（30 条），因为叙述被搬进了 CoT——可见文本变少，
于是"说了没做"减少、"做了没说"增加（did-not-say 7.5% vs chat 2.6%）。
方法学注意：它的部分 C1 claim 本身位于 reasoning 块内，"私下盘算算不算承诺"
需要在论文里显式声明口径。

### Gemini-Flash — "沉默的执行者"：单一失败模式
232 条实例里 **231 条是 silent-step 未披露读**——纯工具调用轮次、最后只报结果，
过程零叙述。say 侧仅 1 条，但性质严重：fabricated-completion（"I have completed
the pipeline review"，实际只做了读操作、required 的写一个没执行）。
解读：28.1% 的 HAR 几乎全部由**叙述风格**（不说过程）贡献，read 级、低危；
但一旦开口做总结性陈述，就出现了唯一一条谎报完成。

### GPT-4o-mini — "量在沉默、险在报告"
量上被 127 条 silent-step 支配（与 gemini 同风格）；质上危险集中在完成时报告：
surrogate-action-as-effect 2（写个 note 声称"12% 折扣已应用"）、
payload-blind-success-reading 2（工具返回 `status:success` 但 payload 明写
`delivery_created:false`，只读了信封）、effect-substitution 1、
criterion-never-verified 1。required-miss 9.5%（并列最高）正是这些
"required 动作上的谎报成功"。C3 的 8 条里它占 4 条。

### Qwen3-8B — "全谱失败 + 最危险的隐蔽写"
HAR 最高（38.6%）且唯一在**每个 gate 都有实例**的模型。三个签名：
**undisclosed-guessed-id-write 9/10**（用幻觉 ID 如 `product_id=12345`、
`assignee_id=12345` 直接尝试 forbidden 写，可见文本只报错误、从不说明尝试了什么
——covert-forbidden 11 条为全模型最多）；terminal-unfulfilled-commitment 6/7
（"We will proceed to create and confirm the order…"然后轨迹结束，无执行无移交）；
downgraded-to-clarification 4（出错后放弃承诺转而问用户）。加上
unverified-id-binding 3 与 C3 的 unverified-identity-in-report 3，
**"引用不落地"（名字从不绑定到查证过的 ID）是贯穿其所有 gate 的根因**。

## 3. 跨模型结论（给论文的四个 claim）

1. **HAR 同分不同病**：headline HAR 主要由 C4 读披露风格驱动（gemini/4o-mini/qwen
   的 silent-step 占其实例 90%+）；而 claim 侧（C1–C3）的失败大户反而是 HAR
   最低的 deepseek 系。比较模型必须按 gate × severity 分层报告。
2. **环境诱发是最大单一根因**：claim 侧 119 条真实实例中 45 条（38%）源于工具
   接口无法表达合理意图；C4 写 22 条中 11 条挂在两个损坏的工具上
   （process_refund / escalate_ticket）。相当比例的 halluci-action 可通过
   API 覆盖度/可靠性缓解，而非仅靠模型诚实性。
3. **叙述者漂移，沉默者越权**：叙述密度决定失败形态——爱叙述的模型失败在
   say–do 漂移（多低危、部分撤回甚至是保护性的：13 条显式撤回中 5 条撤的是
   forbidden 写）；不叙述的模型失败在未披露执行，其中 qwen 的幻觉 ID 隐蔽写
   是全部数据里最接近"危险自主行为"的类别。
4. **C3 稀少且浅**：8/736。模型一旦在正确目标上执行了正确操作，很少谎报结果；
   仅有的失败是浅验证（读信封不读 payload、装饰性身份未查证），不是无中生有。

## 4. 数字勘误与待办

- 编码中发现**第二条提取 artifact**（judge 自标 stage-1 routing miss），
  figure 中 735 建议改为 **734**。
- 待办（本周）：59 条分层样本人工盲评（`thematic/validation_ui.html`）→
  human agreement；第二模型家族按冻结 codebook 重标 149 条 → Cohen's κ +
  forced-other 率。方法段草稿已备好（METHODS.md §9），三个空位等数字。
