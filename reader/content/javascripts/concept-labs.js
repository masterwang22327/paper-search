(function () {
  "use strict";

  const CONTEXT_OPTIONS = [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072];
  const BLOCK_NODES = {
    "norm-1": {
      title: "RMSNorm：只处理当前词元的尺度",
      read: "当前位置的隐藏向量",
      change: "向量尺度，不改 shape",
      invariant: "不读取其他 token，不保存历史"
    },
    attention: {
      title: "Attention：这一步才跨位置读取历史",
      read: "当前 Q 与所有可见历史 K/V",
      change: "RoPE 改 Q/K 坐标；GQA 改 K/V 头的共享方式",
      invariant: "仍保留多个 Query heads，仍执行注意力打分"
    },
    "residual-1": {
      title: "第一次残差：把读取结果写回主状态",
      read: "原始状态 X 与 attention 输出",
      change: "用逐元素相加产生 X1",
      invariant: "主路保留显式 identity 项，shape 不变"
    },
    "norm-2": {
      title: "第二次 RMSNorm：为前馈分支重新整理尺度",
      read: "attention 残差相加后的 X1",
      change: "前馈分支看到的向量尺度",
      invariant: "不跨 token，不会替代残差主路"
    },
    swiglu: {
      title: "SwiGLU：在当前位置上做内容门控",
      read: "当前词元的归一化状态",
      change: "一条 gate 分支控制 value 分支通过多少",
      invariant: "不读历史 token，不是 attention 式路由"
    },
    "residual-2": {
      title: "第二次残差：得到传给下一层的 Y",
      read: "X1 与 SwiGLU 的逐位置输出",
      change: "把前馈改写合并回残差流",
      invariant: "仍是隐藏状态，不是 logits 或概率"
    }
  };
  const LLAMA_CONTEXT_OPTIONS = [128, 256, 512, 1024, 2048];
  const LLAMA_MODELS = {
    "7b": {label: "7B", dim: 4096, layers: 32, heads: 32, tokens: 1e12},
    "13b": {label: "13B", dim: 5120, layers: 40, heads: 40, tokens: 1e12},
    "33b": {label: "33B", dim: 6656, layers: 60, heads: 52, tokens: 1.4e12},
    "65b": {label: "65B", dim: 8192, layers: 80, heads: 64, tokens: 1.4e12}
  };
  const DISTILLATION_MODES = {
    seqkd: {
      badge: "SeqKD · offline hard response",
      rollout: ["teacher beam", "teacher 先生成固定目标语料"],
      privilege: ["无额外特权", "teacher 与 student 接收同一输入"],
      target: ["hard response", "只保留选中序列的 next token"],
      update: ["student NLL", "teacher decode 不可导；只更新 student"],
      density: "每位置 × 1 token",
      cost: "teacher decode + student forward",
      risk: "只保留一条最高概率序列，丢失分布与多样性"
    },
    gkd: {
      badge: "GKD · external teacher",
      rollout: ["当前 student", "按部署上下文采样前缀"],
      privilege: ["同一 prompt", "外部 teacher 在 student prefix 上重算"],
      target: ["更强 frozen teacher", "full-V logits 或 sampled-token 分数"],
      update: ["token divergence", "只更新 student；rollout/teacher detach"],
      density: "每位置 × 完整词表",
      cost: "student rollout + 大 teacher forward",
      risk: "异常前缀上的 recovery 未必正确"
    },
    opsd: {
      badge: "OPSD · privileged self-teacher",
      rollout: ["当前 student", "按部署上下文采样前缀"],
      privilege: ["参考解 y*", "仅 teacher 可见"],
      target: ["同源 fixed teacher", "student prefix 上的 full-V logits"],
      update: ["forward KL", "只更新 student；rollout/teacher detach"],
      density: "每位置 × 完整词表",
      cost: "rollout + 同模型双条件 forward",
      risk: "hindsight/style 压过纠错"
    },
    sdpo: {
      badge: "SDPO · feedback self-teacher",
      rollout: ["当前 policy", "执行后保留原始 attempt prefix"],
      privilege: ["环境文本反馈", "错误、测试或成功 sibling 仅 teacher 可见"],
      target: ["反馈条件 self-teacher", "同一 attempt 上重算 token 分布"],
      update: ["dense logit advantage", "可接入 RLVR optimizer；teacher detach"],
      density: "每位置 × full/top-k 分布",
      cost: "rollout + 环境 + teacher score",
      risk: "反馈错误、泄漏或 prompt injection"
    },
    uopsd: {
      badge: "U-OPSD · consensus self-teacher",
      rollout: ["同模型 G 次采样", "默认 G=8；先抽取并规范化答案"],
      privilege: ["多数票 agreeing trace", "无 gold；置信度分母含截断 rollout"],
      target: ["fixed/EMA self-teacher", "只在 disagreeing prefix 上重算"],
      update: ["forward KL", "vote/parser/teacher/rollout 全 detach"],
      density: "被选分歧轨迹 × 完整词表",
      cost: "G rollouts + vote + 双条件 score",
      risk: "相关错误可高置信自我强化"
    },
    beta: {
      badge: "β-OPSD · reference-to-teacher target",
      rollout: ["当前 student", "仍在 deployment-view 上采样"],
      privilege: ["参考解 y*", "privileged teacher 与 reference 同时定目标"],
      target: ["几何插值 target", "prefix-local logits 近似序列最优分布"],
      update: ["return-to-go", "future log-ratio detach 后更新 student"],
      density: "每位置 × 插值分布",
      cost: "rollout + reference/teacher/student score",
      risk: "局部插值与长程最优仍有近似差"
    }
  };

  function formatInteger(value) {
    return Math.round(value).toLocaleString("en-US");
  }

  function formatBytes(value) {
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let amount = value;
    let unit = 0;
    while (amount >= 1024 && unit < units.length - 1) {
      amount /= 1024;
      unit += 1;
    }
    const digits = amount >= 100 || Number.isInteger(amount) ? 0 : amount >= 10 ? 1 : 2;
    return `${amount.toFixed(digits)} ${units[unit]}`;
  }

  function modeFor(queryHeads, kvHeads) {
    if (kvHeads === queryHeads) return "MHA";
    if (kvHeads === 1) return "MQA";
    return "GQA";
  }

  function setText(root, selector, value) {
    const element = root.querySelector(selector);
    if (element) element.textContent = value;
  }

  function initializeBlockMap(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const buttons = Array.from(root.querySelectorAll("[data-block-node]"));
    const render = key => {
      const detail = BLOCK_NODES[key];
      if (!detail) return;
      buttons.forEach(button => {
        const active = button.dataset.blockNode === key;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      setText(root, "[data-block-readout-title]", detail.title);
      setText(root, "[data-block-readout-read]", detail.read);
      setText(root, "[data-block-readout-change]", detail.change);
      setText(root, "[data-block-readout-invariant]", detail.invariant);
    };
    buttons.forEach(button => button.addEventListener("click", () => render(button.dataset.blockNode)));
  }

  function initializeAttentionLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";

    const state = {
      queryHeads: Number(root.dataset.queryHeads) || 8,
      kvHeads: Number(root.dataset.kvHeads) || 2,
      headDim: Number(root.dataset.headDim) || 64,
      context: Number(root.dataset.context) || 4096,
      layers: Number(root.dataset.layers) || 32,
      batch: Number(root.dataset.batch) || 1,
      bytes: Number(root.dataset.bytes) || 2,
      selectedHead: 0
    };
    const form = root.querySelector("form");
    form?.addEventListener("submit", event => event.preventDefault());

    function gqaDefault() {
      return Math.max(2, state.queryHeads / 4);
    }

    function renderKvControls() {
      const container = root.querySelector('[data-attention-control="kv-heads"]');
      if (!container) return;
      container.replaceChildren();
      for (let value = 1; value <= state.queryHeads; value += 1) {
        if (state.queryHeads % value !== 0) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.value = String(value);
        button.textContent = String(value);
        button.classList.toggle("is-active", value === state.kvHeads);
        button.setAttribute("aria-pressed", String(value === state.kvHeads));
        button.setAttribute("aria-label", `${value} 个 KV heads`);
        button.addEventListener("click", () => {
          state.kvHeads = value;
          render();
          root.querySelector(`[data-attention-control="kv-heads"] [data-value="${value}"]`)?.focus();
        });
        container.appendChild(button);
      }
    }

    function renderHeadMap(groupSize) {
      const strip = root.querySelector("[data-attention-q-strip]");
      if (!strip) return;
      strip.replaceChildren();
      state.selectedHead = Math.min(state.selectedHead, state.queryHeads - 1);
      const selectedGroup = Math.floor(state.selectedHead / groupSize);
      for (let head = 0; head < state.queryHeads; head += 1) {
        const group = Math.floor(head / groupSize);
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.head = String(head);
        button.dataset.group = String(group);
        button.classList.toggle("is-group-start", head % groupSize === 0);
        button.classList.toggle("is-group-peer", group === selectedGroup);
        button.classList.toggle("is-selected", head === state.selectedHead);
        button.textContent = `Q${head}`;
        button.setAttribute("aria-label", `Query head ${head} 使用 KV group ${group}`);
        button.setAttribute("aria-pressed", String(head === state.selectedHead));
        button.addEventListener("click", () => {
          state.selectedHead = head;
          render();
        });
        strip.appendChild(button);
      }
      const group = Math.floor(state.selectedHead / groupSize);
      const start = group * groupSize;
      const end = start + groupSize - 1;
      setText(root, "[data-attention-selected-map]", `Q${state.selectedHead} → KV${group}`);
      setText(root, "[data-attention-selected-query]", `Q${state.selectedHead}`);
      setText(root, "[data-attention-selected-kv]", `KV${group}`);
      root.querySelectorAll("[data-attention-selected-query], [data-attention-selected-kv]").forEach(element => {
        element.classList.add("is-selected-group");
      });
      const range = groupSize === 1
        ? `Q${start} 独享这组 K/V`
        : groupSize === state.queryHeads
          ? `Q0–Q${end} 全部共用这组 K/V`
          : `Q${start}–Q${end} 共用这组 K/V`;
      setText(root, "[data-attention-group-range]", range);
    }

    function render() {
      if (state.queryHeads % state.kvHeads !== 0) state.kvHeads = gqaDefault();
      const mode = modeFor(state.queryHeads, state.kvHeads);
      const groupSize = state.queryHeads / state.kvHeads;
      const totalElements = 2 * state.batch * state.layers * state.context * state.kvHeads * state.headDim;
      const totalBytes = totalElements * state.bytes;
      const mhaBytes = totalBytes * state.queryHeads / state.kvHeads;
      const cacheFraction = totalBytes / mhaBytes;
      const reduction = state.queryHeads / state.kvHeads;
      const savedPercent = Number(((1 - cacheFraction) * 100).toFixed(1));
      const scores = state.batch * state.queryHeads * state.context;

      root.dataset.mode = mode.toLowerCase();
      setText(root, "[data-attention-mode-label]", `${mode} · ${state.queryHeads}:${state.kvHeads}`);
      root.querySelectorAll("[data-attention-preset]").forEach(button => {
        button.classList.toggle("is-active", button.dataset.attentionPreset === mode.toLowerCase());
        button.setAttribute("aria-pressed", String(button.dataset.attentionPreset === mode.toLowerCase()));
      });
      root.querySelectorAll('[data-attention-control="query-heads"] button').forEach(button => {
        button.classList.toggle("is-active", Number(button.dataset.value) === state.queryHeads);
        button.setAttribute("aria-pressed", String(Number(button.dataset.value) === state.queryHeads));
      });
      root.querySelectorAll('[data-attention-control="bytes"] button').forEach(button => {
        button.classList.toggle("is-active", Number(button.dataset.value) === state.bytes);
        button.setAttribute("aria-pressed", String(Number(button.dataset.value) === state.bytes));
      });
      renderKvControls();
      renderHeadMap(groupSize);

      setText(root, '[data-attention-output="context"]', formatInteger(state.context));
      context?.setAttribute("aria-valuetext", `${formatInteger(state.context)} tokens`);
      setText(root, '[data-attention-output="layers"]', formatInteger(state.layers));
      setText(root, '[data-attention-output="batch"]', formatInteger(state.batch));
      setText(root, '[data-attention-shape="q"]', `[${state.batch}, ${state.queryHeads}, 1, ${state.headDim}]`);
      setText(root, '[data-attention-shape="kv"]', `[${state.batch}, ${state.kvHeads}, ${state.context}, ${state.headDim}]`);
      setText(root, "[data-attention-projection]", `${state.queryHeads * state.headDim} / ${state.kvHeads * state.headDim}`);
      setText(root, "[data-attention-cache]", formatBytes(totalBytes));
      setText(root, "[data-attention-elements]", `${formatInteger(totalElements)} 个元素`);
      setText(root, "[data-attention-scores]", formatInteger(scores));
      setText(root, "[data-attention-score-formula]", `${state.batch} × ${state.queryHeads} × ${formatInteger(state.context)}`);
      setText(root, "[data-attention-query-copy]", state.queryHeads);
      const cacheBar = root.querySelector("[data-attention-cache-bar]");
      if (cacheBar) cacheBar.style.width = `${Math.max(2, cacheFraction * 100)}%`;
      const percent = `${Number((cacheFraction * 100).toFixed(1))}%`;
      const compare = reduction === 1
        ? "与同参数 MHA 相同，尚未共享 K/V heads。"
        : `是同参数 MHA 的 ${percent}，减少 ${savedPercent}%（缩小为 1/${reduction}）。`;
      setText(root, "[data-attention-cache-compare]", compare);

      let conclusion;
      let warning;
      if (mode === "MHA") {
        conclusion = `MHA 让 ${state.queryHeads} 个 Query heads 各自拥有一组 K/V。`;
        warning = "这是当前参数下的 cache 基线；Query 头与 KV 头一一对应。";
      } else if (mode === "MQA") {
        conclusion = `MQA 让全部 ${state.queryHeads} 个 Query heads 共享唯一一组 K/V。`;
        warning = `KV payload 减少 ${savedPercent}%（缩小为 1/${reduction}），但更强的参数共享可能影响质量与训练稳定性。`;
      } else {
        conclusion = `GQA 让每 ${groupSize} 个 Query heads 共享一组 K/V。`;
        warning = `KV payload 减少 ${savedPercent}%（缩小为 1/${reduction}），但不能据此推出整层延迟快 ${reduction} 倍。`;
      }
      setText(root, "[data-attention-conclusion]", conclusion);
      setText(root, "[data-attention-warning]", warning);
      setText(
        root,
        "[data-attention-formula-values]",
        `2 × ${state.batch} × ${state.layers} × ${formatInteger(state.context)} × ${state.kvHeads} × ${state.headDim} × ${state.bytes} = ${formatBytes(totalBytes)}`
      );
    }

    root.querySelectorAll('[data-attention-control="query-heads"] button').forEach(button => {
      button.addEventListener("click", () => {
        const priorMode = modeFor(state.queryHeads, state.kvHeads);
        state.queryHeads = Number(button.dataset.value);
        state.kvHeads = priorMode === "MHA" ? state.queryHeads : priorMode === "MQA" ? 1 : gqaDefault();
        render();
      });
    });
    root.querySelectorAll("[data-attention-preset]").forEach(button => {
      button.addEventListener("click", () => {
        const preset = button.dataset.attentionPreset;
        state.kvHeads = preset === "mha" ? state.queryHeads : preset === "mqa" ? 1 : gqaDefault();
        render();
      });
    });
    root.querySelectorAll('[data-attention-control="bytes"] button').forEach(button => {
      button.addEventListener("click", () => {
        state.bytes = Number(button.dataset.value);
        render();
      });
    });
    const headDim = root.querySelector('[data-attention-input="head-dim"]');
    headDim?.addEventListener("change", () => {
      state.headDim = Number(headDim.value);
      render();
    });
    const context = root.querySelector('[data-attention-input="context-index"]');
    context?.addEventListener("input", () => {
      state.context = CONTEXT_OPTIONS[Number(context.value)];
      render();
    });
    const layers = root.querySelector('[data-attention-input="layers"]');
    layers?.addEventListener("input", () => {
      state.layers = Number(layers.value);
      render();
    });
    const batch = root.querySelector('[data-attention-input="batch"]');
    batch?.addEventListener("input", () => {
      state.batch = Number(batch.value);
      render();
    });
    render();
  }

  const LIFECYCLE_MODES = {
    train: {
      badge: "训练 · 参数与优化器状态更新",
      persistLabel: "跨 training step 保留",
      objects: {
        input: ["离散输入/标签", "tokens + targets", "定义有效监督位置"],
        hidden: ["连续隐藏状态", "[B, T, d]", "跨层前向，当前 batch"],
        cache: ["训练中间量", "loss + gradient", "当前 training step"],
        output: ["持久更新", "optimizer step", "写回参数/优化器状态"]
      },
      persistent: "更新后的 checkpoint 参数与 optimizer state",
      release: "activation、loss、gradient 与 step 临时量",
      absent: "跨生成步 KV cache；训练不处在自回归 serving 请求中",
      persistentObject: "output"
    },
    prefill: {
      badge: "Prefill · 参数冻结，批量建立 cache",
      persistLabel: "交给同一请求的 Decode",
      objects: {
        input: ["离散输入", "完整 prompt tokens", "一次送入多个位置"],
        hidden: ["连续隐藏状态", "[B, Tprompt, d]", "并行计算 prompt"],
        cache: ["请求内状态", "批量写入 K/V", "交给后续 Decode"],
        output: ["输出", "首个 next-token logits", "交给解码器"]
      },
      persistent: "checkpoint 参数 + 当前请求 KV cache",
      release: "Prefill hidden 与临时 attention 中间量",
      absent: "label、loss、gradient、optimizer update",
      persistentObject: "cache"
    },
    decode: {
      badge: "Decode · 参数冻结",
      persistLabel: "跨生成步保留",
      objects: {
        input: ["离散输入", "新 token id", "只索引表示"],
        hidden: ["连续隐藏状态", "[B, 1, d]", "当前生成步"],
        cache: ["请求内状态", "追加本步 K/V", "跨生成步保留"],
        output: ["输出", "next-token logits", "交给解码器"]
      },
      persistent: "checkpoint 参数；本次生成不会改写",
      release: "隐藏状态与整份请求 KV cache",
      absent: "label、loss、gradient、optimizer update",
      persistentObject: "cache"
    }
  };

  function initializeLifecycleLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const buttons = Array.from(root.querySelectorAll("[data-lifecycle-mode]"));
    const render = mode => {
      const state = LIFECYCLE_MODES[mode];
      if (!state) return;
      buttons.forEach(button => {
        const active = button.dataset.lifecycleMode === mode;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      setText(root, "[data-lifecycle-badge]", state.badge);
      Object.entries(state.objects).forEach(([key, values]) => {
        const object = root.querySelector(`[data-life-object="${key}"]`);
        if (!object) return;
        const [label, value, note] = values;
        const labelNode = object.querySelector("span");
        const valueNode = object.querySelector("strong");
        const noteNode = object.querySelector("small");
        if (labelNode) labelNode.textContent = label;
        if (valueNode) valueNode.textContent = value;
        if (noteNode) noteNode.textContent = note;
        object.classList.toggle("is-persistent", key === state.persistentObject);
      });
      setText(root, "[data-lifecycle-persist-label]", state.persistLabel);
      setText(root, "[data-lifecycle-persist]", state.persistent);
      setText(root, "[data-lifecycle-release]", state.release);
      setText(root, "[data-lifecycle-absent]", state.absent);
    };
    buttons.forEach(button => button.addEventListener("click", () => render(button.dataset.lifecycleMode)));
    render("decode");
  }

  function normalizeVector(values, center) {
    const mean = center ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
    const denominator = Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length);
    return values.map(value => (value - mean) / denominator);
  }

  function formatVector(values) {
    return `[${values.map(value => value.toFixed(3)).join(", ")}]`;
  }

  function initializeNormalizationLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const base = (root.dataset.baseVector || "1,2,4").split(",").map(Number);
    const baselineLayer = normalizeVector(base, true);
    const baselineRms = normalizeVector(base, false);
    const scaleInput = root.querySelector('[data-norm-input="scale"]');
    const shiftInput = root.querySelector('[data-norm-input="shift"]');
    const render = () => {
      const scale = Number(scaleInput?.value || 1);
      const shift = Number(shiftInput?.value || 0);
      const transformed = base.map(value => scale * value + shift);
      const layer = normalizeVector(transformed, true);
      const rms = normalizeVector(transformed, false);
      const layerDelta = Math.max(...layer.map((value, index) => Math.abs(value - baselineLayer[index])));
      const rmsDelta = Math.max(...rms.map((value, index) => Math.abs(value - baselineRms[index])));
      setText(root, '[data-norm-output="scale"]', scale.toFixed(2));
      setText(root, '[data-norm-output="shift"]', shift.toFixed(2));
      setText(root, '[data-norm-vector="transformed"]', `x' = ${formatVector(transformed)}`);
      setText(root, '[data-norm-vector="layer"]', formatVector(layer));
      setText(root, '[data-norm-vector="rms"]', formatVector(rms));
      setText(root, '[data-norm-delta="layer"]', layerDelta.toFixed(3));
      setText(root, '[data-norm-delta="rms"]', rmsDelta.toFixed(3));
      setText(root, '[data-norm-verdict="layer"]', "正缩放、统一平移都被抵消");
      setText(root, '[data-norm-verdict="rms"]', Math.abs(shift) < 1e-9 ? "正缩放被抵消" : "统一平移没有被抵消");
      const layerBar = root.querySelector('[data-norm-bar="layer"]');
      const rmsBar = root.querySelector('[data-norm-bar="rms"]');
      if (layerBar) layerBar.style.width = `${Math.min(100, layerDelta * 120)}%`;
      if (rmsBar) rmsBar.style.width = `${Math.min(100, rmsDelta * 120)}%`;
    };
    scaleInput?.addEventListener("input", render);
    shiftInput?.addEventListener("input", render);
    root.querySelector("form")?.addEventListener("submit", event => event.preventDefault());
    render();
  }

  function setSignedBar(root, key, value, limit) {
    const bar = root.querySelector(`[data-swiglu-bar="${key}"]`);
    if (!bar) return;
    bar.classList.toggle("is-negative", value < 0);
    bar.style.setProperty("--magnitude", `${Math.min(50, Math.abs(value) / limit * 50)}%`);
  }

  function initializeSwigluLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const gateInput = root.querySelector('[data-swiglu-input="gate"]');
    const valueInput = root.querySelector('[data-swiglu-input="value"]');
    const render = () => {
      const gate = Number(gateInput?.value || 0);
      const value = Number(valueInput?.value || 0);
      const silu = gate / (1 + Math.exp(-gate));
      const product = silu * value;
      [["gate", gate], ["value", value]].forEach(([key, number]) => setText(root, `[data-swiglu-value="${key}"]`, number.toFixed(2)));
      [["gate", gate], ["silu", silu], ["product", product]].forEach(([key, number]) => {
        setText(root, `[data-swiglu-number="${key}"]`, number.toFixed(3));
        setSignedBar(root, key, number, key === "gate" ? 4 : 2);
      });
      setText(root, "[data-swiglu-output]", `输出 = ${product.toFixed(3)}`);
    };
    gateInput?.addEventListener("input", render);
    valueInput?.addEventListener("input", render);
    root.querySelector("form")?.addEventListener("submit", event => event.preventDefault());
    render();
  }

  function canvasContext(canvas, cssHeight) {
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    const width = Math.max(320, Math.round(canvas.getBoundingClientRect().width || canvas.width));
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(cssHeight * ratio);
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { context, width, height: cssHeight };
  }

  function initializeRopeLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const canvas = root.querySelector("[data-rope-canvas]");
    const inputs = {
      query: root.querySelector('[data-rope-input="query"]'),
      key: root.querySelector('[data-rope-input="key"]'),
      shift: root.querySelector('[data-rope-input="shift"]'),
      frequency: root.querySelector('[data-rope-input="frequency"]')
    };
    const drawPanel = (context, centerX, centerY, radius, queryAngle, keyAngle, label) => {
      context.save();
      context.strokeStyle = "rgba(127, 139, 146, .35)";
      context.lineWidth = 1;
      context.beginPath();
      context.arc(centerX, centerY, radius, 0, Math.PI * 2);
      context.moveTo(centerX - radius - 8, centerY);
      context.lineTo(centerX + radius + 8, centerY);
      context.moveTo(centerX, centerY - radius - 8);
      context.lineTo(centerX, centerY + radius + 8);
      context.stroke();
      const arrow = (angle, color, name) => {
        const endX = centerX + Math.cos(angle) * radius;
        const endY = centerY - Math.sin(angle) * radius;
        context.strokeStyle = color;
        context.fillStyle = color;
        context.lineWidth = 4;
        context.beginPath();
        context.moveTo(centerX, centerY);
        context.lineTo(endX, endY);
        context.stroke();
        context.beginPath();
        context.arc(endX, endY, 5, 0, Math.PI * 2);
        context.fill();
        context.font = "600 13px system-ui, sans-serif";
        context.fillText(name, endX + 7, endY - 5);
      };
      arrow(queryAngle, "#137c78", "Q");
      arrow(keyAngle, "#d46d47", "K");
      context.fillStyle = "rgba(92, 103, 110, .9)";
      context.font = "600 12px system-ui, sans-serif";
      context.textAlign = "center";
      context.fillText(label, centerX, centerY + radius + 28);
      context.restore();
    };
    const render = () => {
      const query = Number(inputs.query?.value || 0);
      const key = Number(inputs.key?.value || 0);
      const shift = Number(inputs.shift?.value || 0);
      const frequency = Number(inputs.frequency?.value || 15);
      const theta = frequency * Math.PI / 180;
      const dot = Math.cos((key - query) * theta);
      Object.entries({ query, key, shift }).forEach(([keyName, value]) => setText(root, `[data-rope-output="${keyName}"]`, value));
      setText(root, '[data-rope-output="frequency"]', `${frequency}°`);
      setText(root, "[data-rope-dot]", `点积 ${dot.toFixed(3)}`);
      setText(root, "[data-rope-positions]", `m+s=${query + shift} · n+s=${key + shift}`);
      setText(root, "[data-rope-relative]", `n-m=${key - query}`);
      if (!canvas) return;
      const { context, width, height } = canvasContext(canvas, 270);
      context.clearRect(0, 0, width, height);
      const radius = Math.min(76, width * 0.12);
      drawPanel(context, width * 0.26, height * 0.45, radius, query * theta, key * theta, `原位置 m=${query}, n=${key}`);
      drawPanel(context, width * 0.74, height * 0.45, radius, (query + shift) * theta, (key + shift) * theta, `共同平移 +${shift}`);
      context.fillStyle = "rgba(92, 103, 110, .85)";
      context.font = "600 12px system-ui, sans-serif";
      context.textAlign = "center";
      context.fillText(`两图夹角相同：Δ=${key - query}，cos(Δθ)=${dot.toFixed(3)}`, width / 2, height - 8);
    };
    Object.values(inputs).forEach(input => input?.addEventListener("input", render));
    root.querySelector("form")?.addEventListener("submit", event => event.preventDefault());
    if (typeof ResizeObserver !== "undefined" && canvas) new ResizeObserver(render).observe(canvas);
    render();
  }

  function initializeSlidingWindowLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const canvas = root.querySelector("[data-swa-canvas]");
    const inputs = {
      window: root.querySelector('[data-swa-input="window"]'),
      layers: root.querySelector('[data-swa-input="layers"]'),
      position: root.querySelector('[data-swa-input="position"]')
    };
    const render = () => {
      const windowSize = Number(inputs.window?.value || 4);
      const layers = Number(inputs.layers?.value || 3);
      const position = Number(inputs.position?.value || 15);
      Object.entries({ window: windowSize, layers, position }).forEach(([key, value]) => setText(root, `[data-swa-output="${key}"]`, value));
      setText(root, "[data-swa-summary]", `直接 ${windowSize} · 理论接力约 ${Math.min(position + 1, windowSize * layers)}`);
      setText(root, "[data-swa-position]", position);
      setText(root, "[data-swa-slot]", position % windowSize);
      const slots = root.querySelector("[data-swa-slots]");
      if (slots) {
        slots.replaceChildren();
        for (let slot = 0; slot < windowSize; slot += 1) {
          const span = document.createElement("span");
          span.textContent = String(slot);
          span.classList.toggle("is-active", slot === position % windowSize);
          slots.appendChild(span);
        }
      }
      if (!canvas) return;
      const { context, width, height } = canvasContext(canvas, 285);
      context.clearRect(0, 0, width, height);
      const tokens = 24;
      const left = 52;
      const right = 16;
      const top = 24;
      const rowGap = (height - top - 36) / layers;
      const xStep = (width - left - right) / (tokens - 1);
      context.font = "11px system-ui, sans-serif";
      for (let depth = 0; depth <= layers; depth += 1) {
        const y = top + depth * rowGap;
        const reach = depth === 0 ? 1 : Math.min(position + 1, depth * windowSize);
        const start = position - reach + 1;
        context.fillStyle = "rgba(92, 103, 110, .75)";
        context.textAlign = "right";
        context.fillText(depth === 0 ? `L${layers}` : `L${layers - depth}`, left - 12, y + 4);
        for (let token = 0; token < tokens; token += 1) {
          const x = left + token * xStep;
          const reachable = token >= start && token <= position;
          const direct = depth === 1 && reachable;
          context.beginPath();
          context.arc(x, y, token === position && depth === 0 ? 5 : 3.5, 0, Math.PI * 2);
          context.fillStyle = direct ? "#d46d47" : reachable ? "#65aaa5" : "rgba(127, 139, 146, .22)";
          context.fill();
        }
        if (depth > 0) {
          const fromX = left + Math.max(0, start) * xStep;
          const toX = left + position * xStep;
          context.strokeStyle = depth === 1 ? "rgba(212, 109, 71, .55)" : "rgba(19, 124, 120, .32)";
          context.lineWidth = 2;
          context.beginPath();
          context.moveTo(fromX, y - rowGap + 5);
          context.lineTo(fromX, y - 5);
          context.lineTo(toX, y - 5);
          context.stroke();
        }
      }
      context.fillStyle = "rgba(92, 103, 110, .75)";
      context.textAlign = "center";
      for (let token = 0; token < tokens; token += 4) context.fillText(String(token), left + token * xStep, height - 7);
    };
    Object.values(inputs).forEach(input => input?.addEventListener("input", render));
    root.querySelector("form")?.addEventListener("submit", event => event.preventDefault());
    if (typeof ResizeObserver !== "undefined" && canvas) new ResizeObserver(render).observe(canvas);
    render();
  }

  function initializeInterventionMap(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const buttons = Array.from(root.querySelectorAll("[data-intervention-title]"));
    const render = button => {
      buttons.forEach(candidate => {
        const active = candidate === button;
        candidate.classList.toggle("is-active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
      setText(root, "[data-intervention-readout-title]", button.dataset.interventionTitle);
      setText(root, "[data-intervention-readout-change]", button.dataset.interventionChange);
      setText(root, "[data-intervention-readout-invariant]", button.dataset.interventionInvariant);
      setText(root, "[data-intervention-readout-cost]", button.dataset.interventionCost);
    };
    buttons.forEach(button => button.addEventListener("click", () => render(button)));
  }

  const REWARD_POLICY_MODES = {
    "best-of-n": {
      badge: "不更新 generator",
      data: "冻结 generator 的 N 条候选",
      dataNote: "同一 checkpoint，可增加测试时计算",
      score: "冻结 ORM / PRM 打分",
      scoreNote: "argmax 或答案组加权",
      update: "无",
      updateNote: "选择操作不可导",
      artifact: "被选回答",
      artifactNote: "generator checkpoint 不变",
      inner: "无 policy 训练",
      refresh: "下一次请求可继续用同一模型",
      verdict: "推理时选择，不是 on-policy RL",
      warning: "候选变多提高覆盖率，也会增加撞中 verifier 漏洞的机会",
      updatesParameters: false
    },
    "rs-sft": {
      badge: "CE 更新 generator",
      data: "上一轮 policy 生成的候选",
      dataNote: "checker / RM / search 先选优",
      score: "离散保留 top samples",
      scoreNote: "selector 不接梯度",
      update: "SFT cross-entropy",
      updateNote: "梯度只到 generator",
      artifact: "新 generator checkpoint",
      artifactNote: "单次服务不再依赖同等搜索",
      inner: "固定 selected text，是 offline imitation",
      refresh: "外层 round 用新 checkpoint 重新采样",
      verdict: "内层 offline SFT，外层 online data refresh",
      warning: "过滤错误会被写回模型；历史 replay 与 selector 版本必须固定",
      updatesParameters: true
    },
    "policy-gradient": {
      badge: "reward 更新 policy",
      data: "old / behavior policy rollouts",
      dataNote: "同题 group 可构造 baseline",
      score: "checker / RM 给 trajectory reward",
      scoreNote: "reward 经 value / advantage 变换",
      update: "PPO / RLOO / GRPO loss",
      updateNote: "梯度到 current policy；可能另训 value",
      artifact: "policy + rollout statistics",
      artifactNote: "old/reference/RM 是不同对象",
      inner: "一批 rollout 可有限复用，ratio 修正行为分布",
      refresh: "rollout round 后刷新 old / behavior policy",
      verdict: "近 on-policy policy optimization",
      warning: "on-policy 只说明样本生产者，不保证 reward 或 estimator 正确",
      updatesParameters: true
    },
    dpo: {
      badge: "pair loss 更新 policy",
      data: "固定 chosen / rejected pairs",
      dataNote: "通常来自 human、AI 或历史 policy",
      score: "current/reference 四个 log-prob",
      scoreNote: "没有显式 RM 或 critic",
      update: "DPO pair classification loss",
      updateNote: "只有 current policy 接梯度",
      artifact: "偏好优化后的 policy",
      artifactNote: "reference 保持冻结",
      inner: "minibatch pair 不随 current policy 更新",
      refresh: "标准离线 DPO 不要求刷新；外层飞轮可以另行刷新",
      verdict: "offline preference optimization",
      warning: "固定 pair 简化训练图，但不消除偏好偏差或支持集外问题",
      updatesParameters: true
    },
    "mcts-dpo": {
      badge: "内层固定，外层刷新",
      data: "pi_i 生成并自评的 MCTS tree",
      dataNote: "树上最高/最低 Q sibling 组成 pair",
      score: "outcome + self-eval -> MCTS Q",
      scoreNote: "search 负责造 preference data",
      update: "DPO 把 pi_i 更新为 pi_(i+1)",
      updateNote: "树本身无需可导",
      artifact: "新 policy + 新一轮采样器",
      artifactNote: "下一轮从更新后 policy 建树",
      inner: "单轮 DPO 使用固定 step pairs",
      refresh: "每个 outer iteration 重新生成树与 pair",
      verdict: "inner offline pair，outer online/on-policy refresh",
      warning: "这是一种公开先例，不是 Llama 3.1 内部 MCTS 配方的复建",
      updatesParameters: true
    },
    ilql: {
      badge: "固定日志上的 offline RL",
      data: "behavior policy 产生的静态 transition log",
      dataNote: "训练期间无需 current policy 回环境采样",
      score: "reward + Bellman target",
      scoreNote: "expectile V 与 conservative Q 控制支持集",
      update: "Q / V value networks",
      updateNote: "另有监督训练的 behavior LM",
      artifact: "behavior LM + Q/V + target net",
      artifactNote: "部署时用 Q-V 扰动 logits",
      inner: "全程在固定 dataset D 上训练",
      refresh: "没有外层 rollout refresh 要求",
      verdict: "value-based offline RL",
      warning: "日志若缺少高质量行为，support constraint 不能凭空补出来",
      updatesParameters: true
    }
  };

  function initializeRewardPolicyClock(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const buttons = Array.from(root.querySelectorAll("[data-reward-mode]"));
    const render = mode => {
      const state = REWARD_POLICY_MODES[mode];
      if (!state) return;
      buttons.forEach(button => {
        const active = button.dataset.rewardMode === mode;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      const values = {
        badge: state.badge,
        data: state.data,
        "data-note": state.dataNote,
        score: state.score,
        "score-note": state.scoreNote,
        update: state.update,
        "update-note": state.updateNote,
        artifact: state.artifact,
        "artifact-note": state.artifactNote,
        inner: state.inner,
        refresh: state.refresh,
        verdict: state.verdict,
        warning: state.warning
      };
      Object.entries(values).forEach(([key, value]) => setText(root, `[data-reward-${key}]`, value));
      root.querySelector("[data-reward-update-node]")?.classList.toggle("is-updating", state.updatesParameters);
    };
    buttons.forEach(button => button.addEventListener("click", () => render(button.dataset.rewardMode)));
    render("best-of-n");
  }

  function initializeLlamaBudgetLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const contextInput = root.querySelector('[data-llama-input="context"]');
    const batchInput = root.querySelector('[data-llama-input="batch"]');
    const form = root.querySelector("form");
    const state = {
      model: LLAMA_MODELS[root.dataset.llamaModel] ? root.dataset.llamaModel : "7b",
      context: Number(root.dataset.llamaContext) || 2048,
      batch: Number(root.dataset.llamaBatch) || 1,
      bytes: Number(root.dataset.llamaBytes) || 2
    };
    const formatBillions = value => `${(value / 1e9).toFixed(3)}B`;
    const formatTrillions = value => `${(value / 1e12).toFixed(1)}T`;
    const formatThousands = value => `${Math.round(value / 1000)}k`;
    const formatFlops = value => `${value.toExponential(2).replace("+", "")} FLOPs`;

    form?.addEventListener("submit", event => event.preventDefault());
    if (contextInput) {
      const initialIndex = LLAMA_CONTEXT_OPTIONS.indexOf(state.context);
      contextInput.value = String(initialIndex >= 0 ? initialIndex : LLAMA_CONTEXT_OPTIONS.length - 1);
    }
    if (batchInput) batchInput.value = String(state.batch);

    function render() {
      const model = LLAMA_MODELS[state.model];
      const vocab = 32000;
      const ffn = Math.ceil((8 * model.dim / 3) / 256) * 256;
      const attention = 4 * model.dim * model.dim;
      const feedForward = 3 * model.dim * ffn;
      const blockParams = model.layers * (attention + feedForward + 2 * model.dim);
      const embeddingParams = 2 * vocab * model.dim + model.dim;
      const params = blockParams + embeddingParams;
      const steps = model.tokens / 4e6;
      const trainFlops = 6 * params * model.tokens;
      const weightBytes = params * state.bytes;
      const kvBytes = 2 * state.batch * model.layers * state.context * model.dim * state.bytes;
      const attentionShare = 100 * attention / (attention + feedForward);
      const ffnShare = 100 - attentionShare;
      const blockShare = 100 * blockParams / params;

      root.dataset.llamaModel = state.model;
      root.dataset.llamaContext = String(state.context);
      root.dataset.llamaBatch = String(state.batch);
      root.dataset.llamaBytes = String(state.bytes);
      root.querySelectorAll("[data-llama-preset]").forEach(button => {
        const active = button.dataset.llamaPreset === state.model;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      root.querySelectorAll('[data-llama-control="bytes"] button').forEach(button => {
        const active = Number(button.dataset.value) === state.bytes;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });

      setText(root, "[data-llama-badge]", `${model.label} · ${formatBillions(params)} 参数`);
      setText(root, '[data-llama-output="context"]', formatInteger(state.context));
      setText(root, '[data-llama-output="batch"]', formatInteger(state.batch));
      setText(root, '[data-llama-geometry="core"]', `${formatInteger(model.dim)} / ${model.layers}`);
      setText(root, '[data-llama-geometry="heads"]', `${model.heads} / ${model.heads} · MHA`);
      setText(root, '[data-llama-geometry="ffn"]', `${model.dim / model.heads} / ${formatInteger(ffn)}`);
      setText(root, '[data-llama-geometry="training"]', `${formatTrillions(model.tokens)} / ${formatThousands(steps)}`);
      setText(root, '[data-llama-metric="params"]', formatBillions(params));
      setText(root, '[data-llama-note="params"]', `block ${blockShare.toFixed(1)}% · embedding/head ${(100 - blockShare).toFixed(1)}%`);
      setText(root, '[data-llama-metric="train"]', formatFlops(trainFlops));
      setText(root, '[data-llama-note="train"]', `${formatTrillions(model.tokens)} tokens · 4M/token batch`);
      setText(root, '[data-llama-metric="weights"]', formatBytes(weightBytes));
      setText(root, '[data-llama-metric="kv"]', formatBytes(kvBytes));
      setText(root, '[data-llama-note="kv"]', `2 × ${state.batch} × ${model.layers} × ${formatInteger(state.context)} × ${formatInteger(model.dim)} × ${state.bytes}B`);
      setText(root, '[data-llama-share="attention"]', `${attentionShare.toFixed(1)}%`);
      setText(root, '[data-llama-share="ffn"]', `${ffnShare.toFixed(1)}%`);
      setText(
        root,
        "[data-llama-formula]",
        `N ≈ ${model.layers} × (4 × ${model.dim}² + 3 × ${model.dim} × ${ffn}) + 2 × ${vocab} × ${model.dim}`
      );
      const attentionBar = root.querySelector('[data-llama-bar="attention"]');
      const ffnBar = root.querySelector('[data-llama-bar="ffn"]');
      if (attentionBar) attentionBar.style.width = `${attentionShare}%`;
      if (ffnBar) ffnBar.style.width = `${ffnShare}%`;
      contextInput?.setAttribute("aria-valuetext", `${formatInteger(state.context)} tokens`);
      batchInput?.setAttribute("aria-valuetext", `${state.batch} sequences`);
    }

    root.querySelectorAll("[data-llama-preset]").forEach(button => {
      button.addEventListener("click", () => {
        state.model = button.dataset.llamaPreset;
        render();
      });
    });
    root.querySelectorAll('[data-llama-control="bytes"] button').forEach(button => {
      button.addEventListener("click", () => {
        state.bytes = Number(button.dataset.value);
        render();
      });
    });
    contextInput?.addEventListener("input", () => {
      state.context = LLAMA_CONTEXT_OPTIONS[Number(contextInput.value)];
      render();
    });
    batchInput?.addEventListener("input", () => {
      state.batch = Number(batchInput.value);
      render();
    });
    render();
  }

  function initializeDistillationPolicyLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";
    const buttons = Array.from(root.querySelectorAll("[data-distillation-preset]"));
    const betaControl = root.querySelector("[data-distillation-beta-control]");
    const betaInput = root.querySelector("[data-distillation-beta-input]");
    const state = {
      mode: DISTILLATION_MODES[root.dataset.distillationMode] ? root.dataset.distillationMode : "opsd",
      teacherWeight: Number(betaInput?.value || 65) / 100
    };

    betaControl?.addEventListener("submit", event => event.preventDefault());

    function setPair(key, pair) {
      setText(root, `[data-distillation-value="${key}"]`, pair[0]);
      setText(root, `[data-distillation-note="${key}"]`, pair[1]);
    }

    function renderBeta() {
      const weight = state.teacherWeight;
      const reference = 1 - weight;
      const beta = weight === 0 ? "∞" : (1 / weight).toFixed(2);
      const teacherPercent = `${Math.round(weight * 100)}%`;
      const referencePercent = `${Math.round(reference * 100)}%`;
      setText(root, "[data-distillation-beta-output]", weight.toFixed(2));
      setText(
        root,
        "[data-distillation-beta-formula]",
        `target = softmax(${reference.toFixed(2)} z_ref + ${weight.toFixed(2)} z_teacher), β = ${beta}`
      );
      const referenceBar = root.querySelector("[data-distillation-reference-bar]");
      const teacherBar = root.querySelector("[data-distillation-teacher-bar]");
      if (referenceBar) {
        referenceBar.style.width = referencePercent;
        referenceBar.textContent = reference >= 0.18 ? `reference ${reference.toFixed(2)}` : "";
      }
      if (teacherBar) {
        teacherBar.style.width = teacherPercent;
        teacherBar.textContent = weight >= 0.18 ? `teacher ${weight.toFixed(2)}` : "";
      }
      betaInput?.setAttribute(
        "aria-valuetext",
        `teacher ${weight.toFixed(2)}, reference ${reference.toFixed(2)}, beta ${beta}`
      );
    }

    function render() {
      const detail = DISTILLATION_MODES[state.mode];
      root.dataset.distillationMode = state.mode;
      buttons.forEach(button => {
        const active = button.dataset.distillationPreset === state.mode;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      setText(root, "[data-distillation-badge]", detail.badge);
      ["rollout", "privilege", "target", "update"].forEach(key => setPair(key, detail[key]));
      ["density", "cost", "risk"].forEach(key => {
        setText(root, `[data-distillation-metric="${key}"]`, detail[key]);
      });
      if (betaControl) betaControl.hidden = state.mode !== "beta";
      renderBeta();
    }

    buttons.forEach(button => {
      button.addEventListener("click", () => {
        state.mode = button.dataset.distillationPreset;
        render();
      });
    });
    betaInput?.addEventListener("input", () => {
      state.teacherWeight = Number(betaInput.value) / 100;
      renderBeta();
    });
    render();
  }

  function initializeKlIntuitionLab(root) {
    if (root.dataset.enhanced === "true") return;
    root.dataset.enhanced = "true";

    const teacher = [0.8, 0.15, 0.05];
    const focusInput = root.querySelector("[data-kl-focus]");
    const playButton = root.querySelector("[data-kl-play]");
    const resetButton = root.querySelector("[data-kl-reset]");
    const state = {
      q: distributionFromFocus(Number(focusInput?.value || 98) / 100),
      timer: null,
      step: 0
    };

    function distributionFromFocus(focus) {
      const remainder = Math.max(0, 1 - focus);
      return [focus, remainder * 0.75, remainder * 0.25];
    }

    function fixed(value) {
      return Number.isFinite(value) ? value.toFixed(3) : "∞";
    }

    function entropy(probabilities) {
      return -probabilities.reduce((sum, value) => (
        value > 0 ? sum + value * Math.log(value) : sum
      ), 0);
    }

    function crossEntropy(target, prediction) {
      let total = 0;
      for (let index = 0; index < target.length; index += 1) {
        const value = target[index];
        const probability = prediction[index];
        if (value > 0 && probability <= 0) return Infinity;
        if (value > 0) total -= value * Math.log(probability);
      }
      return total;
    }

    function forwardKl(target, prediction) {
      return target.reduce((sum, value, index) => {
        const probability = prediction[index];
        return value === 0 ? sum : probability > 0
          ? sum + value * Math.log(value / probability)
          : Infinity;
      }, 0);
    }

    function reverseKl(prediction, target) {
      return prediction.reduce((sum, value, index) => {
        const targetValue = target[index];
        return value === 0 ? sum : targetValue > 0
          ? sum + value * Math.log(value / targetValue)
          : Infinity;
      }, 0);
    }

    function stopAnimation() {
      if (state.timer !== null) {
        window.clearInterval(state.timer);
        state.timer = null;
      }
      if (focusInput) focusInput.disabled = false;
      if (playButton) {
        playButton.disabled = false;
        playButton.textContent = "播放一次更新";
      }
    }

    function render() {
      const teacherEntropy = entropy(teacher);
      const ce = crossEntropy(teacher, state.q);
      const forward = forwardKl(teacher, state.q);
      const reverse = reverseKl(state.q, teacher);
      state.q.forEach((value, index) => {
        const teacherBar = root.querySelector(`[data-kl-teacher-bar="${index}"]`);
        const studentBar = root.querySelector(`[data-kl-student-bar="${index}"]`);
        const valueNode = root.querySelector(`[data-kl-value="${index}"]`);
        const gradientNode = root.querySelector(`[data-kl-gradient="${index}"]`);
        const delta = value - teacher[index];
        if (teacherBar) teacherBar.style.width = `${teacher[index] * 100}%`;
        if (studentBar) studentBar.style.width = `${value * 100}%`;
        if (valueNode) valueNode.textContent = `p ${teacher[index].toFixed(2)} · q ${value.toFixed(3)}`;
        if (gradientNode) {
          gradientNode.textContent = `q-p ${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`;
          gradientNode.classList.toggle("is-positive", delta > 0.001);
          gradientNode.classList.toggle("is-negative", delta < -0.001);
        }
      });
      setText(root, "[data-kl-output]", state.q[0].toFixed(2));
      setText(root, '[data-kl-metric="entropy"]', fixed(teacherEntropy));
      setText(root, '[data-kl-metric="ce"]', fixed(ce));
      setText(root, '[data-kl-metric="forward"]', fixed(forward));
      setText(root, '[data-kl-metric="reverse"]', fixed(reverse));
      const readout = state.q[2] < 0.01
        ? "学生给 C 的概率已经接近 0；但教师仍给它 0.05，所以 forward KL 会要求学生为 C 留下非零概率。"
        : Math.abs(forward) < 0.01
          ? "学生已经接近教师：交叉熵几乎等于固定的 H(p)，额外的 forward KL 接近 0。"
          : "q-p 为正，表示学生给得过多，logit 会被压低；q-p 为负，表示学生给得太少，logit 会被抬高。";
      setText(root, "[data-kl-readout]", readout);
      if (focusInput) {
        focusInput.setAttribute("aria-valuetext", `候选 A 概率 ${state.q[0].toFixed(3)}`);
      }
    }

    focusInput?.addEventListener("input", () => {
      stopAnimation();
      state.q = distributionFromFocus(Number(focusInput.value) / 100);
      render();
    });
    resetButton?.addEventListener("click", () => {
      stopAnimation();
      if (focusInput) focusInput.value = "98";
      state.q = distributionFromFocus(0.98);
      render();
    });
    playButton?.addEventListener("click", () => {
      stopAnimation();
      state.step = 0;
      if (focusInput) focusInput.disabled = true;
      playButton.disabled = true;
      playButton.textContent = "播放中...";
      state.timer = window.setInterval(() => {
        state.q = state.q.map((value, index) => value + 0.22 * (teacher[index] - value));
        state.step += 1;
        render();
        if (state.step >= 12 || Math.max(...state.q.map((value, index) => Math.abs(value - teacher[index]))) < 0.002) {
          stopAnimation();
          if (focusInput) {
            focusInput.value = String(Math.round(state.q[0] * 100));
          }
        }
      }, 280);
    });
    render();
  }

  function initialize() {
    const documentMeta = document.querySelector(".reader-document-meta");
    const modernBlock = documentMeta?.dataset.documentId === "papers/modern-transformer-block.md";
    document.body.classList.toggle("reader-modern-transformer-page", modernBlock);
    document.querySelectorAll("[data-modern-block-map]").forEach(initializeBlockMap);
    document.querySelectorAll('[data-reader-widget="attention-head-sharing"]').forEach(initializeAttentionLab);
    document.querySelectorAll('[data-reader-widget="state-lifecycle"]').forEach(initializeLifecycleLab);
    document.querySelectorAll('[data-reader-widget="normalization-axes"]').forEach(initializeNormalizationLab);
    document.querySelectorAll('[data-reader-widget="swiglu-gate"]').forEach(initializeSwigluLab);
    document.querySelectorAll('[data-reader-widget="rope-relative-position"]').forEach(initializeRopeLab);
    document.querySelectorAll('[data-reader-widget="sliding-window-reach"]').forEach(initializeSlidingWindowLab);
    document.querySelectorAll('[data-reader-widget="intervention-map"]').forEach(initializeInterventionMap);
    document.querySelectorAll('[data-reader-widget="reward-policy-clock"]').forEach(initializeRewardPolicyClock);
    document.querySelectorAll('[data-reader-widget="llama-budget"]').forEach(initializeLlamaBudgetLab);
    document.querySelectorAll('[data-reader-widget="distillation-policy"]').forEach(initializeDistillationPolicyLab);
    document.querySelectorAll('[data-reader-widget="kl-intuition"]').forEach(initializeKlIntuitionLab);
  }

  if (typeof document$ !== "undefined") document$.subscribe(initialize);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
  else initialize();
})();
