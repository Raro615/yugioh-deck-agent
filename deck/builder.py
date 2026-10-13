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
쓴다 — 공식 setcode 소속, ``is_extra_deck``, 패에서 발동하는 효과의 존재
여부. "이 카드는 강하다" 같은 판단은 하지 않는다.

🔴 **검색은 기존 것을 쓴다.** 카드군 해석은
:meth:`~core.card_repository.CardRepository.resolve_archetype`, 필터 검색은
:class:`~core.card_search.CardSearchEngine` 이다. 새 검색을 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.card_model import Card
from deck.model import CardRole, DeckDraft, DeckSlot
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
        테마만으로 목표 장수에 못 미치면 **측정 가능한 신호로** 보강한다.

        🔴 **메타 평가를 하지 않는다.** "이 카드가 좋다" 는 판단의 근거가
        이 저장소에 없다. 그래서 고르는 기준은 관측 가능한 것 하나다 —
        ``has_effect_from('HAND')``, 즉 **패에서 발동할 수 있는 효과를 가진
        몬스터**인지. 사용자가 '패트랩 비중' 이나 '초동 안정성' 을 목표로
        줬을 때 그 목표에 **대응하는 신호**이기도 하다.

        🔴 그리고 보강했다는 사실과 그 기준을 ``notes`` 에 적는다. 적지
        않으면 사용자가 테마 카드와 보강 카드를 구별할 수 없다.
        """
        missing = _TARGET_MAIN - draft.main_count
        if missing <= 0:
            return

        excluded = {name.strip() for name in request.excluded_names
                    if name.strip()}
        pool: list[Card] = []
        for card in self.repository.all_cards():
            if card.id in seen or card.is_extra_deck or not card.is_monster:
                continue
            if self._is_excluded(card, excluded):
                continue
            if not card.has_effect_from("HAND"):
                continue
            pool.append(card)
        #: 🔴 결정론적 순서. 무작위로 고르면 같은 요청이 다른 덱을 낸다.
        pool.sort(key=lambda c: c.id)

        copies = 3 if DeckGoal.HAND_TRAP_WEIGHT in request.goals else 2
        added = 0
        for card in pool:
            if draft.main_count >= _TARGET_MAIN:
                break
            take = min(copies, _TARGET_MAIN - draft.main_count)
            if take <= 0:
                break
            seen.add(card.id)
            draft.main.append(DeckSlot(
                card_id=card.id,
                name=card.display_name(),
                copies=take,
                role=CardRole.HAND_TRAP,
                reason=("테마 외 보강 — 패에서 발동 가능한 효과가"
                        " 확인됩니다"),
                theme=None,
            ))
            added += 1

        if added:
            draft.notes.append(
                f"테마 카드만으로 메인 {_TARGET_MAIN}장에 "
                f"{missing}장 부족해 보강했습니다 — 기준은 '패에서 발동"
                f" 가능한 효과를 가진 몬스터' 하나이고 카드 ID 순서입니다."
                f" 🔴 메타 평가가 아닙니다")
        if draft.main_count < _TARGET_MAIN:
            draft.notes.append(
                f"🔴 보강 후에도 메인이 {draft.main_count}장입니다 —"
                f" 목표 {_TARGET_MAIN}장에 못 미칩니다")

    # ------------------------------------------------------------------
    @staticmethod
    def _is_excluded(card: Card, excluded: set[str]) -> bool:
        if not excluded:
            return False
        names = {card.display_name(), card.name, card.name_en, card.name_ko}
        return any(name and name in excluded for name in names)

    def _slot_for(self, card: Card, group: ThemeCandidates,
                  request: DeckRequest) -> DeckSlot:
        role, reason = self._classify(card, group)
        copies = self._copies_for(card, role, request)
        return DeckSlot(
            card_id=card.id,
            name=card.display_name(),
            copies=copies,
            role=role,
            reason=reason,
            theme=group.resolved_names[0] if group.resolved_names else None,
        )

    @staticmethod
    def _classify(card: Card, group: ThemeCandidates) -> tuple[CardRole, str]:
        """
        역할을 **측정 가능한 신호로만** 정한다.

        순서가 의미를 가진다 — 엑스트라 덱 여부가 가장 강한 신호이고,
        그다음이 패에서의 동작, 마지막이 카드 종류다.
        """
        theme = group.resolved_names[0] if group.resolved_names else group.term
        if card.is_extra_deck:
            return (CardRole.EXTRA_DECK,
                    f"{theme} 카드군이고 엑스트라 덱 카드입니다")
        if card.is_monster and card.can_self_special_summon_from_hand:
            return (CardRole.SELF_SPECIAL_SUMMON,
                    f"{theme} 카드군이고 패에서 자체 특수 소환 절차"
                    f"(EFFECT_SPSUMMON_PROC)가 확인됩니다")
        if card.is_monster and card.has_effect_from("HAND"):
            return (CardRole.HAND_TRAP,
                    f"{theme} 카드군이고 패에서 발동 가능한 효과가"
                    f" 확인됩니다")
        if card.is_spell or card.is_trap:
            return (CardRole.THEME_CORE,
                    f"{theme} 카드군의 마법·함정입니다")
        if card.is_monster:
            return (CardRole.THEME_CORE,
                    f"{theme} 카드군의 몬스터입니다")
        return (CardRole.UNCLASSIFIED,
                f"{theme} 카드군이지만 분류 신호가 없습니다")

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
            CardRole.GENERIC_SPELL_TRAP: 3,
            CardRole.UNCLASSIFIED: 4,
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
