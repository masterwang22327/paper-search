# SAPO（arXiv:2511.20347v2）机制初筛

## 结论与边界

Qwen/Alibaba 的 SAPO 继续修复 GSPO 的“整序列 hard clip”：保留 token-level adaptivity，但以温度控制的平滑 gate 衰减 off-policy token 梯度，并对负 advantage 使用更快衰减。当前核对官方 v2 PDF §3-5、Eq.5-8、Figures 4-6；未核代码、数据、许可证或独立复现。

## Loss Design Card

| 项目 | 核验结果 |
|---|---|
| 真实目标 | 在保留近 on-policy token 学习信号的同时抑制 outlier token，延长大模型/MoE RL 的稳定训练窗口。 |
| 代理目标 | 用 `f(r)=4/tau * sigmoid(tau(r-1))` 替代 clipped `r`；其导数 gate `4p(1-p)` 在 `r=1` 为 1，偏离 1 时平滑趋零。 |
| 粒度与梯度 | advantage 按 response/group，ratio/gate 按 token，sequence 内做 token mean；只有 current policy 收梯度。 |
| 非对称项 | `tau_neg > tau_pos` 使负 advantage token 更快衰减；作者解释负更新会提高大量未采样词 logits，较易不稳。 |
| 假设 | 小 on-policy step、sequence 内 token log-ratio 方差低时，平均 token gate 可近似 sequence gate；outlier 时则保留 token adaptivity。 |
| 指标缺口 | 平滑 gate 有非零但可能极小的梯度；稳定更久不等于永不崩溃，论文也明确各方法最终可能失稳。 |

## Design-Defect-Fix 与 Heavy Knowledge / 重知识

| 前置缺陷 | SAPO 修复 | 状态与新代价 |
|---|---|---|
| GRPO token hard clip：band 外梯度为零 | 连续 token gate | 避免不连续/全或无，但引入 `tau_pos/tau_neg` 调参和 residual off-policy 梯度。 |
| GSPO sequence hard clip：少数 outlier 可丢掉整条 response | 只衰减 offending token | 保存其余 token 信号；sequence coherence 只在低 dispersion 假设下近似成立。 |
| 正负 advantage 共用相同稳定性处理 | 负 token 更高 temperature | Figure 5 支持作者设置；是否跨模型/reward 泛化未证明。 |

最重的知识是：SAPO 的 loss 值 `f(r)A` 不是 importance-weighted reward 的常规形式，关键在它的导数被设计成平滑 trust-region gate；只比较 loss 数值而不求梯度，会误解算法。Figure 4 的 Qwen3-30B-A3B 对照显示 SAPO 比 GSPO/GRPO-R2 更晚崩溃且峰值更高，但当前没有多 seed/置信区间，因此证据等级为单篇作者实验。

## 工件状态

本批 PDF/Atom 元数据中未定位专用官方代码、训练数据、权重或许可证；状态为 `not found during bounded check`，仍需专门 artifact audit。

