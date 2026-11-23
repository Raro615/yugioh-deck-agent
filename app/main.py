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
import dataclasses
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
    """
    사용자가 지정한 초기 패로 전개를 본다 (Phase 4-B · 6-T).

    🔴 ``--recipe`` 를 주면 **실제 엔진으로 돌린다** (Phase 6-T). 주지
    않으면 예전처럼 정적 계획만 만들고, 왜 실행하지 않았는지 적는다 —
    레시피 없이 실행하면 덱 장수를 조건으로 보는 효과가 거짓으로 통과한다.
    """
    from deck.hand import FixedHand
    from deck.planner import ComboPlanner
    from deck.report import render_plan, render_simulator_steps

    hand_ids, unresolved = _parse_card_ids(args.hand, agent)
    board_ids, board_unresolved = _parse_card_ids(
        getattr(args, "board", "") or "", agent)
    for name in unresolved + board_unresolved:
        print(f"  🔴 카드를 찾지 못했습니다: {name}")

    recipe_text = getattr(args, "recipe", "") or ""
    #: ``.ydk`` 파일 경로를 그대로 받는다 — EDOPro 가 내보낸 파일이다.
    #: 🔴 줄바꿈이 들어간 레시피 문자열은 경로가 아니므로 먼저 걸러낸다
    #: (``Path`` 에 아주 긴 문자열을 넣으면 OS 오류가 난다).
    if recipe_text and "\n" not in recipe_text and len(recipe_text) < 400:
        candidate = Path(recipe_text)
        if candidate.is_file():
            recipe_text = candidate.read_text(encoding="utf-8")
    _print_opening(agent, recipe_text, hand_ids,
                   getattr(args, "line", "") or "")
    #: 🔴 **주지 않으면 돌리지 않는다** (Phase 6-AH) — ``--search`` 없는
    #: 호출의 출력은 6-AG 와 한 글자도 다르지 않다.
    _print_bounded_search(agent, recipe_text, hand_ids,
                          getattr(args, "search", "") or "",
                          getattr(args, "results", "") or "",
                          getattr(args, "followups", "") or "")

    plan = ComboPlanner(agent.repository).plan(FixedHand(tuple(hand_ids)),
                                               board=board_ids)
    print()
    print("=" * 68)
    print("아래는 실행하지 않은 정적 계획입니다 — 엔진으로 돌린 것이 아닙니다.")
    print("=" * 68)
    print(render_plan(plan))
    print(render_simulator_steps(plan))
    return 0


def _print_bounded_search(agent: DeckAgent, recipe_text: str,
                          hand_ids: "list[int]", search_text: str,
                          results_text: str = "",
                          followups_text: str = "") -> None:
    """
    🔴 **제한 전개 탐색 절** (Phase 6-AH). 목표를 주지 않으면 아무것도 적지
    않는다 — 고르지 않은 탐색을 조용히 돌리지 않는다.

    Discord 의 ``search:`` 와 **같은 것**이고, 두 어댑터가 같은 두 함수를
    쓴다 (:func:`bounded_search_opening` · ``deck.report`` 의 두 렌더러).
    """
    from deck.recipe import parse_recipe
    from deck.report import (
        render_bounded_search, render_bounded_search_brief,
        render_multi_search, render_multi_search_brief,
    )

    if not search_text or not search_text.strip():
        return
    print()
    print("=" * 68)
    print("[제한 전개 탐색] 🔴 적어 둔 경로를 호출하지 않았습니다.")
    print("=" * 68)
    card_id = search_goal_card_id(search_text)
    if card_id is None:
        names = " · ".join(sorted(SEARCH_GOALS))
        print(f"  🔴 `{search_text}` 라는 목표가 없습니다. 있는 목표: {names}")
        print("  🔴 비슷한 목표를 골라 주지 않습니다.")
        return
    if not recipe_text or not recipe_text.strip():
        print("  🔴 하지 않았습니다 — 실제 덱 레시피(--recipe)가 없습니다.")
        return
    wanted, why = search_result_count(results_text)
    if wanted is None:
        print(f"  🔴 하지 않았습니다 — --results 를 읽지 못했습니다. {why}")
        return
    extra, why_extra = search_followup_count(followups_text)
    if extra is None:
        print(f"  🔴 하지 않았습니다 — --followups 를 읽지 못했습니다."
              f" {why_extra}")
        return
    if extra and wanted <= 1:
        #: 🔴 **후속 모드는 복수 결과 모드 위에서 돈다** — 조용히 켜 주지
        #: 않고, 무엇을 주어야 하는지 적는다.
        print("  🔴 하지 않았습니다 — --followups 는 --results 2 이상과"
              " 함께 주십시오 (후속 모드는 복수 결과 탐색의 모드입니다).")
        return
    parsed = parse_recipe(recipe_text, agent.repository)
    if parsed.draft is None:
        print("  🔴 레시피에서 카드를 하나도 읽지 못해 탐색하지 않았습니다.")
        return
    if wanted > 1:
        #: 🔴 **복수 결과 모드** (6-AI). 같은 탐색기이고 예산만 다르다.
        setup, many = bounded_search_many_opening(
            agent.repository, parsed.draft, hand_ids,
            card_id=card_id, max_results=wanted, followups=extra,
        )
        if many is None:
            print("  🔴 탐색하지 않았습니다 — 입력 검증을 통과하지"
                  " 못했습니다.")
            for blocker in setup.blockers:
                print(f"    - {blocker}")
            return
        #: 🔴 **추천은 탐색·재생이 끝난 뒤에 붙는다** (6-AK). 새 명령도
        #: 새 옵션도 만들지 않았다 — 복수 결과 모드의 출력에 이어 붙는다.
        ranking = rank_search_results(many)
        print(render_multi_search_brief(many, agent.repository, ranking))
        print(render_multi_search(many, agent.repository, setup, ranking))
        return
    setup, outcome, rerun = bounded_search_opening(
        agent.repository, parsed.draft, hand_ids, card_id=card_id
    )
    if outcome is None:
        print("  🔴 탐색하지 않았습니다 — 입력 검증을 통과하지 못했습니다.")
        for blocker in setup.blockers:
            print(f"    - {blocker}")
        return
    print(render_bounded_search_brief(outcome, rerun))
    print(render_bounded_search(outcome, rerun, setup))


#: ``/combo search:…`` 가 받는 **목표 이름** → 카드 ID (Phase 6-AH).
#:
#: 🔴 **이름을 추측해 비슷한 것을 골라 주지 않는다.** 없는 이름이면 그
#: 사실을 적고 탐색을 돌리지 않는다 — 사용자가 고르지 않은 목표로 찾은
#: 경로를 보여 주면 그것이 자기 목표인 줄로 읽는다 (``line:`` 과 같은 규율).
#:
#: 🔴 **카드 ID 는 목표 지정에만 쓰인다.** 탐색기 안에는 "이 카드 다음에는
#: 이 효과" 같은 분기가 없다 (``agent.bounded_search`` 의 설명).
SEARCH_GOALS: dict = {
    "galatea": 30741503,
    #: Phase 6-AN — 소재 조건을 등재한 **두 번째** 링크 몬스터다
    #: (:data:`~engine.link_rules.LINK_MATERIAL_RULES`). 🔴 이름을 여기 적는
    #: 것은 **목표로 고를 수 있게** 하는 것뿐이고, 탐색기가 이 카드를 향해
    #: 다르게 움직이지 않는다 — 목표 판정은 ``FieldGoal`` 하나다.
    "longirsu": 76145142,
}


#: ``search:`` 에 적으면 **목표 카드를 지정하지 않는 자율 탐색**이 된다
#: (Phase 6-BB).
#:
#: 🔴 **이것은 목표 이름이 아니다.** :data:`SEARCH_GOALS` 의 이름들은 "그
#: 카드가 필드에 오면 도달" 이지만, 이 값은 **도달 조건을 지정하지 않는다**
#: — 엔진이 허가한 행동을 펼치며 정리된 결정 지점을 모으고, 그중에서
#: 평가가 고른다.
AUTONOMOUS_SEARCH_NAME: str = "auto"

