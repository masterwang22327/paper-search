# DeepSeekMath Eq.3 -> ms-swift v4.4.1 目标函数映射

## 范围与结论（最小有效版）

- 对象：DeepSeekMath arXiv:2402.03300v3 Eq.3，与 ModelScope `ms-swift` tag `v4.4.1`、commit `98a09c18cdf95ff07051324b9b8cc90f5184b24b`（commit date 2026-07-13，Apache-2.0）。代码于 2026-07-15 从官方仓库 `https://github.com/modelscope/ms-swift` 核查。
- 这是一个现代框架的**代码映射**，不是 DeepSeek 官方复现。DeepSeek 官方仓库未发布 GRPO 训练代码。
- 在 `advantage_estimator=grpo, scale_rewards=group, loss_type=grpo, importance_sampling_level=token, kl_in_reward=false` 路径上，数据流与 Eq.3 的主体一致：同 prompt 的 `G` 个序列 -> 组内 reward 中心化/标准化 -> 序列 advantage 广播到 completion token -> token 级 PPO ratio/clip -> sampled reverse-KL -> 每序列 token mean -> batch mean。
- 不能把“`--rlhf_type grpo`”等同于论文精确复现：框架默认 `G=8`，论文为 `G=64`；框架还暴露 batch/no normalization、sequence-level IS、多种 reduction、动态重采样和 rollout 修正等再设计。框架实际 GRPO 默认 `beta=0.04` 与论文相同：`_init_grpo()` 先填入 0.04，因而后面的通用 `_set_default()` 不会再写入其他算法使用的 0.1。只检索字段默认而不追踪初始化顺序会得到错误结论。

## 一批数据、张量与梯度怎样流动

以 `P` 个 prompt、每题 `G` 个 completion、padding 后最大 completion 长度 `T`、`R` 个 reward source 为例：

1. sampler 把每个 prompt 重复 `G` 次；rollout 得到 `N=P*G` 条序列。默认 `G=8`，并要求 global `generation_batch_size` 可被 `G` 整除。
2. rule reward / reward model 产生 `rewards_per_func:[N,R]`；先按 `reward_weights:[R]` 合成 `rewards:[N]`。各 rank 的 reward 被 gather 后再计算 advantage，所以组可跨设备。
3. 默认固定组路径 reshape 为 `[P,G]`，逐行减均值、除标准差，再得到 `advantages:[N]`。这些 reward 与组统计均在 policy 反传图外；reward model 不从 policy loss 收梯度。
4. completion 编码为 `completion_mask:[B,T]`，old/reference/current policy 分别在同一实际采样 token 上给出 `old_logp/ref_logp/current_logp:[B,T]`。序列 advantage 被显式 expand 成 `[B,T]`，不是依靠 loss 中的隐式 broadcast。
5. current policy 的 log-prob 同时进入 `rho=exp(current-old)` 和 KL；old/ref log-prob 在 `no_grad` 下产生。loss 最小化后，梯度只回到 current policy：正 advantage token 概率被上调、负 advantage token 概率被下调，KL 把 current 拉回 reference。
6. 默认 reduction 先对每条 completion 的有效 token 求平均，再对本 microbatch 的序列求平均。训练推理时只保留更新后的 policy；old/ref/reward 均是训练支架。

这里有三个不同的“旧模型”概念，框架配置容易把它们混淆：rollout engine 的采样分布、PPO ratio 分母使用的 `old_per_token_logps`、KL 锚点 `ref_model`。同步 rollout、一次 update 时前两者通常相同；异步/独立 vLLM server 可产生训练-推理 log-prob mismatch，框架为此另有 rollout IS correction，但那不是原论文 Eq.3 的组成部分。

## 可复核映射

| 论文 Eq.3 部件 | ms-swift v4.4.1 实现 | 一致性 / 隐藏行为 |
|---|---|---|
| 每题采样 `G` 个完成 | `GRPOArguments.num_generations=8`；`RepeatSampler(... mini_repeat_count=self.num_generations)` | 语义一致，默认预算不同；论文 `G=64`，且每次 exploration 后单次 update。框架默认 `num_iterations=1` 与其一致。 |
| `A_i=(r_i-mean)/std` | `compute_advantages`: reshape `[-1,K]`，减 group mean，除 `grouped.std + 1e-4` | 主体一致；全等 reward 得 `A=0`，不会 NaN。PyTorch `std()` 默认采用样本标准差，而论文未指明总体/样本标准差。 |
| 序列 advantage 用于各 token | `expand_advantage_to_per_token` 后 loss 接收 `[B,T]` advantage | 与 outcome GRPO 的广播一致。 |
| `rho=pi_theta/pi_old` | `log_ratio=per_token_logps-old_per_token_logps`; `exp(log_ratio)` | log-space 计算；`old` log-prob detached 或预存。 |
| PPO clipped surrogate | `-min(rho*A, clamp(rho,1-eps_low,1+eps_high)*A)` | 符号因训练最小化 loss 而取负；默认 `epsilon_low=epsilon_high=0.2`。非对称 `epsilon_high` 或额外 `delta` 是后续算法入口，不属于原式。论文没有报告其 epsilon 数值。 |
| sampled `KL(pi_theta||pi_ref)` | clamp `d=log pi_ref-log pi_theta` 后计算 `exp(d)-d-1`，乘 `beta` 加到 loss | 估计器同论文；框架把 `d` 截到 `[-20,20]`，KL 再截到 `[-10,10]`，是论文未写的数值保护。 |
| `(1/G) sum_i (1/|o_i|) sum_t` | `loss_type=grpo`: masked token sum / sequence length，再 batch mean | reduction 与 Eq.3 相符；`bnpo`/`dr_grpo`/`dapo` 会改变长序列权重，不能混称原始 Eq.3。 |
| completion-only mask | `completion_mask`；还可把 overlong/truncated completion 整条排除 | padding 不进 loss；overlong filter 会改变有效样本分布，是额外实现选择。 |
| 跨卡 group 统计 | rewards 先 `gather` 成 global tensor，再按连续 `G` reshape；注释要求 advantage 输入已全局聚合 | 组统计可跨 rank，但正确性依赖 sampler 保持同 prompt 的 `G` 个样本连续；不是普通 local-batch normalization。 |

