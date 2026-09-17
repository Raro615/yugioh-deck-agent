"""
공식 OCG 카드 데이터베이스에서 카드별 재정을 수집한다.

**전체 수집은 기본값이 아니다.** 샘플로 파싱을 검증한 뒤에만 전체를 돌린다.
공식 사이트에 부담을 주지 않도록 요청 간 대기와 HTML 캐시를 둔다.

사용법::

    # 샘플 (저장소에 커밋되는 검증용 표본)
    python -m scripts.fetch_ocg_rulings --sample

    # 특정 카드만 (패스코드 또는 cid)
    python -m scripts.fetch_ocg_rulings --card-id 14558127 --card-id 2511
    python -m scripts.fetch_ocg_rulings --cid 4007

    # 식별자가 검증된 카드만 수집된다. 검증은 별도 명령이다:
    #   python -m scripts.build_card_identity --verify 500

    # 이어받기 — 이미 받은 카드는 건너뛴다
    python -m scripts.fetch_ocg_rulings --all --skip-collected --limit 0

    # 갱신 — 전부 다시 확인하고 content_hash 로 new/changed/removed 를 가린다
    python -m scripts.fetch_ocg_rulings --all --limit 0 --refresh

    # 전체 수집 (14,000여 카드 — 매우 오래 걸린다)
    python -m scripts.fetch_ocg_rulings --all --limit 0 --delay 1.5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.card_identity import CardIdentityMapping
from rulings.ruling_model import RulingAvailability
from rulings.ruling_repository import RulingRepository, DEFAULT_RULING_DIR
from rulings.update import RulingUpdatePlan, diff_ruling_set, merge_translations
from sources.ocg_ruling_adapter import OfficialOcgRulingAdapter

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 검증용 표본. 파싱이 어디서 깨지는지 보려면 성질이 다른 카드가 필요하다.
SAMPLE_CARDS: tuple[tuple[int, str], ...] = (
    (89631139, "Q&A 많음(88) · 補足 있음 · 구 카드 · Lua 일본어명 없음"),
    (5318639, "Q&A 아주 많음(316) · 구 카드"),
    (46986414, "Q&A 많음(77) · 補足 없음"),
    (14558127, "Q&A 많음(78) · 補足 있음 · 한국어명과 일본어명이 다름"),
    (2511, "Q&A 적음(7) · 한국어명(라뷰린스 쿠클락)과 일본어명(白銀の城の狂時計)이 완전히 다름"),
    (24224830, "Q&A 적음(11) · 補足 있음"),
    (10000, "Q&A 없음 · 補足 있음 · 최근 카드"),
    (23434538, "Q&A 중간(35) · 補足 있음 · 자주 인용되는 카드"),
    (32864, "Q&A 없음 · 補足 없음 · 구 통상 몬스터 -> ruling_not_found 표본"),
)


def resolve_targets(args, identity: CardIdentityMapping) -> list[tuple[int, int | None]]:
    """``(cid, card_id)`` 목록으로 정리한다."""
    targets: list[tuple[int, int | None]] = []
    seen: set[int] = set()

    def add(cid: int, card_id: int | None) -> None:
        if cid not in seen:
            seen.add(cid)
            targets.append((cid, card_id))

    if args.sample:
        for card_id, _why in SAMPLE_CARDS:
            cid = identity.cid_for(card_id)
            if cid is None:
                print(f"  [건너뜀] 패스코드 {card_id} 의 cid 를 모릅니다.", file=sys.stderr)
                continue
            add(cid, card_id)
    for card_id in args.card_id:
        cid = identity.cid_for(card_id)
        if cid is None:
            print(f"  [건너뜀] 패스코드 {card_id} 의 cid 를 모릅니다.", file=sys.stderr)
            continue
        add(cid, card_id)
    for cid in args.cid:
        add(cid, identity.primary_card_id(cid))
    if args.all:
        for cid in identity.cids:
            add(cid, identity.primary_card_id(cid))
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="공식 OCG 데이터베이스에서 카드별 재정을 수집한다."
    )
    group = parser.add_argument_group("대상")
    group.add_argument("--sample", action="store_true", help="검증용 표본 카드")
    group.add_argument("--card-id", type=int, action="append", default=[],
                       help="패스코드 (여러 번 지정 가능)")
    group.add_argument("--cid", type=int, action="append", default=[],
                       help="공식 cid (여러 번 지정 가능)")
    group.add_argument("--all", action="store_true", help="매핑에 있는 모든 카드")

    parser.add_argument("--limit", type=int, default=50,
                        help="이번 실행에서 처리할 최대 카드 수 (0 이면 제한 없음)")
    parser.add_argument("--delay", type=float, default=1.2, help="요청 간 대기 (초)")
    parser.add_argument("--skip-collected", action="store_true",
                        help="이미 정상 수집한 카드는 다시 확인하지 않는다 (이어받기)")
    parser.add_argument("--refresh", action="store_true",
                        help="HTML 캐시를 무시하고 다시 받는다")
    parser.add_argument(
        "--allow-unverified-identity", action="store_true",
        help=(
            "식별자가 검증되지 않은 카드도 조회한다. 결과에는 "
            "identity_status 가 그대로 남아 authoritative 가 거짓이 된다."
        ),
    )
    parser.add_argument("--out", default=str(DEFAULT_RULING_DIR))
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않는다")
    args = parser.parse_args(argv)

    if not (args.sample or args.card_id or args.cid or args.all):
        parser.error("--sample / --card-id / --cid / --all 중 하나는 필요합니다.")

    identity = CardIdentityMapping.load()
    targets = resolve_targets(args, identity)
    if args.limit:
        targets = targets[: args.limit]
    print(f"대상 카드 {len(targets):,}장 (요청 간 {args.delay}초 대기)")

    out_dir = Path(args.out)
    existing = RulingRepository.load(out_dir, missing_ok=True)
    adapter = OfficialOcgRulingAdapter(delay=args.delay, use_cache=not args.refresh)
    plan = RulingUpdatePlan()
    blocked: list[int] = []

    for index, (cid, card_id) in enumerate(targets, 1):
        before = existing.ruling_set(cid)
        if args.skip_collected and before is not None and before.confirmed:
            plan.record_unchanged(cid)
            continue
        result = adapter.fetch_ruling_set(
            cid,
            card_id=card_id,
            identity=identity,
            allow_unverified_identity=args.allow_unverified_identity,
        )
        plan.merge(diff_ruling_set(before, result))
        # 번역은 공식 사이트에서 오지 않으므로 재수집하면 사라진다. 옮겨 붙이되
        # 원문이 바뀌었으면 is_stale() 이 참이 되어 낡았다는 것이 드러난다.
        result = merge_translations(before, result)
        if result.blocked_by_identity:
            blocked.append(cid)
            print(f"  [{index}/{len(targets)}] cid={cid} 건너뜀: {result.error}",
                  file=sys.stderr)
        elif result.availability is RulingAvailability.SOURCE_UNAVAILABLE:
            print(f"  [{index}/{len(targets)}] cid={cid} 확인 실패: {result.error}",
                  file=sys.stderr)
        else:
            print(f"  [{index}/{len(targets)}] {result}")
        if not args.dry_run and result.confirmed:
            RulingRepository.save_ruling_set(result, out_dir)

    print()
    print(f"요청 {adapter.request_count}건")
    for line in plan.describe():
        print(line)
    if blocked:
        print(
            "  대조 방법: python -m scripts.build_card_identity "
            "--verify-card-id <패스코드>"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
