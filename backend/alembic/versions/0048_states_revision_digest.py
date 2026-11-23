"""수집 상태 표를 장소 입력 revision 문장 trigger에서 뺀다(상태 쓰기의 전역 직렬화 제거, 2026-11-24).

0045는 장소 지도 입력 표마다 문장 trigger(`kt_places_revision`)를 달아, 쓰기 문장마다 `reference_export_input_revisions`의
그 표 행 하나를 갱신한다. 그 행 잠금은 transaction 끝까지 남는다. `transport_collection_states`는 수집기 **모두**가
claim·성공·실패마다 쓰는 표라, 이 trigger가 서로 다른 수집기(공항·고속도로·유가·휴게소 유가)의 상태 쓰기를 한 행에서
줄 세웠다. 앞선 transaction이 상태를 쓴 뒤 저장을 이어 가면 뒤의 상태 UPDATE가 세션 `lock_timeout`(5초)으로 실패했다 —
운영 odroid에서 0045 배포(2026-11-18 23:25Z) 직후부터 14일 38건(공항 26·휴게소 유가 10·유가 2). 0045 이전에는 상태 쓰기가
자기 source 행만 잠갔다.

상태 표는 수십 행이라 장소 캐시는 revision 카운터 대신 같은 REPEATABLE READ snapshot 안에서 표 내용 digest를 직접 읽는다
(`place_map_cache`). 그래서 이 표의 trigger는 필요 없다. 다른 표의 trigger는 그대로다.

`places.transport_collection_states` component 행은 **남긴다**(더는 아무도 올리지 않는 죽은 행). 배포 중 잠시 같은 DB를
보는 옛 이미지는 11개 component 행을 요구하고(없으면 503) 이 표의 trigger가 없으면 캐시를 쓰지 않아(`trusted`=false) 늘
정답을 낸다. 행 삭제는 옛 이미지가 남지 않은 뒤의 별도 migration으로 한다.

`DROP TRIGGER`는 표의 AccessExclusive 잠금이 필요하다. 수집·공개 읽기가 표를 쥐고 있으면 `lock_timeout` 2초로 실패하고
transaction째 되돌아가므로(부분 적용 없음) Dagster drain 뒤 migrate를 다시 돌린다.
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


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
        op.execute("SET LOCAL statement_timeout = '120s'")
    # 남겨 둔 component 행의 epoch를 바꿔, 0048 동안 trigger 없이 바뀐 상태가 옛 revision으로 재사용되지 않게 한다.
    op.execute(sa.text("UPDATE reference_export_input_revisions SET epoch = :epoch WHERE component = :component")
               .bindparams(epoch=str(uuid4()), component=COMPONENT))
    if op.get_bind().dialect.name != "postgresql":
        return
    for action in ACTIONS:
        op.execute(f"CREATE TRIGGER kt_places_revision_{action.lower()} AFTER {action} "
                   f"ON public.{TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.kt_places_revision()")
