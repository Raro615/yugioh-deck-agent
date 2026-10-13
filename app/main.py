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

    from analysis.effect_model import _BINDING_GUIDANCE_KO, HandlerBinding

    from core.provenance import AnalysisStatus

    #: 🔴 **Lua 가 없는 카드에게 거짓 이유를 말하고 있었다** (Phase 3-F-41).
    #: 예전 문구는 ``"Lua 스크립트가 없습니다 (일반 몬스터 등)."`` 하나였고,
    #: Lua 가 없는 **1,440장 전부**에게 그것을 찍었다. 그 안에는 효과가
    #: 분명히 있는 카드 **756장**(`text_derived`)이 섞여 있다 — 실측 예:
    #: 「패러렐 텔레포트 · 마법/속공」. 속공 마법을 "일반 몬스터 등" 이라고
    #: 부르는 것은 추측이고, 카드에 이미 붙어 있는 상태를 읽으면 알 수 있는
    #: 사실을 추측으로 덮은 것이다.
    #:
    #: 🔴 **텍스트 분석을 돌렸다고 말하지 않는다.** ``TextEffectAnalyzer`` 는
    #: production 호출자가 0개다 (Phase 3-F-40·41 전수 확인). 그래서
    #: "텍스트만이 근거" 라고 적고 "텍스트에서 분석했다" 로 적지 않는다.
    _NO_SCRIPT_REASON_KO = {
        AnalysisStatus.NO_EFFECT:
            "공식 DB 가 효과 없는 카드로 분류합니다 (통상 몬스터·토큰).",
        AnalysisStatus.TEXT_DERIVED:
            "효과가 있는 카드인데 스크립트가 아직 없습니다."
            " 효과 텍스트만이 근거이고, 구조화된 텍스트 분석은 돌지 않습니다.",
        AnalysisStatus.UNAVAILABLE:
            "분석 근거가 없습니다 (효과가 없다는 뜻이 아닙니다).",
    }

    analysis = EffectAnalyzer(agent.repository).analyze(card)
    print("=" * 72)
    print(card.summary_ko())

    #: 🔴 **근거 줄을 이른 반환보다 **위**로 올린다** (Phase 3-F-41).
    #: Phase 3-F-40 이 이 줄을 결합 상태 바로 앞에 넣었는데, 그 자리는 아래
    #: ``has_script`` 반환 **뒤**였다. 그래서 설명이 가장 필요한 1,440장은
    #: 근거를 한 번도 보지 못했다.
    record = getattr(card, "provenance", None)
    status = getattr(record, "analysis_status", None)
    if status is not None:
        suffix = " (근거 계층 — 증명은 아래 결합 상태)" if analysis.has_script else ""
        print(f"  분석 근거  : {status.value}{suffix}")

    if not analysis.has_script:
        reason = _NO_SCRIPT_REASON_KO.get(status)
        if reason is None:
            #: 상태를 모르면 모른다고 적는다. 이유를 지어내지 않는다.
            reason = "이 카드의 분석 근거를 판단할 수 없습니다."
        print(f"  Lua 스크립트가 없습니다 — {reason}")
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
        if effect.activation.tree is not None:
            print(f"          논리: {effect.activation.tree.describe_ko()}")
            marks = {"evaluable": "✓", "needs_context": "~", "unknown": "?"}
            for leaf in effect.activation.tree.leaves():
                predicate = leaf.predicate
                if predicate is None:
                    continue
                mark = marks.get(predicate.readiness.value, "?")
                label = (
                    predicate.describe_ko()
                    if predicate.kind.value != "unknown"
                    else leaf.raw.strip()[:46]
                )
                print(f"            {mark} {label}")
        else:
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

    #: 🔴 **결합 상태를 사용자에게 보인다** (Phase 3-F-38).
    #:
    #: Phase 3-F-37 이 블록과 핸들러의 대응을 ``(소스 지문, 블록 offset)``
    #: 쌍으로 증명하고 그 결과를 :attr:`CardAnalysis.handler_binding` 과
    #: ``unbound_effects`` 에 적었는데, 그때까지 **이 출력은 그 값을 읽지
    #: 않았다.** 증명되지 않은 블록은 ``effects`` 에도 ``resolution_effects``
    #: 에도 들어가지 않으므로, 사용자 눈에는 **그냥 효과가 적게 보였다.**
    #:
    #: 🔴 건수는 세 목록 전부에서 **실제 필드를 읽어** 센다. "``effects`` 에
    #: 있으면 ``MATCHED``" 라고 가정하지 않는다 — 그 가정이 깨지는 날
    #: 조용히 틀린 요약을 내게 된다.
    counts: dict[HandlerBinding, int] = {}
    for effect in (list(analysis.effects) + list(analysis.resolution_effects)
                   + list(analysis.unbound_effects)):
        counts[effect.handler_binding] = counts.get(effect.handler_binding, 0) + 1
    total_blocks = sum(counts.values())
    matched = counts.get(HandlerBinding.MATCHED, 0)
    if total_blocks:
        if matched == total_blocks:
            label = _BINDING_GUIDANCE_KO[HandlerBinding.MATCHED][0]
            print(f"\n  결합 상태  : {label} (블록 {total_blocks}개 전부 증명됨)")
        else:
            print(f"\n  🔴 결합 상태  : 증명된 블록 {matched}/{total_blocks}")
            #: 상태마다 **다른 안내**를 준다. 하나의 성공/실패로 합치지 않는다.
            for binding in (HandlerBinding.MISMATCHED, HandlerBinding.UNPROVABLE,
                            HandlerBinding.SOURCE_MISSING):
                count = counts.get(binding, 0)
                if not count:
                    continue
                name, hint = _BINDING_GUIDANCE_KO[binding]
                blocks = ", ".join(
                    effect.index for effect in analysis.unbound_effects
                    if effect.handler_binding is binding
                )
                print(f"      · {name} {count}개 [{blocks}]")
                print(f"        {hint}")
            print("      (증명되지 않은 블록은 위 효과 목록에 넣지 않았습니다 —"
                  " 등록/해결 중 어느 쪽이라고 주장할 근거가 없기 때문입니다.)")

    coverage = analysis.coverage()
    #: 🔴 **분모가 무엇인지 말한다** (Phase 3-F-39 / N31). 예전 문구는
    #: "효과 N개" 였고, N 이 **증명된 등록 효과만**이라는 사실이 어디에도
    #: 없었다. 처리 중 생성되는 효과(코퍼스 전수 8,283개 — 전체 블록의
    #: 23.9%)와 증명되지 않은 블록은 이 N 에 들어 있지 않다.
    print(
        f"\n  구조화 정도 : 등록 효과 {coverage['effects']}개 기준 | "
        f"조건 {coverage['condition_structured']}/{coverage['has_condition']} · "
        f"비용 {coverage['cost_structured']}/{coverage['with_costs']} · "
        f"선택 {coverage['with_selection']} · 처리 {coverage['with_actions']}"
    )
    #: 🔴 미증명 블록이 있을 때만 **빠진 수**를 적는다. 정상 카드의 출력에는
    #: 붙지 않는다 (소음 금지). 분모에 섞지 않는 이유도 함께 적는다 — 결합
    #: 실패를 구조화 실패로 세면 서로 다른 두 실패가 합쳐진다.
    if coverage["unbound_effects"]:
        print(f"      (이 분모에 미증명 블록 {coverage['unbound_effects']}개는"
              " 없습니다 — 증명되지 않은 블록을 구조화 실패로 세면 결합"
              " 실패와 구조화 실패가 합쳐집니다.)")
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