#: 자율 탐색의 기본 예산. 🔴 **실측으로 정한다** — 선택 분기를 8 로 두면
#: 노드 하나가 비싸져서 (실측 47노드 132초) 디스코드 요청이 끝나지 않는다.
#:
#: 🔴 **6 → 7 (Phase 6-BJ §4).** 숫자가 움직인 이유: 「오르페골 갈라테아i」
#: ③ (묘지 소생) 뒤의 **후속 링크 소환이 9번째 걸음**이고, 6 에서는 탐색이
#: 그 자리에 닿지 못했다. 같은 입력 (덱 ``docs/orcust-azamina-note.ydk`` ·
#: 패 기르수 · 하루 우라라 · 증식의 G · 무한포영 · 무덤의 지명자) 의 실측:
#:
#: ====== ======== ====== ====== ========= ==============
#: 행동   소요      노드   깊이   소생 후보 롱기르수까지
#: ====== ======== ====== ====== ========= ==============
#: 6      113.9초  341    8      6건       **0건**
#: **7**  115.7초  330    9      17건      1건
#: ====== ======== ====== ====== ========= ==============
#:
#: 🔴 **소요가 거의 같다** — 깊이가 하나 늘어도 후보 상한
#: (:data:`AUTONOMOUS_DEFAULT_CANDIDATES` 쪽) 이 먼저 차므로 같은 일을 다른
#: 깊이로 나눠 쓴다. 8 로는 올리지 않았다: 위 설명의 실측(47노드 132초)이
#: 그 값에서 노드 하나가 비싸진다고 말한다.
AUTONOMOUS_DEFAULT_ACTIONS: int = 7
AUTONOMOUS_DEFAULT_RESULTS: int = 3
#: 🔴 **20 → 64 (Phase 6-BI §2).** 「오르페골 갈라테아i」 ② 가 한 자리에서
#: 후보를 12개로 가르므로 (비용으로 낼 패 4장 × 패에 넣을 카드 3장), 20 은
#: 그 한 자리와 그 뒤를 담기에 모자랐다 — 실측으로 기본 탐색이 깊이 6 에서
#: 멈추고 **6-BH 까지 찾아내던 7걸음 전개(갈라테아 ②)가 사라졌다.**
#:
#: 🔴 **세는 단위도 함께 고쳤다.** 6-BI 부터 이 상한은 후보 개수가 아니라
#: ``agent.bounded_search.choice_family`` 로 센 **서로 다른 수순**의 수다 —
#: 한 자리에서 선택만 다른 후보들은 전부 보관되지만 **한 개로 세어진다.**
#: 단위만 고쳐서는 모자랐고 (20/16 에서 깊이 6 · 갈라테아② 0건), 값을 올려
#: **두 전개가 같은 실행에 함께 들어오는** 가장 작은 값을 골랐다 (아래 표는
#: 기준점당 상한을 전체의 3/4 로 둔 같은 입력의 측정이다):
#:
#: ====== ====== ====== ====== ========== ========= ================
#: 전체    기준점당 소요   깊이   갈라테아i② 갈라테아② 효과를 **안 쓴**
#:                                                  갈라테아② 전개
#: ====== ====== ====== ====== ========== ========= ================
#: 20     16     47.4초 6      24건       0건       0건
#: 40     32     54.8초 8      36건       3건       **0건**
#: **64** **48** 72.4초 8      77건       20건      9건
#: ====== ====== ====== ====== ========== ========= ================
#:
#: 🔴 **40/32 로는 한쪽만 보인다** — 갈라테아② 에 닿는 세 건이 모두
#: 갈라테아i ② 를 지나므로, 「효과를 쓴 전개」 와 「패를 지킨 전개」 를
#: 나란히 둘 수 없다. 64/48 에서 둘 다 들어온다.
#:
#: 🔴 **값을 올린 대가를 적는다** — 같은 입력의 탐색이 24초에서 **73초**가
#: 되었다 (탐색 상한 240초 안이다). 사용자가 기다리는 시간은 여기에 재생
#: 검증과 기록 만들기가 더해진 값이다.
AUTONOMOUS_DEFAULT_CANDIDATES: int = 64

#: **재생 검증 자리**를 후보 보관 상한에 맞춰 늘리는 비율 (Phase 6-BI §3).
#:
#: 🔴 **왜 필요한가 — 실측이다.** 재생 검증 자리 수는 6-BH 까지
#: ``max_results`` (사용자의 `results:`, 기본 2) 하나였다. 6-BI 가 보관
#: 상한을 20 → 64 로 올려 후보가 **129건**이 되자, 그중 **2건**만 검증되고
#: 추천은 그 둘에서만 나왔다 — 찾아낸 전개가 추천 자리에 닿지 못했다
#: (갈라테아② 경로 20건이 **전부** 미검증이었다).
#:
#: 🔴 **표시 수와 검증 수는 다른 질문이다.** 사용자가 `results:` 로 고르는
#: 것은 "몇 개를 보여 달라" 이고, 검증은 "모아 둔 것 가운데 몇 개를 다시
#: 실행해 확인하느냐" 다. 후보가 늘면 뒤쪽이 함께 늘어야 한다.
#:
#: 🔴 **싸다는 것도 실측이다** — 같은 입력에서 자리 2 → 7 로 늘렸을 때
#: 전체 소요가 71.7초 → 73.1초였다 (탐색이 71초이고 재실행은 한 건당
#: 1초 미만이다). 그 1~2초로 두 경로가 모두 검증 · 추천에 들어온다
#: (자리 2 에서는 갈라테아② 경로 20건이 전부 미검증이었다).
#:
#: 🔴 **10 → 4 (Phase 6-BJ §4).** 숫자가 움직인 이유: 「오르페골 갈라테아i」
#: ③ 뒤에 **롱기르수까지 간 9걸음 후보**가 자리 7 에서 검증 대상에 들지
#: 못했고 (그래서 추천에도 없었다), 그 이유가 **평가의 판단이 아니었다** —
#: 그 후보를 지배하는 후보가 **0개**였다 (실측: ``compare_v2`` 로 114건
#: 전부와 견줬다). 즉 평가는 그것을 나쁘다고 하지 않았고, **자리가 모자랐다.**
#:
#: 같은 입력에서 ``select_top_v2`` 가 그 후보를 포함하기 시작하는 자리 수를
#: 쟀다 (후보 114건 · 보관 상한 64):
#:
#: ====== ============================================ ==========
#: 자리   고른 번호                                      롱기르수
#: ====== ============================================ ==========
#: 7      17 32 55 58 86 106 107                       **없음**
#: 8      + 87                                          없음
#: 10     + 95 96                                       없음
#: 12     + 99 114                                      없음
#: **14** + 1 **69**                                    **있음**
#: 16     + 2 8                                         있음
#: ====== ============================================ ==========
#:
#: 🔴 그래서 **14 이상**이 필요하고, 이 저장소의 식(``ceil(pool/이 값)``)으로
#: 그것을 내는 값이 4 다 (``ceil(64/4) = 16``, 상한도 16 으로 올렸다). 5 는
#: 13 자리여서 모자랐다.
AUTONOMOUS_VERIFY_PER_CANDIDATES: int = 4

#: 재생 검증 자리의 **상한** (Phase 6-BI §3). 🔴 사용자가 `results:` 로 그보다
#: 많이 요구하면 그쪽이 이긴다 — 이 값은 **자동으로 늘리는 한도**다.
#:
#: 🔴 **8 → 16 (Phase 6-BJ §4).** 위 표의 이유이고, 값의 근거는 같다 —
#: 자리가 모자라서 **평가가 나쁘다고 하지 않은 후보**가 추천에 닿지 못했다.
#: 🔴 **공동 추천이 늘어난다**는 것을 함께 적는다: 검증된 후보가 전부
#: 서로를 지배하지 못하면 추천도 그만큼 늘고, 요약은 앞의 몇 개만 적고 나머지
#: 번호를 나열한다 (``deck.report.BRIEF_CANDIDATE_LIMIT``).
AUTONOMOUS_VERIFY_SLOTS_CAP: int = 16
AUTONOMOUS_DEFAULT_NODES: int = 400
AUTONOMOUS_DEFAULT_SECONDS: float = 240.0
AUTONOMOUS_DEFAULT_CHOICE_BRANCHES: int = 4
AUTONOMOUS_DEFAULT_BASELINES: int = 3

#: 자율 탐색이 쓰는 **평가 정책** (Phase 6-BD).
#:
#: 🔴 **v1 을 지우지 않는다.** ``"v1"`` 을 주면 6-BB 의 세 축 그대로 돌고,
#: 같은 입력에서 두 정책을 견줄 수 있다 (보고서 §12).
AUTONOMOUS_DEFAULT_EVALUATION: str = "v2"

#: 기준점 상한을 **서로 다른 첫 행동**으로 셀 것인가 (Phase 6-BD §5).
#:
#: 🔴 **실측으로 켰다** (보고서 §12.4): 같은 노드 수(41) · 같은 최대 깊이(8)
#: · 같은 소요에서 후보가 23 → 28 로 늘고, ``max_baselines=3`` 이 더는
#: 탐색을 끊지 않았다. 같은 첫 행동의 **다른 덤핑 선택**들이 기준점으로
#: 보관된다.
AUTONOMOUS_DEFAULT_BASELINE_PER_OPENING: bool = True

#: 기준점 사이에 **펼칠 차례를 돌릴** 것인가 (Phase 6-BD §5).
#:
#: 🔴 **실측으로 껐다** (보고서 §12.4): 같은 예산에서 최대 깊이가 8 → 3 으로
#: 줄어 깊은 전개가 통째로 사라졌다. 너비를 얻고 깊이를 잃는 맞바꿈이고,
#: 이번 입력에서는 손해였다. 🔴 **기능은 남겨 두고 기본만 끈다** — 다른
#: 예산에서는 달라질 수 있고, 끈 이유를 수치로 적어 둔다.
AUTONOMOUS_DEFAULT_ROTATE_BASELINES: bool = False

