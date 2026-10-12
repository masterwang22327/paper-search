"""Evidence lookup works for disk/PDF/archive files and never modifies inputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from revision_materials import ResearchMaterials, read_github_code
from task_store import TaskArtifactStore
from unittest.mock import patch


def run():
    with tempfile.TemporaryDirectory(prefix='reader research ') as temporary:
        root = Path(temporary)
        (root / 'papers').mkdir()
        (root / 'papers/current.md').write_text('Teaching example\npg + beta * k3\n')
        for index in range(12):
            source = root / 'sources' / f'source-{index}'
            source.mkdir(parents=True)
            (source / 'trainer.py').write_text(f'# implementation {index}\nk3 = ratio - log_ratio - 1\n')
        (root / 'sources/source-0/full.txt').write_text('x' * 150_000 + 'TAIL_MARKER')
        store = TaskArtifactStore(root)
        store.compact_sources()
        materials = ResearchMaterials(root)
        digest = hashlib.sha256(store.database.read_bytes()).hexdigest()
        assert len(materials.inventory()) == 14
        assert materials.read('sources/source-0/full.txt').endswith('TAIL_MARKER')
        assert len(materials.search('k3')) == 13
        assert len(materials.search('k3', 'sources/source-11/')) == 1
        assert materials.read('papers/current.md').endswith('k3\n')
        for unsafe in ('../secret', '/etc/passwd', 'sources/../../secret', 'state/config.json'):
            try:
                materials.read(unsafe)
                raise AssertionError(unsafe)
            except ValueError:
                pass
        (root / 'sources/escape.txt').symlink_to('/etc/passwd')
        assert 'sources/escape.txt' not in materials.inventory()
        try:
            materials.read('sources/escape.txt')
            raise AssertionError('Symlink escape accepted')
        except ValueError:
            pass
        with patch('revision_materials.subprocess.run') as command:
            command.return_value.stdout = 'page text'
            assert materials.read('sources/source-0/paper.pdf', 2, 4) == 'page text'
            args = command.call_args.args[0]
            assert args[-1] == '-' and args[args.index('-f')+1] == '2' and args[args.index('-l')+1] == '4'
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'revision_materials.py'), '--task-dir', str(root)]
        output = subprocess.check_output([*command, 'read', 'sources/source-11/trainer.py', '--start', '2'], text=True)
        assert output.strip() == 'k3 = ratio - log_ratio - 1'
        output = subprocess.check_output([*command, 'search', 'k3', '--prefix', 'sources/source-11/'], text=True)
        assert json.loads(output)[0]['line'] == 2
        assert hashlib.sha256(store.database.read_bytes()).hexdigest() == digest
    with patch('revision_materials.urlopen') as request:
        request.return_value.__enter__.return_value.read.return_value = b'line one\nline two\n'
        url = 'https://github.com/org/repo/blob/' + 'a' * 40 + '/file.py#L2'
        content = read_github_code(url)
        assert '2: line two' in content
        excerpt = read_github_code(url, 2, 2)
        assert '2: line two' in excerpt and '1: line one' not in excerpt
        assert request.call_args.args[0].full_url == 'https://raw.githubusercontent.com/org/repo/' + 'a' * 40 + '/file.py'
        try:
            read_github_code('https://github.com/org/repo/blob/main/file.py')
            raise AssertionError('Moving revision accepted')
        except ValueError:
            pass
    print('Revision evidence reader checks passed (complete archive search/read, PDF ranges, no writes)')


if __name__ == '__main__':
    run()
