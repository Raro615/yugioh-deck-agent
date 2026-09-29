"""
Phase 2-AJ — 실제 카드 semantics 감사.

**이 파일은 기능을 늘리지 않는다.** 2-AD ~ 2-AI 가 만든 결과/조건/부분
/선택/무작위 구조가 **실제 유희왕 카드의 의미를 어디까지 정확하게 적는가**
를 재고, 갈리는 자리를 공식 자료로 닫는다.

두 가지를 고쳤다
----------------
1. **셔플이 든 해결을 트리거로 넘기면 죽었다** (🔴).
   ``timing_events()`` 가 ``ZoneShuffled`` 에서 ``TriggerError`` 를 던졌다.
   같은 판단을 하는 자리가 둘이었고 (:class:`EventReader` 와 이쪽) 한쪽만
   STRUCTURAL-74 가 적어 둔 결정("셔플은 ``UNIMPLEMENTED`` 로 남는다")을
   지키고 있었다. 이제 :func:`~engine.trigger.timing_for` 하나가 판단한다.

2. **리로드의 드로우 매수가 잘못된 칸을 가리키고 있었다** (STRUCTURAL-96).
   공식 재정을 받아 확인하고 ``AFFECTED_COUNT`` 로 고쳤다. 아래 §B 가
   근거다.

수를 세는 두 칸은 카드가 정한다
-------------------------------
==================  ============================  =====================
``ATTEMPTED_COUNT``  하려고 한 수                   교란작전 "원래의 패의 수"
``AFFECTED_COUNT``   실제로 그렇게 된 수             리로드 "덱에 넣은 매수"
==================  ============================  =====================

조작 종류가 정하지 않는다. 2-X 의 관문 · 2-AC 의 ``Shortfall`` · 2-AF 의
``Partial`` 과 **같은 결론**이다 — 카드가 적어 둔 것만 옮긴다.
"""

import json
import pathlib
import re
from collections import Counter

import pytest

from engine.chain import ChainResolutionStatus
from engine.effect.delta import CardDrawn, ZoneMoved, ZoneShuffled
from engine.effect.journal import EventJournal
from engine.effect.library import EFFECT_LIBRARY, RELOAD, entry_for
from engine.effect.operation import OperationKind
from engine.effect.target import CountKind
from engine.event_pipeline import EventReader
from engine.execution import (
    Comparison,
    DeclaredNumber,
    NumberDomain,
    NumericTest,
    OperationOutcome,
    OperationResult,
    ResultAvailability,
    ResultField,
    ResultRef,
    ExecutionValues,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerError,
    TriggerRegistry,
    timing_events,
    timing_for,
)
from engine.vocabulary import Zone

