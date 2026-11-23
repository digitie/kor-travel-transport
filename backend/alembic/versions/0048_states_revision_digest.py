"""수집 상태 표를 장소 입력 revision 문장 trigger에서 뺀다(상태 쓰기의 전역 직렬화 제거, 2026-11-24).

0045는 장소 지도 입력 표마다 문장 trigger(`kt_places_revision`)를 달아, 쓰기 문장마다 `reference_export_input_revisions`의
그 표 행 하나를 갱신한다. 그 행 잠금은 transaction 끝까지 남는다. `transport_collection_states`는 수집기 **모두**가
claim·성공·실패마다 쓰는 표라, 이 trigger가 서로 다른 수집기(공항·고속도로·유가·휴게소 유가)의 상태 쓰기를 한 행에서
줄 세웠다. 앞선 transaction이 상태를 쓴 뒤 저장을 이어 가면 뒤의 상태 UPDATE가 세션 `lock_timeout`(5초)으로 실패했다 —
운영 odroid에서 0045 배포(2026-11-18 23:25Z) 직후부터 14일 38건(공항 26·휴게소 유가 10·유가 2). 0045 이전에는 상태 쓰기가
자기 source 행만 잠갔다.

상태 표는 수십 행이라 장소 캐시는 revision 카운터 대신 같은 REPEATABLE READ snapshot 안에서 표 내용 digest를 직접 읽는다
(`place_map_cache`). 그래서 이 표의 trigger와 component 행은 필요 없다. 다른 표의 trigger는 그대로다.
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0048_states_revision_digest"
down_revision = "0047_fuel_points_gen_product"
branch_labels = None
depends_on = None

TABLE = "transport_collection_states"
COMPONENT = "places." + TABLE
ACTIONS = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
        op.execute("SET LOCAL statement_timeout = '120s'")
        for action in ACTIONS:
            op.execute(f"DROP TRIGGER IF EXISTS kt_places_revision_{action.lower()} ON public.{TABLE}")
    op.execute(sa.text("DELETE FROM reference_export_input_revisions WHERE component = :component")
               .bindparams(component=COMPONENT))


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
        op.execute("SET LOCAL statement_timeout = '120s'")
    op.bulk_insert(sa.table("reference_export_input_revisions",
        sa.column("component", sa.String()), sa.column("epoch", sa.String()),
        sa.column("revision", sa.BigInteger())),
        [{"component": COMPONENT, "epoch": str(uuid4()), "revision": 0}])
    if op.get_bind().dialect.name != "postgresql":
        return
    for action in ACTIONS:
        op.execute(f"CREATE TRIGGER kt_places_revision_{action.lower()} AFTER {action} "
                   f"ON public.{TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.kt_places_revision()")
