"""공항 helper 국소 비교. 운영/HTTP/수집 실행 입구 없음.

--repo 저장소 --rows 1000으로 기준, --candidate 추가로 작업 트리 후보를 측정한다.
양쪽 모두 다음 lot 조회의 autoflush를 모사하며, SQLite RAM DB만 사용한다.
"""
import argparse
import ast
import asyncio
import gc
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import tracemalloc
import types

TRANSPORT = '2c9b416cc92f18cd6f4c47c1852344c7049ad67c'


def git_source(repo, revision, name):
    return subprocess.check_output(['git', '-C', repo, 'show', revision + ':' + name], timeout=10)


def actual_functions(raw, names, namespace):
    nodes = [node for node in ast.walk(ast.parse(raw))
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])),
                 '<immutable-functions>', 'exec'), namespace)
    return namespace


def measure(action):
    gc.collect()
    tracemalloc.start()
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    result = action()
    wall, cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
    live, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, {'cpu_ns': cpu, 'wall_ns': wall, 'python_live_bytes': live,
                    'python_peak_bytes': peak, 'process_peak_rss_kib': resource.getrusage(
                        resource.RUSAGE_SELF).ru_maxrss}


def transport_airport(args):
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import Session
    raw = (Path(args.repo) / 'backend/app/services/collection.py').read_bytes() if args.candidate else git_source(args.repo, TRANSPORT, 'backend/app/services/collection.py')
    model_raw = git_source(args.repo, TRANSPORT, 'backend/app/models.py')
    module = types.ModuleType('collector_fixture_models')
    sys.modules[module.__name__] = module
    # 실제 모델 선언만 로드한다. app.main/db.session/provider는 import하지 않는다.
    exec(compile(model_raw, '<immutable-models>', 'exec'), module.__dict__)
    Airport = module.Airport
    ns = actual_functions(raw, {'_get_or_create_airport'}, {
        'select': select, 'Airport': Airport, 'now_utc': lambda: datetime.now(timezone.utc)})
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Airport.__table__.create(engine)
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    codes = ('GMP', 'PUS', 'CJU')
    with Session(engine) as session:
        for code in codes:
            session.add(Airport(code=code, name_ko='fixture-' + code, name_en=None,
                                source='fixture', created_at=fixed, updated_at=fixed))
        session.commit()
    counts = {'select': 0, 'insert': 0, 'update': 0, 'other': 0}
    @event.listens_for(engine, 'before_cursor_execute')
    def count(_conn, _cursor, statement, _params, _ctx, _many):
        key = statement.lstrip().split(None, 1)[0].lower()
        counts[key if key in counts else 'other'] += 1
    with Session(engine) as session:
        class LocalAdapter:
            async def scalar(self, statement):
                return session.scalar(statement)
            def add(self, value):
                session.add(value)
            async def flush(self):
                session.flush()
        adapter = LocalAdapter()
        async def action():
            returned = set()
            airports = {}
            for i in range(args.rows):
                code = codes[i % len(codes)]
                row = await ns['_get_or_create_airport'](
                    None, adapter, code, 'fixture-' + code, None, 'fixture',
                    **({'airports': airports} if args.candidate else {}))
                # 실제 다음 lot SELECT의 autoflush와 동일하게 양쪽 매 관측 flush.
                session.flush()
                assert row.code == code
                returned.add(row.id)
            session.flush()
            return len(returned)
        distinct, metrics = measure(lambda: asyncio.run(action()))
        assert counts['select'] == (3 if args.candidate else args.rows) and counts['insert'] == 0
        assert counts['update'] == args.rows
        session.rollback()
    engine.dispose()
    return {**metrics, 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'models_sha256': hashlib.sha256(model_raw).hexdigest(), 'sql': counts,
            'distinct_airports': distinct, 'candidate_lookup_lower_bound': distinct,
            'scope': 'actual airport helper; SQLite memory; excludes lot/snapshot/provider'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--rows', type=int, required=True)
    parser.add_argument('--candidate', action='store_true')
    args = parser.parse_args()
    maximum = 1000
    if not 1 <= args.rows <= maximum:
        parser.error('rows outside local fixture bound')
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
    try:
        result = transport_airport(args)
        print(json.dumps({'status': 'PASS_LOCAL_FIXTURE', 'case': 'transport-airport',
                          'rows': args.rows, 'revision': 'working-tree-candidate' if args.candidate else TRANSPORT, **result}, sort_keys=True))
        return 0
    except BaseException as error:
        print(json.dumps({'status': 'NOT_COMPLETED', 'error_class': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