#: 기준점 하나가 모아 둘 **후속 후보 상한** (Phase 6-BE §4).
#:
#: 🔴 **후보 보관 상한을 기준점별로 나눈다** — 전체 상한
#: (:data:`AUTONOMOUS_DEFAULT_CANDIDATES`) · 노드 예산 · 제시 결과 수는
#: 그대로다. 값은 실측으로 정한다 (보고서 §13).
#:
#: 🔴 **12 → 16 (Phase 6-BF §4).** 오르페골 갈라테아 ② 를 등재한 뒤 같은
#: 기본 입력으로 다섯 값을 재서 고른 **최솟값**이다. 다른 상한 — 후보 풀
#: 20 · 노드 400 · 240초 · 분기 4 · 기준점 3 · 행동 6 — 은 **한 글자도
#: 움직이지 않았다.**
#:
#: ===== ======= ===== ====== ========= =============================
#: 상한   소요    노드  최대깊이 갈라테아② 후속을 받은 기준점
#: ===== ======= ===== ====== ========= =============================
#: 끔     7.2초   34    7      3건       1개 (6-BE 가 고친 것이 풀린다)
#: 12     9.1초   64    6      **0건**   2개
#: **16** 11.3초  72    7      1건       2개
#: 18     12.5초  76    7      2건       2개
#: 20     6.5초   34    7      3건       1개 (끔과 같다)
#: ===== ======= ===== ====== ========= =============================
#:
#: 16 · 18 만 **둘 다** 만족한다 — 6-BE 가 수치로 고친 "서로 다른 해결
#: 선택의 기준점 둘 이상이 후속을 받는다" 와, 6-BF 가 등재한 효과에 실제로
#: 닿는다는 것. 더 큰 값(20 · 끔)은 6-BE 가 고친 것을 되돌린다. 그래서
#: **둘 중 작은 쪽**을 고른다.
#:
#: 🔴 **규칙이 아니라 이 입력의 측정값이다.** 다른 덱 · 다른 패에서 같은
#: 값이 최소라고 주장하지 않는다. 그리고 **예산을 키워서 해결한 것이
#: 아니다** — 보관 자리를 기준점 사이에 어떻게 나누는가 하나만 움직였고,
#: 그 결과 깊이가 6 → 7 로 늘었다.
#:
#: 🔴 **이 값이 최단 경로를 찾는다는 뜻은 아니다.** 이 효과에 닿는 가장
#: 짧은 **합법** 경로는 5수이고 (일반 소환 → 기르수 ① → 디베르 ① → 갈라테아
#: 링크 소환 → 갈라테아 ②, ``tests/test_galatea_effect_extension.py`` 가
#: 실제 엔진으로 밟는다), 탐색이 찾아 오는 가장 짧은 경로는 **7수**다. 그
#: 차이는 남은 장애로 보고서 §7 에 적혀 있다.
#: 🔴 **16 → 48 (Phase 6-BI §2).** 「오르페골 갈라테아i」 ② 를 등재하자
#: 그 한 자리에서 후보가 12개로 갈렸고 (비용 4 × 패에 넣을 카드 3), 16 은
#: 그 **한 행동**에 거의 다 쓰였다 — 기준점이 더 펼쳐지지 않아 깊이 6 에서
#: 멈췄다. 전체 상한을 64 로 올린 뒤 (바로 위) 같은 기본 입력으로 재면:
#:
#: ====== ======== ====== ========== ========= ================
#: 상한    소요      깊이   갈라테아i② 갈라테아② 효과를 **안 쓴**
#:                                              갈라테아② 전개
#: ====== ======== ====== ========== ========= ================
#: 16     47.4초   6      24건       0건       0건
#: 32     54.8초   8      36건       3건       **0건**
#: **48** 72.4초   8      77건       20건      **9건**
#: 64     39.0초   8      96건       13건      **0건**
#: ====== ======== ====== ========== ========= ================
#:
#: 🔴 **64 (= 전체 상한) 는 6-BE 가 고친 것을 되돌린다** — 기준점 하나가
#: 보관을 다 쓰고, 실측으로 「효과를 쓰지 않은 갈라테아② 전개」 가 0건이다.
#: 48 에서 **두 전개가 함께** 들어오고 기준점도 나뉜다.
AUTONOMOUS_DEFAULT_CANDIDATES_PER_BASELINE: int = 48
#: 🔴 **값을 실측으로 골랐다** (보고서 §13.4 — **6-BE 당시의 기록**).
#: 전체 보관 상한 20 · 노드 400 · 240초 · 깊이 8 을 그대로 두고 상한만
#: 나눴다. **12** 에서 스켈레촌 기준점이 후속 12개(깊이 6)를 쓰고
#: **디베르 기준점이 8개(깊이 4)** 를 받는다 — 0(제한 없음)에서는
#: 디베르가 **0개**였다. 🔴 **이 세 줄은 값이 12 였을 때의 측정이고,
#: 지금 기본값은 16 이다** (위 표). 깊이 4 에서 멈추던 그 디베르 갈래가
#: 6-BF 가 닫지 못한 장애로 남아 있다 (6-BF 보고서 §4.5).


def card_knowledge(repository):
    """
    카드 저장소에서 **정의 사실만** 떠서 평가에 넘길 그릇을 만든다
    (Phase 6-BD).

    🔴 **판정을 넘기지 않는다.** 넘기는 것은 "토큰인가 · 세트해 두면 상대
    턴에 쓸 수 있는 종류인가 · 인쇄된 효과가 몇 개인가" 뿐이고, 지금
    발동할 수 있는지는 ``legal_actions`` 의 일이다.

    🔴 **왜 어댑터인가** (ADR-007). ``agent`` 는 카드 저장소를 모른다 —
    알면 평가가 카드 데이터에 묶이고, 시험이 저장소 없이는 돌지 않는다.
    """
    from agent.open_evaluation_v2 import CardFacts, CardKnowledge

    class _FromRepository(CardKnowledge):
        """물어본 카드만 읽어 두는 그릇 — 🔴 **덱 전체를 훑지 않는다.**"""

        def __init__(self, source) -> None:
            super().__init__()
            self._source = source
            self._seen: dict = {}

        def get(self, card_id):
            if card_id in self._seen:
                return self._seen[card_id]
            facts = None
            card = None
            try:
                if isinstance(card_id, int):
                    card = self._source.get(card_id)
            except Exception:  # noqa: BLE001 - 모르면 None 이다
                card = None
            if card is not None:
                kinds = set(getattr(card, "type_names", ()) or ())
                facts = CardFacts(
                    is_token=bool(getattr(card, "is_token", False)),
                    #: 🔴 **세트해 두면 상대 턴에 쓸 수 있는 종류**인가 —
                    #: 함정 전부와 속공마법. 발동 조건은 보지 않는다.
                    reactive_backrow=bool(
                        getattr(card, "is_trap", False)
                        or (getattr(card, "is_spell", False)
                            and "QUICKPLAY" in kinds)
                    ),
                    effect_count=len(getattr(card, "effects", ()) or ()),
                    is_monster=bool(getattr(card, "is_monster", False)),
                    #: 🔴 **종류를 그대로 읽는다** (Phase 6-BE §1) — 6-BD 는
                    #: "토큰이 아닌 몬스터" 를 전부 효과 몬스터로 불렀다.
                    is_effect_monster=("EFFECT" in kinds
                                       and "MONSTER" in kinds),
                    is_extra_deck=bool(getattr(card, "is_extra_deck", False)),
                )
            self._seen[card_id] = facts
            return facts

    return _FromRepository(repository)

#: 자율 탐색의 **진행 단계 이름** (Phase 6-BC §5).
#:
#: 🔴 **왜 문자열인가.** 진행 상태를 받는 쪽은 Discord 어댑터이고
#: (``app.discord_bot``), 보내는 쪽은 이 조립 계층이다. 둘 사이에 새 자료형을
#: 두면 ``deck`` · ``agent`` 가 쓰지도 않는 형을 import 하게 되므로
#: (ADR-007), **값 문자열 세 개**로 끝낸다.
#:
#: 🔴 **단계가 늘었다고 일을 더 하지 않는다.** 이 이름들은 **이미 있던
#: 경계**에 붙은 이름이다 — ``run_many`` 전 · ``rerun_select`` 가 불릴 때
#: (= 탐색이 끝나고 재생 검증이 시작될 때) · 돌려주기 직전.
PROGRESS_SEARCHING: str = "searching"
PROGRESS_VERIFYING: str = "verifying"
PROGRESS_REPORTING: str = "reporting"


def notify_progress(progress, stage: str) -> None:
    """
    진행 단계를 **알리기만** 한다 (Phase 6-BC §5).

    ``progress`` 가 ``None`` 이면 아무것도 하지 않는다 — 🔴 **진행 표시는
    선택이고, 주지 않은 호출의 동작은 6-BB 와 같다.**

    🔴 **진행 표시가 탐색을 깨뜨리지 못하게 한다.** 받는 쪽은 Discord 전송
    (끊긴 연결 · 상한 거절 · 권한)이고, 그 예외가 올라오면 **이미 끝난
    탐색을 잃는다**. 그래서 여기서 잡아 로그에만 남긴다 — 🔴 다만 **성공한
    것처럼 조용히 넘기지 않는다** (로그에 단계와 예외가 남는다).
    """
    if progress is None:
        return
    try:
        progress(stage)
    except Exception:  # noqa: BLE001 — 진행 표시 실패로 탐색을 잃지 않는다.
        import logging

        logging.getLogger(__name__).warning(
            "진행 표시를 보내지 못했습니다 (stage=%s)", stage, exc_info=True
        )


