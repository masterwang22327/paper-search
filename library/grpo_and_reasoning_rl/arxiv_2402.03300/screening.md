# DeepSeekMath（arXiv:2402.03300v3）初筛

## 0. 范围、读者定位与证据边界

- 状态：`screened`，P0，Phase 0 试运行；这是可决定是否精读的初筛，不是完整 review。
- 面向：会用 ms-swift/现代 RL 训练框架、但希望补齐策略分布、梯度和 reduction 机制的工程实践者。最低前置是自回归 log-prob、policy gradient、KL；PPO/GAE 在文中从问题动机重建，不假设已经掌握。
- 本单元实际检查：官方 v3 PDF 的摘要、§1、Figure 1、§4.1–4.2（含 Eq. 1–4、Algorithm 1）、Table 5、§5.2（Table 10、Figure 5–7）、§6、Appendix A.1.6（Eq. 19–21）；并检查作者在 PDF 首栏链接的 GitHub、仓库内容/许可证和三个 Hugging Face 模型卡。
- 未检查：其余预训练实验表和全部附录、框架实现逐行对照、独立复现、后续 GRPO 修正论文。后文严格区分 **[论文主张]**、**[表/图证据]**、**[本文推断]**。

## 1. 初筛结论与优先级

**一句话判断**：DeepSeekMath 是 GRPO 的原始一手来源，最聪明的改动是用“同题多答案”的组内相对奖励替代 PPO 的 learned critic；它确实减少一个同量级模型的训练/显存负担，但以每题 `G=64` rollout、同组可辨识性和奖励模型可靠性为代价，且论文自己的 Pass@K 结果不支持把 Top-1 提升直接解释为新推理能力的产生。

质量评分 **88/100，建议进入 S 级精读**：主线相关 25/25、问题重要 15/15、方法创新 14/15、证据 14/20、可复现 6/10、影响/讨论 10/10、背景桥接 4/5。扣分依据是没有训练代码/训练数据、没有方差或多 seed、GRPO 与等预算 PPO 的隔离对比不足，且算法、reward model、在线采样与过程监督的贡献并未完全解耦。

## 2. 历史问题、动机与完整流

### 从 PPO 的矛盾出发

PPO 在 LLM RL 中同时维护 policy、old policy、reference policy、reward model 和一个通常与 policy 同量级的 value model。value model 要从最终或稀疏奖励拟合每个 token 的未来回报，既占显存/算力，又可能在 token 级价值估计上不准（PDF §4.1.1, pp.11–13）。GRPO 的问题不是“不要 baseline”，而是：能否利用同一题的并行采样，把 baseline 从跨状态学习问题改成同题内统计问题？

### 数据、梯度与推理流

1. 从 SFT 问题分布抽问题 `q`；每题由 frozen-for-this-step 的 `pi_old` 在线采样 `G` 个完成，论文训练取 `G=64`。
2. reward model 给每个完成 outcome 分数，或给推理步骤 process 分数。组内做减均值、除标准差，得到相对而非绝对 advantage。
3. Outcome supervision 把同一个序列级标准化奖励广播给该完成的所有 token；process supervision 则令 token advantage 等于其后各步骤标准化奖励之和。
4. 对每个 token 计算 `rho = pi_theta(token)/pi_old(token)`；最大化 `min(rho*A, clip(rho,1-eps,1+eps)*A)`，并减去相对 frozen `pi_ref` 的 KL。
5. 只有 `pi_theta` 收梯度；采样、reward/advantage、`pi_old`、`pi_ref` 和 reward model 在一次 policy 更新中均作为停止梯度目标。论文一次 exploration 后仅做一次 policy update；迭代版本另行用当前 policy 数据和 10% 历史 replay 更新 reward model。
6. 推理时没有 critic、reward 或 reference：只有 RL 后的自回归 policy。训练期省掉 critic 不等于免掉 rollout/RM/reference 成本。

一个组可类比搜索排序中的同 query 候选集：GRPO 学的是同题候选之间谁应上调/下调，而不是学习一个跨所有 query 绝对可比的价值标尺；这个类比也暴露其边界——若一个 query 的所有候选全对或全错，组内排序信号会塌缩。

## 3. Loss Design Card（初筛版）