## Loss Design Card：论文兼容配置

| 项目 | 代码核查结果 |
|---|---|
| 真实目标 | 提高完成的 reward/数学正确率，同时限制相对 SFT reference 的漂移。 |
| 代理目标 | group-relative outcome advantage + token-level PPO clipped ratio + sampled reverse-KL。 |
| 论文兼容关键配置 | `advantage_estimator=grpo`; `scale_rewards=group`; `loss_type=grpo`; `importance_sampling_level=token`; `kl_in_reward=false`; `dynamic_sample=false`; `overlong_filter=false`; `num_iterations=1`; `beta=0.04`。这些均为 v4.4.1 默认或 GRPO 专用默认；唯有 `num_generations` 默认 8 而论文取 64。 |
| 作用域 / reduction | reward 按 sequence；baseline/scale 按 prompt group；ratio、clip、KL 按 completion token；先 sequence token mean，后 sequence mean。 |
| 梯度接收者 | 只有 current policy。old/ref log-prob 在 `no_grad` 下计算；reward function/model 输出和 advantage 不在 policy 图中。 |
| 停止梯度的细节 | 若 `old_per_token_logps` 缺失，fallback 是 `current_logp.detach()`；标准路径在 loss 前用 `no_grad` 预存 old log-prob。 |
| 数值保护 | ratio 在 log-space 相减后 exponentiate；KL 的 log-ratio 先 clip `[-20,20]`，所得 k3 项再 clip `[-10,10]`；advantage 除以 `std+1e-4`；分母 mask count clamp 至至少 1。 |
| 目标—指标缺口 | 正确配置仍只优化框架提供的 weighted reward；reward hacking、同组全错时“较不差”错误被上调、Maj@K 上升但 Pass@K 不升等论文边界没有被实现消除。 |
| 未复现部分 | 原论文 process supervision 是对所有 step reward 联合标准化后，令 token advantage 为后续 step reward 之和；本次检查的通用 outcome reward 路径只产生 `[N]` 序列 reward，未找到对原论文该 PRM 公式的直接实现入口。 |

### 一个容易被默认值放大的数值差异

对 rewards `[1,1,0,0]`，减均值后是 `[0.5,0.5,-0.5,-0.5]`。若 `std` 指总体标准差，advantage 为 `[1,1,-1,-1]`；PyTorch v4.4.1 路径的 `torch.std()` 默认 Bessel correction，样本标准差约 `0.577`，忽略 `1e-4` 时 advantage 约为 `[0.866,0.866,-0.866,-0.866]`。`G=64` 时两种标准差只差因子 `sqrt(63/64)`，但框架默认 `G=8` 时差异更明显。它主要缩放 policy-gradient 相对 KL 的强度，因此即使 `beta` 同为 0.04，实际两项平衡也未必与论文相同。论文只写“group standard deviation”，没有指定 correction，本点是**代码事实 + 本文影响推断**，不是论文主张。

## Design–Defect–Fix：实现层双面检查

