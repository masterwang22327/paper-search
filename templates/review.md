# <Paper Title>：<它解决的核心问题>

!!! abstract "先读摘要"
    - **解决什么**：用一到两句具体描述旧方法的瓶颈。
    - **核心做法**：说明谁对谁做了什么，不用术语代替解释。
    - **不要误解**：给出最重要的适用边界或常见误解。

## 1. 一句话结论

## 2. 适合谁读，需要先知道什么

## 3. 历史问题与动机

## 4. 端到端数据、梯度与推理流程

首次出现变量时说明含义和 shape；复杂流程优先给一个具体输入输出例子或流程图，再给公式。

## 5. 基础数学逻辑与假设

每个关键公式至少说明：变量含义、运算方向、一个最小数值例子，以及公式没有表达什么。

## 6. 目标函数检查表

| Item | Explanation |
|---|---|
| Real task goal | |
| Why it is not directly optimizable | |
| Surrogate objective | |
| Optimization direction | minimize / maximize |
| Unit of application | token / sequence / pair / group / batch / timestep / trajectory / other |
| Gradient recipients | |
| Reduction and masking | |
| Normalization/baseline | |
| Key coefficients and sensitivity | |
| Statistical assumptions | |
| Numerical/distributed details | |
| Objective–metric gap | |
| Main ablation evidence | |
| Framework/code mapping | |

### 逐项解释

### 最小直觉或梯度方向例子

### 目标函数如何演化

| Predecessor Objective | Identified Defect | This Paper’s Redesign | Evidence | New Trade-off | Later Redesign |
|---|---|---|---|---|---|

## 7. 核心创新与不显然的设计

## 8. 设计、缺陷与修正

| Design | Why It Is Clever | Intrinsic/Contingent/Later Defect | Evidence | Follow-up Fix | Removed/Reduced/Shifted | New Cost |
|---|---|---|---|---|---|---|

## 9. 关键但容易忽略的结论

## 10. 论文算法与现代框架的差异

## 11. 实验、消融与证据强度

## 12. 代码、模型与复现材料

| Artifact | Status | URL | Version/Commit | License | What It Can Verify |
|---|---|---|---|---|---|
| Official code | not checked | | | | |
| Weights/model card | not checked | | | | |
| Dataset | not checked | | | | |
| Demo/project page | not checked | | | | |
| Community reproduction | not checked | | | | |

Use only: `verified`, `author_linked`, `author_claimed`,
`community_implementation`, `not_found`, `not_released`, `not_checked`, or
`not_applicable`. `not_found` is search-bounded, not a claim of nonexistence.
Record the source version, retrieval date, and evidence boundary.

## 13. 失败模式、局限与常见误解

## 14. 与读者项目的连接

## 15. 工程与研究启示

## 16. 证据置信度与位置

## 17. 自测：能否复述清楚

- [ ] Can I explain the original bottleneck without naming the proposed method?
- [ ] Can I trace one example through the full data and training flow?
- [ ] Can I explain the objective’s terms and assumptions?
- [ ] Can I pair the key innovation with its main defect and a later fix?
- [ ] Can I distinguish paper claims from later evidence and my inference?
- [ ] Can I explain why this loss is a reasonable proxy, who receives its gradients, and where it can disagree with the real metric?
