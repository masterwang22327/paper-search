# DAPO（arXiv:2503.14476v2）机制初筛

## 结论与边界

DAPO 不是只给 GRPO 换名，而是把长 CoT 训练中的四个失效点拆开处理：非对称 clip、动态过滤零梯度题、batch-token reduction、截断样本的软惩罚。当前只核对官方 v2 PDF 的 §2.3-4.2、Eq.8-12、Figures 2-6 和 Table 1；代码、数据、许可证与多后端一致性尚未独立核验，因此工件只记为 author-linked。

## Loss Design Card

| 项目 | 核验结果 |
|---|---|
| 真实目标 | 在 rule-verifiable 数学任务中稳定扩大长 CoT RL，并提高有效 rollout/token 的利用率。 |
| 代理目标 | GRPO group-normalized outcome advantage + token importance ratio；去掉 reference KL；上/下界拆为 `epsilon_high=0.28`、`epsilon_low=0.2`；总有效 token 上做 reduction。 |
| 梯度与粒度 | advantage 按 response/group；ratio/clip 按 token；Eq.12 的分母是 batch 有效 token 总数，长回答因此贡献更多总权重。 |
| sampling 条件 | 只保留组内既有正确又有错误的 prompt；全对/全错组被重采样替换。 |
| reward shaping | 正确 `+1`、错误 `-1`；超过期望长度后在 4096-token buffer 内线性软惩罚，超限再截断。 |
| 假设 | verifier 可靠；过滤后的题分布仍服务于目标；额外 rollout 不成为瓶颈；去 KL 不造成不可接受漂移。 |
| 指标缺口 | AIME avg@32 和训练 reward 上升不能隔离算法、数据、sampling 预算与系统配方，也不能推出通用 Agent 任务有效。 |

## Design-Defect-Fix

| GRPO/长 CoT 缺陷 | DAPO 修复 | 论文证据 | 新成本或未解问题 |
|---|---|---|---|
| 对正 advantage 的上裁剪限制低概率 token 增长，作者关联其与 entropy collapse | 提高正向上界，保持下界 | §3.1, Figures 2-3 | clip 非对称增加调参空间；机制解释主要来自单一训练系统。 |
| 全对/全错组 advantage 为零，稀释有效 batch | 动态采样直至 batch 全为非零方差组 | §3.2, Eq.11, Figure 6 | 零信号被绕开而非修复；额外 rollout 且训练题分布偏向当前策略边界题。 |
| 每序列 token mean 使长回答每 token 权重变小 | 全 batch token mean | §3.3, Eq.12, Figure 4 | 减少长错误“少罚”，但把优化质量单位从 sequence 转为 token，可能鼓励有正 advantage 的长答案。 |
| 硬截断把潜在正确的超长轨迹统一判错，制造 reward noise | soft overlong punishment | §3.4, Figure 5 | 依赖长度阈值和 buffer；仍未解决 verifier/reward hacking。 |

Table 1 是逐步叠加配方而非正交全因子消融：naive GRPO `30`，依次加入 overlong filtering `36`、Clip-Higher `38`、soft punishment `41`、token loss `42`、dynamic sampling `50`（AIME24 avg@32）。这支持“整套配方有效”，不能单独证明每项在不同加入顺序下的因果增益。

## Heavy Knowledge / 重知识

1. DAPO 的 Dynamic Sampling 改的是有效训练分布与 rollout 预算，不是 advantage estimator；将它和 loss 修改混为一谈会误判算法贡献。
2. DAPO token-level loss 与 Dr.GRPO 固定分母都反对原始 sequence mean，但不等价：前者让长序列占更多总权重，后者用固定生成预算避免样本长度决定相对权重。
3. 删除 KL 是场景判断，不是普遍定理；论文认为长 CoT 应允许远离初始策略，但 learned-RM alignment 或安全任务可能正需要 reference anchor。

## 工件状态

论文明确链接项目页和 `volcengine/verl` 并声称开放训练代码与 17K prompts；本批未固定 commit/tag、逐项定位 DAPO recipe、核对数据 URL/许可证、权重与复现实验。故这些均不是 `verified`。

