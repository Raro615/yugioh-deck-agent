"""
카드 데이터 업데이트 파이프라인.

    python -m scripts.update_cards --check          무엇이 바뀌었는지만 본다
    python -m scripts.update_cards --update         변경을 반영한다
    python -m scripts.update_cards --source lua     특정 소스만 본다

흐름은 다음과 같다.

    수집 -> 변경 감지 -> 병합 -> 분석 -> 인덱스 -> 검증

신규 카드가 나와도 ``core/`` 와 ``analysis/`` 를 고치지 않는다. 소스가 늘면
:mod:`sources.adapters` 에 어댑터를 하나 더 붙이면 된다.

전체를 다시 파싱하지 않는다. 소스별 지문을 이전 실행과 비교해 신규·변경·삭제된
카드만 골라낸다.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.provenance import AnalysisStatus, SourceKind  # noqa: E402
from sources.adapters import (  # noqa: E402
    KoreanDatabaseAdapter,
    LuaScriptAdapter,
    OfficialDatabaseAdapter,
)
from sources.source_manager import ChangeKind, SourceManager  # noqa: E402
from sources.supplementary import SupplementaryAdapter  # noqa: E402

SOURCE_NAMES = {
    "official": SourceKind.OFFICIAL_DB,
    "lua": SourceKind.LUA,
    "korean": SourceKind.KOREAN_DB,
    "supplementary": SourceKind.SUPPLEMENTARY,
}


def build_manager(state_path=None) -> SourceManager:
    """기본 어댑터를 등록한 매니저. 소스를 늘리려면 여기에만 추가한다."""
    return SourceManager(
        adapters=[
            OfficialDatabaseAdapter(),
            LuaScriptAdapter(),
            KoreanDatabaseAdapter(),
            SupplementaryAdapter(),
        ],
        state_path=state_path,
    )


def report_plan(plan) -> None:
    print("소스별 변경 내역")
    print("-" * 60)
    for source, counts in plan.counts().items():
        line = "  ".join(
            f"{kind}={counts.get(kind, 0):,}"
            for kind in ("new", "changed", "removed", "unchanged")
        )
        print(f"  {source:16} {line}")
    affected = plan.changed_card_ids()
    print(f"\n다시 처리할 카드: {len(affected):,}장")
    return affected


def report_bindings(bindings, analysed: int, unbound_blocks: int,
                    unbound_cards: list[int]) -> None:
    """
    효과 블록과 핸들러의 **결합 상태**를 갱신 요약에 적는다 (Phase 3-F-38).

    🔴 **네 상태를 하나의 성공/실패로 합치지 않는다.** ``MISMATCHED`` 는
    "두 소스가 실제로 다르다", ``UNPROVABLE`` 은 "증명할 정보가 없다" 이고
    복구 방법이 서로 다르다. 안내 문구는
    :data:`analysis.effect_model._BINDING_GUIDANCE_KO` 에서 가져온다 —
    CLI 출력과 **같은 표**를 쓰므로 두 경로가 갈리지 않는다.

    🔴 **갱신의 성공·실패 판정을 바꾸지 않는다.** :func:`validate` 의 계약은
    "데이터가 덜 모였다는 이유로 카드가 사라지지 않는다" 이고, 그것은 카드
    레코드의 온전함에 관한 것이다. 결합 상태는 **효과 분석의 증명 여부**라서
    같은 축이 아니다. 그래서 여기서는 **보고만** 하고 종료 코드를 건드리지
    않는다. 그 판단을 바꾸는 것은 갱신 정책 재설계이고 이번 Phase의 범위가
    아니다 (보고서 §6 참고).
    """
    from analysis.effect_model import _BINDING_GUIDANCE_KO, HandlerBinding

    if not analysed:
        return
    matched = bindings.get(HandlerBinding.MATCHED, 0)
    #: 🔴 **집계 범위를 적는다** (Phase 3-F-39 / §4). 이 표는 "다시 분석한
    #: 카드" 기준이고, 바로 아래 :func:`summarise` 의 표는 "저장소 전체"
    #: 기준이다. 3장과 14,127장이 아무 표시 없이 붙어 있었다.
    print(f"\n  효과 블록 결합 상태 (다시 분석한 {analysed:,}장 기준)")
    print(f"    {_BINDING_GUIDANCE_KO[HandlerBinding.MATCHED][0]:22}: "
          f"{matched:,}장")
    for binding in (HandlerBinding.MISMATCHED, HandlerBinding.UNPROVABLE,
                    HandlerBinding.SOURCE_MISSING):
        count = bindings.get(binding, 0)
        if not count:
            continue
        name, hint = _BINDING_GUIDANCE_KO[binding]
        print(f"    ✗ {name:20}: {count:,}장")
        print(f"      {hint}")
    #: 🔴 합이 맞는지 **직접 확인**한다. 어느 상태도 누락되지 않았음을
    #: 요약 자체가 보장해야 한다.
    if sum(bindings.values()) != analysed:
        print(f"    ✗ 상태 합계 {sum(bindings.values()):,} != 분석 {analysed:,}")
    if unbound_blocks:
        sample = ", ".join(str(x) for x in unbound_cards[:5])
        more = " …" if len(unbound_cards) > 5 else ""
        print(f"    증명되지 않은 블록 {unbound_blocks:,}개"
              f" (카드 {len(unbound_cards):,}장: {sample}{more})")
        print("      이 블록들은 등록·해결 효과 어느 쪽으로도 집계하지"
              " 않았습니다 — 어느 쪽이라고 주장할 근거가 없기 때문입니다.")


def validate(repository) -> list[str]:
    """
    업데이트 뒤 데이터가 온전한지 확인한다.

    가장 중요한 규칙: 데이터가 덜 모였다는 이유로 카드가 사라지지 않는다.
    """
    problems: list[str] = []
    cards = repository.all_cards()
    if not cards:
        problems.append("카드가 하나도 없다")
        return problems

    no_provenance = [c for c in cards if c.provenance is None]
    if no_provenance:
        problems.append(f"출처 기록이 없는 카드 {len(no_provenance)}장")

    # Lua 가 없어도 카드로서는 온전해야 한다.
    lua_less = [c for c in cards if c.script is None]
    dropped = [c for c in lua_less if not c.name or c.type_mask == 0]
    if dropped:
        problems.append(f"Lua 가 없다고 기본 정보까지 빠진 카드 {len(dropped)}장")

    # 검색 인덱스가 살아 있는지
    if not repository.find_by_exact_name(cards[0].display_name()):
        problems.append("이름 인덱스가 갱신되지 않았다")
    return problems


def summarise(repository) -> None:
    status = collections.Counter(
        c.provenance.analysis_status.value for c in repository.all_cards()
    )
    #: 🔴 집계 범위를 적는다 (Phase 3-F-39 / §4) — 위 결합 표와 기준이 다르다.
    print("\n카드 데이터 현황 (저장소 전체)")
    print("-" * 60)
    stats = repository.stats()
    print(f"  카드            : {stats['canonical']:,}장 (판본 포함 {stats['total']:,})")
    #: 🔴 ``NO_EFFECT`` 행이 **빠져 있었다** (Phase 3-F-38 이 발견).
    #: 실측 684장이 이 상태인데 표에 없어서, 출력된 행의 합이 카드 총수와
    #: 맞지 않았다 (12,687 + 756 = 13,443 ≠ 14,127). 상태 요약이 자기
    #: 자신과 어긋나는 것은 숨기면 안 되는 종류의 결함이다.
    labels = {
        AnalysisStatus.LUA_VERIFIED.value: "Lua 검증됨",
        AnalysisStatus.TEXT_DERIVED.value: "텍스트 유래 (Lua 없음)",
        AnalysisStatus.NO_EFFECT.value: "효과 없음 (통상 몬스터·토큰)",
        AnalysisStatus.UNAVAILABLE.value: "분석 근거 없음",
    }
    for key, label in labels.items():
        print(f"  {label:26}: {status.get(key, 0):,}장")
    #: 🔴 열거한 상태가 전부인지 확인한다 — 합이 안 맞으면 표가 낡은 것이다.
    unlisted = {k: v for k, v in status.items() if k not in labels}
    if unlisted:
        print(f"  ✗ 표에 없는 분석 상태: {unlisted}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="카드 데이터 업데이트")
    parser.add_argument(
        "--check", action="store_true", help="변경 내역만 보고 아무것도 바꾸지 않는다"
    )
    parser.add_argument("--update", action="store_true", help="변경을 반영한다")
    #: 🔴 **이 flag 는 분석을 켜고 끄는 스위치가 아니다** (Phase 3-F-39).
    #: Phase 3-F-38 이 N30 으로 적어 둔 그대로, ``action="store_true"`` 의
    #: 기본값은 ``False`` 인데 help 는 "(기본 동작)" 이라고 적혀 있었다.
    #: 그래서 ``--update`` 만 주면 **분석 단계가 통째로 빠졌고**, 이 모듈
    #: docstring 이 적어 둔 흐름(수집 -> 변경 감지 -> 병합 -> **분석** ->
    #: 인덱스 -> 검증)과 어긋났다.
    #:
    #: 🔴 **기본값을 뒤집지 않았다.** 끄는 쪽("전부 다시 분석")이 코드에
    #: 아예 없어서 ``False`` 에는 가리킬 동작이 없다. 기본값만 ``True`` 로
    #: 바꾸면 끌 수 없는 flag 가 되고, 없는 반대 동작을 있는 것처럼 만들게
    #: 된다. 고친 것은 **실행 조건**이다 (아래 ``if affected:``). 이 flag 는
    #: 같은 것을 명시적으로 적는 수단으로 남고, 주던 쪽의 출력은 글자 단위로
    #: 같다.
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="변경된 카드만 다시 분석한다 (기본 동작이며 현재 유일한 동작)",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCE_NAMES),
        help="특정 소스만 본다. 여러 번 줄 수 있다",
    )
    args = parser.parse_args(argv)

    if not args.check and not args.update:
        args.check = True  # 기본은 안전한 쪽

    only = [SOURCE_NAMES[name] for name in args.source] if args.source else None
    manager = build_manager()

    available = [a.kind.value for a in manager.available_adapters()]
    print(f"사용 가능한 소스: {', '.join(available) or '없음'}\n")

    plan = manager.plan(only=only) if args.check else manager.commit(only=only)
    affected = report_plan(plan)

    if args.check:
        print("\n--check 모드입니다. 반영하려면 --update 로 실행하세요.")
        return 0

    if plan.is_empty():
        print("\n바뀐 것이 없습니다. 다시 분석하지 않습니다.")
        return 0

    print("\n변경된 카드를 반영해 리포지토리를 다시 만듭니다...")
    from core.card_repository import CardRepository

    repository = CardRepository.build()

    #: 🔴 **flag 로 막지 않는다** (Phase 3-F-39 / N30). 변경된 카드 분석은
    #: 이제 항상 돈다. 안전한 근거: ``EffectAnalyzer.analyze`` 는 파일을 쓰지
    #: 않고 ``Card`` 를 변형하지 않는다 (메모리 캐시만 둔다). 그래서 늘
    #: 돌려도 **저장되는 것이 하나도 바뀌지 않는다** — 늘어나는 것은 출력과
    #: 실행시간뿐이고, 최악(바뀐 카드가 전수 14,127장)이 실측 약 34~54초다.
    if affected:
        from analysis import EffectAnalyzer

        analyzer = EffectAnalyzer(repository)
        analysed = 0
        #: 🔴 **분석 결과를 버리지 않는다** (Phase 3-F-38). 여기서는
        #: ``analyzer.analyze(card)`` 를 부르고 반환값을 그냥 버렸고, 그래서
        #: Phase 3-F-37 이 만든 결합 상태가 갱신 요약까지 오지 못했다.
        #: 카드 단위 ``handler_binding`` 과 증명되지 않은 블록 수를 센다.
        bindings: collections.Counter = collections.Counter()
        unbound_blocks = 0
        unbound_cards: list[int] = []
        for card_id in affected:
            card = repository.get(card_id)
            if card is not None:
                analysis = analyzer.analyze(card)
                bindings[analysis.handler_binding] += 1
                if analysis.unbound_effects:
                    unbound_blocks += len(analysis.unbound_effects)
                    unbound_cards.append(card_id)
                analysed += 1
        print(f"  변경된 카드 {analysed:,}장만 다시 분석했습니다.")
        report_bindings(bindings, analysed, unbound_blocks, unbound_cards)

    problems = validate(repository)
    summarise(repository)
    if problems:
        print("\n검증 실패")
        for problem in problems:
            print(f"  ✗ {problem}")
        return 1
    print("\n검증 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