| 设计 | 收益 | 缺陷与证据类型 | 框架提供的修复入口 | 移除 / 减少 / 转移及成本 |
|---|---|---|---|---|
| `std+1e-4` | 避免零除和 NaN | intrinsic：全等组分子仍为 0，梯度仍消失；代码可直接推出 | `dynamic_sample=true` 重采样零方差组（DAPO 路径） | 信号塌缩被减少，不是移除；成本转为额外 rollout，并把训练分布偏向“当前 policy 恰能产生奖惩差异”的题。 |
| sequence-equal GRPO reduction | 精确对应 Eq.3，每条完成等权 | later-emerging：长度不同导致每 token 梯度权重为 `1/T_i`，可形成长度相关偏置；后续论文证据本单元未读 | `bnpo`、`dr_grpo`、`dapo` reduction | 改变/减少某种长度偏置，但新目标不再是原 Eq.3；哪种更优必须靠后续原论文证据，不能由代码宣称。 |
| 独立 sampled KL | 保持 advantage 的纯 group-relative 语义；与原论文一致 | contingent：单样本 KL 有方差，极端 ratio 在混精下不稳 | log-ratio/KL 双重 clamp；`beta=0` 可完全省 ref model | 数值爆炸风险减少，但 estimator 被截断而引入偏差；关 KL 则把成本换成漂移/reward hacking 风险。 |
| global gather 后组归一化 | 同一 prompt 的组可跨 rank，保持统计语义 | contingent：依赖 global ordering 与固定 `G`；普通数据并行 local mean 会算错 | sampler 重复与 divisibility 检查；动态样本用 prompt/request ID 分组 | 固定组风险减少；代价是 collective、排序约束和更复杂的多轮路径。 |
| token-level IS（默认） | 与 Eq.3 分子/分母逐 token ratio 一致 | later-emerging：独立 rollout engine、异步和 MoE routing 会造成 rollout-training mismatch | rollout IS correction；或 `importance_sampling_level=sequence`（GSPO） | mismatch 可被减少/重新定义，但增加监控、截断偏差或改成不同算法；本单元不评价后续效果。 |

## Heavy Knowledge / 重知识（初版）

1. `std + 1e-4` 不是“修复全同组后仍学习”：分子已经为零，所以该组贡献零梯度；它只防止除零。若开启 dynamic sampling，则框架会重采样零方差组，改变问题采样分布与计算预算。
2. 论文的 sequence-equal reduction 在框架中对应 `loss_type=grpo`，而不是所有名为 GRPO 的 loss。`bnpo` 按全 batch token mean，长回答获得更多权重；`dr_grpo` 除以固定最大长度，改变长度相关梯度尺度。
3. 当 `num_iterations=1` 时，若未缓存 old log-prob，代码令 `old_logp=current_logp.detach()`，ratio 的数值为 1，但梯度仍经 current log-prob；这仍是 policy-gradient surrogate，并非“ratio 为 1 所以没有梯度”。
4. **默认值要按初始化控制流核查。** GRPO 的 `beta=0.04` 在 `_init_grpo` 中先写入，通用 `_set_default` 中的 0.1 实际不会覆盖它；文档也明确确认 GRPO 默认 0.04。
5. 同名 `std` 未必同一个 estimator。框架的样本标准差与许多手算示例用的总体标准差会缩放 advantage；这个缩放还会改变它相对未缩放 KL 项的有效权重。

## 论文目标与配置的 Explain-It-Back

- [ ] 能否从 `[P*G,R]` reward 追到 `[P,G]` group statistic，再追到 `[B,T]` advantage 和 policy gradient？
- [ ] 能否解释为何跨卡 gather 不等于跨题 batch normalization？
- [ ] 能否解释 `loss_type=grpo`、`bnpo`、`dr_grpo` 的 reduction 为什么不是无关紧要的实现细节？
- [ ] 能否解释 ratio 数值为 1 时 current log-prob 为什么仍有梯度？
- [ ] 能否说清 `old policy`、`reference policy` 与 rollout engine 三者的不同职责？
- [ ] 能否指出哪些默认值复刻论文、哪些没有，以及为什么同一个 beta 仍不保证相同优化平衡？

## 证据边界

- 论文证据：official v3 PDF §4.1.1–4.1.3、Eq.3–4、Algorithm 1、§4.2（`G=64`, `beta=0.04`, max length/batch 1024, one update per exploration）、Appendix A.1.6。稳定 URL：`https://arxiv.org/abs/2402.03300v3`。
- 框架证据：官方 repo `https://github.com/modelscope/ms-swift`，tag `v4.4.1`, commit `98a09c18cdf95ff07051324b9b8cc90f5184b24b`；`swift/arguments/rlhf_args.py`（GRPO beta 与 num_generations 默认）；`swift/rlhf_trainers/args_mixin.py`（epsilon、scale、IS、dynamic sample 默认）；`swift/rlhf_trainers/grpo_trainer.py`（sampler、global gather、old/ref log-prob、clip/KL/mask/reduction）；`swift/rl_core/advantage.py`（group statistic、`1e-4`、advantage broadcast）；官方 `loss_types.md` 与 command-line docs。检索日 2026-07-15，Apache-2.0。
- 稳定代码入口：`https://github.com/modelscope/ms-swift/blob/98a09c18cdf95ff07051324b9b8cc90f5184b24b/swift/rlhf_trainers/grpo_trainer.py`；`https://github.com/modelscope/ms-swift/blob/98a09c18cdf95ff07051324b9b8cc90f5184b24b/swift/rl_core/advantage.py`。
- 未运行训练；未验证 Megatron/Ray/Liger 后端与 HF trainer 数值等价；repository 中只找到 Megatron GRPO 测试入口，本次没有发现覆盖 HF `compute_advantages`/reduction 的直接测试。故“代码路径已核查”的置信度高，“各 backend 数值一致”和“可复现 DeepSeek 结果”均不成立。
