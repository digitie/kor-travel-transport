"""공개 유가 화면의 주유소 필터(서버 적용). 지도 마커·묶음·개수·범위 통계·지역 카드·시군구 칩·가격 분포가 같은 조건을 쓴다.

근거 필드는 오피넷 지도 화면(`opinet.experimental.BrowserStation`)이 주는 typed 컬럼만 쓴다(추정·상호명 판별 없음):
셀프 `SELF_DIV_CD`→is_self, 24시 `SEL24_YN`→is_24h, 세차 `CWSH_YN`→has_carwash, 경정비 `MAINT_YN`→has_maintenance,
편의점 `CVS_YN`→has_cvs, 품질인증 `KPETRO_YN`→is_kpetro, 상표 `POLL_DIV_CO`/`POLL_DIV_CD`→brand_code.
직영·면세유·화물차 우대는 근거 필드가 없어 제공하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from fastapi import HTTPException, Query
from sqlalchemy import Integer, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelStation, FuelStatisticsPoint, FuelStatisticsState
from app.services.fuel_refresh_prices import has_fuel_price_at_most

OPINET = "opinet_browser"
# 오피넷 시도 코드(정식 이름) → 화면 이름. 오피넷 원문의 시도 이름은 대부분 짧은 이름이지만 몇 행은 정식 이름이라
# 목록·칩·대화상자 제목이 행마다 달라졌다(2026-11-23 운영: 서울 454행 "서울" + 5행 "서울특별시"). 응답은 이 이름 하나로 쓴다.
SIDO_DISPLAY_NAMES = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
    "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원도": "강원",
    "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "전북특별자치도": "전북",
    "전라남도": "전남", "전남광주통합특별시": "전남광주", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
}
# 화면 상표 묶음 → 저장 brand_code. 알뜰은 자영알뜰(RTE)을 함께 묶는다. ETC는 그 밖(미제공 포함) 전부다.
BRAND_GROUPS: dict[str, tuple[str, ...]] = {
    "SKE": ("SKE",), "GSC": ("GSC",), "HDO": ("HDO",), "SOL": ("SOL",), "ALT": ("RTO", "RTE"),
    "NHO": ("NHO",), "RTX": ("RTX",), "NCO": ("NCO",), "SKG": ("SKG",), "E1G": ("E1G",), "ETC": (),
}
KNOWN_BRAND_CODES = tuple(code for codes in BRAND_GROUPS.values() for code in codes)
NEAR_MIN_STEPS = (10, 20, 30, 50, 70, 100, 150, 200)
FLAG_COLUMNS = {
    "self_only": FuelStation.is_self, "open_24h": FuelStation.is_24h, "carwash": FuelStation.has_carwash,
    "maintenance": FuelStation.has_maintenance, "cvs": FuelStation.has_cvs, "kpetro": FuelStation.is_kpetro,
}


@dataclass(frozen=True)
class FuelStationFilters:
    brands: tuple[str, ...] = ()
    self_only: bool = False
    open_24h: bool = False
    carwash: bool = False
    maintenance: bool = False
    cvs: bool = False
    kpetro: bool = False
    near_min: int | None = None
    # near_min을 현재 화면 최저가로 풀어 낸 상한(원). 화면이 없는 조회(가격 분포)에서는 쓰지 않는다.
    price_ceiling: float | None = None
    ceiling_product: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.brands) or any(getattr(self, name) for name in FLAG_COLUMNS) or self.near_min is not None

    def key(self) -> tuple:
        return (self.brands, *(getattr(self, name) for name in FLAG_COLUMNS), self.near_min, self.price_ceiling)

    def station_conditions(self) -> list:
        """FuelStation 행 조건. 브랜드 전체 선택(빈 목록)은 조건 없음이다."""
        conditions = [column.is_(True) for name, column in FLAG_COLUMNS.items() if getattr(self, name)]
        if self.brands and set(self.brands) != set(BRAND_GROUPS):
            codes = [code for group in self.brands for code in BRAND_GROUPS[group]]
            options = [FuelStation.brand_code.in_(codes)] if codes else []
            if "ETC" in self.brands:
                options.append(or_(FuelStation.brand_code.is_(None), FuelStation.brand_code.notin_(KNOWN_BRAND_CODES)))
            conditions.append(or_(*options))
        return conditions

    def point_conditions(self) -> list:
        """공개 세대 point(가격) 조건: 화면 최저가 + N원 상한."""
        if self.price_ceiling is None or self.ceiling_product is None:
            return []
        return [FuelStatisticsPoint.product_code == self.ceiling_product, FuelStatisticsPoint.price <= self.price_ceiling]

    def marker_conditions(self, at) -> list:
        """지도 장소(FuelStation) 조건: 행 조건 + 마커가 보여 주는 실효 가격이 상한 이하인 주유소.

        상한(화면 최저가 + N원)은 범위 요약의 "최저"와 같은 공개 세대에서 구하고, 마커는 화면에 적힌 가격으로 거른다.
        그래서 "~N원" 안의 마커에는 늘 상한 이하 가격이 적힌다(새 수집 반영 대기 중에도).
        """
        conditions = self.station_conditions()
        if self.price_ceiling is not None and self.ceiling_product is not None:
            conditions.append(has_fuel_price_at_most(self.ceiling_product, self.price_ceiling, at))
        return conditions

    def labels(self) -> list[str]:
        names = {"self_only": "셀프", "open_24h": "24시", "carwash": "세차", "maintenance": "경정비", "cvs": "편의점", "kpetro": "품질인증"}
        labels = [label for name, label in names.items() if getattr(self, name)]
        if self.brands and set(self.brands) != set(BRAND_GROUPS):
            labels.append(f"상표 {len(self.brands)}종")
        if self.near_min is not None:
            labels.append(f"최저가+{self.near_min}원")
        return labels


def fuel_station_filter_params(
    brands: str | None = Query(default=None, max_length=80,
                               description="쉼표로 구분한 상표 묶음(SKE,GSC,HDO,SOL,ALT,NHO,RTX,NCO,SKG,E1G,ETC). 생략은 전체"),
    self_only: bool = Query(default=False, description="셀프 주유소만(오피넷 SELF_DIV_CD)"),
    open_24h: bool = Query(default=False, description="24시간 영업만(SEL24_YN)"),
    carwash: bool = Query(default=False, description="세차장 있음만(CWSH_YN)"),
    maintenance: bool = Query(default=False, description="경정비 있음만(MAINT_YN)"),
    cvs: bool = Query(default=False, description="편의점 있음만(CVS_YN)"),
    kpetro: bool = Query(default=False, description="품질인증 주유소만(KPETRO_YN)"),
    near_min: int | None = Query(default=None, description="현재 지도 범위 최저가 + N원 이하만. 유종 하나를 지정해야 한다. "
                                 f"허용값 {', '.join(map(str, NEAR_MIN_STEPS))}"),
) -> FuelStationFilters:
    groups: tuple[str, ...] = ()
    if brands is not None:
        values = [value.strip() for value in brands.split(",") if value.strip()]
        if not values or any(value not in BRAND_GROUPS for value in values):
            raise HTTPException(status_code=422, detail="상표 묶음 값을 확인해 주세요.")
        groups = tuple(sorted(set(values)))
    if near_min is not None and near_min not in NEAR_MIN_STEPS:
        raise HTTPException(status_code=422, detail="지도 최저가 범위 값을 확인해 주세요.")
    return FuelStationFilters(brands=groups, self_only=self_only, open_24h=open_24h, carwash=carwash,
                              maintenance=maintenance, cvs=cvs, kpetro=kpetro, near_min=near_min)


def sido_display_name(sido_value: str | None, sido_name: str | None) -> str:
    """시도의 화면 이름(짧은 이름). 모르는 코드는 원문 이름(없으면 코드)을 그대로 쓴다."""
    return SIDO_DISPLAY_NAMES.get(sido_value or "") or sido_name or sido_value or ""


def point_station_id(point=FuelStatisticsPoint):
    """오피넷 point의 station_key(= str(FuelStation.id))를 정수 id로 바꾼다. 다른 원천(고속도로 휴게소 코드)은 NULL이다.

    예전 조인 `station_key = CAST(fuel_stations.id AS VARCHAR)`는 주유소 쪽을 식으로 감싸 기본키를 못 썼다. 새 공개 세대는
    늘 마지막 ANALYZE보다 늦게 생겨 계획기가 그 세대를 "1행"으로 추정하고(운영 실제 1.2만 행) 중첩 루프 안쪽에서
    fuel_stations 전체를 point마다 다시 읽었다(places 504·가격 분포 수 초, docs/fuel-statistics.md "공개 세대 조인").
    정수 조인은 추정이 틀려도 안쪽이 기본키 조회라 비용이 point 수에 비례한다. CASE가 원천을 먼저 확인하므로
    숫자가 아닌 키를 정수로 바꾸다 실패하지 않는다(오피넷 키는 저장 시 str(id)로만 만든다).
    """
    return case((point.source == OPINET, cast(point.station_key, Integer)), else_=None)


def station_for_point(point=FuelStatisticsPoint, station=FuelStation):
    return station.id == point_station_id(point)


def published_points_with_station():
    p, state = FuelStatisticsPoint, FuelStatisticsState
    return select(p).join(state, and_(p.source == state.source, p.generated_at == state.generated_at)).join(
        FuelStation, station_for_point(p),
    ).where(p.source == OPINET, p.price > 0)


async def resolve_price_ceiling(session: AsyncSession, filters: FuelStationFilters,
                                bounds: tuple[float, float, float, float] | None, products: list[str],
                                sources: list[str] | None = None, query: str | None = None) -> FuelStationFilters:
    """near_min을 현재 화면(다른 필터 적용) 공개 세대 최저가 + N원으로 푼다. 화면 최저가가 없으면 상한도 없다(빈 결과)."""
    if filters.near_min is None or bounds is None:
        return filters
    if len(products) != 1:
        raise HTTPException(status_code=422, detail="지도 최저가 필터는 유종 하나를 고른 뒤 사용할 수 있습니다.")
    p = FuelStatisticsPoint
    conditions = [p.product_code == products[0], p.longitude.between(bounds[0], bounds[2]),
                  p.latitude.between(bounds[1], bounds[3]), *filters.station_conditions()]
    if query and query.strip():
        # 마커·통계와 같은 검색 조건(상호·상표·주소)으로 화면 최저가를 구한다.
        conditions.append(or_(*(column.icontains(query.strip(), autoescape=True) for column in (p.name, p.brand_name, p.address))))
    minimum = None if sources and OPINET not in sources else await session.scalar(
        published_points_with_station().with_only_columns(func.min(p.price)).where(*conditions))
    # 최저가가 없으면 음수 상한으로 빈 결과를 만든다(다른 범위의 가격으로 대신하지 않는다).
    ceiling = float(minimum) + filters.near_min if minimum is not None else -1.0
    return replace(filters, price_ceiling=ceiling, ceiling_product=products[0])