def is_autonomous_search(name: str) -> bool:
    """``search:`` 가 **자율 탐색**을 고른 것인가 (Phase 6-BB)."""
    return bool(name) and name.strip().lower() == AUTONOMOUS_SEARCH_NAME


def search_goal_card_id(name: str) -> "int | None":
    """``search:`` 로 받은 이름의 목표 카드 ID. 모르는 이름이면 ``None``."""
    if not name or not name.strip():
        return None
    return SEARCH_GOALS.get(name.strip().lower())


def search_followup_count(text) -> tuple:
    """
    ``followups:`` 로 받은 **후속 비흐름 행동 상한** — ``(개수, 설명)``
    (Phase 6-AL).

    🔴 **주지 않으면 0 이다** — 그때는 목표에 처음 도달하면 멈추는 기존
    모드이고 한 글자도 다르지 않다. 🔴 **읽지 못하거나 상한을 벗어나면
    탐색하지 않는다** — 조용히 깎아 주면 그 결과가 "이게 전부" 로 읽힌다.
    """
    from agent.bounded_search import FOLLOWUP_CAP

    if text is None or not str(text).strip():
        return 0, ""
    raw = str(text).strip()
    if isinstance(text, bool):
        return None, f"참/거짓이 아니라 수를 적어 주세요: {text!r}"
    try:
        value = int(raw)
    except ValueError:
        return None, f"정수가 아닙니다: {raw!r}"
    if not 0 <= value <= FOLLOWUP_CAP:
        return None, (f"0 이상 {FOLLOWUP_CAP} 이하로 적어 주세요 "
                      f"(0 이면 첫 도달에서 멈춥니다): {value}")
    return value, ""


def rank_search_results(outcome):
    """
    검증된 복수 결과를 **비교해 추천 후보를 고른다** (Phase 6-AK).

    🔴 **왜 이 자리인가.** 평가는 ``agent`` 의 일이고(``agent.result_ranking``),
    표시는 ``deck`` 의 일이다 — 그런데 어댑터는 둘을 **이어 주기만** 한다
    (``deck`` 은 ``agent`` 를 import 하지 않는다, ADR-007). 사용자에게 보이는
    경로가 둘(CLI · Discord)이므로, 같은 것을 꽂는 자리를 **하나**로 둔다.

    🔴 **탐색과 재생이 끝난 뒤의 독립 단계다.** 받은 결과를 바꾸지 않고 값만
    읽는다. ``outcome`` 이 없으면 평가도 없다.
    """
    if outcome is None:
        return None
    if getattr(outcome, "continues", False):
        #: 🔴 **후속 모드에는 추천을 연결하지 않는다** (6-AL §5). 자원 보존
        #: 기준은 패를 쓰는 행동을 불리하게 보므로, 후속 전개의 가지치기나
        #: 확장 우선순위로 쓰면 후속 전개를 찾지 못한다. 그 사실은 출력이
        #: 한 줄로 밝힌다 (``deck.report`` 의 후속 절).
        return None
    from agent.result_ranking import rank_results

    return rank_results(outcome)


def search_result_count(text) -> tuple:
    """
    ``results:`` 로 받은 **모을 결과 수** — ``(개수, 설명)`` (Phase 6-AI).

    주지 않으면 ``(1, "")`` 다 — 🔴 **단일 결과 모드가 기본이고**, 고르지
    않은 모드로 조용히 바꾸지 않는다. 읽지 못하거나 상한을 벗어나면
    ``(None, 이유)`` 이고, 그때 부르는 쪽은 **탐색을 돌리지 않는다**.

    🔴 **작고 분명한 상한을 둔다** (``RESULTS_CAP``). 조용히 깎아 주지
    않는 이유는 하나 — 5개를 달라고 한 요청에 3개를 돌려주면 그것이 "가능한
    전부" 로 읽힌다.
    """
    from agent.bounded_search import RESULTS_CAP

    if text is None:
        return 1, ""
    if isinstance(text, bool):
        return None, "참·거짓이 아니라 개수를 적어 주세요."
    if isinstance(text, int):
        number = text
    else:
        stripped = str(text).strip()
        if not stripped:
            return 1, ""
        try:
            number = int(stripped)
        except ValueError:
            return None, f"정수가 아닙니다: {stripped!r}"
    if not 1 <= number <= RESULTS_CAP:
        return None, (f"1 이상 {RESULTS_CAP} 이하로 적어 주세요"
                      f" (받은 값 {number}). 1 이면 단일 결과 모드입니다.")
    return number, ""


def bounded_search_opening(
    repository, draft, hand, *, card_id: int, budget=None, rerun: bool = True
) -> tuple:
    """
    선공 전개를 **제한 탐색**으로 돌리고, 찾은 경로를 재생한다 (Phase 6-AH).

    돌려주는 것은 ``(setup, outcome, rerun_result)`` 다.

    🔴 **왜 이 자리인가.** 탐색의 핵심은 ``agent.bounded_search`` 에 있고,
    초기 상태는 ``deck.opening.build_opening`` 이 만들고, 유발과 해결 시점
    선택은 :func:`opening_wiring` 이 꽂는다. 세 계층을 잇는 자리가 하나여야
    CLI 와 Discord 가 같은 답을 낸다 — :func:`opening_wiring` 과 같은
    규율이고, 어댑터는 ``agent`` 를 직접 import 하지 않는다
    (``tests/test_discord_bot.py::test_15``).

    🔴 **재생은 새 초기 상태에서 한다.** 같은 입력으로 ``build_opening`` 을
    **다시** 불러 만든 듀얼에 기록된 걸음을 다시 밟는다 — 탐색이 만든 최종
    상태를 그대로 내보내는 것이 아니다 (§5).

    🔴 **재생이 실패하면 그대로 돌려준다.** 이 자리에서 성공으로 바꾸지
    않는다.
    """
    from agent.bounded_search import BoundedSearch, FieldGoal, rerun_path
    from deck.opening import build_opening

    chooser, triggers = opening_wiring(repository, None)
    setup = build_opening(
        repository, draft, list(hand), chooser=chooser, triggers=triggers
    )
    if not setup.can_run:
        return setup, None, None

    search = BoundedSearch(
        goal=FieldGoal(card_id=card_id, seat=0),
        **({"budget": budget} if budget is not None else {}),
    )
    outcome = search.run(setup.duel)

    done = None
    if rerun and outcome.reached:
        #: 🔴 **새 초기 상태다.** 같은 입력으로 다시 만든 듀얼이고, 탐색이
        #: 쓴 ``setup.duel`` 이 아니다.
        fresh_chooser, fresh_triggers = opening_wiring(repository, None)
        fresh = build_opening(
            repository, draft, list(hand),
            chooser=fresh_chooser, triggers=fresh_triggers,
        )
        if fresh.can_run:
            done = rerun_path(fresh.duel, outcome)
    return setup, outcome, done


def bounded_search_many_opening(
    repository, draft, hand, *, card_id: int, max_results: int,
    budget=None, rerun: bool = True, followups: int = 0
) -> tuple:
    """
    선공 전개의 **서로 다른 결과 여럿**을 모으고 각각을 재생한다 (6-AI §6).

    돌려주는 것은 ``(setup, outcome)`` 이고, ``outcome`` 은
    ``MultiSearchOutcome`` 이다 — 재생 결과가 그 안의 결과마다 들어 있다.

    🔴 **단일 결과 모드와 같은 자리다.** :func:`bounded_search_opening` 과
    같은 :func:`opening_wiring` · ``build_opening`` 을 쓰고, 탐색기도 같은
    ``BoundedSearch`` 다 — 예산의 ``max_results`` 만 다르다.

    🔴 **재생은 같은 입력으로 다시 만든 새 초기 상태에서 한다** (§5).
    탐색이 쓴 ``setup.duel`` 이 아니다. 그 판을 만들지 못하면 탐색이 쓴
    입력에서 사본을 떠 돌리고, 어느 쪽이든 재생 실패를 성공으로 바꾸지
    않는다.

    🔴 **결과 수를 채우려고 중복 경로나 정적 계획을 끼워 넣지 않는다** —
    모은 결과가 하나면 하나로 돌려준다.
    """
    from agent.bounded_search import (
        BoundedSearch, FOLLOWUP_CAP, FieldGoal, RESULTS_CAP, SearchBudget,
    )
    from deck.opening import build_opening

    wanted = max(2, min(int(max_results), RESULTS_CAP))
    extra = max(0, min(int(followups), FOLLOWUP_CAP))
    chooser, triggers = opening_wiring(repository, None)
    setup = build_opening(
        repository, draft, list(hand), chooser=chooser, triggers=triggers
    )
    if not setup.can_run:
        return setup, None

    budget = (
        SearchBudget(max_results=wanted) if budget is None
        else dataclasses.replace(budget, max_results=wanted)
    )
    if extra:
        #: 🔴 **후속 모드** (Phase 6-AL). 같은 탐색기이고 예산만 다르다.
        #:
        #: 🔴 **깊이 상한을 후속 상한만큼 올려 잡는다** — 상한을 무시하는
        #: 것이 아니라, 두 상한이 서로를 잡아먹지 않게 두는 것이다. 기준점이
        #: 깊이 상한에 가까우면 후속 행동을 한 번도 못 하고, 그러면 "후속이
        #: 없다" 가 실제로는 "깊이가 없었다" 가 된다. 올린 값은
        #: ``budget.describe_ko()`` 에 그대로 보인다.
        budget = dataclasses.replace(
            budget,
            max_depth=budget.max_depth + extra,
            max_followup_actions=extra,
            #: 🔴 **기준점 상한과 후속 후보 상한은 역할이 다르다** —
            #: 기준점을 모으는 것이 후속 후보의 자리를 먹지 않는다.
            max_baselines=wanted,
        )
    search = BoundedSearch(goal=FieldGoal(card_id=card_id, seat=0), budget=budget)

    fresh_duel = None
    if rerun:
        fresh_chooser, fresh_triggers = opening_wiring(repository, None)
        fresh = build_opening(
            repository, draft, list(hand),
            chooser=fresh_chooser, triggers=fresh_triggers,
        )
        if fresh.can_run:
            fresh_duel = fresh.duel
    outcome = search.run_many(setup.duel, rerun_from=fresh_duel, rerun=rerun)
    return setup, outcome


