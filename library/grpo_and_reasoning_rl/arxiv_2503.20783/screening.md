# Understanding R1-Zero-Like Training（arXiv:2503.20783v2）有界初筛

## 0. 最小结论与证据边界

- 状态：`reading`，P0；当前只筛查 GRPO 偏置与 Dr. GRPO 修正，不声称完整读完论文的 base-model/Aha-moment 部分。
- 一句话结论：论文指出 DeepSeekMath GRPO Eq.3 的“每序列 token mean”与“每题 reward std”会把本来无偏的同题中心化 return 重加权；Dr. GRPO 去掉两者，使目标回到以固定生成上限缩放、同题 baseline 的 Monte Carlo policy gradient。论文的三 seed 与拆项消融支持它**减少**错误回答变长并提高 token efficiency，但现有证据不足以证明对任意 reward、长程 Agent 或不同模型均“无偏且更优”。
- 已检查：官方 v2 PDF 摘要、Figure 1、§3.1-3.2、Eq.1-3、Figure 4-5、Appendix A-C、G。未检查：全文其余主张、COLM proceedings 页面、代码 commit/license/weights/data、独立复现。

## 1. 两个偏置与修正的机制

GRPO 对同题 `G` 个回答先做 `A_i=(R_i-mean(R))/std(R)`，再对每条回答按 `1/|o_i|` 聚合 token surrogate。于是相对于未标准化的 `A_tilde_i=R_i-mean(R)`，每个 token 的有效权重多了 `1/(std(R)*|o_i|)`（PDF §3.1, Eq.3, Figure 4, pp.5-6）。

- **回答级长度偏置**：正 advantage 的短正确回答被更强强化；负 advantage 的长错误回答因除以更大的长度而少受惩罚。因此“错误回答越来越长”可能是 reduction 的优化产物，而不能自动解释为更深推理。
- **题目级难度偏置**：每题单独除以 reward std，使低 std 的题得到更大缩放。对二元 reward，这通常对应几乎全对/全错的组；但全同组的中心化分子为 0，仍没有梯度，因此论文所谓 easy/hard 高权重严格说只适用于“接近全同但仍混有异类样本”的组。
- **Dr. GRPO 修正**：删除 `std(R)`；把可变 `|o_i|` 分母替换为全局固定 `MAX_TOKENS`。常数只整体缩放梯度，可吸收到学习率，不再根据题或回答长度改变相对权重（§3.2, Listing 1；Appendix A Eq.5-6）。论文还证明 centered group baseline 与 RLOO advantage 仅差常数 `G/(G-1)`。

## 2. 最小 Loss Design Card

| 项目 | 核验结果 |
|---|---|
| 真实目标 | 提高 rule verifier 下的期望数学正确率，同时避免无奖励收益的 token 膨胀。 |
| 代理目标 | token 级 PPO clipped surrogate；序列 outcome return 减同题组均值，不除组 std；masked token sum 除固定生成预算。 |
| 粒度 | reward/centered baseline 按 sequence/group；ratio 与 clip 按 token；固定常数后汇总到 batch。 |
| 梯度 | 只传给 current policy；同题均值作为 action-independent baseline，在期望上不改变 policy-gradient 方向。 |
| 假设 | prompt sampling 固定；组样本来自 old policy；outcome verifier 可靠；固定生成预算不随样本变化。论文实验设 `G=8`、一次 proximal epoch、clip 0.2、KL=0。 |
| 删除项的效果 | 删除长度分母使长错误 token 不再被系统性减罚；删除 per-question std 避免按当前组 reward dispersion 给题目重权。 |
| 数值/reduction | 作者代码建议 `sum(masked_token_loss)/MAX_TOKENS`；这不是 sequence mean 或 batch token mean。若生成预算 curriculum 改变常数，跨阶段梯度尺度仍会变。 |
| 目标-指标缺口 | 无偏地估计选定 reward 的梯度，不等于 reward 无偏、答案验证无漏洞、推理更短一定更好，或最终 benchmark 必然更高。 |

## 3. 证据强度（待继续核验）

- **[论文实验]** Figure 5 在 Qwen2.5-1.5B、MATH train、binary Math-Verify reward 上比较 GRPO/Dr. GRPO；两者 reward/正确回答长度均增长，但 Dr. GRPO 的错误回答明显更短，平均 benchmark 曲线更高。图为曲线，正文未给最终点的精确数字。
- **[拆项消融]** Appendix C Figure 8 分开移除 length/std normalization：回答长度主要由 length 项驱动；四种变体中 vanilla GRPO 的 reward/平均评测最差。这里支持两项都有害，但只在单一 1.5B 设置。
- **[重复性]** Appendix C Figure 9 报告三次独立 run 的均值与标准差，Dr. GRPO 的平均输出更短、平均 benchmark 更高；作者称 statistically significant，但当前所见没有检验类型、p 值或置信区间。
- **[外推边界]** Table 6 的关键配置为 8xA100、约一天、max response 3000、temperature 1、`G=8`、AdamW `1e-6`、一次 update、KL=0、clip 0.2。论文主实验是可验证数学 outcome reward，未覆盖 learned RM、process reward 或长程 Agent。

## 4. Design-Defect-Fix（最小版）

| DeepSeekMath 设计 | 缺陷类型与证据 | Dr. GRPO 修复 | 状态 / 新代价 |
|---|---|---|---|
| 每序列 token mean | intrinsic：优化单位随实际长度变化；Figure 5/8 显示错误回答膨胀 | token sum 除固定最大长度 | **减少**：短回答每 token 梯度不再被放大；但梯度尺度依赖固定预算，padding/截断和预算 curriculum 仍需实现审计。 |
| 每题 group std normalization | intrinsic：不同题按一次 rollout 的 dispersion 被重权；Figure 8 支持删除有益 | 只做组内中心化 | 在本文环境中**减少** difficulty reweighting；代价是 reward scale 不再归一，非二元/跨题异尺度 reward 时可能增大方差或让高尺度题主导。 |
| 去 critic 的 group baseline | 节省 value model，但 baseline 含当前样本且全同组零信号 | centered reward；证明与 RLOO 差常数 | critic 成本仍被移除；零方差组无学习信号未修复，rollout 成本仍为 `G=8`。 |

## 5. Heavy Knowledge / 重知识（初版）

1. “平均 loss”不是无害实现细节：当分母是样本自己的生成长度，它改变不同轨迹的相对优化权重，而不只改变整体学习率。
2. Dr. GRPO 的 fixed denominator 与 ms-swift 的 `loss_type=dr_grpo` 应在后续代码单元核验；不能仅凭同名断言 mask、distributed reduction 和预算常数完全一致。
3. 组内减均值的 baseline 与除 std 是两件事。前者在期望上可不改变 policy gradient，后者根据题目 rollout 结果重缩放整个题的梯度。
4. 论文“unbiased”针对其定义的 expected binary verifier reward 及固定采样假设；它不保证 verifier、clipping surrogate 或有限 batch 本身没有偏差。

## 6. 来源

- 官方 arXiv：`https://arxiv.org/abs/2503.20783v2`；v2 提交于 2025-10-06，PDF 标注 Published as a conference paper at COLM 2025。
- 本地 PDF：`source/arxiv_2503.20783.pdf`，12 页，SHA-256 `98243d51297f011fb5baad8a70a972d061ffbef618f1d7cfc10deea37c5887d0`，检索日 2026-07-15。
- 作者链接代码：`https://github.com/sail-sg/understand-r1-zero`；尚未完成 commit、license 与发布资产核验。

