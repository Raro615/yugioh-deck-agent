"""
Phase 6-AA — **강제 · 임의의 근거와 발동 기회의 수명.**

6-Z 는 유발 발동을 정상 경로에 올렸지만 셋을 남겼다.

    1. 강제 · 임의가 전부 ``UNKNOWN`` 이었고, ``_trigger_actions`` 가 그
       셋을 **한 덩어리로** 내놓아 발동 여부를 전부 고르는 쪽에 맡겼다.
       즉 **모름을 임의로 승격**시켰다.
    2. 기회가 **만료되지 않았다.** 기록 전체를 매번 다시 펼치므로 메인
       페이즈 1 의 소환 유발이 같은 턴의 BATTLE · MAIN2 · END 에서,
       다음 턴의 DRAW · STANDBY 에서까지 관문을 통과했다 (실측).
    3. 소비 단위가 ``(사건, 효과)`` 둘이었다. ``EffectRef`` 는 **개체를
       가르지 않으므로** 한 사건이 같은 이름의 카드 두 장을 유발시킬 때 한
       장의 발동이 다른 장의 기회까지 닫는다.

이 파일이 재는 것은 그 셋이다. 네 군으로 나눈다.

================  ==================================================
A. 근거            강제 · 임의 · 모름을 무엇으로 판정하는가
B. 처리            판정에 따라 ``legal_actions`` 가 무엇을 하는가
C. 수명            기회가 언제 열리고 언제 닫히는가
D. 소비 단위        한 기회를 쓰는 것이 무엇을 닫는가
================  ==================================================

🔴 **실제 카드와 합성 구조 시험을 가른다.** 실행 등재된 유발 효과는 기르수
하나이고 (6-Z ``test_c09``) 그것은 **임의**다. 그래서 **강제**의 처리는
실제 카드로 돌릴 수 없고, 근거만 바꿔 끼운 합성 제안으로 구조를 센다
(``_forced_source``). 그 시험들은 이름에 ``synthetic`` 을 달고, 실제 카드에서
실행됐다고 적지 않는다.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.choice import DeclineChoice, FirstPermittedChoice
from engine.action import PlayerAction, PlayerActionKind
from engine.duel import (
    TRIGGER_HISTORY_MISSING,
    TRIGGER_REQUIREMENT_MISSING,
    Duel,
)
from engine.ids import EffectRef
from engine.trigger import TriggerRequirement
from engine.trigger_compiler import (
    MANDATORY_DECLARATION_TYPE,
    OPTIONAL_DECLARATION_TYPE,
    TEXT_MANDATORY,
    TEXT_OPTIONAL,
    requirement_from,
)
from engine.vocabulary import Phase, Zone

from integration.autonomy import PolicyChooser, TriggerSource, trigger_offers
from tests.conftest import requires_official_db
from tests.engine.test_trigger_normal_path_integration import (
    GIRSU,
    GROWTH,
    MINE,
    THEIRS,
    _board,
    _settle,
    _summon,
    _trigger_action,
)


# ======================================================================
# 공용 도구
# ======================================================================
class _ReplacedRequirement:
    """
    🔴 **합성 — 근거 하나만 바꿔 끼운다.**

    실제 ``TriggerSource`` 를 그대로 쓰고, 돌려받은 제안의
    ``requirement`` 만 갈아 끼운다. 사건 · 사건 번호 · 카드 개체 · 효과는
    **전부 실제 값**이고, 관문도 엔진의 것 그대로다.

    왜 이것이 필요한가: 실행 등재된 유발 효과가 하나이고 그것이 임의이므로
    (``test_a05``) **강제의 처리**를 실제 카드로는 밟을 수 없다. 허가 ·
    비용 · 최종 상태를 우회 주입하는 것이 **아니다** — 바꾸는 것은 이
    Phase 가 새로 판정하기 시작한 그 값 하나다.
    """

    def __init__(self, repository, requirement: TriggerRequirement):
        self._inner = TriggerSource(repository)
        self._requirement = requirement

    def offers(self, duel, seat: int):
        return tuple(
            dataclasses.replace(offer, requirement=self._requirement)
            for offer in self._inner.offers(duel, seat)
        )


def _wired(setup, repository, requirement: TriggerRequirement):
    """그 판의 유발 원천을 ``requirement`` 로 갈아 끼운 사본."""
    return dataclasses.replace(
        setup.duel, triggers=_ReplacedRequirement(repository, requirement)
    )


def _decline_window(duel, seat: int = MINE):
    """
    열린 **임의** 유발 처리 기회를 ``PASS`` 한 걸음으로 지난다 (보완4).

    돌려주는 것은 밟은 걸음 수다. 열린 기회가 없으면 0 이다.

    🔴 **왜 이 도구가 생겼는가.** Phase 6-AB 보완4 가 공식 Fast Effect
    Timing 도표를 근거로 *"유발 기회가 열린 자리에서는 통상 행동 · 페이즈
    이동을 할 수 없다"* 를 구현했다 (*"Many actions can ONLY be performed
    when the game state is open"*). 그래서 **다른 행동으로 기회를 지나는**
    방식이 더 이상 성립하지 않고, 지나는 방법은 ``PASS`` 다. 판이 다시
    열리는 조건도 그 도표가 적는다 — 양쪽이 넘기고 체인이 없을 때다.

    🔴 **강제 묶음은 지나갈 수 없다** — 그 자리에는 ``PASS`` 가 오르지
    않으므로 이 함수가 0 을 돌려준다. 그것이 ``test_b03`` 이 재는 구분이다.
    """
    steps = 0
    while steps < 4:
        legal = duel.legal_actions(duel.to_act)
        passing = [
            action
            for action in legal.allowed
            if action.kind is PlayerActionKind.PASS
        ]
        if not passing or duel.priority.is_open:
            break
        assert duel.apply(passing[0]).accepted is True
        steps += 1
    return steps


def _end_phase(duel):
    """``END_PHASE`` 를 ``legal_actions`` 를 지나 적용한다. 없으면 ``None``."""
    legal = duel.legal_actions(duel.to_act)
    ends = [a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE]
    if not ends:
        return None
    step = duel.apply(ends[0])
    duel.advance()
    return step


# ======================================================================
# A. 근거 — 무엇으로 판정하는가
# ======================================================================


def test_a01_two_sources_must_agree():
    """
    🔴 **두 근거가 같은 쪽을 말할 때만 판정한다.**

    근거 1 은 **카드 텍스트**(답을 만드는 쪽), 근거 2 는 **Lua 선언**
    (어긋날 때 판정을 거두는 쪽). 표 전체를 센다.
    """
    O, F = OPTIONAL_DECLARATION_TYPE, MANDATORY_DECLARATION_TYPE
    assert requirement_from([O], TEXT_OPTIONAL) is TriggerRequirement.OPTIONAL
    assert requirement_from([F], TEXT_MANDATORY) is TriggerRequirement.MANDATORY
    #: 🔴 어긋나면 **거둔다** — Phase 3-F-26 이 센 반례들이 여기로 온다.
    assert requirement_from([F], TEXT_OPTIONAL) is TriggerRequirement.UNKNOWN
    assert requirement_from([O], TEXT_MANDATORY) is TriggerRequirement.UNKNOWN
    #: 텍스트가 말하지 않으면 거둔다.
    assert requirement_from([O], None) is TriggerRequirement.UNKNOWN
    assert requirement_from([F], None) is TriggerRequirement.UNKNOWN
    #: 한 블록이 둘을 함께 선언했으면 거둔다 (선언이 자기 안에서 어긋난다).
    assert requirement_from([O, F], TEXT_OPTIONAL) is TriggerRequirement.UNKNOWN
    assert requirement_from([O, F], TEXT_MANDATORY) is TriggerRequirement.UNKNOWN


def test_a02_the_declaration_alone_never_decides():
    """
    🔴 **접미사는 혼자 답을 만들지 못한다** — Phase 3-F-26 을 뒤집지 않았다.

    그 Phase 가 접미사의 뜻풀이를 **근거 없음**으로 기록했다 (공식 자료에
    그 이름이 0회). 그래서 접미사만 주고 텍스트를 주지 않으면 어느 쪽도
    나오지 않는다 — 접미사의 역할은 **좁히는 것**뿐이고, 그 뜻이 틀렸더라도
    이 판정은 넓어지지 않는다.
    """
    for declared in (
        [OPTIONAL_DECLARATION_TYPE],
        [MANDATORY_DECLARATION_TYPE],
        ["SINGLE", OPTIONAL_DECLARATION_TYPE],
        ["FIELD", MANDATORY_DECLARATION_TYPE],
    ):
        assert requirement_from(declared, None) is TriggerRequirement.UNKNOWN


def test_a03_the_rulebook_does_not_state_the_distinction():
    """
    🔴 **공식 규칙에 이 구분이 없다** — 그래서 근거가 카드 텍스트 하나다.

    룰북의 효과 분류표는 유발 효과의 **발동 시점**만 적는다. 그 사실을
    구조화 데이터에서 직접 읽어 고정한다 — "없다" 를 말로만 적지 않는다.
    """
    import io
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    data = json.load(
        io.open(
            root / "data/rules/structured/sd-rulebook-en-v10.json",
            encoding="utf-8",
        )
    )
    trigger = next(
        row for row in data["effect_types"] if row["name"] == "Trigger Effect"
    )
    assert trigger["activation_timing"]
    #: 🔴 강제 · 임의를 적는 칸이 **없다.**
    assert not [k for k in trigger if "mandator" in k or "option" in k]
    for row in data["effect_types"]:
        blob = json.dumps(row, ensure_ascii=False).lower()
        assert "mandatory" not in blob, row["name"]


@pytest.mark.real_card
@requires_official_db
def test_a04_the_card_text_is_what_decides(repository):
    """
    🔴 **근거는 카드 텍스트다 — 카드 ID 가 아니다.**

    기르수가 통과하는 이유는 그 카드의 텍스트가 「발동할 수 있다」로 적었기
    때문이고, 같은 모양의 텍스트를 가진 카드는 전부 같은 답을 받는다.
    """
    card = repository.get(GIRSU)
    assert card.activation_permission_text == "optional"
    assert "발동할 수 있다" in card.desc

    #: 🔴 **프로덕션 코드에 이 카드 번호가 없다.**
    import io
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    for rel in (
        "core/card_model.py",
        "engine/trigger_compiler.py",
        "engine/duel.py",
        "integration/trigger_registry.py",
    ):
        source = io.open(root / rel, encoding="utf-8").read()
        assert str(GIRSU) not in source, rel


@pytest.mark.real_card
@requires_official_db
def test_a05_the_corpus_splits_into_three_measured_groups(repository):
    """
    실측 — 유발 선언 블록 **8,052개**가 셋으로 갈린다.

    ::

        OPTIONAL    5,176   텍스트=임의만 × TRIGGER_O
        MANDATORY     514   텍스트=강제만 × TRIGGER_F
        UNKNOWN     2,362   (미기재 1,517 · 혼재 766 · 어긋남 79)

    🔴 **수가 늘거나 줄면 여기서 깨진다.** 그것이 이 숫자를 적어 두는
    이유다 — 근거가 넓어졌는지 좁아졌는지가 조용히 지나가지 않는다.
    """
    from engine.trigger_compiler import TRIGGER_DECLARATION_TYPES

    tally = {"OPTIONAL": 0, "MANDATORY": 0, "UNKNOWN": 0}
    for card in repository.all_cards():
        if card.script is None:
            continue
        says = card.activation_permission_text
        for spec in card.script.effects:
            kinds = TRIGGER_DECLARATION_TYPES & set(spec.effect_types)
            if not kinds:
                continue
            tally[requirement_from(spec.effect_types, says).name] += 1

    assert sum(tally.values()) == 8052, tally
    assert tally["OPTIONAL"] == 5176, tally
    assert tally["MANDATORY"] == 514, tally
    assert tally["UNKNOWN"] == 2362, tally
    #: 🔴 **모름이 가장 큰 쪽은 아니지만 사라지지도 않았다** — 29%다.
    assert 0.25 < tally["UNKNOWN"] / 8052 < 0.35


@pytest.mark.real_card
@requires_official_db
def test_a06_the_judgement_is_per_effect_not_per_card(repository):
    """
    🔴 **효과 단위다.** 한 카드의 두 블록이 **다른 답**을 받을 수 있다.

    선언이 블록마다 다르기 때문이다 — 텍스트가 임의만 말하는 카드에
    ``TRIGGER_O`` 블록과 ``TRIGGER_F`` 블록이 함께 있으면 앞은 임의,
    뒤는 모름이다. corpus 에 그런 카드가 실제로 있다는 것을 센다.
    """
    from engine.trigger_compiler import TRIGGER_DECLARATION_TYPES

    split = []
    for card in repository.all_cards():
        if card.script is None:
            continue
        says = card.activation_permission_text
        answers = {
            requirement_from(spec.effect_types, says)
            for spec in card.script.effects
            if TRIGGER_DECLARATION_TYPES & set(spec.effect_types)
        }
        if len(answers) > 1:
            split.append((card.id, sorted(a.value for a in answers)))
    assert split, "한 카드 안에서 답이 갈리는 카드가 없으면 이 시험은 비어 있다"
    #: 🔴 카드 전체를 한 분류로 뭉갰다면 이 수가 0이 된다.
    assert len(split) >= 10, len(split)


# ======================================================================
# B. 처리 — 판정에 따라 무엇을 하는가
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_b01_an_optional_trigger_can_be_taken_or_given_up(repository):
    """
    🔴 **근거 있는 임의** — 발동도 포기도 고르는 쪽의 것이다.

    같은 판에서 둘을 모두 밟는다: 집으면 카드가 움직이고, 집지 않으면
    움직이지 않는다. 엔진이 포기를 강요하지도, 발동을 강요하지도 않는다.

    🔴 **Phase 6-AB 보완4가 "포기하는 방법" 을 정정했다**
    -----------------------------------------------------
    전에는 *"포기는 **적법한 다른 행동**으로 한다"* 였고, 그래서 이 시험이
    유발 기회가 열린 자리에서 ``END_PHASE`` 가 후보로 오르는 것을
    단정했다 (*"임의 유발은 페이즈 전환을 막지 않는다"*).

    **그 단정이 틀렸다.** 공식 Fast Effect Timing 도표는 둘을 적는다 —
    *"Many actions can ONLY be performed when the game state is open (when
    you're in box A)."* 와 *"Whenever either player performs an action, the
    game state is no longer open."* 유발 처리 기회는 box A 가 **아니므로**
    그 자리에서 통상 소환 · 세트 · 페이즈 이동을 할 수 없다. 판이 다시
    열리는 조건도 그 도표가 적는다 — 턴 플레이어가 넘기고, 상대가 되돌려
    넘기고, 체인이 없을 때다.

    🔴 **이 시험이 지키려던 구분은 그대로 살아 있다.** 임의 유발은
    controller 를 **강제하지 않는다** — 그래서 그 자리에 ``PASS`` 가 함께
    오르고 **한 걸음으로 포기할 수 있다.** 강제 유발이면 ``PASS`` 가 오르지
    않는다 (``test_b03``). 바뀐 것은 "포기를 어떻게 적는가" 이고, "포기할
    수 있는가" 가 아니다.

    실측한 결함: 전 해석 아래에서는 내 일반 행동 하나가 **상대의 미처리
    기회까지** 닫았다 (6-AB 최종 보완의 BLOCKER-F3-1 — 내 세트 수락 →
    상대 claims 1 → 0 → 내 ``END_PHASE`` 수락).
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    offers = trigger_offers(duel, repository, MINE)
    assert offers and offers[0].is_optional

    #: ① 집는다 — 움직인다.
    assert duel.apply(_trigger_action(duel)).accepted is True
    _settle(duel)
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 1

    #: ② 다른 판에서 집지 않는다 — 움직이지 않는다.
    setup2, _ = _board(repository, selector=DeclineChoice())
    other = setup2.duel
    _summon(other)
    assert _trigger_action(other) is not None

    #: 🔴 **포기는 ``PASS`` 한 걸음이다** — 임의이므로 그것이 오른다.
    legal = other.legal_actions(MINE)
    passing = [a for a in legal.allowed if a.kind is PlayerActionKind.PASS]
    assert passing, "임의 유발은 한 걸음으로 포기할 수 있다"
    #: 🔴 그리고 그 자리에서 **페이즈 이동은 오르지 않는다** — 판이 열린
    #: 상태가 아니다 (공식 Fast Effect Timing — box A 에서만 할 수 있다).
    assert not [
        a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE
    ]

    #: 🔴 포기하면 기회가 닫히고 **흐름이 다시 열린다.**
    step = other.apply(passing[0])
    assert step.accepted is True
    assert _trigger_action(other) is None
    assert _end_phase(other) is not None
    assert len(other.state.player(MINE).zone(Zone.GRAVE)) == 0


