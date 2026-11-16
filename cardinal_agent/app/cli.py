"""Installable local CLI. User state never belongs in the source checkout."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.resources import files
import json
import math
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
import time
from uuid import uuid4

from cardinal_agent.app import __version__


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def default_home():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'cardinal-agent'


def load_config(home):
    path = home / 'config.json'
    if not path.exists():
        raise ValueError('Initialize this profile first: cardinal init (or cardinal init --demo).')
    config = json.loads(path.read_text(encoding='utf-8'))
    if config.get('provider') not in ('deepseek', 'openrouter'):
        raise ValueError('Invalid provider in config.json.')
    budget = config.get('budget_usd')
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
        raise ValueError('budget_usd must be a finite positive number.')
    return config


def configure_data(home):
    from cardinal_agent import data
    data.EMAILS_PATH = home / 'data/emails.jsonl'
    data.DOCS_DIR = home / 'data/docs'
    data._read_emails.cache_clear()


def initialize(args, home):
    if (home / 'config.json').exists():
        raise ValueError('Profile already exists. Use configure or choose a different --home.')
    if not math.isfinite(args.budget) or args.budget <= 0:
        raise ValueError('--budget must be finite and positive.')
    if args.demo and any((home / 'data').rglob('*')):
        raise ValueError('Demo initialization requires an empty data directory.')
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    (home / 'data/docs').mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.demo:
        resources = files('cardinal_agent.app').joinpath('demo')
        for resource in resources.joinpath('docs').iterdir():
            (home / 'data/docs' / resource.name).write_bytes(resource.read_bytes())
        (home / 'data/emails.jsonl').write_bytes(resources.joinpath('emails.jsonl').read_bytes())
    atomic_json(home / 'config.json', {'version': 1, 'provider': args.provider, 'model': args.model or ('deepseek-flash' if args.provider == 'deepseek' else 'openai/gpt-6-luna'),
                'budget_usd': args.budget, 'demo_data': args.demo})
    print(f'Profile initialized: {home}\nData: {"fictional demo" if args.demo else "empty; import your own documents or emails"}')
    print('Next: cardinal doctor. API keys are read from the environment, never saved in config.json.')


def import_docs(source, home, replace=False):
    if source.is_symlink():
        raise ValueError('Document source must not be a symlink.')
    source = source.resolve()
    candidates = [source] if source.is_file() else sorted(source.rglob('*.md'))
    if not source.exists() or not candidates:
        raise ValueError('Provide a Markdown file or directory containing .md files.')
    planned = []
    names = set()
    for path in candidates:
        if path.is_symlink() or path.suffix.lower() != '.md':
            raise ValueError('Document import accepts regular .md files, not symlinks.')
        if path.stat().st_size > 10_000_000:
            raise ValueError(f'Document exceeds 10 MB: {path.name}')
        relative = path.name if source.is_file() else path.relative_to(source).as_posix()
        name = re.sub(r'[^a-zA-Z0-9_-]+', '-', relative[:-3].replace('/', '--')).strip('-').lower() + '.md'
        if name == '.md':
            raise ValueError('Document filename needs an alphanumeric identifier.')
        if name in names:
            raise ValueError('Normalized document filenames collide; rename the source files.')
        names.add(name)
        text = path.read_text(encoding='utf-8')
        # The read tool preserves whole lines; reject unsupported input now.
        if any(len(line) > 6000 for line in text.splitlines()):
            raise ValueError(f'{path.name}: a line exceeds 6000 characters; split long paragraphs before import.')
        destination = home / 'data/docs' / name
        if destination.exists() and destination.read_text(encoding='utf-8') != text and not replace:
            raise ValueError(f'{name} already exists; use --replace to update it.')
        planned.append((destination, text))
    for destination, text in planned:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.write_text(text, encoding='utf-8')
    print(f'Imported {len(planned)} Markdown documents. Restart an active chat to load updates.')


def import_emails(source, home, replace=False):
    source = source.resolve()
    destination = home / 'data/emails.jsonl'
    if destination.exists() and not replace:
        raise ValueError('An email archive already exists; use --replace to replace it.')
    if not source.is_file() or source.stat().st_size > 100_000_000:
        raise ValueError('Provide a JSONL file of at most 100 MB.')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    ids = set()
    try:
        with source.open(encoding='utf-8') as input_file, NamedTemporaryFile('w', encoding='utf-8', dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            for number, line in enumerate(input_file, 1):
                if not line.strip():
                    continue
                try:
                    email = json.loads(line)
                    if not isinstance(email, dict) or any(not isinstance(email.get(k), str) for k in ('id', 'date', 'from', 'subject', 'body')):
                        raise ValueError()
                    if not email['id'] or email['id'] in ids:
                        raise ValueError()
                    if not isinstance(email.get('to'), list) or not all(isinstance(v, str) for v in email['to']):
                        raise ValueError()
                    stamp = datetime.fromisoformat(email['date'].replace('Z', '+00:00'))
                    if stamp.tzinfo is None:
                        raise ValueError()
                    email['date'] = stamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
                    email.setdefault('thread_id', email['id'])
                    email.setdefault('reply_to', None)
                    if email['thread_id'] is not None and not isinstance(email['thread_id'], str):
                        raise ValueError()
                    if email['reply_to'] is not None and not isinstance(email['reply_to'], str):
                        raise ValueError()
                except (ValueError, TypeError, KeyError):
                    raise ValueError(f'Invalid email on line {number}; check required fields, unique ID and timezone-aware date.') from None
                ids.add(email['id'])
                output.write(json.dumps(email, ensure_ascii=False) + '\n')
            if not ids:
                raise ValueError('The email archive is empty.')
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f'Imported {len(ids)} emails. Restart an active chat to load updates.')


def runtime_config(home, config):
    from cardinal_agent.llm import _load_env
    _load_env()
    os.environ['CARDINAL_LLM_PROVIDER'] = config['provider']
    os.environ['CARDINAL_CACHE_DIR'] = str(home / 'cache')
    os.environ['CARDINAL_BUDGET_USD'] = str(config['budget_usd'])
    configure_data(home)


def doctor(home, config):
    from cardinal_agent import sandbox
    from cardinal_agent.llm import LM, total_spend
    runtime_config(home, config)
    key_name = 'DEEPSEEK_API_KEY' if config['provider'] == 'deepseek' else 'OPENROUTER_API_KEY'
    model = LM(config.get('model')).model
    report = {'profile': str(home), 'provider': config['provider'], 'model': model,
              'api_key_configured': bool(os.environ.get(key_name)), 'key_environment_variable': key_name,
              'markdown_documents': len(list((home / 'data/docs').glob('*.md'))),
              'email_archive_present': (home / 'data/emails.jsonl').is_file(),
              'demo_data': config.get('demo_data', False), 'os_jail': sandbox.jail(),
              'terminal_default': 'disabled; explicit opt-in required',
              'profile_lifetime_budget_usd': config['budget_usd'], 'recorded_spend_usd': total_spend(),
              'privacy': 'Local orchestration/storage; prompts and selected evidence go to the configured model provider. No model request made by doctor.'}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['api_key_configured'] else 2


def chat(args, home, config):
    from cardinal_agent import adapters, sandbox
    from cardinal_agent.agent.cardinal_tools import build_cardinal_tools
    from cardinal_agent.llm import LM
    from cardinal_agent.types import AgentConfig
    from cardinal_agent.user import ConsoleUser
    runtime_config(home, config)
    key_name = 'DEEPSEEK_API_KEY' if config['provider'] == 'deepseek' else 'OPENROUTER_API_KEY'
    if not os.environ.get(key_name):
        raise ValueError(f'Set {key_name} in your environment, then run cardinal doctor. Do not put keys in chat.')
    if args.terminal and sandbox.jail() == 'none' and not args.allow_unisolated_terminal:
        raise ValueError('OS command isolation is unavailable. Use documents/email tools, or explicitly pass --allow-unisolated-terminal with --terminal after reviewing the security guide.')
    if args.allow_unisolated_terminal and not args.terminal:
        raise ValueError('--allow-unisolated-terminal requires --terminal.')
    lm = LM(config.get('model'), tag='local/agent')
    aux = LM(config.get('model'), tag='local/aux')
    resume_id = getattr(args, 'resume', None)
    if resume_id and not re.fullmatch(r'[A-Za-z0-9-]+', resume_id):
        raise ValueError('Invalid conversation ID.')
    identifier = resume_id or (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    settings = AgentConfig(checkpoint_path=home / 'checkpoints' / f'{identifier}.json', mode='confirm', user=ConsoleUser(), memory_dir=home / 'memory',
                           workspace=home / 'workspace', aux_lm=aux,
                           deny_rules=(r'\brm\b', r'\b(?:curl|wget|ssh|scp)\b'))
    specs = [t for t in build_cardinal_tools(lm, settings) if t.name not in ('remember', 'recall', 'ask_user')
             and (args.terminal or t.name != 'run_terminal')]
    # The same harness works with imported archives from any year.
    for spec in specs:
        spec.description = spec.description.replace('2001 email archive', 'imported local email archive')
    session = adapters.run_agent_session(lm, specs, settings)
    path = home / 'conversations' / f'{identifier}.json'
    record = {'id': identifier, 'version': __version__, 'provider': config['provider'], 'model': lm.model,
              'mode': 'confirm', 'terminal_enabled': args.terminal, 'turns': []}
    if resume_id and path.exists():
        record = json.loads(path.read_text(encoding='utf-8'))
    print(f'Cardinal Agent {__version__} | {config["provider"]}/{lm.model} | confirm mode')
    print(f'Local profile: {home}. Selected content is sent to your model provider.')
    if config.get('demo_data'):
        print('This profile contains fictional demo data; it is not connected to a company account.')
    if args.command == 'chat':
        print('Type exit to leave. Use /status for usage. Tool approvals/questions appear as needed.')
    exit_code = 0
    try:
        if resume_id:
            try:
                result = session.resume()
                print(f'\nassistant> {result.text}')
                record['turns'].append({'status': result.status, 'assistant': result.text, 'resumed': True})
                if result.status != 'done':
                    return 1
            except Exception as exc:
                print(f'Resume stopped ({type(exc).__name__}): {exc}', file=sys.stderr)
                return 1
            finally:
                if session.transcript:
                    record.update({'transcript': session.transcript, 'usage': {'agent': lm.usage(), 'aux': aux.usage()}})
                    atomic_json(path, record)
        while True:
            try:
                message = args.question if args.command == 'ask' else input('\nyou> ').strip()
            except (EOFError, KeyboardInterrupt):
                break
            if message in ('exit', 'quit', '/exit'):
                break
            if message == '/status':
                print(json.dumps({'agent': lm.usage(), 'aux': aux.usage()}, indent=2))
                continue
            if not message:
                if args.command == 'ask':
                    raise ValueError('Question must not be empty.')
                continue
            started = time.perf_counter()
            try:
                result = session.send(message)
                print(f'\nassistant> {result.text}')
                if result.status != 'done':
                    print(f'[Stopped: {result.status}]')
                    exit_code = 1
                record['turns'].append({'user': message, 'assistant': result.text, 'status': result.status,
                                        'seconds': time.perf_counter() - started})
            except KeyboardInterrupt:
                record['turns'].append({'user': message, 'status': 'interrupted'})
                exit_code = 130
                break
            except Exception as exc:
                record['turns'].append({'user': message, 'status': 'error', 'error_type': type(exc).__name__})
                print(f'Run failed ({type(exc).__name__}): {exc}', file=sys.stderr)
                exit_code = 1
                break
            finally:
                record.update({'transcript': session.transcript, 'usage': {'agent': lm.usage(), 'aux': aux.usage()}})
                atomic_json(path, record)
            if args.command == 'ask':
                break
    finally:
        if record['turns']:
            atomic_json(path, record)
            print(f'Conversation saved: {identifier}')
    return exit_code


def parser():
    p = argparse.ArgumentParser(prog='cardinal', description='Local employee assistant: documents, email, memory and approved commands.')
    p.add_argument('--version', action='version', version=f'Cardinal Agent {__version__}')
    p.add_argument('--home', type=Path, default=default_home(), help='isolated local profile directory')
    commands = p.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='initialize an empty or fictional-demo profile')
    init.add_argument('--demo', action='store_true')
    init.add_argument('--provider', choices=['deepseek', 'openrouter'], default='deepseek')
    init.add_argument('--model')
    init.add_argument('--budget', type=float, default=1.0, help='profile lifetime spending cap in USD')
    commands.add_parser('doctor', help='check configuration without a model request')
    demo = commands.add_parser('demo', help='offline BM25 search, no model/API needed')
    demo.add_argument('query', nargs='?', default='onboarding')
    configure = commands.add_parser('configure', help='change non-secret profile settings')
    configure.add_argument('--provider', choices=['deepseek', 'openrouter'])
    configure.add_argument('--model')
    configure.add_argument('--budget', type=float)
    imp = commands.add_parser('import', help='import your own Markdown documents or email JSONL')
    imp.add_argument('kind', choices=['docs', 'emails'])
    imp.add_argument('source', type=Path)
    imp.add_argument('--replace', action='store_true')
    for name in ('chat', 'ask'):
        c = commands.add_parser(name)
        if name == 'ask':
            c.add_argument('question')
        else:
            c.add_argument('--resume', metavar='ID', help='resume an interrupted checkpoint; uncertain tools require operator reconciliation')
        c.add_argument('--terminal', action='store_true', help='enable commands; every command requires approval')
        c.add_argument('--allow-unisolated-terminal', action='store_true', help='explicitly allow terminal without OS jail')
    runs = commands.add_parser('runs', help='inspect durable run states without calling a model')
    actions = runs.add_subparsers(dest='run_action', required=True)
    actions.add_parser('list', help='list run summaries')
    show = actions.add_parser('show', help='show one run and optionally its event trace')
    show.add_argument('id')
    show.add_argument('--trace', action='store_true', help='include potentially sensitive conversation/tool events')
    hist = commands.add_parser('history', help='list saved conversations or inspect one')
    hist.add_argument('--show', metavar='ID')
    mem = commands.add_parser('memory', help='inspect or delete a local memory record')
    mem.add_argument('--forget', metavar='MEMORY_ID')
    return p


def _main(argv=None):
    args = parser().parse_args(argv)
    home = args.home.expanduser().resolve()
    try:
        if args.command == 'init':
            initialize(args, home)
            return 0
        config = load_config(home)
        if args.command == 'configure':
            updated = dict(config)
            for arg, key in [('provider', 'provider'), ('model', 'model'), ('budget', 'budget_usd')]:
                if getattr(args, arg) is not None:
                    updated[key] = getattr(args, arg)
            if not math.isfinite(updated['budget_usd']) or updated['budget_usd'] <= 0:
                raise ValueError('--budget must be finite and positive.')
            if args.provider and args.provider != config['provider'] and args.model is None:
                updated['model'] = 'deepseek-flash' if args.provider == 'deepseek' else 'openai/gpt-6-luna'
            atomic_json(home / 'config.json', updated)
            print('Configuration updated. Existing spending is not reset.')
        elif args.command == 'doctor':
            return doctor(home, config)
        elif args.command == 'import':
            (import_docs if args.kind == 'docs' else import_emails)(args.source, home, args.replace)
        elif args.command == 'demo':
            configure_data(home)
            from cardinal_agent import data
            from cardinal_agent.pipelines.documents import DocumentIndex
            print('Offline retrieval only; no LLM answer and no API call.')
            print(json.dumps(DocumentIndex(data.load_docs()).search(args.query), ensure_ascii=False, indent=2))
        elif args.command in ('chat', 'ask'):
            return chat(args, home, config)
        elif args.command == 'runs':
            from cardinal_agent.agent.runs import inspect_run, list_runs
            if args.run_action == 'list':
                result = list_runs(home / 'checkpoints')
            else:
                if not re.fullmatch(r'[A-Za-z0-9-]+', args.id):
                    raise ValueError('Invalid run ID.')
                result = inspect_run(home / 'checkpoints' / f'{args.id}.json', include_trace=args.trace)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == 'history':
            if args.show:
                if not re.fullmatch(r'[A-Za-z0-9-]+', args.show):
                    raise ValueError('Invalid conversation ID.')
                print((home / 'conversations' / (args.show + '.json')).read_text(encoding='utf-8'))
            else:
                for path in sorted((home / 'conversations').glob('*.json')):
                    print(path.stem)
        elif args.command == 'memory':
            from cardinal_agent.agent.memory import MemoryStore
            store = MemoryStore(home / 'memory')
            records = store.records()
            if args.forget:
                kept = [r for r in records if r['id'] != args.forget]
                if len(kept) == len(records):
                    raise ValueError('Memory ID not found.')
                atomic_json(store.path, kept)
                print('Memory record deleted. Historical conversation/cache files are separate and remain on disk.')
            else:
                print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def main(argv=None):
    # Keep the entry point composable in tests/other Python applications;
    # model and dataset overrides apply only while this CLI invocation runs.
    from cardinal_agent import data
    paths = (data.EMAILS_PATH, data.DOCS_DIR)
    names = ('CARDINAL_LLM_PROVIDER', 'CARDINAL_CACHE_DIR', 'CARDINAL_BUDGET_USD')
    environment = {key: os.environ.get(key) for key in names}
    try:
        return _main(argv)
    finally:
        data.EMAILS_PATH, data.DOCS_DIR = paths
        data._read_emails.cache_clear()
        for key, value in environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == '__main__':
    raise SystemExit(main())
