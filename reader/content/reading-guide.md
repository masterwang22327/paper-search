# 按任务选读与阶段说明

[返回阶段目录](index.md)。这里保留各阶段的前置知识、学习目标和检查点，按需查看即可。正文中的上一篇 / 下一篇沿同一条路线衔接。

## 按当前问题进入

已掌握前置知识时，可以直接进入对应分支；概念衔接不清楚时，再看下方阶段说明。

| 当前任务 | 建议入口 |
|---|---|
| 补齐基础 | [公式阅读桥](papers/formula-reading-bridge.md) → [Transformer](papers/arxiv-1706.03762.md) → [现代 Block](papers/modern-transformer-block.md) |
| 训练与微调 | [AdamW](papers/adam-adamw.md) → [分布式训练](papers/megatron-zero.md) → [数值稳定](papers/training-numerical-stability.md) → [参数高效微调](papers/peft-adapters-prefix-prompt-qlora.md) |
| 后训练与 Agent RL | [Instruct 模型后训练](papers/instruct-model-effective-post-training.md) → [长轨迹信用分配](papers/agentic-rl-credit-assignment.md) → [评测器有效性](papers/evaluator-judge-validity-cua.md) |
| 知识库与检索 | [Embedding 系统调研](papers/embedding-models-lineage-selection.md) → [DPR](papers/dpr-dense-retrieval.md) → [RAG](papers/rag-external-memory.md) |
| 推理效率与长上下文 | [推理服务与量化](papers/inference-serving-quantization.md) → [高效注意力与状态](papers/efficient-attention-delta-state.md) → [有效上下文评测](papers/evaluation-effective-context.md) |

## 阅读与核查方法

先抓问题、输入输出和最小流程，再看公式与实验边界。公式不清楚时，先确认变量、shape 和运算方向；结论不清楚时，从正文引用打开固定 PDF 核对。

“作者主张”是论文报告的结果，“来源事实”能在原文定位，“工件事实”来自固定代码或模型；“本报告推断”是解释，“未知”表示证据不足。阅读时不要混为一谈。

## 阶段说明与完整路线

<!-- GENERATED_LEARNING_PATH -->
