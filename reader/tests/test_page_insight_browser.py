#!/usr/bin/env python3
"""Exercise manual insight controls against a running Reader with mocked model results."""

import copy
import sys

from playwright.sync_api import expect, sync_playwright
from test_page_insight import ANSWER


def run(base):
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    url = base + "/pdf-viewer/?file=/sources/arxiv-1706.03762v7/paper.pdf&source_id=arxiv-1706.03762v7&page=3"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme="light")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        posts = []
        saved = {}
        held = []
        mode = {"hold": False, "fail": False}

        def reply(route, request):
            from urllib.parse import parse_qs, urlparse
            if request.method == "GET":
                query = parse_qs(urlparse(request.url).query)
                key = (int(query["page"][0]), query["model"][0], query["reasoning_effort"][0])
                route.fulfill(json={"insight": saved.get(key), "cached": key in saved})
                return
            payload = request.post_data_json
            posts.append(payload)
            if mode["fail"]:
                route.fulfill(status=502, json={"error": "模拟模型服务失败"})
                return
            value = {
                "source_id": payload["source_id"], "page": payload["page"],
                "model": payload["model"], "reasoning_effort": payload["reasoning_effort"],
                "content": copy.deepcopy(ANSWER), "created_at": "2026-09-08T00:00:00+08:00"
            }
            value["content"]["main_point"] = f"第 {payload['page']} 页的概览结果。"
            key = (payload["page"], payload["model"], payload["reasoning_effort"])
            saved[key] = value
            if mode["hold"]:
                held.append((route, value))
                return
            route.fulfill(json={"insight": value, "cached": False})

        page.route("**/api/pdf/page-insight*", reply)
        page.route("**/api/translation/page?*", lambda route: route.fulfill(json={"translation": None, "source_text": ""}))
        page.route("**/api/translation/full?*", lambda route: route.fulfill(json={"status": "idle", "total": 15, "completed": 0}))
        page.goto(url)
        expect(page.locator("#insight-toggle")).to_be_enabled(timeout=30000)
        page.locator("#insight-toggle").click()
        expect(page.locator("#insight-status")).to_have_text("尚未生成")
        assert not posts
        page.locator("#insight-model").select_option("gpt-6-astra")
        page.locator("#insight-effort").select_option("low")
        assert page.locator('#insight-effort option[value="ultra"]').is_disabled()
        page.locator("#generate-insight").click()
        expect(page.locator(".insight-main")).to_have_text("第 3 页的概览结果。")
        assert posts[-1]["model"] == "gpt-6-astra" and posts[-1]["reasoning_effort"] == "low"
        expect(page.locator("#generate-insight")).to_have_text("重新解析")
        expect(page.locator(".insight-analysis h3")).to_have_text("1. 掩码如何避免未来信息泄漏")
        expect(page.locator(".insight-analysis .insight-prose p")).to_have_count(3)
        expect(page.locator(".insight-source-quote")).to_be_hidden()
        page.locator(".insight-source-anchor").click()
        expect(page.locator(".pdf-insight-highlight")).to_have_count(1)
        page.locator("#insight-content").evaluate("el => el.scrollTop = el.scrollHeight")
        page.locator(".pdf-insight-highlight").click()
        expect(page.locator(".insight-analysis.is-selected")).to_have_count(1)
        expect(page.locator(".insight-analysis.is-selected h3")).to_be_in_viewport()
        expect(page.locator("#page-number")).to_have_value("3")
        expect(page.locator(".insight-priority")).to_have_count(0)
        mode["fail"] = True
        page.locator("#generate-insight").click()
        expect(page.locator("#insight-status")).to_contain_text("保留上次结果")
        expect(page.locator(".insight-main")).to_have_text("第 3 页的概览结果。")
        mode["fail"] = False

        # A late response for page 3 must not populate page 4.
        mode["hold"] = True
        page.locator("#generate-insight").click()
        expect(page.locator("#generate-insight")).to_be_disabled()
        page.locator("#next").click()
        expect(page.locator("#insight-title")).to_contain_text("第 4 页")
        expect(page.locator(".insight-main")).to_have_count(0)
        for route, value in held:
            route.fulfill(json={"insight": value, "cached": False})
        mode["hold"] = False
        expect(page.locator("#insight-title")).to_contain_text("第 4 页")
        expect(page.locator(".insight-main")).to_have_count(0)
        post_count = len(posts)
        page.locator("#previous").click()
        expect(page.locator(".insight-main")).to_have_text("第 3 页的概览结果。")
        assert len(posts) == post_count
        page.reload()
        expect(page.locator("#insight-toggle")).to_be_enabled(timeout=30000)
        page.locator("#insight-toggle").click()
        expect(page.locator(".insight-main")).to_have_text("第 3 页的概览结果。")
        expect(page.locator("#insight-model")).to_have_value("gpt-6-astra")
        expect(page.locator("#insight-effort")).to_have_value("low")
        divider = page.locator("#insight-resizer")
        expect(divider).to_be_visible()
        before = page.locator("#insight-panel").bounding_box()["width"]
        bounds = divider.bounding_box()
        page.mouse.move(bounds["x"] + bounds["width"] / 2, bounds["y"] + 120)
        page.mouse.down()
        page.mouse.move(bounds["x"] - 120, bounds["y"] + 120, steps=12)
        page.mouse.up()
        page.wait_for_timeout(500)
        after = page.locator("#insight-panel").bounding_box()["width"]
        assert after > before + 90, (before, after)
        expect(page.locator("#page-number")).to_have_value("3")
        page.reload()
        expect(page.locator("#insight-toggle")).to_be_enabled(timeout=30000)
        page.locator("#insight-toggle").click()
        assert abs(page.locator("#insight-panel").bounding_box()["width"] - after) < 2
        divider.dblclick()
        page.wait_for_timeout(300)
        assert abs(page.locator("#insight-panel").bounding_box()["width"] - before) < 2
        expect(page.locator("#page-number")).to_have_value("3")
        page.locator("#translation-toggle").click()
        expect(page.locator("#insight-panel")).to_be_hidden()
        expect(divider).to_be_hidden()
        expect(page.locator(".pdf-insight-highlight")).to_have_count(0)
        expect(page.locator("#translation-panel")).to_be_visible()
        page.locator("#insight-toggle").click()
        expect(page.locator("#translation-panel")).to_be_hidden()
        expect(page.locator(".insight-main")).to_have_text("第 3 页的概览结果。")

        # The PDF also runs inside the Mac browser's adjustable evidence pane.
        for width, height in ((1440, 1000), (900, 850), (600, 850)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(500)
            expect(page.locator("#insight-title")).to_contain_text("第 3 页")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("#viewport").bounding_box()["height"] > 200
            pdf_bounds = page.locator("#viewport").bounding_box()
            insight_bounds = page.locator("#insight-panel").bounding_box()
            assert pdf_bounds["x"] + pdf_bounds["width"] <= insight_bounds["x"] + 1
            assert page.evaluate("""() => {
                const selectors = ['#insight-model', '#insight-effort', '#generate-insight', '#close-insight'];
                const rects = selectors.map(s => document.querySelector(s).getBoundingClientRect());
                return rects.every((a, i) => a.left >= 0 && a.right <= innerWidth && rects.every((b, j) =>
                    i === j || a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top));
            }""")
            page.screenshot(path=f"/tmp/page-insight-{width}.png")
        canvas = page.locator('.pdf-page[data-page="3"] canvas')
        if canvas.count() == 0:
            canvas = page.locator("canvas.is-rendered").first
        expect(canvas).to_be_visible()
        assert canvas.evaluate("""canvas => {
            const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
            let min = 255, max = 0;
            for (let i = 0; i < data.length; i += 64) { min = Math.min(min, data[i]); max = Math.max(max, data[i]); }
            return max - min > 100;
        }""")
        page.emulate_media(color_scheme="dark")
        page.screenshot(path="/tmp/page-insight-dark.png")
        page.unroute("**/api/pdf/page-insight*")
        page.route("**/api/pdf/page-insight*", lambda route: route.fulfill(status=404, content_type="text/html", body="<!DOCTYPE html><h1>Not found</h1>"))
        page.locator("#next").click()
        expect(page.locator("#insight-status")).to_contain_text("当前服务尚未加载概览接口")
        assert not errors, errors
        browser.close()
        print("Manual trigger, model/effort, cache, failure recovery, stale-page isolation, desktop pane layout and PDF pixels passed.")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001")
