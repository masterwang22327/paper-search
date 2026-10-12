"""Behavior checks for distinguishing suspicious formula markup from code."""
import importlib.util
from pathlib import Path
import sys
import unittest

path = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_math.py'
spec = importlib.util.spec_from_file_location('audit_math', path)
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)

class AuditTests(unittest.TestCase):
    def test_screenshot_expressions(self):
        for value in ['R_i-mean_group = (G-1)/G * A_i_LOO', 'T_i=sum_t m_it', 'ell_it=log pi_theta(o_it|q,o_i,<t)']:
            with self.subTest(value=value):
                self.assertEqual(audit.classify_code(value)[0], 'high')

    def test_real_code_is_not_math(self):
        for value in ['grouped.std(dim=1)', 'torch.exp(logps)', 'model.forward()', 'per_device_batch_size * seq_len * grad_accum * data_parallel_size', 'domain token mean -> alpha_i weight -> domain sum', '[batch=1,L_t]', '--learning-rate', 'sources/model.py:12', 'num_items_in_batch']:
            with self.subTest(value=value):
                self.assertIsNone(audit.classify_code(value))

    def test_tex_inside_code(self):
        self.assertEqual(audit.classify_code(r'\frac{G-1}{G}')[0], 'high')

    def test_prose_excludes_code_and_rendered_math(self):
        doc = audit.Document(r'<p>正文 <code>\frac{a}{b}</code><span class="arithmatex">\(x\)</span></p>')
        self.assertEqual(audit.prose(doc.root), '正文 ')

    def test_unprocessed_delimiter_survives(self):
        doc = audit.Document('<p>$$\nx = 1\n$$</p>')
        self.assertIn('$$', audit.prose(doc.root))

    def test_pre_and_void_elements(self):
        doc = audit.Document('<article><input hidden><pre><code>x_i=y_i</code></pre><p><code>x_i=y_i</code></p></article>')
        nodes = [n for n in doc.root.walk() if n.tag == 'code']
        self.assertTrue(nodes[0].inside('pre'))
        self.assertFalse(nodes[1].inside('pre'))

if __name__ == '__main__':
    unittest.main()