@pytest.mark.real_card
@requires_official_db
def test_b02_an_unknown_trigger_is_withheld_not_offered(repository):
    """
    🔴 **모름을 임의로 승격하지 않는다** — 이 Phase 의 핵심 수정이다.

    6-Z 는 모름을 후보로 올려 발동 여부를 고르는 쪽에 맡겼다. 그러면 정책의
    거절과 규칙이 허락한 포기가 **구별되지 않는다** — 실제로 강제였다면
    규칙이 요구한 처리가 조용히 생략된다.

    지금은 후보가 아니고, **무엇을 모르는지** 보류에 적힌다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = _wired(setup, repository, TriggerRequirement.UNKNOWN)
    _summon(duel)

    #: 제안은 여전히 생긴다 — 사건은 실제로 있다.
    assert len(duel._trigger_offers(MINE)) == 1
    legal = duel.legal_actions(MINE)
    #: 🔴 그런데 후보가 **아니다.**
    assert not [
        a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    #: 🔴 그리고 **조용하지 않다.**
    held = [w for w in legal.withheld if w.missing == TRIGGER_REQUIREMENT_MISSING]
    assert len(held) == 1, [(w.kind.value, w.reason) for w in legal.withheld]
    assert "강제인지 임의인지 판정할 수 없어" in held[0].reason
    #: 직접 넣어도 받지 않는다.
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=duel._trigger_offers(MINE)[0].source,
        effect_ref=EffectRef(GIRSU, 0),
    )
    assert duel.apply(action).accepted is False


@pytest.mark.real_card
@requires_official_db
def test_b03_synthetic_a_mandatory_trigger_blocks_the_phase(repository):
    """
    🔴 **합성** — 근거 있는 **강제**는 정책의 거절로 생략되지 않는다.

    엔진이 대신 발동해 주지는 않는다 (그러면 해결 중의 선택까지 엔진이
    정한다). 대신 **흐름을 막는다**: 그 기회가 열려 있는 동안 페이즈를
    넘길 수 없고, 고르는 쪽에게 남은 길은 그 발동을 집는 것이다.

    🔴 실행 등재된 유발이 임의 하나뿐이므로 (``test_a05`` 의 표에서
    ``MANDATORY`` 514건은 **실행 구현이 없는** 카드들이다) 이 구조는
    합성으로만 센다. 실제 카드에서 강제 유발을 해결했다고 적지 않는다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = _wired(setup, repository, TriggerRequirement.MANDATORY)
    _summon(duel)

    forced = duel._trigger_offers(MINE)
    assert len(forced) == 1 and forced[0].is_mandatory

    legal = duel.legal_actions(MINE)
    #: ① 후보로는 올라 있다 — 고르는 쪽이 집을 수 있다.
    activations = [
        a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(activations) == 1, activations
    #: ② 🔴 **페이즈를 넘길 수 없다.**
    assert not [
        a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE
    ]
    held = [w for w in legal.withheld if w.kind is PlayerActionKind.END_PHASE]
    assert len(held) == 1, [(w.kind.value, w.reason) for w in legal.withheld]
    assert "강제 유발 1건" in held[0].reason
    #: 직접 넣어도 받지 않는다.
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted is False


@pytest.mark.real_card
@requires_official_db
def test_b04_synthetic_the_block_lifts_once_the_duty_is_done(repository):
    """
    🔴 **합성** — 강제 유발을 발동하면 흐름이 **다시 열린다.**

    막는 것이 목적이 아니라 **생략을 막는 것**이 목적이므로, 처리가 끝나면
    막을 이유가 없다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = _wired(setup, repository, TriggerRequirement.MANDATORY)
    chooser = PolicyChooser(FirstPermittedChoice())
    _summon(duel)

    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    )
    assert duel.apply(action).accepted is True
    _settle(duel)

    #: 사건을 썼으므로 기회가 닫혔다.
    assert duel._mandatory_offers(MINE) == ()
    legal = duel.legal_actions(MINE)
    assert [a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE]
    del chooser


@pytest.mark.real_card
@requires_official_db
def test_b05_synthetic_unknown_never_blocks_the_flow(repository):
    """
    🔴 **합성** — 모름은 흐름을 막지 않는다.

    막으면 영영 막힌다: 모름은 발동해서 해소할 수 없으므로 (후보가 아니다)
    듀얼이 그 자리에서 끝난다. 그래서 모름의 처리는 "보류에 적고 흐름은
    열어 둔다" 이고, 그것이 강제와 다른 점이다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = _wired(setup, repository, TriggerRequirement.UNKNOWN)
    _summon(duel)
    assert duel._mandatory_offers(MINE) == ()
    legal = duel.legal_actions(MINE)
    assert [a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE]
    assert _end_phase(duel) is not None


# ======================================================================
# C. 수명 — 기회가 언제 닫히는가
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_c01_the_opportunity_closes_when_the_phase_ends(repository):
    """
    🔴 **지나간 페이즈의 사건은 기회를 열지 않는다** — 6-Z 의 결함이었다.

    근거는 룰북의 페이즈 구조다: *"After a card's activation, and at the end
    of each phase or step, Priority passes to the opponent"*. 메인 페이즈 1
    의 소환 유발을 배틀 페이즈에 발동하는 것은 그 사건의 시점이 아니다.

    실측 (6-AA 이전)::

        MAIN1  offers=1  gate=valid/ok
        BATTLE offers=1  gate=valid/ok   ← 결함
        MAIN2  offers=1  gate=valid/ok   ← 결함
        END    offers=1  gate=valid/ok   ← 결함
        DRAW(T2) offers=1 gate=valid/ok  ← 결함
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    assert duel.state.turn.phase is Phase.MAIN1
    assert len(duel._trigger_offers(MINE)) == 1
    assert _trigger_action(duel) is not None

    #: 🔴 **먼저 그 기회를 지난다** (보완4). 판이 열린 상태가 아니면
    #: ``END_PHASE`` 가 후보로 오르지 않는다 (``_decline_window`` 의 설명).
    assert _decline_window(duel) >= 1

    seen = []
    for _ in range(5):
        if _end_phase(duel) is None:
            break
        seen.append(
            (
                duel.state.turn.turn_number,
                duel.state.turn.phase.name,
                len(duel._trigger_offers(MINE)),
            )
        )
    assert seen, "페이즈를 한 번도 넘기지 못하면 이 시험은 아무것도 재지 않는다"
    #: 🔴 페이즈가 바뀐 뒤에는 **어디서도** 기회가 열리지 않는다.
    assert all(count == 0 for _, _, count in seen), seen
    assert any(phase == "BATTLE" for _, phase, _ in seen), seen


@pytest.mark.real_card
@requires_official_db
def test_c02_the_floor_moves_with_the_phase(repository):
    """
    기회를 닫는 것은 **기록 번호의 바닥**이다 (``Duel.timing_floor``).

    새 식별자를 만들지 않았다 — ``EventJournal`` 이 identity 로 쓰는 번호
    (``JournalEvent.sequence``) 그대로다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    assert duel.timing_floor == 0
    _summon(duel)
    recorded = len(duel.journal)
    assert recorded >= 1
    #: 소환 사건은 바닥보다 뒤에 있다 — 그래서 열려 있다.
    assert duel._trigger_offers(MINE)[0].event_sequence >= duel.timing_floor

    #: 🔴 **기회를 지난 뒤에 페이즈를 넘긴다** (보완4 — 판이 열린 상태가
    #: 아니면 ``END_PHASE`` 가 오르지 않는다). 바닥을 올리는 것은 여전히
    #: **페이즈 전환**이고, 포기는 ``window_passed`` 만 적는다.
    assert _decline_window(duel) >= 1
    assert duel.timing_floor == 0, "포기는 시점의 바닥을 올리지 않는다"

    _end_phase(duel)
    #: 🔴 페이즈가 바뀌며 바닥이 기록 끝으로 올라갔다.
    assert duel.timing_floor >= recorded
    assert duel._trigger_offers(MINE) == ()


@pytest.mark.real_card
@requires_official_db
def test_c03_asking_repeatedly_changes_nothing(repository):
    """
    🔴 **묻는 것만으로 판 · 사건 · 기회가 바뀌지 않는다.**

    6-Z 가 판과 사건을 센 자리에 **기회와 바닥**을 더한다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)

    before = (
        duel.state.state_hash(),
        len(duel.journal),
        duel.consumed_events,
        duel.timing_floor,
    )
    counts = set()
    for _ in range(6):
        counts.add(len(duel._trigger_offers(MINE)))
        duel.legal_actions(MINE)
    assert counts == {1}, counts
    assert (
        duel.state.state_hash(),
        len(duel.journal),
        duel.consumed_events,
        duel.timing_floor,
    ) == before


@pytest.mark.real_card
@requires_official_db
def test_c04_a_rejected_illegal_action_spends_no_opportunity(repository):
    """
    🔴 **거절된 불법 행동이 적법한 기회를 소비하지 않는다.**

    세 가지 불법을 넣어 본다 — 사건 없는 짝 · 다른 효과 번호 · 흐름 위반.
    셋 다 거절되고, 그 뒤에도 기회는 그대로 열려 있다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    opened = duel._trigger_offers(MINE)
    assert len(opened) == 1
    hand = duel.state.player(MINE).zone(Zone.HAND)

    illegal = [
        #: ① 사건이 없는 카드 개체로 같은 효과를 발동한다.
        PlayerAction.activate_effect(
            actor=MINE, source=hand[0].instance_id, effect_ref=EffectRef(GIRSU, 0)
        ),
        #: ② 등록되지 않은 효과 번호.
        PlayerAction.activate_effect(
            actor=MINE, source=opened[0].source, effect_ref=EffectRef(GIRSU, 9)
        ),
        #: ③ 상대가 내 자리에서 발동한다.
        PlayerAction.activate_effect(
            actor=THEIRS, source=opened[0].source, effect_ref=EffectRef(GIRSU, 0)
        ),
    ]
    for action in illegal:
        assert duel.apply(action).accepted is False, action
        assert duel.consumed_events == frozenset(), action

    #: 🔴 그 뒤에도 정상 발동이 그대로 된다.
    assert duel._trigger_offers(MINE) == opened
    assert duel.apply(_trigger_action(duel)).accepted is True


@pytest.mark.real_card
@requires_official_db
def test_c05_declining_closes_the_offer_within_the_phase(repository):
    """
    🔴 **같은 페이즈 안에서 발동하지 않기로 한 임의 유발은 다시 제안되지
    않는다** — 이름과 단정이 **두 번** 바뀐 자리다. 그 이력을 남긴다.

    ====  ==================================  ============================
    6-AA  ``…leaves_the_offer_open…``         한계로 기록 (``BLOCKER-6AA-2``)
    6-AB  같은 단정, 설명만 고침               「경우」 이므로 **규칙대로**라고
                                             읽었다
    보완  ``…closes_the_offer…``              🔴 **단정 자체가 틀렸다**
    ====  ==================================  ============================

    6-AB 의 해석은 *"기르수는 「경우에 발동」 이므로 그 사건 뒤에 다른 일이
    일어나도 기회가 남는 것이 규칙대로다"* 였다. **「경우」 에 대한 사실은
    맞지만 결론이 틀렸다** — *"타이밍을 놓치지 않는다"* 는 *"같은 페이즈에서
    나중에 마음대로 발동할 수 있다"* 는 뜻이 아니다.

    근거는 공식 Fast Effect Timing 도표다: 유발은 체인을 시작하지 않는 행위
    뒤와 체인 해결 뒤에 확인되고, 그 자리에서 양쪽이 패스하면 판은 **open
    state** 로 돌아간다. 그 확인 자리에서 유발 대신 다른 일을 골랐다면 그
    자리의 기회는 지나간 것이다.
    (https://www.yugioh-card.com/en/play/fast-effect-timing/)

    🔴 **그래도 6-AA 가 일괄 규칙을 만들지 않은 판단은 옳았다.** 지금 닫는
    것은 "다음 행동" 이 아니라 **판이 open state 로 돌아갔다**는 사실이다
    (``Duel.window_floor`` — 6-AB 추가 보완이 ``declined_events`` 를 이것으로
    바꿨다. 행동 종류를 열거하지 않는다).

    「때 / 경우」 의 구분이 사라진 것도 아니다 — 그것은 ``_missed_timing``
    이 따로 답하고, ``tests/engine/test_trigger_execution_and_timing.py``
    의 ``test_b02`` · ``test_b03`` 이 두 사실을 갈라서 센다.
    """
    setup, _ = _board(repository, selector=DeclineChoice())
    duel = setup.duel
    _summon(duel)
    assert len(duel._trigger_offers(MINE)) == 1
    assert _trigger_action(duel) is not None, "받지 못한 기회는 포기가 아니다"

    #: 🔴 **포기는 ``PASS`` 한 걸음이다** (보완4가 정정한 자리). 전에는 이
    #: 자리에서 곧바로 세트를 했고, 그것이 "포기" 였다. 공식 Fast Effect
    #: Timing 도표는 그 행동을 **판이 열린 상태에서만** 허용하므로
    #: (*"Many actions can ONLY be performed when the game state is
    #: open"*) 포기를 먼저 적고 그 다음에 세트를 한다.
    #:
    #: 🔴 **이 시험의 단정은 그대로다** — 포기한 임의 유발은 같은 페이즈
    #: 안에서 다시 제안되지 않는다. 바뀐 것은 포기를 어떻게 적는가다.
    assert _decline_window(duel) >= 1
    assert _trigger_action(duel) is None, "포기한 기회는 다시 오르지 않는다"

    #: 다른 행동을 한다 — 같은 페이즈 안이다.
    sets = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.SET_SPELL_TRAP
    ]
    assert sets, "세트할 카드가 없으면 이 시험은 아무것도 재지 않는다"
    assert duel.apply(sets[0]).accepted is True
    assert duel.state.turn.phase is Phase.MAIN1

    #: 🔴 **닫혔다.** 제안 자체는 남아 있고 (사건은 지워지지 않는다) 닫힌
    #: 것은 **그 자리의 창**이다 — 둘을 가르는 것이 이번 수정의 요점이다.
    assert len(duel._trigger_offers(MINE)) == 1
    assert _trigger_action(duel) is None
    declined = [
        w
        for w in duel.legal_actions(MINE).withheld
        if "기회는 이미 끝났습니다" in w.reason
    ]
    assert len(declined) == 1
    #: 빠진 규칙이 아니다 — 규칙이 그렇게 정했다.
    assert declined[0].missing is None


