"""All revision turns remain accessible across follow-ups, errors and reopening."""
import sys
from playwright.sync_api import sync_playwright, expect
from test_reader import CHROME_PATHS


def run(base):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(next(path for path in CHROME_PATHS if path.is_file())), headless=True)
        page = browser.new_page(viewport={'width': 1484, 'height': 960})
        discussion = None
        fail = False
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def respond(route):
            nonlocal discussion
            url = route.request.url
            if '/bootstrap' in url:
                route.fulfill(json={'token': 'test'})
            elif '/revision/propose' in url:
                if fail:
                    route.fulfill(status=500, json={'error': '模拟失败'})
                    return
                data = route.request.post_data_json
                if discussion is None:
                    discussion = {'id': 'history-test', 'status': 'draft', 'target_text': '\n\n'.join(item['text'] for item in data['contexts']),
                                  'target_blocks': [item['block_id'] for item in data['contexts']], 'turns': []}
                else:
                    assert data['discussion_id'] == discussion['id']
                number = len(discussion['turns']) + 1
                discussion['turns'].append({'id': str(number), 'instruction': data['instruction'], 'candidate': {
                    'candidate_id': str(number), 'title': f'回复 {number}',
                    'markdown': f'第 {number} 轮解释：动机、含义与来源。\n\n' + ('这里是较长的说明，便于检查历史滚动。\n\n' * 15),
                    'summary': '机制说明', 'change_note': '补充上下文'}})
                route.fulfill(json=discussion)
            elif '/state?' in url:
                route.fulfill(json={'revision_discussions': {'items': [discussion] if discussion else []}})
            else:
                route.fulfill(json={})
        page.route('**/api/**', respond)
        page.goto(base + '/papers/reasoning-rl-reductions/')
        def open_editor():
            page.evaluate('''() => {
                const block=[...document.querySelectorAll('article p[data-reader-block]')].find(e=>e.textContent.length>50);
                block.scrollIntoView({block:'center'});
                const range=document.createRange();range.selectNodeContents(block);
                getSelection().removeAllRanges();getSelection().addRange(range);
                document.dispatchEvent(new Event('selectionchange'));
            }''')
            page.locator('.knowledge-selection-menu [data-action="edit"]').click()
        open_editor()
        dialog = page.locator('.reader-revision-editor__dialog')
        composer = dialog.locator('[name="instruction"]')
        for number in range(1, 6):
            composer.fill(f'第 {number} 个问题')
            dialog.locator('[type="submit"]').click()
            expect(dialog.locator('.reader-revision-turn')).to_have_count(number)
            expect(composer).to_have_value('')
        expect(dialog.locator('.reader-revision-history-nav')).to_contain_text('5 轮')
        history = dialog.locator('.reader-revision-editor__preview')
        expect(dialog.locator('[name="model"]')).not_to_be_visible()
        settings = dialog.locator('.reader-revision-settings > summary')
        height_before = history.bounding_box()['height']
        settings.click()
        expect(dialog.locator('[name="model"]')).to_be_visible()
        assert abs(history.bounding_box()['height'] - height_before) < 2
        page.keyboard.press('Escape')
        expect(dialog.locator('[name="model"]')).not_to_be_visible()
        expect(dialog.get_by_role('button', name='收起', exact=True)).to_be_visible()
        assert history.evaluate('e=>e.scrollHeight>e.clientHeight')
        jump = dialog.get_by_role('combobox', name='跳转到某轮对话')
        document_scroll = page.evaluate('window.scrollY')
        jump.select_option('0')
        expect(dialog.locator('.reader-revision-turn').first.locator('.reader-revision-turn__question')).to_be_in_viewport()
        dialog.get_by_role('button', name='最新回复 ↓').click()
        expect(dialog.locator('.reader-revision-turn').last.locator('.reader-revision-turn__question')).to_be_in_viewport()
        assert abs(page.evaluate('window.scrollY') - document_scroll) < 2
        fail = True
        composer.fill('失败后保留的追问')
        dialog.locator('[type="submit"]').click()
        expect(dialog.get_by_role('alert')).to_contain_text('模拟失败')
        expect(dialog.locator('.reader-revision-turn')).to_have_count(5)
        expect(composer).to_have_value('失败后保留的追问')
        fail = False
        dialog.get_by_role('button', name='关闭', exact=True).click()
        open_editor()
        expect(dialog.locator('.reader-revision-turn')).to_have_count(5)
        page.screenshot(path='/tmp/reader-revision-history.png')
        dialog.get_by_role('button', name='关闭', exact=True).click()
        page.reload()
        open_editor()
        expect(dialog.locator('.reader-revision-turn')).to_have_count(5)
        for width, height in ((1484, 960), (1100, 650), (952, 800), (390, 800), (1280, 600)):
            page.set_viewport_size({'width': width, 'height': height})
            box = dialog.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            assert box['height'] <= height - 24
            composer.fill('')
            assert history.bounding_box()['height'] >= 100, (width, height, box, history.bounding_box())
            assert 112 <= composer.bounding_box()['height'] <= min(260, height * .35)
            composer.fill('窄窗口仍可追问')
            expect(composer).to_be_in_viewport()
        assert not errors, errors
        browser.close()
        print('Revision history checks passed: five rounds, jump, error preservation, reopen/reload and responsive composer')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000')
