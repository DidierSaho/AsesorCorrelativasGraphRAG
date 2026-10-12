"""Revisa los archivos publicables sin imprimir secretos. Requiere Git.

Opcional --zip genera un paquete con exactamente los archivos revisados.
No es una auditoría exhaustiva ni reemplaza secret scanning de GitHub.
"""
import argparse
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DIRS = {'.git', '.aws', '.venv', 'venv', '.idea', '.vscode', '__pycache__'}
ALLOWED_SUFFIXES = {'.py', '.md', '.txt', '.drawio', '.svg', '.example'}
PATTERNS = {
    'AWS access key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
    'private key': re.compile(r'-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----'),
    'credential assignment': re.compile(
        r'(?im)^\s*[\"\']?(?:AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|AWS_ACCESS_KEY_ID|'
        r'api_key|password|access_token|secret_key)[\"\']?\s*[:=]\s*[\"\']?[A-Za-z0-9/+_=.-]{16,}'),
    'AWS account ARN': re.compile(r'arn:aws[^:\s]*:[^:\s]+:[^:\s]*:[0-9]{12}:'),
    'personal filesystem path': re.compile(r'(?:/Us' r'ers/[^/\s]+/|C:\\Us' r'ers\\[^\\\s]+\\)'),
}

def public_files(root=ROOT):
    result = subprocess.run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '.'],
        cwd=root, check=True, capture_output=True,
    )
    return sorted({name.decode() for name in result.stdout.split(b'\0') if name})

def inspect(root, files):
    findings = []
    for name in files:
        relative = Path(name)
        path = root / relative
        if path.is_symlink():
            findings.append((name, 'symlink: revisar destino'))
            continue
        if (set(relative.parts) & FORBIDDEN_DIRS or
            (relative.name.startswith('.env') and relative.name != '.env.example') or
            relative.name in {'credentials', 'secrets.toml', 'PAUSA-Y-REINICIO.md'}):
            findings.append((name, 'archivo privado/entorno incluido'))
            continue
        if relative.name != '.gitignore' and relative.suffix not in ALLOWED_SUFFIXES:
            findings.append((name, 'tipo de archivo no revisado; revisar manualmente'))
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except (UnicodeError, OSError):
            findings.append((name, 'no se pudo revisar como texto'))
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append((name, label))
    return findings

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', action='store_true', help='Generar aws-graphrag-demo-public.zip')
    args = parser.parse_args()
    files = public_files()
    findings = inspect(ROOT, files)
    for name, reason in findings:
        print(f'REVISAR: {name}: {reason}')
    if findings:
        raise SystemExit(1)
    print(f'OK: {len(files)} archivos publicables; sin coincidencias de los patrones revisados.')
    if args.zip:
        destination = ROOT / 'aws-graphrag-demo-public.zip'
        if destination.exists():
            parser.error('El paquete ya existe; no se sobrescribe automáticamente.')
        with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
            for name in files:
                archive.write(ROOT / name, arcname=name)
        print(f'Paquete generado: {destination.name}')

if __name__ == '__main__':
    main()
