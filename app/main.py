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
from core.card_search import CardSearchEngine, SearchFilters, SearchResult  # noqa: E402
from core.query_parser import (  # noqa: E402
    SEARCH_MODE_ARCHETYPE,
    SEARCH_MODE_EXACT_NAME,
    SEARCH_MODE_RELATED,
    KoreanQueryParser,
    ParsedQuery,
    detect_relation_intent,
)
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
        # 한국어 데이터는 리포지토리가 자동으로 찾아 적용한다.
        repository = CardRepository.build(
            db_path=db_path,
            script_dir=script_dir,
            use_cache=use_cache,
        )
        return cls(repository, default_limit=default_limit)

    def search_korean(self, query: str, limit: int | None = None):
        """
        한국어 질의를 해석해 검색한다.

        처리 순서 (앞에서 확정되면 뒤는 보지 않는다):

        1. **카드명 정확 일치** — 카드명 안에 게임 용어가 들어 있어도
           ("마법족의 마을" 의 '마법') 용어 파싱이 가로채지 못하게 가장 먼저 본다.
        2. **관련 카드 / 카드군** — "오르페골과 관련된 카드", "오르페골 카드".
           그 말이 실제 카드군인지는 카드 데이터로 확인하며, 아니면 그냥 넘어간다
           ("마법 카드" 는 카드군이 아니라 카드 종류다).
        3. **조건 검색** — 게임 용어/수치 파싱.
        4. **카드명 부분 일치** — 조건으로 해석되지 않은 조각이 남았을 때.

        Returns:
            (ParsedQuery, SearchResult). ``parsed.search_mode`` 에 어느 경로였는지,
            ``parsed.relation`` 에 카드군/관계 상세가 담긴다.
        """
        effective_limit = limit if limit is not None else self.parser.default_limit

        # --- 1단계: 카드명 정확 일치 ---
        exact = self.repository.resolve_exact_name(query)
        if exact is not None:
            filters = SearchFilters(
                name=query, name_exact=True, limit=effective_limit
            )
            parsed = ParsedQuery(
                filters=filters,
                original=query,
                matched_terms=[f"카드명 정확 일치 '{query}'"],
                search_mode=SEARCH_MODE_EXACT_NAME,
            )
            parsed.exact_name = exact
            return parsed, self.engine.search(filters)

        # --- 2단계: 관련 카드 / 카드군 ---
        intent = detect_relation_intent(query)
        if intent is not None:
            mode, term = intent
            parsed = self._resolve_relation(query, mode, term, effective_limit)
            if parsed is not None:
                return parsed

        # --- 3단계: 게임 용어 / 조건 파싱 ---
        parsed = self.parser.parse(query)
        if limit is not None:
            parsed.filters.limit = limit

        # --- 4단계: 카드명 일부만 입력한 경우 ---
        override = self._name_collision_override(query, parsed)
        if override is not None:
            parsed.filters = override
            parsed.matched_terms = [f"이름 '{query}'"]
            parsed.unknown_terms = []
            parsed.search_mode = "partial_name"

        return parsed, self.engine.search(parsed.filters)

    def _resolve_relation(
        self, query: str, mode: str, term: str, limit: int | None
    ):
        """
        카드군/관계 검색을 시도한다. 그 말이 카드군으로 확인되지 않으면
        ``None`` 을 돌려주고 호출자는 평소의 조건 파싱으로 넘어간다.
        """
        if mode == SEARCH_MODE_RELATED:
            match = self.repository.relations_for_term(term)
            cards = match.cards if match else []
        else:
            match = self.repository.resolve_archetype(term)
            cards = match.cards if match else []
        if not match or not cards:
            return None

        filters = SearchFilters(limit=limit)
        parsed = ParsedQuery(
            filters=filters,
            original=query,
            matched_terms=[f"{mode} '{term}'"],
            search_mode=mode,
        )
        parsed.relation = match
        total = len(cards)
        shown = cards[:limit] if limit is not None else cards
        return parsed, SearchResult(cards=shown, total=total, filters=filters)

    def name_suggestions(self, query: str, exclude: set[int]) -> list[Card]:
        """이름에 질의를 포함하는 다른 카드들 (정확 일치와 구분해 보여준다)."""
        found = self.repository.deduplicate(
            self.repository.find_by_name_substring(query)
        )
        return [c for c in found if c.id not in exclude]

    def _name_collision_override(self, query: str, parsed) -> SearchFilters | None:
        """
        질의 전체가 카드명일 때 쓸 이름 검색 조건을 돌려준다.
        해당 없으면 ``None``.

        정확 일치는 1단계에서 이미 처리했으므로 여기서는 부분 일치만 본다.
        조건을 좁게 잡아, 용어만으로 온전히 해석된 질의
        (예: "기계족 빛속성 몬스터")는 절대 가로채지 않는다.
        """
        if parsed.filters.name:
            return None  # 이미 이름 검색으로 해석됨
        # 해석되지 않은 조각이 남아 있을 때만 이름 검색으로 넘긴다.
        if parsed.unknown_terms and self.repository.find_by_name_substring(query):
            return SearchFilters(name=query, limit=parsed.filters.limit)
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
        label = "카드 텍스트(한국어)" if card.name_ko else "카드 텍스트"
        print(f"  {label}:")
        for line in card.desc.splitlines():
            print(f"    {line}")
    if card.desc_en and card.desc_en != card.desc:
        print("  카드 텍스트(원문):")
        for line in card.desc_en.splitlines():
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
        "desc_en": card.desc_en,
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
                    "search_mode": parsed.search_mode,
                    "interpreted": parsed.explain_ko(),
                    "exact_name_match": (
                        None
                        if parsed.exact_name is None
                        else {
                            "card_count": parsed.exact_name.card_count,
                            "printing_count": parsed.exact_name.printing_count,
                            "printings": parsed.exact_name.printings,
                        }
                    ),
                    "relation": (
                        None
                        if parsed.relation is None
                        else {
                            "term": parsed.relation.term,
                            "archetypes": getattr(parsed.relation, "names", None)
                            or (
                                parsed.relation.archetype.names
                                if getattr(parsed.relation, "archetype", None)
                                else []
                            ),
                            "counts_by_type": (
                                parsed.relation.counts_by_type()
                                if hasattr(parsed.relation, "counts_by_type")
                                else None
                            ),
                        }
                    ),
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
    print(f"검색 모드: {parsed.search_mode} ({parsed.mode_label_ko()})")
    print(parsed.explain_ko())

    # 카드군 / 관련 카드 검색
    if parsed.relation is not None:
        relations = getattr(parsed.relation, "relations", None)
        print(f"검색 결과: {result.total}장" + (f" (상위 {len(result)}장 표시)" if result.total > len(result) else ""))
        print("-" * 72)
        by_card = (
            {r.card.id: r.relation_types for r in relations} if relations else {}
        )
        for i, card in enumerate(result, 1):
            print(format_card_line(card, i))
            types = by_card.get(card.id)
            if types:
                print(f"       관계: {', '.join(types)}")
        return 0

    if parsed.exact_name is not None:
        match = parsed.exact_name
        print(f"검색 결과: {match.card_count}종")
        print("-" * 72)
        for i, card in enumerate(result, 1):
            print(format_card_line(card, i))
            passcodes = match.printings.get(card.id, [])
            if len(passcodes) > 1:
                print(
                    f"       판본 {len(passcodes)}개: "
                    + ", ".join(str(p) for p in passcodes)
                )
        # 이름에 질의를 포함하는 다른 카드는 따로 보여준다.
        others = agent.name_suggestions(query, {c.id for c in result})
        if others:
            print()
            print(f"이름에 '{query}' 을(를) 포함하는 다른 카드: {len(others)}장")
            for card in others[: args.limit or len(others)]:
                print(format_card_line(card))
        return 0

    print(
        f"검색 결과: {result.total}장"
        + (f" (상위 {len(result)}장 표시)" if result.total > len(result) else "")
    )
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


