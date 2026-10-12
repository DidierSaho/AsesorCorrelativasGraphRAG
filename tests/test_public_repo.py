"""Chequeos del filtro de publicación sin AWS."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_check', ROOT / 'tools/check_public_repo.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

class PublicRepoTests(unittest.TestCase):
    def test_current_public_inventory_is_clean(self):
        files = check.public_files()
        self.assertIn('.env.example', files)
        self.assertNotIn('.env', files)
        self.assertNotIn('PAUSA-Y-REINICIO.md', files)
        self.assertEqual(check.inspect(ROOT, files), [])

    def test_private_files_rejected_even_if_tracked(self):
        for name in ['.env', '.env.production', '.aws/credentials', '.idea/workspace.xml',
                     '.streamlit/secrets.toml', 'PAUSA-Y-REINICIO.md', 'backup.zip']:
            with self.subTest(name=name):
                self.assertTrue(check.inspect(ROOT, [name]))

    def test_secret_patterns_without_revealing_values(self):
        examples = ['AK' + 'IA' + 'A' * 16, 'AS' + 'IA' + 'B' * 16,
                    'gh' + 'p_' + 'C' * 36,
                    'AWS_SECRET_' + 'ACCESS_KEY=' + 'D' * 40,
                    '-----BEGIN ' + 'PRIVATE KEY-----',
                    'arn:aws:bedrock:eu-west-1:' + '1' * 12 + ':inference-profile/example']
        for example in examples:
            with self.subTest(), patch.object(Path, 'read_text', return_value=example):
                self.assertTrue(check.inspect(ROOT, ['sample.txt']))
