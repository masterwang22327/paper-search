# Research Roadmap

Active research is task-local, but the research program remains long term.
Use this roadmap to choose the next task; do not treat it as an instruction to
run all tracks at once.

## Goal

Build technical judgment rather than a pile of PDFs: reconstruct method
lineage, distinguish claims from evidence, understand objectives and data/
gradient flow, identify boundary conditions, and turn selected findings into
reproducible engineering or research actions.

## Priority Tracks

| Priority | Track | Questions To Resolve |
| --- | --- | --- |
| P0 | PPO, RLHF, GRPO, and Reasoning RL | What changes when the critic is removed? Which gains come from objective, data, reward, or sampling budget? Which later corrections address length bias, variance, clipping, or KL behavior? |
| P1 | Agent RL | How do long-horizon credit assignment, environment feedback, memory, planning, and cost-aware evaluation change the RL problem? |
| P1 | Inference-time search, verifier, and evaluation | Where does training outperform search, and how do verifier/PRM/judge reliability and reward hacking limit conclusions? |
| P2 | Training systems and reproducibility | What is required to reproduce a result: rollout/training topology, data, code revision, hardware, evaluation, and hidden defaults? |
| P2 | Background bridges | Connect vision, retrieval/RAG, graph reasoning, multilingual systems, speech, and diffusion to the main tracks when the connection clarifies a mechanism. |

## Reading Mix

For each topic, include a bounded mix of foundational work, representative
methods, corrections/negative results, systems/reproductions, and recent
preprints. A recent preprint is not automatically important; record version and
peer-review status.

## Suggested First Task Package

1. `ppo-lineage`: PPO objective, clipping, KL, advantage estimation.
2. `grpo-baseline`: DeepSeekMath/GRPO objective and official artifacts.
3. `grpo-corrections`: RLOO, Dr. GRPO, DAPO, GSPO, and evidence-backed
   comparison boundaries.
4. `reasoning-rlvr`: verifiable rewards, reasoning data, evaluation leakage,
   and when claimed gains are experimentally supported.

Use one task per question, then a dedicated synthesis task. Promote only
audited records to `library/`.
