"""Export an audited source ZIP from a Git commit, never from private state."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tomllib
import zipfile


def git(*args):
    return subprocess.check_output(['git', *args])


def allowed(name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts:
        return False
    forbidden = {'.git', '.env', '.venv', '.aws', '.codex', '.agents', '__pycache__',
                 '.pytest_cache', '.lm_cache', '.cardinal', 'dist', 'build', 'runs'}
    if (any(part in forbidden or (part.startswith('.env') and part != '.env.example') for part in path.parts)
            or name.endswith(('.pyc', '.pem', '.key'))):
        return False
    # Source releases ship fictional demo data. The full public course
    # archive is obtained separately when reproducing archive benchmarks.
    if name == 'data/emails.jsonl.gz' or name.startswith(('data/emails/', 'data/raw/')):
        return False
    return (path.parts[0] in {'cs329z_hw1', 'tests', 'local_tests', 'docs', 'tools', '.github'}
            or name.startswith('data/docs/') or name in {
                'README.md', 'COURSE_README.md', 'LICENSE', 'CHANGELOG.md', 'RELEASE_NOTES.md',
                'pyproject.toml', 'uv.lock', '.gitignore', '.env.example',
                'data/download.py', 'data/source.json', 'data/priority_rubric.md'})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--out', type=Path, default=Path('dist'))
    parser.add_argument('--source-only', action='store_true', help='skip the wheel check for source-only verification')
    args = parser.parse_args(argv)
    commit = git('rev-parse', '--verify', '--end-of-options', args.ref + '^{commit}').decode().strip()
    archive = git('archive', '--format=tar', commit)
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            if member.isfile() and allowed(member.name):
                contents[member.name] = source.extractfile(member).read()
    project = tomllib.loads(contents['pyproject.toml'].decode())['project']
    version = project['version']
    prefix = f'cardinal-agent-{version}/'
    manifest = {'name': project['name'], 'version': version, 'source_commit': commit,
                'excluded': ['credentials', 'runtime profiles/logs/caches', 'full public course email archive'],
                'files': {name: hashlib.sha256(content).hexdigest() for name, content in sorted(contents.items())}}
    contents['SOURCE_MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out / 'code.zip'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, content in sorted(contents.items()):
            info = zipfile.ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, content)
    artifacts = [output]
    if not args.source_only:
        wheels = sorted(args.out.glob(f'cardinal_agent-{version}-*.whl'))
        if len(wheels) != 1:
            raise SystemExit('Build exactly one matching wheel first: uv build --wheel --out-dir dist')
        artifacts += wheels
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (args.out / 'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name, digest in checksums.items()))
    (args.out / 'release-manifest.json').write_text(json.dumps({
        'version': version, 'source_commit': commit, 'artifacts': checksums,
        'install': 'Install the wheel or unzip code.zip and run uv sync --locked. Python 3.11+ and configured provider API key required for live chat.'}, indent=2) + '\n')
    print(json.dumps({'source_commit': commit, 'version': version, 'artifacts': checksums}, indent=2))


if __name__ == '__main__':
    main()