| 项目 | 初筛记录 |
|---|---|
| 真实目标 | 提高数学答案正确率，同时限制策略偏离 SFT/reference，避免奖励过优化与能力破坏。 |
| 为何不能直接优化 | 离散文本的最终正确率不可对 token 直接反传；真实泛化能力也没有可微标尺。 |
| 代理目标 | 组内标准化 reward 形成 advantage；用 PPO clipped importance ratio 调整采样 token 概率，并显式减去 sampled `KL(pi_theta || pi_ref)`。见 Eq.3。 |
| 优化方向 | 最大化 reward surrogate、最小化 KL；实现若写 loss 则整体取负。 |
| 数据作用域 | 每题一组 `G` 个序列；先每序列 token mean，再 group mean，再对问题/批次取期望。Outcome advantage 为序列级但广播到 token。 |
| 梯度接收者 | 仅 policy `theta`。old/reference policy、reward model、离散采样和组统计 detached；迭代 RM 是另一训练阶段。 |
| reduction / mask | Eq.3 为 `(1/G) sum_i (1/|o_i|) sum_t`，只含 completion token。每个完成等权，不因更长而总权重更大；padding mask/分布式全局组语义未说明。 |
| baseline / normalization | Outcome: `(r_i-mean(group))/std(group)`；同序列所有 token 相同。Process: 步骤奖励统一标准化后，对 token 累加未来步骤奖励。 |
| 系数 | `epsilon` 控制 ratio clip；`beta` 控 KL，论文为 0.04；policy LR `1e-6`。移除 clip 会允许单批数据造成过大 ratio；移除 KL 会增加 reward hacking/遗忘风险；beta 太大则基本冻结在 reference。 |
| 统计假设 | 同题的 `G` 个样本能估计有意义的相对基线；RM 在组内排序和尺度上可靠；online rollout 与当前 policy 足够接近；token 广播能合理分配序列奖励。 |
| 数值/分布式 | KL 用 `x - log x - 1`，`x=pi_ref/pi_theta` 的逐样本非负估计；概率比应在 log-space 形成以避免下溢。论文未说明 std=0、epsilon、精度、跨卡 group/reduction。 |
| 目标—指标缺口 | reward 上升可只是把已有正确路径的概率质量前移。Figure 7：Maj@K 改善而 Pass@K 不改善，不能据此声称扩大可解问题集合。 |
| 消融证据 | Figure 5：作者报告 online RFT > offline RFT、GRPO > online RFT、process > outcome；Figure 6：迭代 RL 尤其首轮有效。曲线未给多 seed/error bar。 |
| 代码/框架映射 | 官方仓库没有 GRPO 训练实现，故无法核验 `num_generations/group size`、`beta`、clip、token/sequence aggregation 等配置到 Eq.3 的映射；现代框架同名 `GRPO` 不应自动视为复现此 reduction。 |

### 逐项机制与一个最小例子

- `rho*A` 是重要性校正后的 policy-gradient 代理。若 `A>0`，提高该 token 概率；若 `A<0`，降低它。clip 让超出 trust region 的进一步收益饱和，但并不是硬约束，KL 仍承担全局锚定。
- 假设同题四个 outcome reward 为 `[1,1,0,0]`，均值 `0.5`、总体标准差 `0.5`，advantages 为 `[+1,+1,-1,-1]`。正确完成的全部 token 被共同上调，错误完成全部 token 被下调；它没有指出错误发生在哪一步，这是 outcome credit assignment 的核心缺陷。
- KL 估计令 `x=pi_ref/pi_theta`，逐 token 项 `x-log(x)-1 >= 0`；在 `pi_theta` 样本下取期望恰为 `KL(pi_theta||pi_ref)`。直接放入 objective，不再先混入 reward 再经 GAE，避免 KL 改变 group advantage 的语义。
- **[本文推断]** 若组内 reward 完全相同，标准差为零；实际框架必须加 epsilon、跳过组或置零，但论文没有指定。不同处理会改变有效 batch 和难题/易题权重，是框架隐藏行为。
- **[本文推断]** Process advantage 是未折扣的未来步骤 reward 之和，步骤更多的完成可能产生更大 advantage 尺度；这把更细 credit assignment 的收益换成潜在的步数/长度偏置。

### Loss Evolution Map

| 前身 | 已识别缺陷 | 本文重设计 | 本文证据 | 新代价 / 后续待查 |
|---|---|---|---|---|
| PPO + GAE + learned value | 同量级 critic 显存/计算重；稀疏末端奖励使 token value 难拟合 | 同题 group reward baseline，移除 critic | 方法图 Figure 4；Table 5 下游提升，但无等预算 PPO 直接隔离 | `G` rollout 成本、同组退化、相对归一化偏差；后续修正尚未在本单元核验 |
| PPO 把 per-token KL 混入 reward | KL 进入 return/GAE，使 advantage 计算更复杂 | KL 直接成为 objective 正则 | Eq.2 对 Eq.3–4 的定义性比较 | beta 仍需调；sampled KL 方差及实现差异未报告 |
| Outcome reward | 全序列同一 credit，错步定位差 | Process step reward + future-step sum | Figure 5 中 PS 曲线优于 OS（作者报告） | PRM 标注噪声、步骤长度尺度；作者还指出 PRM800K 有噪声 |