def cmd_analyze(agent: DeckAgent, args) -> int:
    """카드 효과를 구조적으로 분해해 보여준다."""
    from analysis import EffectAnalyzer

    card = agent.repository.get(args.card_id)
    if card is None:
        print(f"카드를 찾을 수 없습니다: {args.card_id}", file=sys.stderr)
        return 1

    analysis = EffectAnalyzer(agent.repository).analyze(card)
    print("=" * 72)
    print(card.summary_ko())
    if not analysis.has_script:
        print("  Lua 스크립트가 없습니다 (일반 몬스터 등).")
        print("=" * 72)
        return 0

    if analysis.setcodes:
        print(f"  소속 카드군 : {', '.join(analysis.setcodes)}")
    if analysis.listed_series:
        print(f"  지명 카드군 : {', '.join(analysis.listed_series)} (소속과 다름)")

    labels = {
        "activation": "① 발동 조건",
        "cost": "② 비용",
        "selection": "③ 선택",
        "action": "④ 처리",
    }
    for effect in analysis.effects:
        print(f"\n  [{effect.index}] {'/'.join(effect.effect_types) or '-'}")
        if effect.trigger_event:
            print(f"      발동 계기  : {effect.trigger_event}")
        # 조건 → 비용 → 선택 → 처리 순서로 보여준다.
        for stage in effect.pipeline():
            mark = " " if stage.structured else "~"
            print(f"     {mark}{labels[stage.stage]} : {stage.summary}")
        for requirement in effect.activation.requirements:
            print(f"          · {requirement.describe_ko()}")
        if effect.targets_card:
            print("          · 규칙상 대상 지정")
        for action in effect.actions:
            src = "/".join(action.from_locations) or "?"
            print(
                f"          · {action.kind.value}: {src} → {action.to_location}"
            )
        unparsed = list(effect.activation.unparsed) + list(effect.unparsed)
        if unparsed:
            print(f"        미구조화  : {', '.join(unparsed[:6])}")

    if analysis.resolution_effects:
        print(f"\n  처리 중 생성되는 효과 {len(analysis.resolution_effects)}개 (적용 제약 등)")
    coverage = analysis.coverage()
    print(
        f"\n  구조화 정도 : 효과 {coverage['effects']}개 | "
        f"조건 {coverage['condition_structured']}/{coverage['has_condition']} · "
        f"비용 {coverage['cost_structured']}/{coverage['with_costs']} · "
        f"선택 {coverage['with_selection']} · 처리 {coverage['with_actions']}"
    )
    print("  (~ 표시는 구조화하지 못한 단계)")
    print("=" * 72)
    return 0


