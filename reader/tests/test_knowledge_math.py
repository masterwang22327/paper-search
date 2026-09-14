#!/usr/bin/env python3
"""Check display math adjacent to prose in persisted assistant answers."""

import subprocess
import sys

from playwright.sync_api import expect, sync_playwright
from test_reader import CHROME_PATHS, READER_DIR, TASK_ID, free_port, wait_for_server


ANSWER = r"""固定一个 query，注意力分布为：
\[A_{i,s}=\frac{e^{z_{i,s}}}{\sum_{u\le t}e^{z_{i,u}}},\qquad p_s=\frac1H\sum_i A_{i,s}.\]
目标分布沿历史 token 位置归一化。
\[r_s=\operatorname{Softmax}(I)_s,\qquad \frac{\partial L_t^I}{\partial I_s}=r_s-p_s.\]
因此，\(r_s-p_s<0\) 时提高该位置分数。

- 列表中的公式：
  \[
  x=\frac{1}{2}
  \]
  列表后文。

美元分隔符：
$$
y=x^2
$$
美元公式后文。

代码保持原样：`\[inline_code\]`

```tex
\[fenced_code\]
```
"""

ANSWER += "\n\\[B_l\\mathbf{1}=\boldsymbol{1},\\qquad \\mathbf{1}^{T}B_l=\boldsymbol{1}^{T},\\qquad B_l\\ge 0.\\]\n"
ANSWER += "\n\\[\\frac{broken\\]\n"


def run(base):
    chrome = next(path for path in CHROME_PATHS if path.is_file())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
        page = browser.new_page(viewport={"width": 1524, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def reply(route):
            if "/api/bootstrap" in route.request.url:
                route.fulfill(json={"token": "test", "task_id": TASK_ID})
            elif "/api/state?" in route.request.url:
                route.fulfill(json={
                    "revisions": {"items": []}, "faq": {"items": []},
                    "messages": [{"id": "math-answer", "role": "assistant", "content": ANSWER}],
                })
            else:
                route.fulfill(json={})

        page.route("**/api/**", reply)
        page.goto(base + "/papers/deepseek-v2-v3-r1-lineage/")
        page.locator(".evidence-panel-toggle").click()
        page.locator('[data-reader-tab="assistant"]').click()
        answer = page.locator(".knowledge-rich-text").filter(has_text="固定一个 query")
        expect(answer.locator(".knowledge-math-block mjx-container")).to_have_count(5)
        expect(answer.locator(".knowledge-math-inline mjx-container")).to_have_count(1)
        expect(answer.locator("mjx-merror")).to_have_count(0)
        expect(answer.locator(".knowledge-math-error")).to_have_count(1)
        expect(answer.locator(".knowledge-math-error")).to_contain_text(r"\frac{broken")
        expect(answer).to_contain_text("美元公式后文。")
        expect(answer).to_contain_text("列表后文。")
        expect(answer.locator("code").first).to_have_text(r"\[inline_code\]")
        expect(answer.locator("pre code")).to_have_text("\\[fenced_code\\]\n")
        expect(answer.locator("code mjx-container")).to_have_count(0)
        page.screenshot(path="/tmp/reader-knowledge-math.png")
        assert not errors, errors
        browser.close()
    print("Knowledge math regression checks passed")


if __name__ == "__main__":
    port = free_port()
    server = subprocess.Popen([
        sys.executable, str(READER_DIR / "site_store.py"), "serve", "--database",
        str(READER_DIR / "user-data" / TASK_ID / "site.sqlite3"), "--port", str(port),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        wait_for_server(base)
        run(base)
    finally:
        server.terminate()
        server.wait(timeout=10)
