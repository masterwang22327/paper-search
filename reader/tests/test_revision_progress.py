"""Revision progress remains visible during a pending request and stops afterward."""
import sys

from playwright.sync_api import expect, sync_playwright
from test_reader import CHROME_PATHS


def run(base):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=str(next(path for path in CHROME_PATHS if path.is_file())), headless=True)
        page = browser.new_page(viewport={"width": 1484, "height": 960})
        pending = []
        progress_calls = []
        progress_fails = False
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            url = route.request.url
            if "/bootstrap" in url:
                route.fulfill(json={"token": "test"})
            elif "/revision/propose" in url:
                pending.append(route)
            elif "/revision/progress" in url:
                progress_calls.append(url)
                if progress_fails:
                    route.fulfill(status=503, json={"error": "进度暂不可用"})
                else:
                    route.fulfill(json={"status": "running", "stage": "reading",
                        "message": "正在读取论文原文…", "last_event_seconds": 2})
            else:
                route.fulfill(json={})

        page.route("**/api/**", respond)
        page.goto(base + "/papers/reasoning-rl-reductions/")
        page.evaluate("""() => {
            const block = [...document.querySelectorAll('article p[data-reader-block]')]
                .find(element => element.textContent.length > 50);
            block.scrollIntoView({block: 'center'});
            const range = document.createRange(); range.selectNodeContents(block);
            getSelection().removeAllRanges(); getSelection().addRange(range);
            document.dispatchEvent(new Event('selectionchange'));
        }""")
        page.locator('.knowledge-selection-menu [data-action="edit"]').click()
        dialog = page.locator(".reader-revision-editor__dialog")
        composer = dialog.locator('[name="instruction"]')
        status = dialog.locator(".reader-revision-editor__status")
        submit = dialog.locator('[type="submit"]')
        composer.fill("请核对这个实现")
        submit.click()
        expect(status).to_contain_text("正在读取论文原文")
        expect(status).to_contain_text("已等待")
        expect(status).to_contain_text("最近活动")
        expect(submit).to_be_disabled()
        data = pending[0].request.post_data_json
        assert data["progress_job_id"] in progress_calls[-1]
        dialog.get_by_role("button", name="收起", exact=True).click()
        expect(status).to_contain_text("正在读取论文原文")
        dialog.get_by_role("button", name="展开", exact=True).click()
        # Losing progress connectivity must leave the actual question pending.
        progress_fails = True
        expect(status).to_contain_text("进度连接暂不可用", timeout=6000)
        expect(submit).to_be_disabled()
        progress_fails = False
        expect(status).to_contain_text("正在读取论文原文", timeout=6000)
        pending.pop().fulfill(status=504, json={"error": "模型响应超时，请重试本轮问题"})
        expect(dialog.get_by_role("alert")).to_contain_text("模型响应超时")
        expect(composer).to_have_value("请核对这个实现")
        expect(submit).to_be_enabled()
        count = len(progress_calls)
        page.wait_for_timeout(1300)
        assert len(progress_calls) == count, "Progress continued polling after failure"
        # Retrying uses a fresh job and the final result replaces pending status.
        submit.click()
        expect(status).to_contain_text("正在读取论文原文")
        retry = pending.pop()
        retry_data = retry.request.post_data_json
        assert retry_data["progress_job_id"] != data["progress_job_id"]
        retry.fulfill(json={"id": "test-discussion", "status": "draft", "turns": [{
            "id": "test-turn", "instruction": retry_data["instruction"], "candidate": {
                "candidate_id": "test-candidate", "title": "核对结果", "summary": "说明",
                "markdown": "这是核对后的解释。", "change_note": "补充说明"}}]})
        expect(dialog.locator(".reader-revision-turn")).to_have_count(1)
        expect(status).to_contain_text("候选已生成")
        count = len(progress_calls)
        page.wait_for_timeout(1300)
        assert len(progress_calls) == count, "Progress continued polling after completion"
        assert not errors, errors
        browser.close()
        print("Revision progress checks passed: pending, collapse, reconnect, timeout, retry and cleanup")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