def _parse_card_ids(raw: str, agent: DeckAgent) -> tuple[list[int], list[str]]:
    """
    쉼표로 구분한 카드 지정을 ID 목록으로 바꾼다. 이름도 받는다.

    🔴 **장수를 제한하지 않는다** (Phase 4-B). 룰북 데이터의 패 상한 6 은
    엔드 페이즈 종료 시점의 상한이고, 그 파일이 "그 외 시점의 상한은
    룰북에 없다" 고 적어 두었다. 그래서 몇 장을 주든 그대로 넘긴다.
    """
    ids: list[int] = []
    unresolved: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            ids.append(int(token))
            continue
        found = agent.repository.find_by_exact_name(token)
        if found:
            ids.append(found[0].id)
        else:
            unresolved.append(token)
    return ids, unresolved


def cmd_deck(agent: DeckAgent, args) -> int:
    """테마 요청으로 덱 초안을 만들고 검증한다 (Phase 4-B)."""
    from deck.builder import DeckBuilder
    from deck.report import render_draft, render_request, render_validation
    from deck.request import parse_deck_request
    from deck.validator import DeckValidator

    request = parse_deck_request(args.request)
    print(render_request(request))
    if request.is_empty:
        return 1

    draft = DeckBuilder(agent.repository).build(request)
    print(render_draft(draft))
    validation = DeckValidator().validate(draft)
    print(render_validation(validation))
    return 1 if validation.has_violation else 0


def cmd_combo(agent: DeckAgent, args) -> int:
    """사용자가 지정한 초기 패로 전개 계획을 만든다 (Phase 4-B)."""
    from deck.hand import FixedHand
    from deck.planner import ComboPlanner
    from deck.report import render_plan, render_simulator_steps

    hand_ids, unresolved = _parse_card_ids(args.hand, agent)
    board_ids, board_unresolved = _parse_card_ids(
        getattr(args, "board", "") or "", agent)
    for name in unresolved + board_unresolved:
        print(f"  🔴 카드를 찾지 못했습니다: {name}")

    plan = ComboPlanner(agent.repository).plan(FixedHand(tuple(hand_ids)),
                                               board=board_ids)
    print(render_plan(plan))
    print(render_simulator_steps(plan))
    return 0


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

    p = sub.add_parser("deck", parents=[common],
                       help="테마로 덱 초안 구성 + 규격 검증")
    p.add_argument("request", help='예: "오르페골 + K9 덱, 초동 안정성 우선"')
    p.set_defaults(func=cmd_deck)

    p = sub.add_parser("combo", parents=[common],
                       help="지정한 초기 패로 전개 계획 (무작위 패 생성은 미구현)")
    p.add_argument("hand",
                   help="쉼표로 구분한 카드 ID 또는 카드명 (장수 제한 없음)")
    p.add_argument("--board", default="",
                   help="이미 필드·묘지에 있는 카드 (선택)")
    p.set_defaults(func=cmd_combo)

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