from tests.conftest import requires_official_db
from tests.engine.test_bulk_selection import MINE, THEIRS, reload_state, run_reload

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: "되돌린 수만큼 드로우" 계열. 스크립트가 전부 ``Duel.Draw(p,#g,…)`` 다.
TODECK_THEN_DRAW = (
    22589918,  # 리로드          — "덱에 넣은 매수만큼"
    52817046,  # 기억말소        — "덱에 넣은 매수만큼"
    38757297,  # 포톤 레오       — "덱에 넣은 매수만큼"
    77561728,  # 교란작전        — **"원래의 패의 수만큼"**
    85852291,  # 요술망치        — "덱에 넣은 매수만큼"
    83107873,  # 뇌조룡          — "덱으로 되돌린 수만큼"
    19489718,  # 마건총          — "덱으로 되돌린 수만큼"
)


@pytest.fixture
def state(repository):
    return reload_state(repository, hand=3)


# ======================================================================
# A. 🔴 셔플이 든 해결을 트리거로 넘길 수 있는가
# ======================================================================


def test_a_a_shuffle_no_longer_kills_the_trigger_hand_off(state):
    """
    **이것이 이번 Phase 의 BLOCKER 였다.**

    리로드는 등재된 실제 카드이고 정상적으로 해결된다. 그런데 그 해결을
    트리거 계층으로 넘기는 마지막 한 걸음에서 죽었다 —
    ``TriggerError: 이 변화를 시점으로 옮길 수 없습니다: ZoneShuffled``.

    효과가 실행되는 것과 **그 다음이 이어지는 것**은 다른 질문이다.
    """
    journal = EventJournal()
    _, resolved = run_reload(state, journal=journal)
    assert resolved.status is ChainResolutionStatus.RESOLVED

    events = timing_events(journal.events[-1])

    points = [event.point for event in events]
    assert points == [
        TimingPoint.CARD_MOVED,
        TimingPoint.CARD_MOVED,
        TimingPoint.CARD_MOVED,
        TimingPoint.UNIMPLEMENTED,  # 셔플
        TimingPoint.CARD_DRAWN,
        TimingPoint.CARD_DRAWN,
        TimingPoint.CARD_DRAWN,
        TimingPoint.EFFECT_RESOLVED,
    ]


def test_a_the_shuffle_keeps_its_place_instead_of_being_dropped(state):
    """
    **빠뜨리지 않는다.** 옮길 이름이 없다고 목록에서 지우면 "그 자리에
    아무 일도 없었다" 가 되고, 그것은 사실이 아니다.

    자리도 그대로다 — 되돌리기 **뒤**, 드로우 **앞**. 공식 보충이
    말하는 순서가 그것이다 (§B).
    """
    journal = EventJournal()
    run_reload(state, journal=journal)

    events = timing_events(journal.events[-1])
    shuffle = [e for e in events if e.point is TimingPoint.UNIMPLEMENTED]

    assert len(shuffle) == 1
    assert "ZoneShuffled" in shuffle[0].note
    assert events.index(shuffle[0]) == 3


def test_a_no_timing_name_was_invented_for_shuffling():
    """
    **이름을 지어내지 않았다** (STRUCTURAL-74 그대로).

    "덱을 섞었을 때" 라는 시점을 새로 만들지 않은 근거는 corpus 다:
    EDOPro 의 상수 목록에 ``EVENT_*SHUFFLE`` 이 **없고**, 그것에 반응하는
    카드 스크립트도 **없다**. 없는 사건에 이름을 붙이면 그 이름이 옳은지
    아무도 확인하지 않는다.
    """
    constants = (ROOT / "data/constants/constant.lua").read_text(errors="replace")
    assert not re.search(r"EVENT_\w*SHUFFLE", constants)

    reacting = [
        path.stem
        for path in ROOT.glob("c*.lua")
        if re.search(r"EVENT_\w*SHUFFLE", path.read_text(errors="replace"))
    ]
    assert reacting == []

    assert not any(point.value == "deck_shuffled" for point in TimingPoint)


def test_a_both_converters_now_give_the_same_answer(state):
    """
    **한 판단을 두 벌 두지 않는다.** 갈렸던 것이 원인이었다.

    :class:`EventReader` 는 처음부터 ``unimplemented`` 로 남기고 있었고,
    ``timing_events`` 만 죽었다. 이제 둘 다 :func:`timing_for` 를 부른다.
    """
    journal = EventJournal()
    _, resolved = run_reload(state, journal=journal)

    observed = EventReader(
        GameStateView.from_state(state, viewer=MINE)
    ).read(resolved.result, actor=MINE)
    collected = timing_events(journal.events[-1])

    # 마지막 하나(EFFECT_RESOLVED)는 변화가 아니라 사건이므로 관측 쪽에 없다.
    assert [event.point for event in observed] == [
        event.point for event in collected[:-1]
    ]


def test_a_from_delta_still_refuses_to_invent(state):
    """
    **너그러워진 것은 파이프라인이지 :meth:`TimingEvent.from_delta` 가
    아니다.** 저쪽은 여전히 모르는 변화에 예외를 던진다 — 그것이 "지어내지
    않는다" 를 지키는 자리다.
    """
    shuffled = ZoneShuffled(player=MINE, zone=Zone.DECK, size=20, draw=0)

    with pytest.raises(TriggerError):
        TimingEvent.from_delta(shuffled)

    assert timing_for(shuffled).point is TimingPoint.UNIMPLEMENTED


def test_a_a_shuffle_produces_no_candidates_and_no_blind_spot(state):
    """
    셔플 사건으로는 후보가 나오지 않는다. **그것이 맞는 답이다** — 셔플에
    반응하는 카드가 없으므로 "못 봤다" 도 남기지 않는다.
    """
    journal = EventJournal()
    run_reload(state, journal=journal)
    shuffle = timing_events(journal.events[-1])[3]

    collector = TriggerCollector(
        GameStateView.from_state(state, viewer=MINE), TriggerRegistry()
    )
    collection = collector.collect(shuffle)

    assert collection.candidates == ()
    assert collection.unchecked == ()


# ======================================================================
# B. STRUCTURAL-96 — 공식 재정이 답한 자리
# ======================================================================


def ruling_set(cid: int) -> dict:
    return json.loads((ROOT / f"data/rulings/ocg/{cid}.json").read_text())


def test_b_the_official_database_answers_which_count_the_card_means():
    """
    **스크립트와 공식 텍스트가 갈렸고, 공식 재정이 답했다.**

    ``c22589918.lua`` 는 ``Duel.Draw(p,#g,…)`` — 넣으려 한 수.
    공식 텍스트는 "デッキに加えた枚数分" — 실제로 들어간 수.

    OCG-QA-11919 가 같은 계열("デッキに戻した数だけドロー")에서 직접
    답한다: 덱에 **돌아가지 않은** 카드는 그 수에 들어가지 않는다.
    """
    data = ruling_set(5849)

    assert data["card_id"] == RELOAD
    assert data["name_ja"] == "リロード"
    assert data["card_text_ja"] == (
        "自分の手札を全てデッキに加えてシャッフルする。"
        "その後、デッキに加えた枚数分のカードをドローする。"
    )

    answers = [r["answer_original"] for r in data["rulings"]]
    counted = [a for a in answers if "デッキに戻した数" in a]
    assert counted, "수를 세는 방법을 말한 재정이 없습니다."
    assert "含まれません" in counted[0]


def test_b_every_ruling_we_read_is_from_the_official_database():
    """
    **출처를 확인한다.** 나무위키 · 커뮤니티 · 모델의 기억이 아니다.
    """
    for cid in (5849, 5546):
        data = ruling_set(cid)
        assert data["source_url"].startswith(
            "https://www.db.yugioh-card.com/yugiohdb/"
        )
        for record in data["rulings"] + [data["supplement"]]:
            if record is None:
                continue
            assert record["provenance"]["source"] == "konami_ocg_database"
            assert record["provenance"]["authority"] == "official"


def test_b_the_identity_is_still_unverified_and_says_so():
    """
    **권위가 둘로 갈린다는 점을 뭉개지 않는다.** 재정 내용은 공식이지만
    passcode ↔ cid 링크는 아직 검증되지 않았다. 그래서 수집 결과는
    ``authoritative`` 가 거짓이다.

    이름과 텍스트가 맞는다는 것은 **내용으로** 확인했고 (위 시험),
    그것은 링크 검증과 다른 일이다.
    """
    for cid in (5849, 5546):
        assert ruling_set(cid)["identity_status"] == "unverified"


def test_b_reload_now_points_at_the_affected_count():
    draw = entry_for(EffectRef(RELOAD, 0)).definition.operations[2]

    assert draw.count.kind is CountKind.FROM_RESULT
    assert draw.count.result == ResultRef(0, ResultField.AFFECTED_COUNT)


def test_b_the_official_supplement_confirms_the_three_step_shape():
    """
    **한 덩어리가 아니라 차례다.** 그래서 조작 셋 + ``ResultRef`` 하나로
    적는 지금 모양이 맞다.

        "『自分の手札を全てデッキに加えてシャッフルする』処理を行います。
         その後、『デッキに加えた枚数分のカードをドローする』処理を行います。
         （これらの処理は同時に行われません。）"
    """
    supplement = ruling_set(5849)["supplement"]["text_original"]

    assert "これらの処理は同時に行われません" in supplement
    assert "デッキが０枚の状況でも発動できます" in supplement

    kinds = [op.kind for op in entry_for(EffectRef(RELOAD, 0)).definition.operations]
    assert kinds == [
        OperationKind.RETURN_TO_DECK,
        OperationKind.SHUFFLE,
        OperationKind.DRAW,
    ]


def test_b_the_same_family_does_not_share_one_count(repository):
    """
    **어느 칸인지는 카드가 정한다.** 계열이 정하지 않는다.

    일곱 장 모두 스크립트는 ``Duel.Draw(p,#g,…)`` 로 같은데, 공식 텍스트는
    여섯 장이 "덱에 넣은/되돌린 수"(실제로 된 수)이고 교란작전 한 장만
    **"원래의 패의 수"**(하려고 한 수)다.

    조작 종류(``RETURN_TO_DECK``)로 기본값을 정했다면 그 한 장이 조용히
    틀렸을 것이다.
    """
    affected, attempted = [], []
    for card_id in TODECK_THEN_DRAW:
        text = repository.get(card_id).desc
        assert "드로우" in text
        (attempted if "원래의 패의 수" in text else affected).append(card_id)

    assert attempted == [77561728]
    assert len(affected) == 6

    japanese = ruling_set(5546)["card_text_ja"]
    assert "元の手札の数だけ" in japanese


def test_b_the_scripts_all_take_the_same_shortcut():
    """
    일곱 장 전부 ``#g`` 다. **스크립트는 구현이지 의미가 아니다** —
    이 카드들에서 두 수가 언제나 같아서 통하는 지름길이다.
    """
    for card_id in TODECK_THEN_DRAW:
        text = (ROOT / f"c{card_id}.lua").read_text(errors="replace")
        assert re.search(r"Duel\.Draw\([^,]+,\s*#\w+\s*,", text), card_id


# ======================================================================
# C. ResultRef / OperationResult 가 실제로 표현하는 것 (§6 Q1)
# ======================================================================


def test_c_the_two_counts_are_separate_questions():
    """세 장을 고르고 둘만 됐다면 시도는 3, 처리는 2다."""
    result = OperationResult(0, affected_count=2, attempted_count=3)

    assert result.value_of(ResultField.ATTEMPTED_COUNT) == 3
    assert result.value_of(ResultField.AFFECTED_COUNT) == 2
    assert result.is_partial
    assert not result.is_complete


def test_c_success_is_not_a_number():
    """성패는 수가 아니므로 장수를 묻는 자리에 쓸 수 없다."""
    with pytest.raises(KeyError):
        OperationResult(0, affected_count=2).value_of(ResultField.SUCCEEDED)


def test_c_not_yet_is_not_unknown_and_not_zero():
    """
    §9 — 넷을 뭉개지 않는다. 아직 닿지 않았다 · 하지 않았다 · 그 칸이 없다
    · 있다.
    """
    values = ExecutionValues()
    assert values.look_up(ResultRef(0)).availability is ResultAvailability.NOT_YET

    skipped = values.with_result(
        OperationResult(0, outcome=OperationOutcome.NOT_APPLIED)
    )
    assert (
        skipped.look_up(ResultRef(0)).availability is ResultAvailability.NOT_APPLIED
    )

    no_count = values.with_result(OperationResult(0, affected_count=None))
    assert (
        no_count.look_up(ResultRef(0)).availability is ResultAvailability.NO_FIELD
    )

    for lookup in (
        values.look_up(ResultRef(0)),
        skipped.look_up(ResultRef(0)),
        no_count.look_up(ResultRef(0)),
    ):
        assert lookup.value is None  # **0 이 아니다**


@pytest.mark.real_card
def test_c_the_dependency_really_carries_a_number_between_operations(repository):
    """
    §6 Q1 의 답. 실제 카드에서 앞 결과가 뒤의 수가 된다 — 고정 숫자도,
    "마지막 결과" 같은 암묵 참조도 아니다.
    """
    for hand in (1, 3, 5):
        state = reload_state(repository, hand=hand)
        _, resolved = run_reload(state)

        moved = [d for d in resolved.deltas if isinstance(d, ZoneMoved)]
        drawn = [d for d in resolved.deltas if isinstance(d, CardDrawn)]
        assert len(moved) == hand
        assert len(drawn) == len(moved)


@pytest.mark.real_card
def test_c_attempted_and_affected_agree_for_every_registered_card(repository):
    """
    **지금은 두 수가 언제나 같다.** 실행기가 둘을 가르는 길은
    ``Partial.AS_MANY_AS_POSSIBLE`` 하나뿐인데 (``_plan_card_operation`` 의
    ``refused``), 그렇게 적힌 실제 카드가 아직 0장이기 때문이다.

    그래서 리로드에서 ``ATTEMPTED`` 를 ``AFFECTED`` 로 고친 것은 **지금의
    동작을 바꾸지 않는다.** 고친 이유는 동작이 아니라 **주장**이 틀렸기
    때문이다 — 언젠가 갈릴 때 조용히 틀리지 않도록.
    """
    from engine.effect.operation import Partial

    for entry in EFFECT_LIBRARY:
        for operation in entry.definition.operations:
            assert getattr(operation, "partial", Partial.ALL_OR_NOTHING) is (
                Partial.ALL_OR_NOTHING
            ), entry.card_id

    state = reload_state(repository, hand=3)
    _, resolved = run_reload(state)
    assert resolved.status is ChainResolutionStatus.RESOLVED


# ======================================================================
# D. corpus — 현재 구조가 어디까지 적는가 (§7)
# ======================================================================


def scan(pattern: str) -> list[int]:
    rx = re.compile(pattern)
    return sorted(
        int(path.stem[1:])
        for path in ROOT.glob("c*.lua")
        if rx.search(path.read_text(errors="replace"))
    )


def test_d_reading_a_previous_result_is_a_real_and_common_shape():
    """
    앞 결과를 뒤가 읽는 모양. **표현 가능하다** — ``ResultRef`` 가 그것이다.

    ::

        반환값을 0 과 견준다      1,433   → OperationGuard + NumericTest
        GetOperatedGroup           311    → STRUCTURAL-87 (옮기지 않기로 함)
        반환값을 변수로 받는다      146    → ResultRef(AFFECTED_COUNT)
    """
    gate = scan(
        r"Duel\.(Destroy|SendtoGrave|SendtoDeck|SendtoHand|Remove|Release|Draw"
        r"|Discard(?:Hand|Deck)?)\([^\n]*?\)\s*(>|==|~=|>=)\s*0"
    )
    operated = scan(r"Duel\.GetOperatedGroup\(\)")
    captured = scan(
        r"local\s+\w+\s*=\s*Duel\.(Destroy|SendtoGrave|SendtoDeck|SendtoHand"
        r"|Remove|Release|Draw|Discard(?:Hand|Deck)?)\("
    )

    assert len(gate) == 1433
    assert len(operated) == 311
    assert len(captured) == 146

    # 1,433 곳이 묻는 것은 "하나라도 됐는가" 이고, 그 조건은 이미 적을 수
    # 있다. 막는 것은 조건 계층이 아니라 **조작 자체**다 (ADR-006).
    assert NumericTest.any_at_all() == NumericTest(Comparison.AT_LEAST, 1)


def test_d_comparing_two_results_is_still_not_expressible():
    """
    STRUCTURAL-93 — ``NumericTest`` 의 오른쪽이 **상수뿐**이다.

    자리가 하나 더 늘었다. 마건총(19489718)이 "전부 도착했는가" 를 직접
    검사한다::

        Duel.SendtoDeck(g,tp,SEQ_DECKBOTTOM,REASON_EFFECT)>0
        and g:FilterCount(Card.IsLocation,nil,LOCATION_DECK)==#g

    그 한 곳이 묻는 것은 ``affected == attempted`` 이고,
    :attr:`OperationResult.is_complete` 가 **이미 답한다.** 그래서 연산자를
    늘리지 않는다 — 실제로 필요한 것은 "값끼리 견주기" 가 아니라 "완전히
    됐는가" 였다.
    """
    complete_sites = scan(r"FilterCount\(Card\.IsLocation,[^)]*\)\s*==\s*#\w+")
    assert complete_sites == [19489718]

    assert OperationResult(0, affected_count=3, attempted_count=3).is_complete
    assert not OperationResult(0, affected_count=2, attempted_count=3).is_complete

    with pytest.raises(TypeError):
        NumericTest(Comparison.AT_LEAST, ResultRef(0))  # 오른쪽은 int 뿐


def test_d_declared_values_are_not_all_numbers():
    """
    **STRUCTURAL-97 (신규).** ``DeclaredNumber`` 는 수만 담는다
    (``NumberDomain.values: tuple[int, ...]``). 그런데 실제 카드는 수가
    아닌 것도 선언한다.

    ::

        AnnounceNumber        60  ┐
        AnnounceLevel         27  ├ 수  — 지금 구조로 적을 수 있다 (106)
        AnnounceNumberRange   19  ┘
        AnnounceCard          32  ┐
        AnnounceAttribute     29  ├ 수가 아니다 — 적을 수 없다 (92)
        AnnounceRace          20  │
        AnnounceAnotherAttr…   7  │
        AnnounceAnotherRace    4  ┘
        AnnounceCoin           1    동전 (STRUCTURAL-74 계열, 별개)

    "카드명을 선언한다" 를 수로 적을 방법이 없다. coverage 부족이 아니라
    **담는 것이 다른 것**이다.
    """
    counts: Counter = Counter()
    for path in ROOT.glob("c*.lua"):
        for match in re.finditer(
            r"Duel\.Announce(\w+)\(", path.read_text(errors="replace")
        ):
            counts[match.group(1)] += 1

    numeric = counts["Number"] + counts["Level"] + counts["NumberRange"]
    other = (
        counts["Card"]
        + counts["Attribute"]
        + counts["Race"]
        + counts["AnotherAttribute"]
        + counts["AnotherRace"]
    )
    assert numeric == 106
    assert other == 92

    # 담는 것이 수라는 것은 **타입이 말한다.** 선언된 값도 수다.
    assert NumberDomain.__annotations__["values"] == "tuple[int, ...]"
    assert DeclaredNumber.__annotations__["value"] == "int"

    # 수를 담는 쪽은 멀쩡히 돌고, 수가 아닌 것을 담을 자리가 **없다.**
    assert NumberDomain((1, 2, 3)).values == (1, 2, 3)
    assert not hasattr(NumberDomain((1,)), "names")


# ======================================================================
# E. 판정 계층의 불변 (§9 · §11)
# ======================================================================


@pytest.mark.real_card
def test_e_the_same_seed_gives_the_same_resolution(repository):
    first = reload_state(repository, seed=3)
    second = reload_state(repository, seed=3)

    run_reload(first)
    run_reload(second)

    assert first.state_hash() == second.state_hash()


@pytest.mark.real_card
def test_e_a_clone_does_not_share_the_outcome(repository):
    """
    ``clone()`` 은 난수원까지 복제한다 (``project()`` 와 다른 점이다).
    복제본에서 해결해도 원본은 한 글자도 바뀌지 않는다.
    """
    original = reload_state(repository, seed=3)
    before = original.state_hash()
    copy = original.clone()

    run_reload(copy)

    assert original.state_hash() == before
    assert copy.state_hash() != before


@pytest.mark.real_card
def test_e_resolving_reveals_nothing_new_to_the_opponent(repository):
    """
    §10 — 되돌린 카드도 뽑은 카드도 **상대에게 정체가 보이지 않는다.**
    사건이 일어났다는 사실과 카드가 무엇인가는 다른 것이다.
    """
    state = reload_state(repository, hand=3)
    _, resolved = run_reload(state)

    opponent = GameStateView.from_state(state, viewer=THEIRS)
    for card in opponent.player(MINE).hand.cards:
        assert card is None or card.card_id is None

    events = EventReader(opponent).read(resolved.result, actor=MINE)
    assert len(events) == 7