## 4. Core Idea 与 Heavy Knowledge / 重知识

1. **Critic 不是被“无 baseline”取代，而是被 query-conditional Monte Carlo baseline 取代。** 省去的是学习跨状态 value function，不是方差控制本身；代价从参数/优化转移到同题 rollout 数。
2. **组内标准化改变了 reward 的含义。** 梯度关心“比同题其他答案好多少”，一题内部总 advantage 近似零，因此绝对都很差的组也可能奖励“相对不差”的错误答案；全对/全错组又可能不给信号。
3. **Outcome reward 被广播到每个 token，但 Eq.3 对每条序列做 token mean。** 这让完成大致等权，并不能解决 token credit assignment；框架若改为 batch token mean，会改变长短序列权重和实际目标。
4. **论文最有价值的负结果来自作者自己。** Figure 7 的 Pass@K 不升提示 RL 主要重排已有候选概率，而非扩张探索支持集。这比只看 MATH Top-1 的 46.8→51.7 更接近机制判断。
5. **“省内存”不等于“更省总计算”。** 论文配置每题 64 个完成、batch 1024、max length 1024；critic 被删掉，但生成与 RM 打分成为主成本。系统实现可能把成本从训练显存移向 rollout 吞吐。
6. **官方可复现物只覆盖模型推理与评测，不覆盖算法训练。** 权重能复核部分结果，不能证明 Eq.3、reward 数据、distributed reduction 或训练稳定性。

## 5. Design–Defect–Fix Map（本文范围内）

| 设计 | 聪明之处 | 缺陷类型与证据 | 修复 | 结果 / 新成本 |
|---|---|---|---|---|
| 同题 group baseline 替代 critic | reward model 本就常按同题比较训练，统计结构匹配 | intrinsic：组同质时 std/信号退化；论文未处理零方差 **[本文推断]** | 本文未给；后续文献待精读 | 未知 |
| PPO clip + 独立 KL | 同时限制局部 update 和对 reference 的全局漂移 | intrinsic：clip 不是硬 trust region；beta 造成能力提升与保守性的竞争 | 本文固定 beta=0.04，无消融 | 风险仅被约束，未证明消除 |
| Process supervision | 把末端 reward 的粗 credit 细化到步骤 | contingent/intrinsic：PRM 有标注噪声，future sum 可能随步骤数放大 | iterative RM 用新 policy 数据 + 10% replay | 分布陈旧被缓解但转移为持续标注/训练 RM 成本 |
| Online sampling | 训练数据随当前 policy 演化，覆盖后期分布 | later-emerging：探索仍受 SFT prompts 和 naive nucleus sampling 限制；作者 §5.2.3 明确承认 | 作者建议 OOD prompts、tree search、高效推理 | 尚属未来方向；探索计算增大 |
| GRPO 对 correct/incorrect 给不同符号与强度 | 相比 online RFT，不只统一强化正确样本，也惩罚错误样本 | intrinsic：完全信任有噪 reward，可能放大 reward error | 作者提出 uncertainty/weak-to-strong robust algorithm | 未实现；问题未移除 |

注意：表中“后续修复”只记录原论文实现或明确提出的方向；真正的 Dr.GRPO、DAPO、GSPO 等后续证据尚未读，不能在此初筛中宣称某缺陷已解决。

## 6. 实验证据强度与不可推出的结论

- **[表证据]** Table 5，CoT Top-1：Instruct→RL 为 GSM8K `82.9→88.2`、MATH `46.8→51.7`、MGSM-zh `73.2→79.6`、CMATH `84.6→88.8`；tool-integrated 四项也均提升。RL 训练只使用约 144K 个 GSM8K/MATH 风格 SFT 问题（PDF §4.2, pp.14–15）。
- **[论文主张]** Figure 5 支持 online sampling 优于 offline RFT、GRPO 的有符号/有幅度 gradient coefficient 优于 online RFT、process 优于 outcome；但图中没有误差条，当前检查未发现多 seed。
- **[关键边界]** Figure 7 在 temperature 0.7、K≤64 下显示 Maj@K 提升而 Pass@K 不提升。作者解释为把 Top-K 中已有正确响应推到更高概率，而非增强 fundamental capability（§5.2.2, p.21）。
- **不能推出** “GRPO 单独造成全部 4.9 MATH 点提升”：最终 pipeline 同时依赖 DeepSeekMath 预训练/SFT、reward model、在线采样和具体数据；没有同等 rollout/模型/调参预算下的 PPO head-to-head，也没有 seed 方差或完整训练成本。
- **外推风险**：数学答案可验证且同题可批量采样，适合相对 reward；长时序 Agent 的环境状态、不可逆动作和稀疏非平稳回报未被本文实验覆盖。