# ======================================================================
# D. 소비 단위 — 한 기회를 쓰는 것이 무엇을 닫는가
# ======================================================================


def test_d01_the_key_names_the_event_the_effect_and_the_instance():
    """
    🔴 **소비 단위는 세 짝이다** — 사건 · 효과 · 카드 개체.

    6-Z 는 둘(사건 · 효과)이었다. ``EffectRef`` 는 ``(card_id, ordinal)``
    이므로 **개체를 가르지 않는다** — 둘만 담으면 한 사건이 같은 이름의
    카드 두 장을 유발시킬 때 한 장의 발동이 다른 장의 기회를 함께 닫는다.
    """
    from engine.ids import InstanceId

    class _Offer:
        def __init__(self, source):
            self.event_key = "EV"
            self.effect_ref = EffectRef(1, 0)
            self.source = source

    first = Duel._consumption_key(_Offer(InstanceId(1)))
    second = Duel._consumption_key(_Offer(InstanceId(2)))
    assert len(first) == 3
    assert first != second, "개체가 다르면 키가 달라야 한다"
    assert first[2] == InstanceId(1)
    #: 같은 개체 · 같은 사건 · 같은 효과면 같은 키다 (중복 발동을 막는다).
    assert first == Duel._consumption_key(_Offer(InstanceId(1)))


