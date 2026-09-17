"""
유희왕 덱 분석 / 카드 검색 에이전트 CLI.

    python -m app.main search "4레벨 빛속성 기계족 몬스터 중 특수 소환 효과가 있는 카드"
    python -m app.main card 2511
    python -m app.main related 2511
    python -m app.main archetype LABRYNTH
    python -m app.main stats
    python -m app.main repl

질의는 한국어 자연어로 입력한다. 어떻게 해석했는지는 항상 함께 출력하므로
의도와 다르게 해석된 경우 바로 확인할 수 있다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 저장소 루트를 import 경로에 넣어 `python app/main.py` 로도 실행되게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.card_model import Card  # noqa: E402
from core.card_repository import CardRepository  # noqa: E402
from core.card_search import CardSearchEngine, SearchFilters  # noqa: E402
from core.query_parser import KoreanQueryParser  # noqa: E402
from sources.korean_names import KoreanTextSource  # noqa: E402
from sources.official_db import OfficialDatabaseNotFound  # noqa: E402


class DeckAgent:
    """리포지토리 + 검색 엔진 + 질의 파서를 묶은 진입점."""

    def __init__(self, repository: CardRepository, default_limit: int | None = 20):
        self.repository = repository
        self.engine = CardSearchEngine(repository)
        self.parser = KoreanQueryParser(default_limit=default_limit)

    @classmethod
    def build(
        cls,
        db_path: str | None = None,
        script_dir: str | None = None,
        default_limit: int | None = 20,
        use_cache: bool = True,
    ) -> DeckAgent:
        korean = KoreanTextSource.autoload()
        repository = CardRepository.build(
            db_path=db_path,
            script_dir=script_dir,
            use_cache=use_cache,
            korean_source=korean if korean else None,
        )
        return cls(repository, default_limit=default_limit)

    def search_korean(self, query: str, limit: int | None = None):
        parsed = self.parser.parse(query)
        if limit is not None:
            parsed.filters.limit = limit

        # 카드명이 게임 용어와 겹치는 경우를 구제한다.
        # 예) "마법족의 마을" 은 카드명이지만 '마법' 이 카드 종류로 해석되어
        #     마법 카드 전체가 나온다. 실제로 그런 이름의 카드가 있으면
        #     이름 검색이 이긴다.
        override = self._name_collision_override(query, parsed)
        if override is not None:
            parsed.filters = override
            parsed.matched_terms = [f"이름 '{query}'"]
            parsed.unknown_terms = []

        return parsed, self.engine.search(parsed.filters)

    def _name_collision_override(self, query: str, parsed) -> SearchFilters | None:
        """
        질의 전체가 카드명일 때 쓸 이름 검색 조건을 돌려준다.
        해당 없으면 ``None``.

        조건을 좁게 잡아, 용어만으로 온전히 해석된 질의
        (예: "기계족 빛속성 몬스터")는 절대 가로채지 않는다.
        """
        if parsed.filters.name:
            return None  # 이미 이름 검색으로 해석됨

        limit = parsed.filters.limit
        if self.repository.find_by_exact_name(query):
            return SearchFilters(name=query, name_exact=True, limit=limit)
        # 부분 일치는 해석되지 않은 조각이 남아 있을 때만 인정한다.
        if parsed.unknown_terms and self.repository.find_by_name_substring(query):
            return SearchFilters(name=query, limit=limit)
        return None


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def format_card_line(card: Card, index: int | None = None) -> str:
    prefix = f"{index:>3}. " if index is not None else "     "
    return f"{prefix}{card.summary_ko()}  [{card.id}]"


def print_card_detail(agent: DeckAgent, card: Card) -> None:
    print("=" * 72)
    print(card.summary_ko())
    print(f"  카드 ID : {card.id}")
    names = [
        ("한국어", card.name_ko),
        ("공식 DB", card.name_en),
        ("일본어", card.name_ja),
    ]
    for label, value in names:
        if value:
            print(f"  {label:<7}: {value}")
    archetypes = agent.repository.archetype_name(card)
    if archetypes:
        print(f"  카드군  : {', '.join(archetypes)}")
    if card.is_pendulum:
        print(
            f"  펜듈럼  : 스케일 {card.pendulum_scale_left}/{card.pendulum_scale_right}"
        )
    if card.is_link:
        print(f"  링크마커: {', '.join(card.link_markers)}")
    if card.desc:
        print("  카드 텍스트(원문):")
        for line in card.desc.splitlines():
            print(f"    {line}")
    if card.effects:
        print(f"  Lua 효과 블록 {len(card.effects)}개:")
        for eff in card.effects:
            bits = []
            if eff.effect_types:
                bits.append("/".join(eff.effect_types))
            if eff.code:
                bits.append(eff.code)
            if eff.ranges:
                bits.append("발동위치=" + "/".join(eff.ranges))
            if eff.categories:
                bits.append("분류=" + "/".join(eff.categories))
            print(f"    - {eff.index}: {'  '.join(bits)}")
    else:
        print("  Lua 효과 블록: 없음 (스크립트 없음 또는 헬퍼 기반 소환법)")
    print("=" * 72)


def card_to_dict(agent: DeckAgent, card: Card) -> dict:
    return {
        "id": card.id,
        "name": card.display_name(),
        "name_en": card.name_en,
        "name_ja": card.name_ja,
        "name_ko": card.name_ko,
        "type": card.type_names,
        "type_ko": card.type_ko,
        "attribute": card.attribute_name,
        "race": card.race_name,
        "level": card.level,
        "rank": card.rank,
        "link_rating": card.link_rating,
        "atk": card.atk,
        "def": card.defense,
        "archetypes": agent.repository.archetype_name(card),
        "desc": card.desc,
        "effects": [
            {
                "index": e.index,
                "types": e.effect_types,
                "code": e.code,
                "ranges": e.ranges,
                "categories": e.categories,
            }
            for e in card.effects
        ],
    }


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------
def cmd_search(agent: DeckAgent, args) -> int:
    query = " ".join(args.query)
    parsed, result = agent.search_korean(query, limit=args.limit)

    if args.json:
        print(
            json.dumps(
                {
                    "query": query,
                    "interpreted": parsed.filters.describe_ko(),
                    "unknown_terms": parsed.unknown_terms,
                    "total": result.total,
                    "cards": [card_to_dict(agent, c) for c in result],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f'질의: "{query}"')
    print(parsed.explain_ko())
    print(f"검색 결과: {result.total}장" + (f" (상위 {len(result)}장 표시)" if result.total > len(result) else ""))
    print("-" * 72)
    for i, card in enumerate(result, 1):
        print(format_card_line(card, i))
    if result.total == 0:
        print("  조건에 맞는 카드가 없습니다.")
    return 0


def cmd_card(agent: DeckAgent, args) -> int:
    target = " ".join(args.target)
    card = None
    if target.isdigit():
        card = agent.repository.get(int(target))
    if card is None:
        found = agent.repository.find_by_exact_name(target)
        if not found:
            found = agent.repository.find_by_name_substring(target)
        if not found:
            print(f"카드를 찾을 수 없습니다: {target}", file=sys.stderr)
            return 1
        card = found[0]
        if len(found) > 1:
            print(f"({len(found)}장 중 첫 번째를 표시합니다)")
    print_card_detail(agent, card)
    return 0


def cmd_related(agent: DeckAgent, args) -> int:
    card = agent.repository.get(args.card_id)
    if card is None:
        print(f"카드를 찾을 수 없습니다: {args.card_id}", file=sys.stderr)
        return 1
    related = agent.repository.related_cards(args.card_id)
    print(f"{card.summary_ko()} 와(과) 관련된 카드: {len(related)}장")
    print("  (카드 텍스트가 서로를 지명하거나 같은 카드군에 속하는 카드)")
    print("-" * 72)
    for i, other in enumerate(related[: args.limit or len(related)], 1):
        print(format_card_line(other, i))
    return 0


def cmd_archetype(agent: DeckAgent, args) -> int:
    name = " ".join(args.name)
    cards = agent.repository.by_archetype(name)
    print(f"카드군 '{name}': {len(cards)}장")
    print("-" * 72)
    for i, card in enumerate(cards[: args.limit or len(cards)], 1):
        print(format_card_line(card, i))
    if not cards:
        print("  해당 카드군을 찾을 수 없습니다.")
        print("  (상수 이름 기준입니다. 예: LABRYNTH, BLUEEYES, SALAMANGREAT)")
    return 0


def cmd_stats(agent: DeckAgent, args) -> int:
    stats = agent.repository.stats()
    labels = {
        "total": "전체 레코드",
        "canonical": "중복 제거 후",
        "alternate_art": "다른 일러스트/에라타 판본",
        "with_script": "Lua 스크립트 보유",
        "with_official_data": "공식 DB 메타데이터 보유",
        "monsters": "몬스터",
        "spells": "마법",
        "traps": "함정",
    }
    print("카드 데이터 현황")
    print("-" * 40)
    for key, label in labels.items():
        print(f"  {label:<26}: {stats[key]:>7,}")
    constants = agent.repository.constants
    print(f"  {'CARD_* 상수':<26}: {len(constants.card_ids):>7,}")
    print(f"  {'SET_* 카드군 상수':<26}: {len(constants.setcodes):>7,}")
    return 0


def cmd_repl(agent: DeckAgent, args) -> int:
    print("한국어로 질의를 입력하세요. 종료하려면 빈 줄 또는 Ctrl-D.")
    print('예: 4레벨 빛속성 기계족 몬스터 중 특수 소환 효과가 있는 카드')
    while True:
        try:
            query = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not query:
            return 0
        parsed, result = agent.search_korean(query, limit=args.limit)
        print(parsed.explain_ko())
        print(f"{result.total}장 검색됨")
        for i, card in enumerate(result, 1):
            print(format_card_line(card, i))


# ---------------------------------------------------------------------------
def _add_common_options(target: argparse.ArgumentParser, *, top_level: bool) -> None:
    """
    공통 옵션을 등록한다.

    서브커맨드 앞뒤 어디에 써도 되도록 양쪽에 모두 등록하되,
    서브커맨드 쪽은 기본값을 SUPPRESS 로 두어 값을 주지 않았을 때
    앞쪽에서 지정한 값을 덮어쓰지 않게 한다.
    """
    kw = {} if top_level else {"default": argparse.SUPPRESS}
    target.add_argument("--db", help="cards.cdb 경로 (기본: 자동 탐색)", **kw)
    target.add_argument("--scripts", help="c*.lua 디렉터리 (기본: 저장소 루트)", **kw)
    target.add_argument(
        "--limit",
        type=int,
        help="출력 개수 (0 이면 전체)",
        **({"default": 20} if top_level else {"default": argparse.SUPPRESS}),
    )
    target.add_argument(
        "--no-cache",
        action="store_true",
        help="Lua 파싱 캐시 사용 안 함",
        **({} if top_level else {"default": argparse.SUPPRESS}),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yugioh-deck-agent",
        description="유희왕 카드 검색 / 덱 분석 에이전트 (한국어 자연어 질의 지원)",
    )
    _add_common_options(parser, top_level=True)

    common = argparse.ArgumentParser(add_help=False)
    _add_common_options(common, top_level=False)

    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("search", parents=[common], help="한국어 자연어 카드 검색")
    p.add_argument("query", nargs="+")
    p.add_argument("--json", action="store_true", help="JSON 으로 출력")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("card", parents=[common], help="카드 상세 정보 (ID 또는 이름)")
    p.add_argument("target", nargs="+")
    p.set_defaults(func=cmd_card)

    p = sub.add_parser("related", parents=[common], help="관련 카드 (지명 / 피지명 / 같은 카드군)")
    p.add_argument("card_id", type=int)
    p.set_defaults(func=cmd_related)

    p = sub.add_parser("archetype", parents=[common], help="카드군 소속 카드 목록")
    p.add_argument("name", nargs="+")
    p.set_defaults(func=cmd_archetype)

    p = sub.add_parser("stats", parents=[common], help="데이터 현황")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("repl", parents=[common], help="대화형 검색")
    p.set_defaults(func=cmd_repl)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    limit = None if args.limit == 0 else args.limit
    try:
        agent = DeckAgent.build(
            db_path=args.db,
            script_dir=args.scripts,
            default_limit=limit,
            use_cache=not args.no_cache,
        )
    except OfficialDatabaseNotFound as exc:
        print(exc, file=sys.stderr)
        return 2

    args.limit = limit
    return args.func(agent, args)


if __name__ == "__main__":
    raise SystemExit(main())
