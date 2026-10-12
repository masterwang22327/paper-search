"""Exercise chapter notes against real persistence in an isolated temporary store."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import urllib.request

from playwright.sync_api import expect, sync_playwright
from test_reader import CHROME_PATHS, READER_DIR, TASK_ID

sys.path.insert(0, str(READER_DIR))
from server import ApiError, ReaderState
from runtime_store import RuntimeStore


def run(base):
    document_id = 'papers/reasoning-rl-reductions.md'
    with urllib.request.urlopen(base + '/context-manifest.json') as response:
        manifest = json.load(response)
    with tempfile.TemporaryDirectory() as temporary, sync_playwright() as p:
        state = ReaderState.__new__(ReaderState)
        state.task_dir = READER_DIR.parent / 'tasks' / TASK_ID
        state.user_dir = Path(temporary)
        state.runtime_store = RuntimeStore(state.user_dir / 'state.sqlite3')
        state.site_manifest = manifest
        state.lock = threading.RLock()
        state.save_runtime_json(state.reading_progress_path(document_id), {
            'document_sha256': 'old-document',
            'checkpoint': {'scroll_ratio': 1, 'heading_title': '精读附录'},
            'note': {'text': '原来保存的便签', 'position': {
                'heading_title': '文档开头', 'section_index': 0, 'scroll_ratio': 0,
            }},
        })
        requests = []
        fail_save = False

        def respond(route):
            if '/api/bootstrap' in route.request.url:
                route.fulfill(json={'token': 'test'})
            elif '/api/reading-progress' in route.request.url:
                if route.request.method == 'POST':
                    payload = route.request.post_data_json
                    requests.append(payload)
                    if fail_save:
                        route.fulfill(status=500, json={'error': '模拟保存失败'})
                        return
                    try:
                        value = state.save_reading_progress(payload)
                    except ApiError as error:
                        route.fulfill(status=error.status, json={'error': error.message})
                        return
                else:
                    value = state.get_reading_progress(document_id)
                route.fulfill(json=value)
            else:
                route.fulfill(json={})

        browser = p.chromium.launch(executable_path=str(next(path for path in CHROME_PATHS if path.is_file())), headless=True)
        page = browser.new_page(viewport={'width': 1484, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/api/**', respond)
        page.goto(base + '/papers/reasoning-rl-reductions/#grpo', wait_until='domcontentloaded')
        page.wait_for_function('window.MathJax?.startup?.document?.math')
        page.evaluate('MathJax.startup.promise')
        action = lambda name: page.locator(f'[data-reading-action="{name}"]')
        role = lambda name: page.locator(f'[data-reading-role="{name}"]')
        def card(note_id):
            target = page.locator(f'[data-note-id="{note_id}"]')
            if target.count():
                group = target.locator('..')
                if group.get_attribute('open') is None:
                    group.locator('summary').click()
            return target
        record = lambda: state.get_reading_progress(document_id)
        page.locator('#grpo').evaluate('el => el.scrollIntoView()')
        action('toggle').click()
        expect(role('panel')).to_be_visible()
        expect(role('status')).to_contain_text('文档已更新')
        expect(page.locator('.reader-reading-memo__note-group[open]')).to_have_count(0)
        expect(card('legacy-note')).to_contain_text('原来保存的便签')
        assert page.locator('.reader-reading-memo__more').count() == 0
        assert page.locator('[data-reading-action="locate"]').count() == 0
        assert role('panel').evaluate('''panel => {
            const r = panel.getBoundingClientRect();
            for (let x=r.left+8; x<r.right-8; x+=12)
                for (let y=r.top+8; y<r.bottom-8; y+=12)
                    if (!panel.contains(document.elementFromPoint(x,y))) return false;
            return getComputedStyle(panel).backgroundColor === 'rgb(255, 255, 255)';
        }''')
        action('save-current').click()
        expect(role('resume-position')).not_to_contain_text('精读附录')
        saved = copy.deepcopy(record()['resume_position'])
        assert 0 < saved['scroll_ratio'] < 1
        expect(role('progress-ring')).to_have_attribute('aria-valuenow', '100')

        # Adding a note must preserve the original single note and writing location.
        action('note').click()
        page.locator('.reader-reading-memo textarea').fill('这里的 baseline 为什么无偏？')
        page.evaluate('window.scrollBy(0, 900)')
        action('save-note').click()
        expect(role('note-text')).to_have_count(2)
        first = copy.deepcopy(record()['notes'][1])
        assert abs(first['position']['scroll_ratio'] - saved['scroll_ratio']) < 0.005
        card(first['id']).locator('[data-reading-action="edit-note"]').click()
        expect(role('editor-position')).to_contain_text(first['position']['heading_title'])
        page.locator('.reader-reading-memo textarea').fill('下次继续推导 baseline 的期望。')
        action('save-note').click()
        expect(card(first['id'])).to_contain_text('期望')
        assert record()['notes'][1]['position'] == first['position']
        card(first['id']).locator('[data-reading-action="note-location"]').click()
        expect(role('panel')).not_to_be_visible()
        page.wait_for_timeout(1100)
        assert abs(page.evaluate('scrollY / (document.documentElement.scrollHeight - innerHeight)') - saved['scroll_ratio']) < 0.03

        # Two notes in another chapter form one group; all three remain independent.
        page.locator('.md-content__inner h2[id]').nth(4).evaluate('el => el.scrollIntoView()')
        action('toggle').click()
        for text in ('第二章的问题', '同一章的另一个问题'):
            action('note').click()
            page.locator('.reader-reading-memo textarea').fill(text)
            action('save-note').click()
            expect(role('editor')).not_to_be_visible()
        notes = record()['notes']
        assert len(notes) == 4
        assert notes[2]['position']['heading_id'] != first['position']['heading_id']
        assert notes[2]['position']['heading_id'] == notes[3]['position']['heading_id']
        expect(page.locator('.reader-reading-memo__note-group')).to_have_count(3)
        expect(page.locator('.reader-reading-memo__note-group').first).to_have_class('reader-reading-memo__note-group is-current')
        expect(page.locator('.reader-reading-memo__note-group[open]')).to_have_count(1)
        expect(role('notes-title')).to_have_text('章节便签 · 4')
        page.screenshot(path='/tmp/reader-chapter-notes.png')

        page.reload(wait_until='domcontentloaded')
        action('toggle').click()
        expect(role('note-text')).to_have_count(4)
        assert record()['resume_position'] == saved
        card(notes[2]['id']).locator('[data-reading-action="edit-note"]').click()
        page.locator('.reader-reading-memo textarea').fill('保存失败时保留草稿')
        fail_save = True
        action('save-note').click()
        expect(role('status')).to_contain_text('保存失败')
        expect(page.locator('.reader-reading-memo textarea')).to_have_value('保存失败时保留草稿')
        assert record()['notes'][2]['text'] == '第二章的问题'
        fail_save = False
        action('cancel-note').click()
        card(notes[2]['id']).locator('[data-reading-action="delete-note"]').click()
        expect(role('note-text')).to_have_count(3)
        expect(card(notes[3]['id'])).to_contain_text('同一章的另一个问题')
        expect(card('legacy-note')).to_contain_text('原来保存的便签')
        card('legacy-note').locator('[data-reading-action="delete-note"]').click()
        expect(role('note-text')).to_have_count(2)
        page.reload(wait_until='domcontentloaded')
        action('toggle').click()
        expect(role('note-text')).to_have_count(2)
        assert card('legacy-note').count() == 0
        for note in record()['notes']:
            card(note['id']).locator('[data-reading-action="delete-note"]').click()
            expect(page.locator(f'[data-note-id="{note["id"]}"]')).to_have_count(0)
        expect(role('note-empty')).to_be_visible()
        page.keyboard.press('Escape')
        expect(role('panel')).not_to_be_visible()

        # Fresh history still advances the ring on scrolling.
        state.save_runtime_json(state.reading_progress_path(document_id), {'checkpoint': {'scroll_ratio': 0}, 'notes': []})
        page.reload(wait_until='domcontentloaded')
        action('toggle').wait_for()
        page.evaluate('window.scrollTo(0, (document.documentElement.scrollHeight-innerHeight)*0.5)')
        page.wait_for_timeout(1200)
        assert int(role('progress-ring').get_attribute('aria-valuenow')) >= 49
        assert not errors, errors
        browser.close()
        print(f'Chapter note checks passed ({len(requests)} saves in temporary storage; user data untouched)')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000')
