# Third-Party Frontend Assets

These files are pinned locally so the generated reader works without runtime CDN requests.

| Component | Version | License | Upstream |
|---|---:|---|---|
| PDF.js distribution | 5.4.54 | Apache-2.0 | `mozilla/pdf.js` / `pdfjs-dist` |
| MathJax distribution | 3.2.2 | Apache-2.0 | `mathjax/MathJax` |
| markdown-it | 15.0.1 | MIT | `markdown-it/markdown-it` |
| markdown-it-texmath | 1.0.0 | MIT | `goessner/markdown-it-texmath` |

## SHA-256

```text
f23c8fecac9f573f7112951349452c9f3180ad68244171551ef5842f4f349acb  pdfjs/pdf.mjs
92ac8bcb27043c92919e0063b95ad45e374098b7ab364de4920226dab4611d99  pdfjs/pdf.worker.mjs
300480069078b5892d2363a2b65e2dfbbf30fe5c80f83edbfecf4610fd093862  mathjax/tex-mml-chtml.js
f9f377ca892291fbe32904e77a00c6e27e8f95c14f435a54c8cb6859b3d97692  markdown-it.min.js
926e075a1745e1019813b8418b90183feea0c7b3782c85dceb4f246da999edc6  markdown-it-texmath.js
```

The complete license text is stored beside each component. MathJax font files are the unmodified `woff-v2` assets from the same 3.2.2 package.

`mathjax/input/tex/extensions/boldsymbol.js` is the unmodified MathJax 3.2.2 extension from `https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/input/tex/extensions/boldsymbol.js`, under the same Apache-2.0 license.
