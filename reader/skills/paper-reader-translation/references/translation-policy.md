# Translation Policy

## Page boundary

- Translate only `<current_page_text>`.
- Use `<previous_page_tail>` and `<next_page_head>` only to finish syntax or resolve pronouns.
- Do not duplicate adjacent-page content in the current translation.

## Visual correction

- Prefer the page image for column and block order.
- Prefer extracted text for exact prose spelling, URLs, and citation numbers.
- For formulas and symbolic notation, prefer the page image for semantic identity and attachment. Text extraction is not authoritative for arrow direction, accents, superscripts, subscripts, delimiters, or glyph placement.
- When text and image disagree materially, preserve the checkable content and add a warning.

## Formulas and tables

- Preserve display formulas verbatim when extraction remains readable.
- Audit every formula-bearing sentence against the image before returning JSON. Treat Unicode combining mathematical marks (U+20D0-U+20FF) as extraction hazards, not safe output characters.
- Translation fields are plain text, not a TeX renderer. Use stable linear notation such as `f→`, `h→_t`, `f←`, `h←_t`, and `x_{T_x}` instead of combining glyphs such as `f⃗` or `h⃖`.
- Translate prose around formulas; do not explain or solve formulas unless the source does.
- Translate table headings and cells in reading order. When the row/column structure is reliable, use `table_data.headers` and `table_data.rows`; do not encode the table as Markdown inside `translation`.
- Preserve numeric values, units, significance marks, citations, dashes, and intentionally empty cells exactly. Explain merged headers or unclear alignment briefly in `table_data.notes`.
- If structure is unreliable, omit `table_data`, translate the readable content as labeled lines, lower confidence, and add a warning.
- Keep Figure, Table, Section, Appendix, and equation numbers traceable to the source.

## Figures and diagrams

- Keep the original image as the evidence. Do not pretend to replace text inside it.
- For every meaningful figure on the page, add a `figure` block with `figure_data` when the visual can be read reliably.
- Summarize the whole figure, not only its caption or largest labels. For workflows and architecture diagrams, follow arrows and record stages, branches, merges, repeated modules, and feedback loops in `flow_steps`.
- Translate visible labels as `{original, translation}` pairs. Preserve variables, formulas, model names, and abbreviations when translation would reduce traceability.
- For charts, state the axes, series, comparison, and visible trend in `summary`; leave `flow_steps` empty unless the chart itself expresses a process.
- Put illegible small text, ambiguous arrows, cropped panels, or inferred relationships in `figure_data.notes` and `warnings`. Never fill gaps from general knowledge.

## References

- Keep author names, venue names, titles, DOI, arXiv IDs, and URLs unchanged by default.
- Do not spend tokens translating a reference list unless the page contains argument-bearing prose alongside it.

## Output

- `translation`: complete readable plain Chinese text for this page. Separate paragraphs with blank lines; do not wrap it in a Markdown code fence.
- `blocks`: optional page-local blocks with `type`, `original_text`, `translation`, `confidence`, `bbox`, and `refs`; table and figure blocks may additionally carry `table_data` or `figure_data`. Keep each `original_text` grounded in the current page; the host assigns stable IDs.
- `glossary_updates`: only new, reusable source-term mappings.
- `warnings`: concrete uncertainty or extraction limitations; return an empty list when none exist.