@pytest.mark.real_card
@requires_official_db
def test_d02_consuming_one_opportunity_closes_only_that_one(repository):
    """
    🔴 **다른 개체 · 다른 효과의 기회를 함께 닫지 않는다.**

    실제 발동으로 기회 하나를 쓴 뒤, 손으로 만든 **다른 개체** 와 **다른
    효과** 의 키가 소비 목록에 들어 있지 않음을 센다.
    """
    from engine.ids import InstanceId

    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    offer = duel._trigger_offers(MINE)[0]
    assert duel.apply(_trigger_action(duel)).accepted is True
    assert len(duel.consumed_events) == 1

    used = Duel._consumption_key(offer)
    assert used in duel.consumed_events

    class _Other:
        def __init__(self, source, effect_ref):
            self.event_key = offer.event_key
            self.effect_ref = effect_ref
            self.source = source

    #: 같은 사건 · 같은 효과인데 **다른 개체** — 닫히지 않았다.
    other_instance = Duel._consumption_key(
        _Other(InstanceId(offer.source.value + 1000), offer.effect_ref)
    )
    assert other_instance not in duel.consumed_events
    #: 같은 사건 · 같은 개체인데 **다른 효과** — 닫히지 않았다.
    other_effect = Duel._consumption_key(
        _Other(offer.source, EffectRef(GIRSU, 1))
    )
    assert other_effect not in duel.consumed_events


