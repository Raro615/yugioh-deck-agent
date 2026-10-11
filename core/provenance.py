"""
카드 데이터의 출처와 상태 추적.

카드 한 장에 신뢰도 점수 하나를 매기지 않는다. 같은 카드라도 기본 정보는
공식 DB 에서, 한국어 이름은 한국어 DB 에서, 효과 분석은 Lua 에서 오며,
각각 확보 시점과 상태가 다르기 때문이다. 필드 단위로 추적한다::

    Card
     ├─ basic_info      source=official_db   status=confirmed
     ├─ korean_name     source=korean_db     status=confirmed
     ├─ effect_text     source=korean_db     status=confirmed
     └─ effect_analysis source=lua           status=lua_verified

Lua 가 없는 신규 카드도 카드로서 온전히 등록되며, 효과 분석만
``TEXT_DERIVED`` 나 ``UNAVAILABLE`` 로 표시된다. 데이터가 덜 모였다는 이유로
카드가 검색에서 사라지지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SourceKind(str, Enum):
    """데이터가 어디에서 왔는가."""

    OFFICIAL_DB = "official_db"
    """cards.cdb — 카드 ID/종류/레벨/속성/종족/공수 등 구조화된 기본 정보."""
    OFFICIAL_TEXT = "official_text"
    """공식 카드명과 공식 효과 텍스트."""
    KOREAN_DB = "korean_db"
    """공식 한국어 카드명과 한국어 효과 텍스트."""
    LUA = "lua"
    """카드 스크립트 — 실제 게임 처리 로직."""
    SUPPLEMENTARY = "supplementary"
    """보조 자료. 공식 데이터와 같은 신뢰도로 취급하지 않는다."""
    DERIVED = "derived"
    """다른 필드에서 계산해 낸 값."""
    UNKNOWN = "unknown"


class FieldStatus(str, Enum):
    """그 필드 값이 어떤 상태인가."""

    CONFIRMED = "confirmed"
    """공식 소스에서 그대로 가져온 값."""
    SUPPLEMENTARY = "supplementary"
    """보조 자료에서 온 값. 규칙 판단의 근거로 쓰지 않는다."""
    MISSING = "missing"
    """아직 확보하지 못했다."""
    CONFLICTED = "conflicted"
    """소스끼리 값이 달라 한쪽을 조용히 덮어쓰지 않았다."""


class AnalysisStatus(str, Enum):
    """
    효과 분석이 어디에 **근거하는가** — 그 분석이 **옳은가가 아니다**.

    Lua 분석과 텍스트 유래 분석을 절대 같게 취급하지 않는다.

    🔴 **이 enum 은 근거(출처) 계층이다** (Phase 3-F-40 이 명시). 값을 만드는
    자리는 :meth:`core.card_repository.CardRepository._record_provenance`
    **한 곳**이고, 그 분기들은 전부 "어느 소스가 붙어 있는가" 만 본다.
    분석을 실제로 돌려 보고 결정하는 값이 아니다.

    🔴 **결합 증명은 다른 계층이다.** 블록과 핸들러의 대응이 증명됐는지는
    :class:`analysis.effect_model.HandlerBinding` 이 재고, 그것은 분석
    시점에 ``c*.lua`` 를 다시 읽어 ``(소스 지문, 블록 offset)`` 쌍으로
    판정한다 (Phase 3-F-37). **두 값은 서로 다른 시점·다른 근거이고 어긋날
    수 있다.** 실측으로 ``LUA_VERIFIED`` 가 ``MISMATCHED`` ·
    ``UNPROVABLE`` · ``SOURCE_MISSING`` 과 **동시에 성립한다**
    (Phase 3-F-40 §4 의 사례 ②③⑤⑥).

    🔴 **그래서 둘을 하나로 합치지 않는다.** ``HandlerBinding.MATCHED`` 를
    보고 이 상태를 올려서도 안 되고(결합 성공은 의미의 정확성이 아니다),
    결합이 어긋났다고 이 상태를 일괄 강등해서도 안 된다(근거가 사라진 것은
    아니다).
    """

    LUA_VERIFIED = "lua_verified"
    """
    **Lua 스크립트가 분석 근거로 붙어 있다** — 조건은 ``card.script is not
    None`` 하나다.

    🔴 **"효과를 구조화했다" 는 뜻이 아니다.** 실측: 이 상태인 12,687장 중
    **215장**은 등록 효과가 **0개**다. 그중 183장은 파서가 효과 블록을
    하나도 뽑지 못했고(``Fusion.AddProcMix`` · ``EnableReviveLimit`` 만 있는
    융합 몬스터 등), 32장은 블록이 전부 해결 효과다. 스크립트가 붙었다는
    사실과 거기서 무엇을 뽑았다는 사실은 다르다.

    🔴 **"검증했다" 는 뜻도 아니다.** 결합 증명은 ``HandlerBinding`` 이,
    구조화 정도는 :meth:`analysis.effect_model.CardAnalysis.coverage` 가
    따로 보고한다.
    """
    TEXT_DERIVED = "text_derived"
    """
    **공식 텍스트만이 근거다** (Lua 가 없다). 게임 처리와 어긋날 수 있다.

    🔴 실측 주의: 이 상태가 붙는 조건은 "Lua 가 없고 효과 텍스트가 있다"
    이고, **텍스트 분석을 실제로 돌린 결과가 아니다.**
    :class:`analysis.text_effect_analyzer.TextEffectAnalyzer` 는 현재
    production 호출자가 **하나도 없다** (Phase 3-F-40 전수 확인). 즉 이
    상태는 "텍스트에서 유추할 수 있다" 는 근거 표시다.

    **효과가 있는 카드에만 쓴다.** 효과 자체가 없는 통상 몬스터까지 여기
    넣으면, 듀얼 엔진이 "text_derived 는 실행 차단" 규칙을 적용할 때 푸른 눈의
    백룡 같은 멀쩡한 카드가 함께 막힌다 (실측 747장).
    """
    NO_EFFECT = "no_effect"
    """
    공식 DB 가 통상 몬스터/토큰이라고 밝힌 카드. **분석할 효과가 없다.**

    ``Lua 없음`` 과 구분하는 것이 핵심이다. Lua 가 없는 이유가
    "효과가 없어서"인지 "스크립트가 아직 없어서"인지에 따라 듀얼 엔진의
    판단이 정반대가 된다.
    """
    UNAVAILABLE = "unavailable"
    """분석 근거가 아직 없다. 효과가 없다는 뜻이 **아니다.**"""
    UNKNOWN = "unknown"


#: 필드 값을 결정할 때의 소스 우선순위.
#: 공식 구조화 데이터 > 공식 텍스트 > Lua > 한국어 > 보조.
#: 다만 Lua 는 '게임 처리 로직' 의 최상위 근거이고 공식 문구를 정하지는 않는다.
SOURCE_PRIORITY: dict[SourceKind, int] = {
    SourceKind.OFFICIAL_DB: 100,
    SourceKind.OFFICIAL_TEXT: 80,
    SourceKind.LUA: 60,
    SourceKind.KOREAN_DB: 40,
    SourceKind.SUPPLEMENTARY: 20,
    SourceKind.DERIVED: 10,
    SourceKind.UNKNOWN: 0,
}

#: 필드별 우선순위 예외.
#: 표시용 이름과 텍스트는 한국어 공식 데이터가 영어 원문보다 앞선다
#: (원문은 지워지지 않고 name_en / desc_en 에 남는다).
#: 효과 분석은 Lua 가 최상위다.
FIELD_PRIORITY: dict[str, list[SourceKind]] = {
    "basic_info": [SourceKind.OFFICIAL_DB, SourceKind.SUPPLEMENTARY],
    "card_name": [
        SourceKind.KOREAN_DB,
        SourceKind.OFFICIAL_TEXT,
        SourceKind.OFFICIAL_DB,
        SourceKind.LUA,
    ],
    "effect_text": [
        SourceKind.KOREAN_DB,
        SourceKind.OFFICIAL_TEXT,
        SourceKind.OFFICIAL_DB,
    ],
    "effect_analysis": [SourceKind.LUA, SourceKind.OFFICIAL_TEXT],
    "related_cards": [
        SourceKind.LUA,
        SourceKind.OFFICIAL_DB,
        SourceKind.SUPPLEMENTARY,
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class FieldProvenance:
    """필드 하나의 출처 기록."""

    field: str
    source: SourceKind = SourceKind.UNKNOWN
    status: FieldStatus = FieldStatus.MISSING
    retrieved_at: str | None = None
    detail: str | None = None
    conflicts: list[str] = field(default_factory=list)
    """다른 소스가 제시한 값. 덮어쓰지 않고 남겨 둔다."""

    def describe_ko(self) -> str:
        text = f"{self.field}: {self.source.value} ({self.status.value})"
        if self.conflicts:
            text += f" · 충돌 {len(self.conflicts)}건"
        return text


@dataclass(slots=True)
class DataAvailability:
    """어떤 소스가 이 카드를 다루고 있는가."""

    cdb_available: bool = False
    official_text_available: bool = False
    korean_available: bool = False
    lua_available: bool = False
    effect_analysis_available: bool = False
    text_analysis_available: bool = False

    #: 🔴 **``text_analysis_available`` 이 두 메서드에서 빠져 있었다**
    #: (Phase 3-F-41 이 발견). 여섯 칸 중 다섯 칸만 요약했다. 그래서 Lua 가
    #: 없는 카드에서 유일하게 켜지는 플래그가 **요약에 나타나지 않았다** —
    #: ``describe_ko()`` 가 ``✗효과분석`` 만 보여 주고 "텍스트가 근거다" 는
    #: 사실을 떨어뜨렸다 (실측 756장이 그 상태다). 자기 자신을 요약하는
    #: 메서드가 자기 필드를 빠뜨리는 것은 숨기면 안 되는 결함이다
    #: (Phase 3-F-38 의 ``NO_EFFECT`` 행 누락과 같은 모양).
    def missing(self) -> list[str]:
        return [
            name
            for name, present in (
                ("cdb", self.cdb_available),
                ("official_text", self.official_text_available),
                ("korean", self.korean_available),
                ("lua", self.lua_available),
                ("effect_analysis", self.effect_analysis_available),
                ("text_analysis", self.text_analysis_available),
            )
            if not present
        ]

    def describe_ko(self) -> str:
        marks = {
            "CDB": self.cdb_available,
            "공식텍스트": self.official_text_available,
            "한국어": self.korean_available,
            "Lua": self.lua_available,
            "효과분석": self.effect_analysis_available,
            "텍스트근거": self.text_analysis_available,
        }
        return " ".join(f"{'✓' if ok else '✗'}{name}" for name, ok in marks.items())


@dataclass(slots=True)
class CardProvenance:
    """카드 한 장의 출처 기록 전체."""

    card_id: int
    availability: DataAvailability = field(default_factory=DataAvailability)
    fields: dict[str, FieldProvenance] = field(default_factory=dict)
    analysis_status: AnalysisStatus = AnalysisStatus.UNAVAILABLE
    first_seen: str | None = None
    last_updated: str | None = None

    def record(
        self,
        field_name: str,
        source: SourceKind,
        status: FieldStatus = FieldStatus.CONFIRMED,
        detail: str | None = None,
    ) -> FieldProvenance:
        """필드의 출처를 기록한다. 이미 있으면 우선순위를 비교한다."""
        existing = self.fields.get(field_name)
        if existing is not None and existing.source is not source:
            # 값을 조용히 덮어쓰지 않는다. 낮은 우선순위 소스는 충돌로 남긴다.
            order = FIELD_PRIORITY.get(field_name, list(SOURCE_PRIORITY))
            if _rank(source, order) <= _rank(existing.source, order):
                # 들어온 쪽이 우선순위가 낮거나 같다. 기존 값을 유지하고
                # 다른 값이 있었다는 사실만 남긴다.
                if source.value not in existing.conflicts:
                    existing.conflicts.append(source.value)
                return existing
            # 들어온 쪽이 우선한다. 밀려난 소스를 충돌로 기록한다.
            if existing.source.value not in existing.conflicts:
                existing.conflicts.append(existing.source.value)
            existing.source = source
            existing.status = status
            existing.retrieved_at = _now()
            existing.detail = detail
            return existing

        entry = FieldProvenance(
            field=field_name,
            source=source,
            status=status,
            retrieved_at=_now(),
            detail=detail,
        )
        self.fields[field_name] = entry
        return entry

    def source_of(self, field_name: str) -> SourceKind:
        entry = self.fields.get(field_name)
        return entry.source if entry else SourceKind.UNKNOWN

    def has_conflict(self) -> bool:
        return any(entry.conflicts for entry in self.fields.values())

    def describe_ko(self) -> str:
        lines = [
            f"카드 {self.card_id} · {self.availability.describe_ko()}",
            f"  효과 분석: {self.analysis_status.value}",
        ]
        lines.extend(f"  {entry.describe_ko()}" for entry in self.fields.values())
        return "\n".join(lines)


def _rank(source: SourceKind, order: list[SourceKind]) -> int:
    """우선순위 목록에서의 순위. 목록에 없으면 전역 우선순위를 쓴다."""
    if source in order:
        return len(order) - order.index(source)
    return -SOURCE_PRIORITY.get(source, 0)
