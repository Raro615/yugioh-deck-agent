"""
덱 구성 — **후보 선정과 최종 구성을 나눈다** (Phase 4-B).

    DeckRequest
        ↓  candidates()        테마별 후보 집합 (저장소에 물어본 결과)
    ThemeCandidates
        ↓  build()             역할 분류 → 매수 → 메인/엑스트라
    DeckDraft

왜 둘로 나누는가
----------------
후보 선정은 **조회**이고 최종 구성은 **결정**이다. 한 함수에 두면 "왜 이
카드가 들어왔는가" 와 "왜 2장인가" 가 같은 자리에서 섞여, 어느 쪽이 틀렸을
때 가릴 수 없다.

🔴 **카드 효과를 추측하지 않는다.** 역할 분류는 전부 측정 가능한 신호만
쓴다 — 공식 setcode 소속, ``is_extra_deck``, 그리고 :mod:`deck.evidence` 가
Lua 블록에서 읽은 패 관련 사실. "이 카드는 강하다" 같은 판단은 하지 않는다.

🔴 **그리고 역할과 그 근거를 따로 적는다** (:class:`~deck.model.RoleEvidence`).
Phase 5-C 까지는 ``has_effect_from("HAND")`` 하나가 사실과 역할을 겸했고,
그 결과 특수 소환 절차를 가진 카드까지 "패트랩 계열" 로 덱에 들어갔다 —
Phase 5-D 가 그것을 고쳤다. 자세한 측정값은 :mod:`deck.evidence` 에 있다.

🔴 **검색은 기존 것을 쓴다.** 카드군 해석은
:meth:`~core.card_repository.CardRepository.resolve_archetype`, 필터 검색은
:class:`~core.card_search.CardSearchEngine` 이다. 새 검색을 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.card_model import Card
from deck.evidence import HandTrapEvidence, hand_effect_facts
from deck.model import CardRole, DeckDraft, DeckSlot, RoleEvidence
from deck.request import DeckGoal, DeckRequest

#: 메인 덱 목표 장수. 룰북이 40~60 을 규정하므로 그 하단을 쓴다
#: (:mod:`deck.validator` 가 같은 데이터로 검증한다).
_TARGET_MAIN = 40

#: 엑스트라 덱 목표 장수. 룰북 ``zones`` 의 Extra Deck capacity 와 같다.
_TARGET_EXTRA = 15

#: 테마 카드 한 종류의 기본 매수. 🔴 금지·제한 데이터가 없으므로
#: 3 을 '안전한 상한' 이라고 주장하지 않는다 — 단지 이 빌더의 기본값이고,
#: 검증 단계가 "검증 불가" 로 표시한다.
_DEFAULT_COPIES = 2


@dataclass(slots=True)
class ThemeCandidates:
    """한 테마에 대한 **조회 결과**. 아직 덱이 아니다."""

    term: str
    resolved_names: list[str] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return bool(self.resolved_names)


class DeckBuilder:
    """테마와 목표로 덱 초안을 만든다."""

    def __init__(self, repository, search_engine=None):
        self.repository = repository
        #: 검색 엔진은 지금 역할 분류에만 쓴다. 넘기지 않으면 만들지 않는다 —
        #: 쓰지 않는 의존을 들고 다니지 않는다.
        self.search_engine = search_engine

    # ------------------------------------------------------------------
    # 1단계 — 후보 선정 (조회)
    # ------------------------------------------------------------------
    def candidates(self, request: DeckRequest) -> list[ThemeCandidates]:
        """
        테마마다 카드군을 해석하고 소속 카드를 모은다.

        🔴 해석되지 않은 테마도 **빈 결과로 남긴다.** 조용히 빼면 사용자가
        지정한 테마가 사라진 것을 알 수 없다.
        """
        out: list[ThemeCandidates] = []
        for term in request.themes:
            match = self.repository.resolve_archetype(term)
            if match is None:
                out.append(ThemeCandidates(term=term))
                continue
            out.append(ThemeCandidates(
                term=term,
                resolved_names=list(match.names),
                cards=list(match.cards),
            ))
        return out

    # ------------------------------------------------------------------
    # 2단계 — 최종 구성 (결정)
    # ------------------------------------------------------------------
    def build(self, request: DeckRequest) -> DeckDraft:
        """후보에서 덱 초안을 만든다."""
        groups = self.candidates(request)
        draft = DeckDraft(requested_themes=list(request.themes))

        excluded = {name.strip() for name in request.excluded_names
                    if name.strip()}
        seen: set[int] = set()

        for group in groups:
            if not group.resolved:
                draft.unresolved_themes.append(group.term)
                continue
            draft.resolved_themes.extend(
                n for n in group.resolved_names
                if n not in draft.resolved_themes)

            for card in group.cards:
                if card.id in seen:
                    continue
                if self._is_excluded(card, excluded):
                    continue
                seen.add(card.id)
                slot = self._slot_for(card, group, request)
                if card.is_extra_deck:
                    draft.extra.append(slot)
                else:
                    draft.main.append(slot)

        self._fill(draft, request, seen)
        self._trim(draft, request)
        self._record_notes(draft, groups, request)
        return draft

    # ------------------------------------------------------------------
    def _fill(self, draft: DeckDraft, request: DeckRequest,
              seen: set[int]) -> None:
        """
        테마만으로 목표 장수에 못 미칠 때 **요청에 대응하는 근거가 있을 때만**
        보강한다.

        🔴 **Phase 5-D 가 이 함수의 기준을 바꿨다.** 그 전에는 장수가
        부족하다는 사실만으로 ``has_effect_from("HAND")`` 인 카드를 **카드
        ID 순서로** 집어넣고 전부 "패트랩 계열" 이라고 적었다. 실제로
        `/deck request:"오르페골 덱 짜줘"` 가 그렇게 8종을 넣었고, 그 8종의
        실제 효과는 세 가지로 갈렸다 (:mod:`deck.evidence` 의 표).

        무엇이 틀렸는가:

        1. ``has_effect_from("HAND")`` 는 **발동 위치 사실**이다. 특수 소환
           절차(``EFFECT_SPSUMMON_PROC``)도 참이 된다 — 8종 중 4종이 그랬다.
        2. 그 사실 하나로 **패트랩이라는 역할**을 주장했다. 측정한 것과
           주장한 것이 다르다.
        3. **장수 부족**이 카드 선정의 근거가 됐다. 장수가 부족하다는 것은
           몇 장이 필요한지를 알려 줄 뿐, **어떤 카드**인지는 알려 주지
           않는다.
        4. 🔴 그리고 이 저장소에는 "이 카드가 오르페골 덱에 맞는가" 를
           판정할 데이터가 **없다.** 없는 판정을 카드 ID 순서가 대신했다.

        지금 하는 일:

        * 사용자가 **패트랩 비중**을 목표로 줬을 때만 보강한다. 그때 후보는
          :attr:`~deck.evidence.HandTrapEvidence.NEGATION_FROM_HAND` 인
          카드뿐이고(실측 37장), 그 사실을 근거로 적는다.
        * 목표가 없으면 **보강하지 않는다.** 부족한 장수와 "고를 근거가
          없다" 를 ``notes`` 에 적고 멈춘다 —
          :mod:`deck.validator` 가 장수 위반을 그대로 보고한다.
        * 어느 경우에도 **테마 적합성을 주장하지 않는다.**
        """
        missing = _TARGET_MAIN - draft.main_count
        if missing <= 0:
            return

        if DeckGoal.HAND_TRAP_WEIGHT not in request.goals:
            #: 🔴 장수 부족만으로는 카드를 고르지 않는다.
            draft.notes.append(
                f"🔴 테마 카드만으로 메인이 {draft.main_count}장이고 목표"
                f" {_TARGET_MAIN}장에 {missing}장 부족합니다 —"
                f" **보강하지 않았습니다.** 이 저장소에는 어떤 카드가 이"
                f" 덱에 맞는지 판정할 데이터가 없고, 장수가 부족하다는"
                f" 사실은 '몇 장' 만 알려 줄 뿐 '어떤 카드' 인지는 알려"
                f" 주지 않습니다. 패트랩 비중을 목표로 지정하면 무효/무력화"
                f" 범주가 확인된 카드로만 보강합니다")
            return

        added = self._fill_with_negation_evidence(draft, request, seen)
        if added:
            draft.notes.append(
                f"'패트랩 비중 우선' 목표에 따라 메인 {_TARGET_MAIN}장까지"
                f" {added}종류를 보강했습니다 — 후보는 **패에서 발동 가능한"
                f" 효과에 무효/무력화 범주가 확인된** 카드뿐입니다."
                f" 🔴 후보 사이의 순서는 카드 ID 이고 그것은 **임의입니다**"
                f" — 어느 카드가 더 좋은지, 이 덱에 맞는지는 판정하지"
                f" 않았습니다")
        if draft.main_count < _TARGET_MAIN:
            draft.notes.append(
                f"🔴 보강 후에도 메인이 {draft.main_count}장입니다 —"
                f" 목표 {_TARGET_MAIN}장에 못 미칩니다. 근거가 있는 후보가"
                f" 더 없어서 멈췄습니다 (근거 없는 카드로 채우지 않습니다)")

    def _fill_with_negation_evidence(self, draft: DeckDraft,
                                     request: DeckRequest,
                                     seen: set[int]) -> int:
        """
        무효/무력화 근거가 확인된 카드로만 보강한다. 넣은 종류 수를 돌려준다.

        🔴 후보 자격은 :mod:`deck.evidence` 가 읽은 **사실**이고, 후보
        사이의 순서는 **임의**(카드 ID)다. 둘을 섞어 적지 않는다 — 자격은
        측정이고 순서는 임의다.
        """
        excluded = {name.strip() for name in request.excluded_names
                    if name.strip()}
        pool: list[Card] = []
        for card in self.repository.all_cards():
            if card.id in seen or card.is_extra_deck or not card.is_monster:
                continue
            if self._is_excluded(card, excluded):
                continue
            facts = hand_effect_facts(card)
            if facts.evidence is not HandTrapEvidence.NEGATION_FROM_HAND:
                continue
            pool.append(card)
        #: 결정론적 순서. 무작위로 고르면 같은 요청이 다른 덱을 낸다.
        pool.sort(key=lambda c: c.id)

        added = 0
        for card in pool:
            if draft.main_count >= _TARGET_MAIN:
                break
            take = min(3, _TARGET_MAIN - draft.main_count)
            if take <= 0:
                break
            seen.add(card.id)
            facts = hand_effect_facts(card)
            draft.main.append(DeckSlot(
                card_id=card.id,
                name=card.display_name(),
                copies=take,
                role=CardRole.HAND_TRAP,
                reason=(f"테마 외 보강 — {facts.describe_ko()}"
                        f" (범주 {', '.join(facts.categories)})."
                        f" 🔴 이 덱에 맞는지는 판정하지 않았습니다"),
                theme=None,
                evidence=RoleEvidence.LUA_EFFECT_CATEGORY,
            ))
            added += 1
        return added

    # ------------------------------------------------------------------
    @staticmethod
    def _is_excluded(card: Card, excluded: set[str]) -> bool:
        if not excluded:
            return False
        names = {card.display_name(), card.name, card.name_en, card.name_ko}
        return any(name and name in excluded for name in names)

    def _slot_for(self, card: Card, group: ThemeCandidates,
                  request: DeckRequest) -> DeckSlot:
        role, reason, evidence = self._classify(card, group)
        copies = self._copies_for(card, role, request)
        return DeckSlot(
            card_id=card.id,
            name=card.display_name(),
            copies=copies,
            role=role,
            reason=reason,
            theme=group.resolved_names[0] if group.resolved_names else None,
            evidence=evidence,
        )

    @staticmethod
    def _classify(card: Card, group: ThemeCandidates
                  ) -> tuple[CardRole, str, RoleEvidence]:
        """
        역할을 **측정 가능한 신호로만** 정하고, 그 근거를 함께 돌려준다.

        순서가 의미를 가진다 — 엑스트라 덱 여부가 가장 강한 신호이고,
        그다음이 패에서의 동작, 마지막이 카드 종류다.

        🔴 **Phase 5-D 가 패 관련 분기를 고쳤다.** 그 전에는
        ``card.has_effect_from("HAND")`` 하나로 :attr:`CardRole.HAND_TRAP`
        을 붙였다. 그 메서드는 ``SetRange`` 에 ``LOCATION_HAND`` 이 있는지만
        보므로 **특수 소환 절차와 지속 효과까지** 패트랩이 됐다. 지금은
        :mod:`deck.evidence` 가 읽은 사실을 쓰고, 근거 등급에 따라 **다른
        역할**을 붙인다 — 무효/무력화 범주가 확인된 것만
        :attr:`CardRole.HAND_TRAP` 이다.
        """
        theme = group.resolved_names[0] if group.resolved_names else group.term
        if card.is_extra_deck:
            return (CardRole.EXTRA_DECK,
                    f"{theme} 카드군이고 엑스트라 덱 카드입니다",
                    RoleEvidence.PRINTED_CARD_TYPE)
        if card.is_monster and card.can_self_special_summon_from_hand:
            return (CardRole.SELF_SPECIAL_SUMMON,
                    f"{theme} 카드군이고 패에서 자체 특수 소환 절차"
                    f"(EFFECT_SPSUMMON_PROC)가 확인됩니다",
                    RoleEvidence.LUA_EFFECT_BLOCK)
        if card.is_monster:
            facts = hand_effect_facts(card)
            if facts.evidence is HandTrapEvidence.NEGATION_FROM_HAND:
                return (CardRole.HAND_TRAP,
                        f"{theme} 카드군이고 {facts.describe_ko()}"
                        f" — 범주 {', '.join(facts.categories)}",
                        RoleEvidence.LUA_EFFECT_CATEGORY)
            if facts.evidence is HandTrapEvidence.ACTIVATABLE_ONLY:
                return (CardRole.HAND_ACTIVATABLE,
                        f"{theme} 카드군이고 {facts.describe_ko()}"
                        f" — 🔴 패트랩이라는 근거는 아닙니다",
                        RoleEvidence.LUA_EFFECT_BLOCK)
        if card.is_spell or card.is_trap:
            return (CardRole.THEME_CORE,
                    f"{theme} 카드군의 마법·함정입니다",
                    RoleEvidence.PRINTED_CARD_TYPE)
        if card.is_monster:
            return (CardRole.THEME_CORE,
                    f"{theme} 카드군의 몬스터입니다",
                    RoleEvidence.PRINTED_CARD_TYPE)
        return (CardRole.UNCLASSIFIED,
                f"{theme} 카드군이지만 분류 신호가 없습니다",
                RoleEvidence.NONE)

    @staticmethod
    def _copies_for(card: Card, role: CardRole,
                    request: DeckRequest) -> int:
        """
        매수를 정한다.

        🔴 **금지·제한 데이터가 이 저장소에 없다.** 그래서 여기서 정하는
        매수는 '규칙상 허용된 최대' 가 아니라 **이 빌더의 기본값**이다.
        :mod:`deck.validator` 가 그 사실을 "검증 불가" 로 적는다.
        """
        if role is CardRole.EXTRA_DECK:
            return 1
        copies = _DEFAULT_COPIES
        if DeckGoal.OPENING_STABILITY in request.goals and role in (
                CardRole.SELF_SPECIAL_SUMMON,):
            copies = 3
        #: 🔴 ``HAND_ACTIVATABLE`` 에는 가산하지 않는다. 패트랩 비중을
        #: 원한 사용자에게 "무엇을 하는지 모르는 카드" 를 더 넣어 주는
        #: 것이 되고, 그것은 요청에 대한 근거가 아니다.
        if DeckGoal.HAND_TRAP_WEIGHT in request.goals and role is (
                CardRole.HAND_TRAP):
            copies = 3
        return copies

    @staticmethod
    def _trim(draft: DeckDraft, request: DeckRequest) -> None:
        """
        목표 장수를 넘으면 **뒤에서 잘라낸다.**

        🔴 잘라낸 사실을 ``notes`` 에 적는다. 조용히 줄이면 "왜 이 카드가
        빠졌는가" 를 알 수 없다. 자르는 순서는 목표에 따라 다르다.
        """
        order = DeckBuilder._priority(request)
        draft.main.sort(key=lambda s: (order.get(s.role, 99), -s.copies,
                                       s.card_id))
        draft.extra.sort(key=lambda s: s.card_id)

        removed_main = DeckBuilder._cut(draft.main, _TARGET_MAIN)
        removed_extra = DeckBuilder._cut(draft.extra, _TARGET_EXTRA)
        if removed_main:
            draft.notes.append(
                f"메인 목표 {_TARGET_MAIN}장을 맞추려고 후보 "
                f"{removed_main}종류를 뺐습니다")
        if removed_extra:
            draft.notes.append(
                f"엑스트라 목표 {_TARGET_EXTRA}장을 맞추려고 후보 "
                f"{removed_extra}종류를 뺐습니다")

    @staticmethod
    def _priority(request: DeckRequest) -> dict[CardRole, int]:
        """목표가 자르는 순서를 바꾼다."""
        base = {
            CardRole.SELF_SPECIAL_SUMMON: 0,
            CardRole.THEME_CORE: 1,
            CardRole.HAND_TRAP: 2,
            #: 🔴 ``HAND_ACTIVATABLE`` 은 ``HAND_TRAP`` 보다 **뒤**다.
            #: 근거가 더 약하므로 자를 때 먼저 빠진다. ``.get(role, 99)`` 에
            #: 맡기지 않고 적는다 — 빠뜨리면 조용히 맨 뒤로 간다.
            CardRole.HAND_ACTIVATABLE: 3,
            CardRole.GENERIC_SPELL_TRAP: 4,
            CardRole.UNCLASSIFIED: 5,
        }
        if DeckGoal.HAND_TRAP_WEIGHT in request.goals:
            base[CardRole.HAND_TRAP] = 0
            base[CardRole.SELF_SPECIAL_SUMMON] = 1
        return base

    @staticmethod
    def _cut(slots: list[DeckSlot], target: int) -> int:
        """``target`` 장을 넘지 않을 때까지 뒤에서 뺀다. 뺀 종류 수를 돌려준다."""
        removed = 0
        while slots and sum(s.copies for s in slots) > target:
            slots.pop()
            removed += 1
        return removed

    @staticmethod
    def _record_notes(draft: DeckDraft, groups: list[ThemeCandidates],
                      request: DeckRequest) -> None:
        for group in groups:
            if group.resolved:
                draft.notes.append(
                    f"테마 '{group.term}' → 카드군 "
                    f"{', '.join(group.resolved_names)} "
                    f"(소속 카드 {len(group.cards):,}장 확인)")
            else:
                draft.notes.append(
                    f"🔴 테마 '{group.term}' 을 카드군으로 해석하지"
                    f" 못했습니다 — 이 테마에서 가져온 카드가 없습니다")
        if not request.goals:
            draft.notes.append(
                "구성 목표가 지정되지 않아 기본 순서로 구성했습니다")