def cmd_relations(agent: DeckAgent, args) -> int:
    """카드의 관계를 소속과 상호작용으로 나눠 보여준다."""
    from analysis import EffectAnalyzer, RelationshipBuilder

    card = agent.repository.get(args.card_id)
    if card is None:
        print(f"카드를 찾을 수 없습니다: {args.card_id}", file=sys.stderr)
        return 1

    builder = RelationshipBuilder(agent.repository, EffectAnalyzer(agent.repository))
    relationships = builder.for_card(args.card_id)
    print(card.summary_ko())
    print("-" * 72)

    memberships = [r for r in relationships if r.is_membership]
    interactions = [r for r in relationships if not r.is_membership]

    print(f"소속 (같은 카드군): {len(memberships)}건")
    for relation in memberships:
        print(f"  · {relation.target_archetype}   근거={relation.evidence}")
    print(f"\n상호작용: {len(interactions)}건")
    for relation in interactions:
        target = (
            agent.repository.get(relation.target_card_id)
            if relation.target_card_id
            else None
        )
        label = target.display_name() if target else relation.describe_ko()
        print(f"  · {relation.kind.value:16} {label}")
        if relation.constraint and not relation.constraint.is_empty():
            print(f"      조건: {relation.constraint.describe_ko()}")
        if relation.from_location or relation.to_location:
            print(
                f"      이동: {relation.from_location or '?'} → "
                f"{relation.to_location or '?'}"
            )
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

    p = sub.add_parser("analyze", parents=[common], help="카드 효과 구조 분석")
    p.add_argument("card_id", type=int)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("relations", parents=[common], help="카드 관계 (소속/상호작용)")
    p.add_argument("card_id", type=int)
    p.set_defaults(func=cmd_relations)

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
