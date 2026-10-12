"""Manual table edits survive rerender and preserve the table and math source."""
import sys
from playwright.sync_api import sync_playwright, expect
from test_reader import CHROME_PATHS, TASK_ID, READER_DIR


def run(base):
    state = {"revisions": {"items": []}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(next(p for p in CHROME_PATHS if p.is_file())), headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def reply(route):
            url = route.request.url
            if '/api/bootstrap' in url:
                route.fulfill(json={"token": "test", "task_id": TASK_ID})
            elif '/api/state?' in url:
                route.fulfill(json=state)
            elif '/api/revision/manual' in url:
                data = route.request.post_data_json
                contexts = data['contexts']
                state['revisions']['items'] = [{**data, 'id': 'manual-test', 'source': 'manual',
                    'selection_contexts': contexts, 'target_blocks': [c['block_id'] for c in contexts],
                    'target_text': '\n\n'.join(c['text'] for c in contexts)}]
                route.fulfill(json=state['revisions'])
            elif '/api/revision/delete' in url:
                state['revisions']['items'] = []
                route.fulfill(json=state['revisions'])
            else:
                route.fulfill(json={})
        page.route('**/api/**', reply)
        page.route('**/javascripts/knowledge-assistant.js*', lambda route: route.fulfill(
            path=str(READER_DIR / 'content/javascripts/knowledge-assistant.js'), content_type='application/javascript'))
        for mode in ('text', 'formula', 'multi'):
            page.goto(base + '/papers/20260911-translation/')
            page.evaluate('MathJax.startup.promise')
            info = page.evaluate('''mode => {
                const table = [...document.querySelectorAll('article table')].find(t => t.textContent.includes('三路共享词表'));
                const cell = table.querySelector(mode === 'formula' ? 'tbody tr td:nth-child(2)' : 'tbody tr td');
                const range = document.createRange(); range.selectNodeContents(cell);
                if (mode === 'multi') range.setEndAfter(cell.nextElementSibling.lastChild);
                cell.scrollIntoView({block:'center'});
                getSelection().removeAllRanges(); getSelection().addRange(range);
                document.dispatchEvent(new Event('selectionchange'));
                return {id: cell.dataset.readerBlock, cells: table.querySelectorAll('td,th').length};
            }''', mode)
            page.locator('.knowledge-selection-menu').get_by_role('button', name='手动修改').click()
            page.locator('[name="markdown"]').fill('修改验证 $2d$')
            page.get_by_role('button', name='保存修改', exact=True).click()
            replacement = page.locator('.reader-manual-replacement')
            expect(replacement).to_have_count(1)
            expect(replacement).to_be_visible()
            assert replacement.evaluate('el => Boolean(el.closest("td"))')
            expect(replacement).to_contain_text('修改验证')
            page.reload()
            page.evaluate('MathJax.startup.promise')
            expect(replacement).to_be_visible()
            expect(replacement).to_contain_text('修改验证')
            cell = page.locator(f'[data-reader-block="{info["id"]}"]')
            assert cell.evaluate('el => el.closest("table").querySelectorAll("td,th").length') == info['cells']
            replacement.get_by_role('button', name='查看原文').click()
            expect(cell.locator('.reader-manual-original')).to_be_visible()
            page.once('dialog', lambda dialog: dialog.accept())
            replacement.get_by_role('button', name='恢复', exact=True).click()
            expect(replacement).to_have_count(0)
            expect(cell).to_be_visible()
        assert not errors, errors
        browser.close()
    print('Manual table edit checks passed (text, formula, multi-cell, reload, restore)')

if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000')
