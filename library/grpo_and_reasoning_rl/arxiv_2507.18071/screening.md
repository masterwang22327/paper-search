# GSPO（arXiv:2507.18071v2）机制初筛

## 结论与边界

Qwen/Alibaba 的 GSPO 直接修改 GRPO 的 off-policy correction 单位：将每 token importance ratio 与 clip 换成基于整条 response likelihood 的几何均值 ratio，并对整条 response clip。当前核对官方 v2 PDF §2-5、Eq.2-17、Figures 1-2；未独立复现，论文的稳定性优势主要来自 Qwen3-30B-A3B MoE 内部设置，外推到 dense/其他系统需保留边界。

## Loss Design Card

| 项目 | 核验结果 |
|---|---|
| 真实目标 | 降低长序列、独立 rollout/training engine 和 MoE routing 下 token ratio 噪声导致的训练崩溃。 |
| 代理目标 | `s_i=(pi_theta(y_i|x)/pi_old(y_i|x))^(1/len(y_i))`，以 group-normalized sequence reward advantage 加权，并在 sequence level clip。 |
| 粒度 | reward、advantage、ratio、clip 均按 sequence；`log s_i` 是 token log-ratio 的均值，梯度再平均分给该 response 的 token。 |
| 梯度 | 未 clip 时，同一 response 各 token 共享 `s_i*A_i/len(y_i)` 权重；区别于 GRPO 让每 token 乘各自 ratio。 |
| 数值设计 | 几何均值/长度归一防止 likelihood product 随长度指数缩放；GSPO clip 量级 `3e-4/4e-4`，不能复用 GRPO 的 `0.2`。 |
| 指标缺口 | 训练曲线稳定和内部 Qwen3 收益不能证明 token ratio 在所有 LLM RL 场景都“理论错误”，尤其 token/step reward 与多轮 credit assignment。 |

## Design-Defect-Fix

| 设计链 | 修复状态 | 证据 | 新缺陷/成本 |
|---|---|---|---|
| GRPO token ratio 对同一 response 的 token 给不同权重，长序列噪声累积 | GSPO 以 sequence ratio 统一权重，论文 MoE 设置中**减少**崩溃 | §3-5, Eq.5-12, Figure 1 | 一个 outlier token 可使整个 sequence 被 clip，牺牲其余近 on-policy token 的学习信号。 |
| MoE rollout/training routing 不一致使 token log-prob 波动 | GSPO 报告无需 Routing Replay 即收敛 | §5.3 | 只在作者系统核验；sequence likelihood 仍来自 token log-prob，不能视为消除所有 engine mismatch。 |
| sequence reward 与 token correction 粒度不一致 | 全部统一为 sequence level | §4.1 | outcome reward 合适；process/multi-turn token advantage 需要 GSPO-token，问题转为细粒度 credit 设计。 |

## Heavy Knowledge / 重知识

1. GSPO 的 sequence ratio 不是原始 trajectory likelihood ratio，而是其 `1/T` 次方；这是为了可控方差而加入的长度归一，改变了严格 importance sampling 权重，故“完全理论正确”应视为作者主张而非已定事实。
2. clip range 取决于 ratio 定义。`3e-4` 级 GSPO band 与 `0.2` GRPO band 不可直接比较或互换。
3. GSPO-token 用 stop-gradient 构造数值等于 sequence ratio、但把梯度入口留在 token ratio；当 token advantage 相同，它与 GSPO 数值和梯度等价，只有细粒度 advantage 时才体现额外能力（Eq.13-17）。

## 工件状态

本批 PDF/文本中未找到作者链接的专用代码、权重或数据入口；只能记录 `not found during bounded check`，不能写成“未发布”。Qwen3 的公开模型资产是否可复核 GSPO 训练主张尚未检查。

