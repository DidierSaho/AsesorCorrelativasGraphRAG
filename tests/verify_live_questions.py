"""Opt-in: .venv/bin/python tests/verify_live_questions.py --live

Sólo Converse: no llama a GraphRAG, no sincroniza ni modifica recursos AWS.
Cada ejecución tiene un máximo explícito de consultas y contabiliza tokens.
"""
import argparse
import json
import os
from pathlib import Path
import boto3
from dotenv import load_dotenv
from question_cases import CASES
from test_atomic_relations import namespace

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true', help='Autoriza llamadas facturables a Nova Micro')
parser.add_argument('--limit', type=int, default=40)
args = parser.parse_args()
if not args.live:
    parser.error('Para llamar a AWS es obligatorio --live; las pruebas locales son unittest discover.')
if not 1 <= args.limit <= 50:
    parser.error('--limit debe estar entre 1 y 50')
load_dotenv(Path(__file__).resolve().parents[1] / '.env')
client = boto3.Session(profile_name=os.getenv('AWS_PROFILE') or None,
                       region_name=os.getenv('AWS_REGION', 'eu-west-1')).client('bedrock-runtime')
usage = {'inputTokens': 0, 'outputTokens': 0}
class MeteredRuntime:
    def converse(self, **kwargs):
        response = client.converse(**kwargs)
        for key in usage:
            usage[key] += response.get('usage', {}).get(key, 0)
        return response
namespace['MODEL_ARN'] = os.environ['MODEL_ARN']
namespace['interpretation_client'] = lambda: MeteredRuntime()
failed = 0
for question, intent, subjects in CASES[:args.limit]:
    try:
        context = namespace['interpret_question'](question)
        actual = (context['intent'], context['subjects'])
        ok = actual == (intent, subjects)
        details = {'actual': actual, 'expected': (intent, subjects)}
    except Exception as exc:
        ok = False
        details = {'error': f'{type(exc).__name__}: {exc}'}
    failed += not ok
    print(json.dumps({'ok': ok, 'question': question, **details}, ensure_ascii=False), flush=True)
print(json.dumps({'cases': min(args.limit, len(CASES)), 'failed': failed, 'tokens': usage}), flush=True)
raise SystemExit(1 if failed else 0)
