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
    import collections

    status = collections.Counter(
        c.provenance.analysis_status.value for c in repository.all_cards()
    )
    print("\n카드 데이터 현황")
    print("-" * 60)
    stats = repository.stats()
    print(f"  카드            : {stats['canonical']:,}장 (판본 포함 {stats['total']:,})")
    labels = {
        AnalysisStatus.LUA_VERIFIED.value: "Lua 검증됨",
        AnalysisStatus.TEXT_DERIVED.value: "텍스트 유래 (Lua 없음)",
        AnalysisStatus.UNAVAILABLE.value: "분석 근거 없음",
    }
    for key, label in labels.items():
        print(f"  {label:22}: {status.get(key, 0):,}장")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="카드 데이터 업데이트")
    parser.add_argument(
        "--check", action="store_true", help="변경 내역만 보고 아무것도 바꾸지 않는다"
    )
    parser.add_argument("--update", action="store_true", help="변경을 반영한다")
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="변경된 카드만 다시 분석한다 (기본 동작)",
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

    if args.changed_only and affected:
        from analysis import EffectAnalyzer

        analyzer = EffectAnalyzer(repository)
        analysed = 0
        for card_id in affected:
            card = repository.get(card_id)
            if card is not None:
                analyzer.analyze(card)
                analysed += 1
        print(f"  변경된 카드 {analysed:,}장만 다시 분석했습니다.")

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