@pytest.mark.real_card
@requires_official_db
def test_d03_the_same_opportunity_cannot_be_used_twice(repository):
    """같은 사건 · 같은 효과 · 같은 개체는 **한 번**이다 (6-Z 를 유지한다)."""
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)
    assert duel.apply(action).accepted is True
    _settle(duel)
    assert _trigger_action(duel) is None
    assert duel.apply(action).accepted is False
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 1


@pytest.mark.real_card
@requires_official_db
def test_d04_a_fork_does_not_write_back_into_the_original(repository):
    """
    🔴 **분기 사본의 소비 상태가 원본에 영향을 주지 않는다.**

    ``consumed_events`` 와 ``timing_floor`` 는 둘 다 **값**이므로
    ``dataclasses.replace`` 로 뜬 사본이 값으로 가져간다. 사본에서 발동해도
    원본의 목록이 늘지 않는다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    assert duel.consumed_events == frozenset()
    before_floor = duel.timing_floor

    fork = dataclasses.replace(duel, state=duel.state.clone())
    assert fork.apply(_trigger_action(fork)).accepted is True
    assert len(fork.consumed_events) == 1
    #: 🔴 **원본은 그대로다.**
    assert duel.consumed_events == frozenset()
    assert duel.timing_floor == before_floor
    assert _trigger_action(duel) is not None

    #: 사본이 페이즈를 넘겨도 원본의 바닥은 움직이지 않는다.
    _settle(fork)
    _end_phase(fork)
    assert fork.timing_floor > before_floor
    assert duel.timing_floor == before_floor


@pytest.mark.real_card
@requires_official_db
def test_d05_a_state_hash_alone_does_not_decide_what_can_be_activated(repository):
    """
    🔴 **판의 해시가 같다고 발동 가능성이 같지 않다.**

    ``GameState.state_hash`` 는 판의 **모양**이고, 기회는 흐름 위의 자리다
    (``consumed_events`` · ``timing_floor``). 둘을 같게 보면 "이미 쓴
    기회" 와 "아직 안 쓴 기회" 가 한 상태로 뭉개진다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    fork = dataclasses.replace(duel, state=duel.state.clone())

    #: 사본에서 기회만 소비하고 **판은 아직 바꾸지 않는다** (해결 전이다).
    assert fork.apply(_trigger_action(fork)).accepted is True
    assert fork.state.state_hash() == duel.state.state_hash(), (
        "발동만으로는 판의 모양이 바뀌지 않는다 — 그래서 이 시험이 성립한다"
    )
    #: 🔴 그런데 **기회는 다르다.**
    assert fork.consumed_events != duel.consumed_events
    assert _trigger_action(fork) is None
    assert _trigger_action(duel) is not None
