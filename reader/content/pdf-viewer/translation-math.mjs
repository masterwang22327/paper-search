let parser;
let queue = Promise.resolve();

// Only infer math for standalone formula lines. Prose and ambiguous inline
// notation stay as written; explicit TeX delimiters always take precedence.
export function normalizeTranslationMath(value) {
  return value.split("\n").map(line => {
    if (/\\[\[\]()]/.test(line) || line.includes("$") || /[\u3400-\u9fff]/u.test(line)) return line;
    if ((line.match(/[_^]\{|\\(?:frac|sum|pi|theta)|[πΣ∑]/g) || []).length < 2) return line;
    return "\\[" + line.replace(/π/g, "\\pi ").replace(/[Σ∑]/g, "\\sum ")
      .replace(/θ/g, "\\theta ").replace(/ε/g, "\\epsilon ") + "\\]";
  }).join("\n");
}

export function renderTranslationMath(element, value) {
  if (!parser && window.markdownit && window.texmath) {
    parser = window.markdownit({ html: false, breaks: true });
    parser.use(window.texmath, { delimiters: ["brackets", "dollars"], engine: { renderToString: source => source } });
    const markup = (tokens, index, display) => {
      const tag = display ? "div" : "span";
      return `<${tag} class="arithmatex">${display ? "\\[" : "\\("}${parser.utils.escapeHtml(tokens[index].content)}${display ? "\\]" : "\\)"}</${tag}>`;
    };
    for (const name of ["math_inline", "math_inline_double", "math_block", "math_block_eqno"]) {
      parser.renderer.rules[name] = (tokens, index) => markup(tokens, index, name !== "math_inline");
    }
  }
  if (!parser) { element.textContent = value; return; }
  element.innerHTML = parser.render(normalizeTranslationMath(value));
  queue = queue.then(async () => {
    if (!window.MathJax?.startup?.promise) {
      await new Promise(resolve => window.addEventListener("load", resolve, { once: true }));
    }
    await window.MathJax?.startup?.promise;
    if (element.isConnected) await window.MathJax?.typesetPromise?.([element]);
  }).catch(() => { /* Keep the source text readable when a formula is invalid. */ });
  if (element.querySelector(".arithmatex")) {
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "copy-formula-source";
    copy.textContent = "复制公式原文";
    copy.addEventListener("click", async event => {
      event.stopPropagation();
      try { await navigator.clipboard.writeText(value); copy.textContent = "已复制"; }
      catch { copy.textContent = "请选中文字复制"; }
    });
    element.appendChild(copy);
  }
}