def _share_options(per_opening, rotate, per_baseline=None) -> dict:
    """🔴 **주지 않은 칸은 건드리지 않는다** — 기본 동작이 그대로다."""
    out: dict = {}
    if per_opening is not None:
        out["baseline_per_opening"] = bool(per_opening)
    if rotate is not None:
        out["rotate_baselines"] = bool(rotate)
    if per_baseline is not None:
        out["max_candidates_per_baseline"] = max(0, int(per_baseline))
    return out


def autonomous_search_opening(
    repository, draft, hand, *, max_results: int = AUTONOMOUS_DEFAULT_RESULTS,
    actions: int = AUTONOMOUS_DEFAULT_ACTIONS, candidates: int = 0,
    budget=None, rerun: bool = True, progress=None,
    evaluation: str = AUTONOMOUS_DEFAULT_EVALUATION,
    baseline_per_opening: "bool | None" = None,
    rotate_baselines: "bool | None" = None,
    candidates_per_baseline: "int | None" = None,
) -> tuple:
    """
    **목표 카드 없이** 선공 전개를 탐색한다 (Phase 6-BB).

    돌려주는 것은 ``(setup, outcome)`` 이고 ``outcome`` 은
    ``MultiSearchOutcome`` 이다 — 기존 복수 결과 모드와 **같은 자료형**이다.

    🔴 **탐색기를 새로 만들지 않았다.** 같은 ``BoundedSearch`` · 같은
    ``opening_wiring`` · 같은 ``build_opening`` 을 쓰고, 다른 것은 둘뿐이다 —
    목표가 ``OpenGoal`` (도달 조건에 카드가 없다) 이고, 후보를 **평가 전에
    크게 모아 두었다가** 상위만 재생한다는 것.

    🔴 **고정 경로 정책을 부르지 않는다.** ``opening_wiring(repository,
    None)`` 이므로 ``ComboLine`` 의 해결 선택 선호도 꽂히지 않는다 — 해결
    중 선택은 탐색기의 분기(``max_choice_branches``)가 만든다.

    🔴 **자율 탐색의 기준점은 "첫 소환이 정리된 자리" 다.** 그래서 전개의
    거의 전부가 후속 행동이고, ``actions`` 가 사실상의 행동 예산이다.

    ``progress`` 를 주면 **단계 이름만** 받아 간다 (Phase 6-BC §5,
    :func:`notify_progress`) — 🔴 **탐색을 나누거나 중간 결과를 내보내지
    않는다.** 알리는 자리는 ``run_many`` 전과 ``rerun_select`` 가 불리는
    순간뿐이고, 그 순간은 **탐색이 끝나고 재생 검증이 시작되는 경계**다.
    """
    from agent.bounded_search import (
        BoundedSearch, CANDIDATE_CAP, FOLLOWUP_CAP, OpenGoal, RESULTS_CAP,
        SearchBudget,
    )
    from agent.open_evaluation import select_top
    from agent.open_evaluation_v2 import select_top_v2
    from deck.opening import build_opening

    #: 🔴 **평가 정책과 탐색 배분은 따로 고른다** (Phase 6-BD §5) — 둘을 한
    #: 칸으로 묶으면 어느 변경이 어떤 효과를 냈는지 가를 수 없다.
    knowledge = (None if str(evaluation) == "v1"
                 else card_knowledge(repository))

    wanted = max(2, min(int(max_results), RESULTS_CAP))
    steps = max(1, min(int(actions), FOLLOWUP_CAP))
    pool = int(candidates) or AUTONOMOUS_DEFAULT_CANDIDATES
    pool = max(wanted, min(pool, CANDIDATE_CAP))

    chooser, triggers = opening_wiring(repository, None)
    setup = build_opening(
        repository, draft, list(hand), chooser=chooser, triggers=triggers
    )
    if not setup.can_run:
        return setup, None

    if budget is None:
        budget = SearchBudget(
            #: 🔴 **깊이는 행동 예산보다 넉넉히** — 패스도 걸음을 쓴다.
            max_depth=steps + 6,
            max_nodes=AUTONOMOUS_DEFAULT_NODES,
            max_seconds=AUTONOMOUS_DEFAULT_SECONDS,
            max_choice_branches=AUTONOMOUS_DEFAULT_CHOICE_BRANCHES,
            max_results=wanted,
            max_candidates=pool,
            max_followup_actions=steps,
            max_baselines=AUTONOMOUS_DEFAULT_BASELINES,
            **_share_options(
                (AUTONOMOUS_DEFAULT_BASELINE_PER_OPENING
                 if baseline_per_opening is None else baseline_per_opening),
                (AUTONOMOUS_DEFAULT_ROTATE_BASELINES
                 if rotate_baselines is None else rotate_baselines),
                (AUTONOMOUS_DEFAULT_CANDIDATES_PER_BASELINE
                 if candidates_per_baseline is None
                 else candidates_per_baseline),
            ),
        )
    else:
        budget = dataclasses.replace(
            budget, max_results=wanted, max_candidates=pool,
            max_followup_actions=steps,
            **_share_options(baseline_per_opening, rotate_baselines,
                             candidates_per_baseline),
        )
    search = BoundedSearch(goal=OpenGoal(card_id=0, seat=0), budget=budget)

    fresh_duel = None
    if rerun:
        fresh_chooser, fresh_triggers = opening_wiring(repository, None)
        fresh = build_opening(
            repository, draft, list(hand),
            chooser=fresh_chooser, triggers=fresh_triggers,
        )
        if fresh.can_run:
            fresh_duel = fresh.duel

    #: 🔴 **다시 실행해 확인할 자리 수** — 표시 수가 아니라 **보관 상한**에
    #: 맞춘다 (Phase 6-BI §3, :data:`AUTONOMOUS_VERIFY_PER_CANDIDATES`).
    #: 사용자가 `results:` 로 더 많이 요구하면 그쪽이 이긴다.
    verify = max(
        wanted,
        min(
            -(-pool // AUTONOMOUS_VERIFY_PER_CANDIDATES),
            AUTONOMOUS_VERIFY_SLOTS_CAP,
        ),
    )

    def _pick(rows):
        #: 🔴 **이 자리가 "탐색 끝 · 검증 시작" 이다** (Phase 6-BC §5).
        #: ``run_many`` 는 모으기를 마친 뒤에만 선택 함수를 부르므로, 여기서
        #: 알리면 단계 이름이 **실제 경계와 어긋나지 않는다**.
        notify_progress(progress, PROGRESS_VERIFYING)
        if str(evaluation) == "v1":
            return select_top(rows, verify)
        return select_top_v2(rows, verify, knowledge=knowledge)

    notify_progress(progress, PROGRESS_SEARCHING)
    outcome = search.run_many(
        setup.duel, rerun_from=fresh_duel, rerun=rerun,
        #: 🔴 **모은 다음 평가해서 상위만 재생한다** — 깊이 우선으로 먼저
        #: 닿은 것이 곧 추천이 되지 않게.
        rerun_select=(None if not rerun else _pick),
    )
    notify_progress(progress, PROGRESS_REPORTING)
    return setup, outcome


#: 한 자리에서 적는 **다른 후보의 최대 수**. 넘으면 수만 적는다.
#:
#: 🔴 **자른 것을 숨기지 않는다** — 자른 자리는 ``allowed_total`` 이
#: 목록보다 크고, 화면이 "N개 중 M개 표시" 로 적는다 (사용자 요구 §1).
DECISION_SIBLING_LIMIT: int = 8

#: 보류도 같은 규율로 자른다. 보류는 한 자리에서 수십 건이 될 수 있다.
DECISION_WITHHELD_LIMIT: int = 6


def _action_shape(duel, action) -> dict:
    """
    행동 하나를 **값**으로 — 종류 · 카드 · 효과 · 소재 · 비용.

    🔴 **이름을 붙이지 않는다** (패스코드만). 사람이 읽는 이름은 카드
    저장소가 있는 내보내기 계층이 붙인다.
    """

    def passcode(instance) -> "int | None":
        found = duel.state.find_instance(instance)
        return None if found is None else found.card_id

    shape: dict = {"kind": action.kind.value}
    if action.source is not None:
        shape["card"] = passcode(action.source)
    ref = getattr(action, "effect_ref", None)
    if ref is not None:
        shape["effect_ref"] = str(ref)
    materials = tuple(getattr(action, "materials", ()) or ())
    if materials:
        shape["materials"] = [passcode(one) for one in materials]
    costs = tuple(getattr(action, "cost_cards", ()) or ())
    if costs:
        shape["cost"] = [passcode(one) for one in costs]
    targets = tuple(getattr(action, "targets", ()) or ())
    if targets:
        found = []
        for target in targets:
            instance = getattr(target, "instance_id", None)
            found.append(None if instance is None else passcode(instance))
        shape["targets"] = found
    return shape


def _decision_snapshot(duel, legal, chosen) -> dict:
    """
    **고르는 자리 하나**를 값으로 적는다 (Phase 6-BL).

    담는 것은 셋이다 — 고른 행동의 모양, **같은 자리의 다른 허용 후보**,
    그리고 **그 자리의 보류**(엔진이 묻고 막은 것). 🔴 셋 다 ``legal`` 에서
    그대로 읽은 것이고 하나도 지어내지 않았다.

    🔴 **보류와 미지원을 가른다.** ``missing`` 이 붙은 보류는 "이 저장소에
    그 규칙이 없다" 이고, 붙지 않은 것은 "규칙이 막았다" 다 —
    :meth:`~engine.duel.LegalActions.unsupported` 가 세는 그 구분이다.
    """
    key = chosen.canonical_state()
    siblings = [
        _action_shape(duel, action)
        for action in legal.allowed
        if action.canonical_state() != key
    ]
    withheld = [
        {
            "kind": held.kind.value,
            "code": getattr(held.code, "value", str(held.code)),
            "reason": held.reason,
            "missing": bool(getattr(held, "missing", None)),
        }
        for held in legal.withheld
    ]
    return {
        #: 🔴 **재실행이 본 것**이다 — 탐색이 그때 본 것과 같다고 주장하지
        #: 않는다 (클래스 머리말).
        "source": "rerun",
        "seat": legal.seat,
        "chosen": _action_shape(duel, chosen),
        "allowed_total": len(legal.allowed),
        "allowed": siblings[:DECISION_SIBLING_LIMIT],
        "withheld_total": len(withheld),
        "withheld": withheld[:DECISION_WITHHELD_LIMIT],
    }


class ScriptedActionPolicy:
    """
    탐색이 **찾아낸** 행동들을 순서대로 다시 고르는 선택 방식 (Phase 6-BB).

    🔴 **사람이 적어 둔 경로가 아니다.** ``ComboLine`` 도 ``PlannedAction``
    도 쓰지 않고, 탐색이 기록한 ``PathStep.action_key`` 를 그대로 받는다.

    🔴 **후보 밖을 고르지 않는다.** 기록된 다음 행동이 그 자리의 허용
    후보에 없으면 ``None`` 을 돌려주고, 그러면 ``execute_opening`` 이
    필수 흐름(패스)만 지나가거나 **멈춘다** — 비슷한 행동으로 메꾸지
    않는다.

    🔴 **그 자리의 다른 후보를 함께 적는다** (Phase 6-BL) —
    :attr:`decisions`.

    왜 여기인가: 이 함수는 ``execute_opening`` 이 고를 자리마다 부르는
    것이고, 그때 ``legal`` **전부**를 받는다. 그래서 "엔진이 그 자리에서
    무엇을 허가했고 무엇을 보류했는가" 를 **지어내지 않고** 적을 수 있는
    유일한 자리다.

    🔴 **탐색 기록에는 이것이 없다.** :class:`~agent.bounded_search.PathStep`
    은 고른 행동 하나와 해결 중 선택만 들고 있고, **형제 후보를 적지
    않는다** (실측: 6-BK 까지 그 칸이 없었다). 그래서 이 칸은 **재실행이
    같은 자리에서 다시 본 것**이고, 그 사실을 기록이 함께 적는다
    (``source: "rerun"``) — 탐색이 그때 본 것과 같다고 **주장하지
    않는다.**

    🔴 **이름을 짓지 않는다.** 여기서는 패스코드와 종류만 적고, 사람이
    읽는 이름은 카드 저장소가 있는 내보내기 계층이 붙인다
    (:func:`~deck.replay_export.export_opening_replay`) — 같은 규율이
    ``ExecutedStep.material_card_ids`` 에도 적혀 있다.
    """

    __slots__ = ("_want", "taken", "name", "decisions")

    def __init__(self, keys, name: str = "autonomous-rerun"):
        self._want = list(keys)
        self.taken: list[tuple] = []
        self.name = name
        self.decisions: list[dict] = []

    @property
    def done(self) -> bool:
        return not self._want

    @property
    def left(self) -> int:
        return len(self._want)

    def __call__(self, duel, legal):
        if not self._want:
            return None
        want = self._want[0]
        for action in legal.allowed:
            if action.canonical_state() == want:
                self._want.pop(0)
                self.taken.append(want)
                self.decisions.append(
                    _decision_snapshot(duel, legal, action)
                )
                return action
        return None


#: 후보가 **평가에서 어떤 처지였는가** — 화면이 그대로 적는 낱말들.
#:
#: 🔴 **우열이 아니다.** ``excluded`` 는 "비교에 들어가지 못했다" 이고
#: "졌다" 가 아니다. 그 둘을 한 낱말로 쓰면 근거가 없는 후보를 **낮게
#: 평가했다고 설명하는** 셈이 된다 (사용자 요구 §3).
CANDIDATE_STATES: tuple[str, ...] = (
    "recommended",       # 지배당하지 않았다
    "dominated",         # 비교에 들어갔고 **실제로** 다른 후보에게 뒤졌다
    "unexplored",        # 후속을 한 번도 탐색받지 못한 기준점이다
    "not_recommended",   # 추천에 오르지 않았고, 위 어느 사유도 아니다
    "excluded",          # 비교에 **들어가지 못했다** (검증 · 측정 · 선정)
    "unknown",           # 평가 기록에 이 번호가 없다
)


def _candidate_state(one, ranking=None) -> dict:
    """
    후보 하나의 **처지**를 값으로 (Phase 6-BM).

    🔴 **판정하지 않는다.** ``OpenCandidate`` 에 이미 적힌 것을 옮기기만
    한다 — ``exclusion`` · ``rerun_state`` · ``verified`` · ``dominated_by``.
    평가 기록에 번호가 없으면 ``unknown`` 이고, 그것을 "낮다" 로 바꾸지
    않는다.

    🔴 **「뒤졌다」 를 추측으로 쓰지 않는다** (6-BM 후속, 실측으로 잡았다).
    처음 판은 "추천이 아니고 비교 대상이면 뒤진 것" 으로 적었는데, 실제
    실행에서 **기준점 후보**가 그렇게 찍혔다 — 평가기 자신은 그 후보를
    *"지배당한 것도, 재생이 실패한 것도 아니다"* 라고 적는다
    (``RankingV2.unexplored``). 그래서 이제 **``dominated_by`` 에 실제로
    이름이 있을 때만** 뒤졌다고 적고, 탐색받지 못한 기준점은 따로 적으며,
    둘 다 아니면 사유를 주장하지 않고 근거 글자에 맡긴다.
    """
    if one is None:
        return {
            "kind": "unknown",
            "label": "평가 기록에 이 번호가 없습니다",
            "eligible": None,
        }
    exclusion = getattr(getattr(one, "exclusion", None), "value", None)
    eligible = bool(getattr(one, "eligible", False))
    if not eligible:
        return {
            "kind": "excluded",
            #: 🔴 **"빠졌다" 이고 "졌다" 가 아니다.**
            "label": "평가 비교에 들어가지 않았습니다",
            "eligible": False,
            "exclusion": exclusion,
            "rerun_state": getattr(one, "rerun_state", ""),
            "verified": bool(getattr(one, "verified", False)),
        }
    beaten = tuple(getattr(one, "dominated_by", ()) or ())
    unexplored = tuple(getattr(ranking, "unexplored", ()) or ())
    if getattr(one, "recommended", False):
        kind, label = "recommended", "어느 후보에게도 지배당하지 않았습니다"
    elif int(getattr(one, "index", -1)) in {int(i) for i in unexplored}:
        #: 🔴 **탐색받지 못한 기준점** — 지배당한 것이 아니다.
        kind, label = ("unexplored",
                       "후속 행동을 한 번도 탐색받지 못한 기준점입니다")
    elif beaten:
        #: 🔴 **이름이 있을 때만** 뒤졌다고 적는다.
        kind, label = ("dominated",
                       "비교에 들어갔고 다른 후보에게 뒤졌습니다")
    else:
        #: 🔴 **사유를 주장하지 않는다** — 근거 글자가 말한다.
        kind, label = ("not_recommended",
                       "추천에 오르지 않았습니다 (사유는 아래 근거에 적혀 "
                       "있습니다)")
    return {
        "kind": kind,
        "label": label,
        "eligible": True,
        "exclusion": exclusion,
        "rerun_state": getattr(one, "rerun_state", ""),
        "verified": bool(getattr(one, "verified", False)),
    }


def autonomous_recommendation_block(outcome, ranking, index: int) -> "dict | None":
    """
    **이 후보가 왜 추천인가** — 평가기가 실제로 적은 것만 (Phase 6-BL).

    🔴 **점수를 만들지 않는다.** 평가기는 점수를 내지 않고 **지배 관계**로
    고른다 (``RankingV2``). 그래서 여기 담기는 것은 그 판정의 글자
    (:meth:`~agent.open_evaluation_v2.RankingV2.reason_ko`) 와 **그 축이
    증명하지 않는 것**(``Criterion.limit_ko``) 이다.

    🔴 **최종 추천을 앞선 행동의 동기로 소급하지 않는다.** 이 칸은
    **마지막 장면**의 것이고, 걸음마다 붙는 ``decisions`` 와 **다른
    사실**이다 — 그 구분이 사용자 요구 §2 의 핵심이다. 그래서 칸 이름도
    자리도 따로 둔다.

    🔴 **탐색이 무엇을 보지 않았는지 함께 적는다** — ``choice_*`` 수치는
    탐색 한 번의 것이고 걸음마다의 것이 아니다 (그 사실을 ``scope`` 로
    적는다).
    """
    if ranking is None:
        return None
    one = ranking.candidate(index)
    best = [other.index for other in ranking.recommended]
    mine = index in best
    block: dict = {
        "index": index,
        "policy": ranking.policy_label,
        "recommended": mine,
        "reason": ranking.reason_ko(index),
        "stop_note": ranking.stop_note_ko(index),
        "note": ranking.note,
        #: 🔴 **추천인 후보에만 적는다** (Phase 6-BM). 추천이 아닌 후보에
        #: 추천 목록을 실으면 화면이 "그 후보들과 **우열을 가리지 못했다**"
        #: 고 적게 되는데, 그것은 **일어나지 않은 비교**다 — 지배당해서
        #: 빠진 후보도, 평가 대상에서 제외된 후보도 그 문장의 뜻이 아니다.
        "co_recommended": (
            [other for other in best if other != index] if mine else []
        ),
        #: 🔴 **기록에 있는 상태를 그대로 싣는다** (Phase 6-BM). 근거가 없는
        #: 후보를 "더 낮게 평가했다" 로 적지 않기 위한 칸이다 — 비교에서
        #: 빠진 것인지, 재생 검증을 받지 못한 것인지, 값을 읽지 못한 것인지는
        #: 서로 다른 사실이고 화면이 그대로 적어야 한다.
        "state": _candidate_state(one, ranking),
        #: 🔴 **평가가 실제로 쓴 축**과 그 축이 증명하지 않는 것.
        "criteria": [
            {
                "label": item.label_ko,
                "reads": item.reads_ko,
                "limit": item.limit_ko,
                "role": item.role_ko,
            }
            for item in (ranking.criteria or ())
        ],
        #: 🔴 **센 적이 없는 것**도 적는다 (평가기가 스스로 적어 둔 목록).
        "unjudged": list(ranking.unjudged or ()),
    }
    if one is not None and getattr(one, "dominated_by", ()):
        block["dominated_by"] = list(one.dominated_by)
    if outcome is not None:
        block["search"] = {
            #: 🔴 이 수치는 **탐색 한 번**의 것이다 — 걸음마다의 것이 아니다.
            "scope": "탐색 한 번 전체",
            "choice_branches": int(getattr(outcome, "choice_branches", 0) or 0),
            "choice_plans": int(getattr(outcome, "choice_plans", 0) or 0),
            #: 🔴 **미탐색** — 확인하지 않은 대안이 남은 물음의 수.
            "choice_offers_truncated": int(
                getattr(outcome, "choice_offers_truncated", 0) or 0
            ),
            "budget_hit": list(getattr(outcome, "budget_hit", ()) or ()),
            "nodes_expanded": int(getattr(outcome, "nodes_expanded", 0) or 0),
            "deepest": int(getattr(outcome, "deepest", 0) or 0),
        }
    return block


def autonomous_rerun_record(repository, draft, hand, result, *,
                             flow_kinds=None, recommendation=None) -> tuple:
    """
    자율 탐색이 고른 결과를 **처음부터 다시 실행해** 전개 기록을 만든다
    (Phase 6-BB §5).

    돌려주는 것은 ``(record, reason)`` 이다 — 기록을 만들지 못하면
    ``(None, 이유)`` 다.

    🔴 **탐색 중 여러 분기의 사건을 한 경로처럼 합치지 않는다.** 새 초기
    상태를 만들어 **그 경로만** 다시 밟고, 그 한 번의 실행 기록을
    내보낸다.

    🔴 **재실행이 어긋나면 기록을 내보내지 않는다.** 기록된 행동이 그 자리의
    허용 후보에 없거나, 끝난 판의 상태 해시가 탐색이 적어 둔 것과 다르면
    실패로 적는다.

    🔴 **고정 경로 기능을 건드리지 않는다** — ``line`` 을 꽂지 않으므로
    ``ComboLine`` 의 해결 선호도 들어오지 않는다.
    """
    from agent.bounded_search import FLOW_ACTION_KINDS
    from agent.choice import FirstPermittedChoice, ScriptedChoice
    from deck.opening import build_opening, execute_opening
    from deck.replay_export import export_opening_replay
    from integration.autonomy import PolicyChooser, TriggerSource

    flow = FLOW_ACTION_KINDS if flow_kinds is None else frozenset(flow_kinds)
    steps = [step for step in result.path if step.kind not in flow]
    if not steps:
        return None, "다시 실행할 비흐름 행동이 없습니다."
    plan = tuple(ask.chosen for step in steps for ask in step.choices)
    #: 🔴 **흐름 걸음의 선택도 빠뜨리지 않는다** — 흐름 걸음에서 물은 것이
    #: 있으면 각본 순서가 어긋나므로, 그때는 다시 실행하지 않는다.
    if any(step.choices for step in result.path if step.kind in flow):
        return None, ("흐름 걸음에서도 해결 중 선택을 물었습니다 — 각본"
                      " 순서를 보장할 수 없어 다시 실행하지 않았습니다.")

    selector = ScriptedChoice(plan, FirstPermittedChoice(),
                              name="autonomous-rerun")
    setup = build_opening(
        repository, draft, list(hand),
        chooser=PolicyChooser(selector), triggers=TriggerSource(repository),
    )
    if not setup.can_run:
        return None, "다시 실행할 초기 상태를 만들지 못했습니다."
    policy = ScriptedActionPolicy(step.action_key for step in steps)
    run = execute_opening(setup, repository, choose=policy)
    if not policy.done:
        return None, (f"기록된 행동 {len(steps)}개 가운데 {policy.left}개를"
                      " 그 자리의 허용 후보에서 찾지 못했습니다 — 🔴 비슷한"
                      " 행동으로 메꾸지 않았습니다.")
    wanted = getattr(result.resources, "state_hash", "")
    got = setup.duel.state.state_hash()
    if wanted and got != wanted:
        return None, (f"다시 실행한 끝 상태가 탐색이 적어 둔 것과 다릅니다"
                      f" (해시 {got[:12]}… ≠ {wanted[:12]}…).")
    #: 🔴 **선택 근거를 함께 싣는다** (Phase 6-BL). 이 자리에서만 실을 수
    #: 있다 — 고르는 함수가 그 자리의 ``legal`` 을 본 유일한 자리이고, 이
    #: 함수가 그 함수를 꽂은 유일한 자리다.
    return export_opening_replay(
        setup, run, repository,
        decisions=tuple(policy.decisions),
        recommendation=recommendation,
    ), ""


def rank_autonomous_results(outcome, repository=None, *,
                            evaluation: str = AUTONOMOUS_DEFAULT_EVALUATION):
    """
    자율 탐색 결과의 **비교와 추천** (Phase 6-BB · v2 는 Phase 6-BD).

    ``repository`` 를 주면 **카드 정의 사실**을 v2 평가에 넘긴다 — 주지
    않으면 v2 는 토큰 여부도 세트 종류도 모르므로 그 값들이 전부
    "판단 불가(C)" 로 남는다 (🔴 0 으로 메우지 않는다).

    🔴 **왜 이 자리인가.** :func:`rank_search_results` 와 같은 규율이다 —
    평가는 ``agent`` 의 일이고 표시는 ``deck`` 의 일이며, 어댑터는 둘을
    이어 주기만 한다 (ADR-007).

    🔴 **6-AK 의 기준을 그대로 쓰지 않는다.** 그쪽 두 축(남은 패 · 일반
    소환권)만으로 자율 탐색을 견주면 **아무것도 하지 않은 쪽이 언제나
    이긴다** — 목표가 없으므로 "패를 가장 많이 남긴 결과" 가 곧 "일반
    소환만 하고 멈춘 결과" 다. 그래서 필드에 남은 것을 축으로 더한
    ``agent.open_evaluation`` 을 쓴다.
    """
    if outcome is None:
        return None
    if str(evaluation) == "v1":
        from agent.open_evaluation import rank_open

        return rank_open(outcome)
    from agent.open_evaluation_v2 import rank_open_v2

    return rank_open_v2(
        outcome,
        knowledge=(None if repository is None else card_knowledge(repository)),
    )


def opening_wiring(repository, line=None) -> tuple:
    """
    선공 전개 실행에 꽂을 둘 — ``(chooser, triggers)`` (Phase 6-Z).

    꽂지 않으면 유발 효과가 ``legal_actions`` 에 오르지 않고, 올라도 해결
    중에 고를 사람이 없어 거절된다. 둘 다 조립 층과 Agent 층의 것이므로
    ``deck`` 이 만들지 않고 **부르는 쪽**이 값으로 넘긴다.

    🔴 **왜 이 자리인가.** 사용자에게 보이는 경로가 둘이다 — CLI 와
    Discord 어댑터. 둘이 각자 꽂으면 같은 입력에 다른 답이 나오고, 어느
    쪽이 맞는지 알 수 없다. 그리고 어댑터는 ``agent`` · ``integration`` 을
    직접 import 하지 않는다 (``tests/test_discord_bot.py::test_15``) —
    그 경계를 지키면서 같은 것을 꽂는 유일한 방법이 **공용 자리 하나**다.

    🔴 ``FirstPermittedChoice`` 는 **전략이 아니라 기준점**이다 —
    ``first_meaningful`` 과 같은 자리다 (허용된 후보의 앞쪽을 집는다).
    이것으로 돌린 결과는 실제로 일어난 일이고, 최선의 전개가 아니다.

    ``line`` (Phase 6-AD)
    ---------------------
    검증용 전개 경로를 주면, 그 경로가 **해결 시점에 고르려는** 카드 목록을
    선택 정책에 싣는다 (``ComboLine.resolution_preferences``).

    🔴 **왜 이 자리인가.** 규칙상 해결 중에 고르는 선택은 **고르는 시점의
    행동에 적을 수 없다** — 그때는 아무것도 정해져 있지 않다 (6-AD ②). 그래서
    경로의 의도가 닿아야 하는 곳은 행동을 거르는 쪽이 아니라 **해결 중에
    묻는 쪽**이고, 그 둘을 꽂는 자리가 여기 하나다.

    🔴 **강제가 아니다.** :class:`~agent.choice.PreferredCardChoice` 는 엔진이
    그 자리에서 내놓은 허용 후보 안에서만 집고, 없으면 뒤의 기준점
    (``FirstPermittedChoice``) 에게 넘긴다 — 경로에 적힌 카드를 후보 밖에서
    끌어오지 않는다. 실제로 무엇이 집혔는지는 기록이 말한다.
    """
    from agent.choice import FirstPermittedChoice, PreferredCardChoice
    from integration.autonomy import PolicyChooser, TriggerSource

    selector = FirstPermittedChoice()
    wanted = tuple(getattr(line, "resolution_preferences", ()) or ())
    if wanted:
        selector = PreferredCardChoice(wanted, selector)
    return PolicyChooser(selector), TriggerSource(repository)


def _print_opening(agent: DeckAgent, recipe_text: str,
                   hand_ids: "list[int]", line_text: str = "") -> None:
    """
    🔴 **실제 엔진 실행 절** (Phase 6-T). 레시피가 없으면 그 사실을 적는다.

    ``line_text`` (Phase 6-AC) 는 **검증용 전개 정책의 이름**이다. 주지
    않으면 ``first_meaningful`` 그대로다 — Discord 쪽 ``line:`` 과 **같은
    것**이고, 두 어댑터가 같은 함수(``deck.combo_policy.line_named``)를
    쓴다.
    """
    from deck.combo_policy import COMBO_LINES, line_named, line_progress
    from deck.opening import build_opening, execute_opening, opening_hand_size
    from deck.recipe import parse_recipe
    from deck.report import (
        render_opening_board,
        render_opening_run,
        render_opening_setup,
    )

    print()
    print("=" * 68)
    print("실제 엔진 실행")
    print("=" * 68)
    if not recipe_text.strip():
        print(f"  🔴 하지 않았습니다 — 실제 덱 레시피가 없습니다.")
        print(f"  패 {opening_hand_size()}장만으로는 부족하고 덱 레시피"
              " 전체가 필요합니다 — 남은 덱의 장수와 카드가 효과의 발동"
              " 조건이기 때문입니다.")
        print("  넘기는 방법: --recipe \"욕망의 항아리 x3, 11091375 x37\"")
        print("              또는 --recipe <경로>.ydk")
        return

    parsed = parse_recipe(recipe_text, agent.repository)
    for note in parsed.notes:
        print(f"  {note}")
    for token in parsed.unresolved:
        print(f"  ⚠️ 레시피에서 카드를 찾지 못했습니다: {token}"
              " — 덱에 넣지 않았습니다")
    if parsed.draft is None:
        print("  🔴 레시피에서 카드를 하나도 읽지 못해 실행하지 않았습니다.")
        return

    #: 🔴 **유발 발동과 해결 시점 선택을 꽂는다** (Phase 6-Z).
    #:
    #: 꽂지 않으면 유발 효과가 ``legal_actions`` 에 오르지 않고, 올라도
    #: 해결 중에 고를 사람이 없어 거절된다. 둘 다 조립 층과 Agent 층의
    #: 것이므로 ``deck`` 이 만들지 않고 **이 자리가 값으로** 넘긴다.
    #:
    #: 🔴 ``FirstPermittedChoice`` 는 **전략이 아니라 기준점**이다 —
    #: ``first_meaningful`` 과 같은 자리다 (허용된 후보의 앞쪽을 집는다).
    #: 아래 출력은 그 선택으로 실제로 일어난 일이고, 최선의 전개가 아니다.
    line = line_named(line_text)
    if line_text and line_text.strip() and line is None:
        names = " · ".join(sorted(COMBO_LINES))
        print(f"  ⚠️ --line {line_text} 라는 검증용 전개 경로가 없습니다 —"
              f" 기본 선택 방식(first_meaningful)으로 실행했습니다."
              f" 있는 경로: {names}")
    chooser, triggers = opening_wiring(agent.repository, line)
    setup = build_opening(
        agent.repository,
        parsed.draft,
        hand_ids,
        chooser=chooser,
        triggers=triggers,
    )
    run = execute_opening(
        setup,
        agent.repository,
        **({"choose": line.policy()} if line is not None else {}),
    )
    if line is None:
        print("  🔴 고른 방식은 검증용 기준점입니다 — 행동은"
              " first_meaningful, 해결 중의 카드 선택은 first-permitted."
              " 최선의 전개가 아닙니다.")
    else:
        print(f"  🔴 고른 방식은 검증용 전개 정책 {line.name} 입니다 —"
              f" 사람이 적어 둔 경로를 따라갔을 뿐이고 최선 전개 탐색도,"
              f" 범용 AI 도, 엔진이 스스로 찾은 전개도 아닙니다.")
        print(f"     경로: {line.title_ko}")
        if line.resolution_preferences:
            #: 🔴 **해결 시점의 선택을 따로 적는다** (6-AD §6). 발동 기록의
            #: 대상이 비어 있는 것이 정상이므로, 그 칸을 보고 "아무것도 고르지
            #: 않았다" 로 읽히지 않게 한다.
            print(f"     해결 중에 고르려는 카드:"
                  f" {' · '.join(str(c) for c in line.resolution_preferences)}"
                  f" (엔진이 낸 허용 후보 안에서만 집습니다)")
        print(f"     {line_progress(run, line).describe_ko()}")
    print(render_opening_setup(setup))
    print(render_opening_run(run))
    print(render_opening_board(setup, agent.repository))


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
    p.add_argument("--recipe", default="",
                   help="실제 덱 레시피 — 주면 엔진으로 실행 검증합니다."
                        ' 예: "욕망의 항아리 x3, 11091375 x37" 또는 .ydk 경로')
    p.add_argument("--line", default="",
                   help="검증용 전개 경로 이름 — 적어 둔 경로를 따라"
                        " 실행합니다. 예: orcust-girsu")
    p.add_argument("--search", default="",
                   help="제한 전개 탐색의 목표 — 적어 둔 경로를 쓰지 않고"
                        " 엔진이 허가한 분기를 펼칩니다. 예: galatea")
    p.add_argument("--results", default="",
                   help="모을 서로 다른 결과 수 (2~5, 기본은 1개) — 주면"
                        " 결과들의 남은 자원을 비교합니다. 🔴 강약 평가가"
                        " 아닙니다")
    p.add_argument("--followups", default="",
                   help="목표 도달 뒤 더 탐색할 비흐름 행동 수 (0~3, 기본은"
                        " 0 = 첫 도달에서 멈춤) — --results 2 이상과 함께"
                        " 주십시오. 🔴 최선 전개도 최종 집 완성도 아닙니다")
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