## 7. 官方工件与复现状态（检查于 2026-07-15）

| 工件 | 状态 | 稳定位置 / 版本 | 许可证 | 能核验什么 / 不能核验什么 |
|---|---|---|---|---|
| 作者链接 GitHub | verified | `https://github.com/deepseek-ai/DeepSeek-Math`, commit `b8b0f8ce093d80bf8e9a641e44142f06d092c305`（2024-04-15）；未见 tag | code MIT | 含 inference、evaluation、测试集和保存输出；**不含 GRPO/SFT/pretrain 训练代码** |
| Base 权重/模型卡 | verified | HF `deepseek-ai/deepseek-math-7b-base`, revision `036a8c6...` | DeepSeek License v1.0 | 可运行 base 推理；不能复现训练 |
| Instruct 权重/模型卡 | verified | HF `deepseek-ai/deepseek-math-7b-instruct`, revision `0a5828f...` | DeepSeek License v1.0 | 可做 SFT→RL 前后比较 |
| RL 权重/模型卡 | verified | HF `deepseek-ai/deepseek-math-7b-rl`, revision `f3cd419...` | DeepSeek License v1.0 | 可复核生成/部分 benchmark；不能确认 GRPO 梯度实现 |
| 评测数据/脚本 | verified | 上述 GitHub commit 的 `evaluation/` | code MIT；各 benchmark 数据来源许可需逐项追溯 | 可复跑仓库支持的评测流程；仓库含预存 outputs/results |
| 120B math corpus / 144K RL prompts / RM train data | not found | 仅论文与 README 描述 | data 未由 Model License 授权（license §1 明示） | 无法复现数据筛选、RM 或 policy 训练 |
| GRPO 训练配置/optimizer state | not found | 无 | — | Eq.3 的 padding、std epsilon、混精和分布式 reduction 不可核验 |
| 官方 demo | not found | README 的 Replicate 链接为 `cjwbw` 命名空间，未据此认定官方 | — | 不作为算法复现证据 |
| 独立社区复现 | not checked | — | — | 留待后续专门检索 |

## 8. 常见误解、迁移连接与 Explain-It-Back

- “group relative”不是把不同题的 reward 做 batch normalization；同题组边界必须保持，分布式切 batch 时尤其容易错。
- GRPO 不是天然 verifier-only：原论文实际训练 neural outcome/process reward model；后来 RLVR 的 rule reward 是谱系中的再设计，不能倒灌回原论文。
- 与 OpenSearch 排序最贴切的连接是 query-group learning-to-rank：组内候选排序信号强，但跨 query 的绝对质量和没有正例的 query 都棘手。
- 与 SuperPoint matching 的连接是 RANSAC 式“同一实例内相对验证”：省去全局价值标尺，但候选集合若缺少正确 hypothesis，归一化不会创造正确解。

- [ ] 能否说清 PPO critic 为什么在稀疏末端 reward 的 LLM 中既贵又难学？
- [ ] 能否沿 `q → G completions → rewards → group normalization → token ratios/KL → policy gradient` 追踪一个 batch？
- [ ] 能否解释 outcome reward 为何仍有 credit assignment 问题，以及 process reward 新增长度/噪声成本？
- [ ] 能否解释删除 critic 后成本被转移到哪里？
- [ ] 能否用 Figure 7 说明 Top-1/ Maj@K 提升为何不等于 Pass@K/能力边界提升？
- [ ] 能否列出官方权重能复核和不能复核的主张？

## 9. 证据位置与文件完整性

- 官方摘要页：`https://arxiv.org/abs/2402.03300v3`。
- 官方 PDF：`source/arxiv_2402.03300v3.pdf`，30 页，SHA-256 `6cc20b3c5b8d25b8b53868fc4ec1792c144f07d67bdf7395138efd4422197e7b`，检索 2026-07-15。
- 关键页：摘要/Figure 1 p.1；引言 pp.2–3；Table 5 p.12；GRPO Eq.1–4/Figure 4/Algorithm 1 pp.11–14；训练配置 pp.14–15；Table 10/Figure 5 pp.19–20；Figure 6–7/§5.2.2–5.2.3 pp.20–22；结论 p.22；Appendix Eq.19–21 pp.29–30。
- 证据强度：方法定义和作者仓库状态高；单论文实验支持中等；“为何有效”的机制结论中等偏低；后续缺陷/修复尚未核验。
