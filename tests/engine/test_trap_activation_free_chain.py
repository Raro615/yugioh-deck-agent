"""
Phase 6-Q — 함정 카드 발동 조건과 실제 실행 경로 연결.

막고 있던 것은 **한 문장이 적어 둔 빈 칸** 하나였다
---------------------------------------------------
``TRAP_TRIGGER_MISSING`` (Phase 3-E-16) 은 이렇게 적고 있었다.

    "trap-activation-timing (함정의 유발 조건을 효과마다 구분할 수 없다 —
     공식 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다)"

🔴 **그 진단은 맞았다.** 그래서 6-Q 는 관문을 없애지 않고 그 칸을 만들었다
(:attr:`~engine.effect.definition.EffectDefinition.activation_waits_for_event`)
— 카드 종류로 종류 전체를 통과시키는 것이 아니라, **적어 둔 사실에만** 답한다.

필요했던 것이 왜 그것뿐이었나
-----------------------------
함정의 발동에 필요한 다른 규칙은 **전부 이미 있었다.**

    스펠 스피드 2 · 3     classify_spell_speed — 카드 종류에서 나온다
    응수 가능 여부         RESPONSE_TABLE (룰북의 표 그대로)
    세트한 턴 제약         ActivationTimingChecker._set_turn_refusal
                          (RULE-SPELLTRAP-009, 스펠 스피드로 가른다)
    세트 기록             GameState.rule_uses + Duel._set_this_turn
    응답 창 · 우선권       PriorityState · Duel.legal_antions 의 창 검사
    카드별 조건 · 비용 · 대상  EffectActivator.can_activate
    발동 절차 (앞면 · 묘지)  NormalSpellPlacement.reveal / retire

이 파일의 ``F`` 절이 그 일곱을 **하나씩 센다** — 하나라도 없었다면 관문을
열어서는 안 됐다.

``EVENT_FREE_CHAIN`` 을 엔진에 싣지 않았다
------------------------------------------
🔴 그 이름은 **Lua 내부 태그**이고 공식 규칙의 개념이 아니다 — 이 저장소의
공식 자료 전체에서 "Free Chain" 은 **0회** 나온다 (Phase 3-F-25). 게다가
공식 스펠 스피드와 **끝에서 뒤집힌다**: 필드 마법(속도 1)은 100% 가
``EVENT_FREE_CHAIN`` 인데 카운터 함정(속도 3)은 1.4% 뿐이다.

그래서 엔진은 그 태그를 모른다. 옮긴 것은 **그 태그가 답하는 질문 하나**
("이 발동이 사건을 기다리는가")이고, 그 답은 손으로 적었다 (ADR-006).

여기서 하지 않은 것
-------------------
새 듀얼 엔진 · 새 체인 엔진 · TRIGGER 자동 발동 · 우선권 재설계 · 지속 함정의
필드 잔존 · 카운터 함정의 응답 타이밍. 뒤의 둘은 ``_OUT_OF_SCOPE_TYPES`` 가
이유를 대고 막는다 (RULE-SPELLTRAP-010 · 011), 그리고 🔴 **그 표가 6-Q 전까지
함정에 닿지 않고 있었다** (``C`` 절이 센다).
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import (
    TRAP_EVENT_UNSUPPORTED,
    TRAP_NOT_SET,
    TRAP_TRIGGER_MISSING,
    ActionValidator,
    _OUT_OF_SCOPE_TYPES,
    activation_is_set_trap,
)
from engine.activation_timing import (
    SET_TURN_MISSING,
    ActivationTiming,
    ActivationTimingChecker,
    SpellSpeed,
    classify_spell_speed,
)
from engine.duel import Duel, duel_components
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.journal import EffectEvent, EventJournal
from engine.effect.library import EFFECT_LIBRARY, definition_registry
from engine.ids import EffectRef
from engine.priority import PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.target_bridge import target_combinations
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P0, P1 = 0, 1

#: 등재된 함정 다섯 장. **전부 일반 함정**(``['TRAP']``)이고 ``ACTIVATE``
#: 블록 하나에 ``SetCode(EVENT_FREE_CHAIN)`` 이다 (``A`` 절이 센다).
GIFT_OF_GREED = 5915629  # 욕망의 선물 — 대상 없음 · 상대가 2장 드로우
FINE = 92595643  # 벌금 — 패 2장 버리기 (Phase 6-P 의 다중 선택)
FORCEOUT = 94192409  # 강제 탈출 장치 — 몬스터 1장을 패로 (Phase 6-O)
LOST = 24623598  # 로스트 — 🔴 ``executable=False``
PRIMER = 69091732  # 의적의 입문서 — 상대 패 5장 이상
ALL_TRAPS = (GIFT_OF_GREED, FINE, FORCEOUT, LOST, PRIMER)

LUSTER_DRAGON = 11091375  # 통상 몬스터 (6-O 의 룰북 줄이 덮는다)
POT_OF_GREED = 55144522  # 통상 마법 — 상대가 체인 1 을 만드는 데 쓴다
RELOAD = 22589918  # 속공 마법 — 세트한 턴 제약을 함정과 **같이** 받는다

DEFS = definition_registry()


# ======================================================================
# 판 만들기 — 전부 실제 엔진으로
# ======================================================================


def staged(
    repository,
    *,
    mine=(),
    their_mzone=(),
    their_hand=0,
    fodder=0,
    journal=None,
    turn_player=P0,
):
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=turn_player,
        seed=1,
    )
    sources = [
        state.create_instance(card_id, owner=P0, zone=Zone.HAND).instance_id
        for card_id in mine
    ]
    for _ in range(fodder):
        state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.HAND)
    placed = []
    for card_id in their_mzone:
        card = state.create_instance(card_id, owner=P1, zone=Zone.MZONE)
        state.move(card, Zone.MZONE, to_player=P1, position=Position.FACEUP_ATTACK)
        placed.append(card.instance_id)
    for _ in range(their_hand):
        state.create_instance(LUSTER_DRAGON, owner=P1, zone=Zone.HAND)
    state.turn.turn_number = 5
    state.turn.turn_player = turn_player
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=turn_player, phase=Phase.MAIN1),
        **duel_components(journal=journal),
    )
    return duel, sources, placed


def set_down(duel, instance, seat=P0):
    """실제 ``SET_SPELL_TRAP`` 행위로 세운다 — 기록이 남아야 한다."""
    step = duel.apply(PlayerAction.set_spell_trap(actor=seat, source=instance))
    assert step.accepted, step.reason
    return instance


def next_turn(duel, to_seat=P0, phase=Phase.MAIN1):
    duel.state.turn.turn_number += 1
    duel.state.turn.turn_player = to_seat
    duel.state.turn.set_phase(phase)
    duel.priority = PriorityState.idle(turn_player=to_seat, phase=phase)


def activations(duel, seat, card_id=None):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and (card_id is None or a.effect_ref.card_id == card_id)
    ]


def made(seat, instance, card_id, targets=()):
    return PlayerAction.activate_effect(
        actor=seat, source=instance, effect_ref=EffectRef(card_id, 0), targets=targets
    )


def informed(duel, seat=P0):
    """등록소를 **받은** 검증기 — 생산 경로가 쓰는 것과 같다."""
    return ActionValidator(duel.view(seat), definitions=DEFS)


def blind(duel, seat=P0):
    """등록소를 **받지 못한** 검증기 — "적지 않았다" 쪽을 재는 데 쓴다."""
    return ActionValidator(duel.view(seat))


def fabricated_trap(repository, *, waits_for_event, card_id=PRIMER):
    """
    🔴 **지어낸 정의.** 등재된 다섯 장은 전부 ``False`` 이므로
    (``test_a02``), ``None`` · ``True`` 가지를 밟으려면 값을 손으로 만들어야
    한다. 실제 카드로는 닿지 않는 코드가 **거부를 제대로 하는지** 본다.

    카드 ID 는 그대로 두고 **축만** 바꾼다 — 그래서 이 시험이 재는 것은
    카드가 아니라 축이다 (``test_e04`` 가 AST 로 카드 분기 0 을 지킨다).
    """
    base = DEFS.definition_for(EffectRef(card_id, 0))
    assert base is not None
    import dataclasses

    return dataclasses.replace(base, activation_waits_for_event=waits_for_event)


class _Registry:
    """정의 하나만 돌려주는 등록소. ``definition_for`` 만 쓰인다."""

    def __init__(self, definition):
        self._definition = definition

    def definition_for(self, effect_ref):
        return (
            self._definition
            if effect_ref == self._definition.effect_ref
            else DEFS.definition_for(effect_ref)
        )


# ======================================================================
# A. 감사 — 등재된 함정의 실제 데이터 (§4-A · §5)
# ======================================================================


@pytest.mark.real_card
def test_a01_all_registered_traps_are_plain_normal_traps(repository):
    """
    🔴 **실측 — 등재된 함정 다섯 장은 전부 일반 함정이다.**

    지속 · 카운터가 **0장**이라는 사실이 이 Phase 의 범위를 정했다 (§6):
    룰북이 발동 시점을 문장으로 확정해 둔 범주 하나만 연다.
    """
    traps = [
        entry
        for entry in EFFECT_LIBRARY
        if repository.get(entry.definition.source_card_id).is_trap
    ]
    assert {e.definition.source_card_id for e in traps} == set(ALL_TRAPS)
    for entry in traps:
        card = repository.get(entry.definition.source_card_id)
        assert tuple(card.type_names) == ("TRAP",), (card.name, card.type_names)
        assert classify_spell_speed(card).speed is SpellSpeed.FAST
        #: ``ACTIVATE`` 블록 하나이고 사건을 적지 않는다.
        blocks = [s for s in card.effects if "ACTIVATE" in s.effect_types]
        assert len(blocks) == 1, card.name
        assert blocks[0].code == "EVENT_FREE_CHAIN", card.name


@pytest.mark.real_card
def test_a02_the_axis_is_written_only_where_it_is_needed():
    """
    **§16 — 적은 곳이 다섯 장뿐이다.** 마법 · 몬스터에는 적지 않았다.

    축을 전부에 뿌리면 "적지 않았다" 가 어디인지 알 수 없게 된다.
    """
    written = {
        e.definition.source_card_id: e.definition.activation_waits_for_event
        for e in EFFECT_LIBRARY
        if e.definition.activation_waits_for_event is not None
    }
    assert set(written) == set(ALL_TRAPS), written
    assert set(written.values()) == {False}, written
    #: 기본값은 ``None`` — "적지 않았다" 다.
    assert EffectDefinition.__dataclass_fields__[
        "activation_waits_for_event"
    ].default is None


@pytest.mark.real_card
def test_a03_the_rulebook_states_the_timing_for_normal_traps():
    """
    🔴 **§5 — 근거는 룰북 문장이다.** ``EVENT_FREE_CHAIN`` 이 아니다.

    - RULE-SPELLTRAP-009 — *"you can activate it **at any time** after
      that—starting from the beginning of the next turn"*
    - RULE-SPELLTRAP-008 — *"you can activate Trap Cards **during your
      opponent's turn**"*

    ``engine`` 은 ``rules`` 를 import 하지 않으므로 (ADR-007) **이 시험이
    둘을 대조한다** — 스펠 스피드 표와 같은 약속이다.
    """
    import json

    document = json.loads(
        (ROOT / "data/rules/documents/sd-rulebook-en-v10.json").read_text(
            encoding="utf-8"
        )
    )
    found = {}

    def walk(node):
        if isinstance(node, dict):
            rid = node.get("rule_id") or node.get("id")
            if isinstance(rid, str) and rid.startswith("RULE-SPELLTRAP-"):
                found[rid] = (node.get("text") or node.get("body") or "")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    normal = found["RULE-SPELLTRAP-009"]
    #: 🔴 룰북 원문은 **ﬁ 합자**(U+FB01)를 쓴다 (PDF 에서 그대로 왔다).
    #: 데이터를 고치지 않고 **원문 그대로** 대조한다.
    assert "you must Set it on the ﬁeld ﬁrst" in normal
    assert "cannot activate a Trap in the same turn that you Set it" in normal
    assert "at any time after that" in normal
    assert "during your opponent" in found["RULE-SPELLTRAP-008"]
    #: 지속 · 카운터는 **다른 문장**이 다룬다 — 그래서 범위 밖이다.
    assert "remain on the" in found["RULE-SPELLTRAP-010"]
    assert "in response to the activation of other" in found["RULE-SPELLTRAP-011"]


@pytest.mark.real_card
def test_a04_free_chain_never_appears_in_the_official_material():
    """
    🔴 **§5 — "Free Chain" 은 공식 자료에 0회다** (Phase 3-F-25 재측정).

    그래서 엔진이 그 이름을 **실행 코드로 읽지 않는다.** 설명에 적는 것과
    읽는 것은 다른 일이므로 **AST** 로 잰다.
    """
    hits = []
    for folder in ("data/rules", "data/rulings"):
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*.json"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "Free Chain" in text or "free chain" in text:
                hits.append(path.relative_to(ROOT).as_posix())
    assert hits == [], hits

    read = set()
    for module in (ROOT / "engine").rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                read.add(node.attr)
            if isinstance(node, ast.Name):
                read.add(node.id)
    assert "EVENT_FREE_CHAIN" not in read
    assert "trigger_events" not in read


# ======================================================================
# B. 축이 판정을 가른다 (§12 · §18-2)
# ======================================================================


@pytest.mark.real_card
def test_b01_a_registry_blind_validator_still_says_unknown(repository):
    """
    🔴 **"적지 않았다" 는 6-Q 뒤에도 허가가 아니다.**

    등록소를 받지 못한 검증기에는 축이 ``None`` 으로 보이고, 그러면 이유가
    종전 그대로 ``TRAP_TRIGGER_MISSING`` 이다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    verdict = blind(duel).validate(made(P0, trap, GIFT_OF_GREED))
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == TRAP_TRIGGER_MISSING


@pytest.mark.real_card
def test_b02_an_informed_validator_passes_the_same_action(repository):
    """**같은 판 · 같은 카드 · 바뀐 것은 등록소 하나다.**"""
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    action = made(P0, trap, GIFT_OF_GREED)
    assert blind(duel).validate(action).validity is ActionValidity.UNKNOWN
    passed = informed(duel).validate(action)
    assert passed.validity is ActionValidity.VALID, passed.reason


@pytest.mark.real_card
def test_b03_a_trap_that_waits_for_an_event_is_refused_by_name(repository):
    """
    🔴 **§12 — 사건을 기다리는 함정은 거부된다.**

    실측(일반 함정 전수): ``ACTIVATE`` 블록 1,386개 중 **390개(28.1%)** 가
    사건을 적는다. 카드 종류만 보고 종류 전체를 통과시키면 그 390개가
    아무 때나 발동하게 된다 — 그래서 축을 본다.
    """
    duel, (trap,), _ = staged(repository, mine=(PRIMER,), their_hand=6)
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    action = made(P0, trap, PRIMER)

    waiting = _Registry(fabricated_trap(repository, waits_for_event=True))
    verdict = ActionValidator(duel.view(P0), definitions=waiting).validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == TRAP_EVENT_UNSUPPORTED

    #: 그리고 그 이유는 ``TRAP_TRIGGER_MISSING`` 과 **다른 문자열**이다 —
    #: 고칠 곳이 다르기 때문이다.
    assert TRAP_EVENT_UNSUPPORTED != TRAP_TRIGGER_MISSING


@pytest.mark.real_card
def test_b04_the_axis_changes_the_cached_condition_state(repository):
    """
    **축이 ``canonical_state`` 에 들어간다.**

    빠뜨리면 사건을 기다리는 함정과 기다리지 않는 함정이 같은 조건으로
    캐시된다 — ``activation_kind`` 와 같은 이유다.
    """
    from engine.action_validation import _NormalSpellActivation

    states = {
        _NormalSpellActivation(None, None, value).canonical_state()
        for value in (None, True, False)
    }
    assert len(states) == 3, states


# ======================================================================
# C. 지속 · 카운터 함정은 여전히 범위 밖이다 (§6 · §12)
# ======================================================================


@pytest.mark.real_card
def test_c01_the_out_of_scope_table_now_reaches_traps(repository):
    """
    🔴 **``_OUT_OF_SCOPE_TYPES`` 가 함정에 닿는다** (Phase 6-Q).

    3-E-16 이 적어 둔 그대로, 그 표의 ``TRAP`` 항목은 **닿지 않는 코드**
    였다 — 함정은 위 분기에서 먼저 돌아갔다. 6-Q 가 함정 분기를 열면서
    그 표를 함정에도 적용했다. 열면서 **막는 것을 늘린** 자리다.
    """
    table = dict(_OUT_OF_SCOPE_TYPES)
    assert "CONTINUOUS" in table and "COUNTER" in table
    source = (ROOT / "engine/action_validation.py").read_text(encoding="utf-8")
    assert "_trap_activation_out_of_scope" in source
    #: 함정 분기가 그 표를 읽는다.
    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_trap_activation_out_of_scope"
    )
    names = {n.id for n in ast.walk(func) if isinstance(n, ast.Name)}
    assert "_OUT_OF_SCOPE_TYPES" in names


@pytest.mark.real_card
@pytest.mark.parametrize("extra", ["CONTINUOUS", "COUNTER"])
def test_c02_a_continuous_or_counter_trap_stays_out_of_scope(repository, extra):
    """
    **지속 · 카운터 함정은 축을 적어도 범위 밖이다.**

    룰북이 **다른 문장**으로 다룬다 — 지속은 필드에 남고
    (RULE-SPELLTRAP-010), 카운터는 다른 발동에 응답한다
    (RULE-SPELLTRAP-011). 그 둘의 계층이 없으므로 열지 않는다.

    🔴 저장소에 등재된 지속 · 카운터 함정이 **0장**이므로 (``test_a01``)
    종류를 손으로 붙여서 그 가지를 직접 잰다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)

    view = duel.view(P0)
    card = view.find(trap)
    assert card is not None and card.definition is not None
    import dataclasses

    widened = dataclasses.replace(
        card.definition, type_names=card.definition.type_names + (extra,)
    )

    from engine.action_validation import _trap_activation_out_of_scope

    out = _trap_activation_out_of_scope(view, None, trap, widened, False)
    assert out, (extra, out)
    assert dict(_OUT_OF_SCOPE_TYPES)[extra] in {rule for _, rule in out}


# ======================================================================
# D. 세트 턴 · 발동 위치 (§9 · §11-A · §11-B · §11-C)
# ======================================================================


@pytest.mark.real_card
def test_d01_a_trap_set_this_turn_is_not_a_candidate(repository):
    """
    🔴 **§11-A — 세트한 턴에는 후보가 아니다** (RULE-SPELLTRAP-009).

    막는 곳이 검증기가 아니라 **타이밍 계층**이다. 검증기는 통과시키고,
    ``ActivationTimingChecker`` 가 ``INVALID`` 로 막는다 — 두 관문이 서로
    다른 사실을 본다는 증거다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    action = made(P0, trap, GIFT_OF_GREED)

    assert duel._set_this_turn(action) is True
    assert activations(duel, P0, GIFT_OF_GREED) == []
    assert informed(duel).validate(action).validity is ActionValidity.VALID
    timed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(duel.chain, duel.priority, set_this_turn=True), action
    )
    assert timed.validity is ActionValidity.INVALID
    assert timed.code is ValidationCode.SET_THIS_TURN
    assert "RULE-SPELLTRAP-007 · 009" in timed.reason


@pytest.mark.real_card
def test_d02_the_next_turn_opens_it(repository):
    """**§11-B — 같은 판 · 같은 카드 · 바뀐 것은 턴 번호 하나다.**"""
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    assert activations(duel, P0, GIFT_OF_GREED) == []
    next_turn(duel, P1)
    next_turn(duel, P0)
    assert duel._set_this_turn(made(P0, trap, GIFT_OF_GREED)) is False
    assert [a.source for a in activations(duel, P0, GIFT_OF_GREED)] == [trap]


@pytest.mark.real_card
def test_d03_an_unknown_set_turn_is_not_promoted(repository):
    """
    🔴 **세트한 턴을 모르면 ``UNKNOWN`` 이다.** 허가가 아니다.

    이 값은 관측에 없으므로 (상대가 언제 세웠는지는 공개 정보가 아니다)
    판을 들고 있는 쪽이 넘긴다. 넘기지 않으면 모른다 — 그리고 모르는 것이
    허가가 되지 않는다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    timed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(duel.chain, duel.priority, set_this_turn=None),
        made(P0, trap, GIFT_OF_GREED),
    )
    assert timed.validity is ActionValidity.UNKNOWN
    assert timed.missing_rule == SET_TURN_MISSING


@pytest.mark.real_card
def test_d04_a_trap_in_the_hand_is_not_a_candidate(repository):
    """
    🔴 **§11-C — 패의 함정은 후보가 아니다** (RULE-SPELLTRAP-009:
    *"you must Set it on the field first"*).

    ``INVALID`` 가 아니라 ``UNKNOWN`` 으로 막는다 — 발동 **위치**는 이
    관문이 범위 조건으로 다루고 있고 (마법도 그렇다), 한 질문에 두 길을
    두면 둘이 갈라진다. ``UNKNOWN`` 은 허가가 아니므로 안전한 쪽이다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    #: 세우지 않는다 — 패에 그대로 둔다.
    assert duel.state.find_instance(trap).zone is Zone.HAND
    assert activations(duel, P0, GIFT_OF_GREED) == []
    verdict = informed(duel).validate(made(P0, trap, GIFT_OF_GREED))
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == TRAP_NOT_SET


@pytest.mark.real_card
def test_d05_a_face_up_trap_is_not_a_set_trap(repository):
    """
    **앞면으로 돌아간 함정은 "세트된 함정" 이 아니다.**

    발동 절차로 앞면이 된 뒤 다시 발동하는 것은 **다른 일**이고
    (지속 함정의 필드 효과 — RULE-SPELLTRAP-010), 그 계층이 없다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    duel.state.move(trap, Zone.SZONE, to_player=P0, position=Position.FACEUP)
    next_turn(duel, P1)
    next_turn(duel, P0)
    assert not activation_is_set_trap(duel.view(P0), None, trap, False)
    verdict = informed(duel).validate(made(P0, trap, GIFT_OF_GREED))
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == TRAP_NOT_SET


# ======================================================================
# E. 좁은 요구를 걸지 않았다 — 그리고 그것이 허가가 아니다 (§3 · §12)
# ======================================================================


@pytest.mark.real_card
def test_e01_no_turn_player_requirement_is_added(repository):
    """
    🔴 **§3-9 — ``IsTurnPlayer`` 를 걸지 않는다** (RULE-SPELLTRAP-008).

    걸면 ``NOT_TURN_PLAYER`` 라는 ``INVALID`` 가 나오고, 그것은 "규칙이
    금지한다" 는 **거짓말**이다. 상대 턴에 쓰는 것이 함정의 본질이다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    next_turn(duel, P1, phase=Phase.BATTLE)
    verdict = informed(duel).validate(made(P0, trap, GIFT_OF_GREED))
    assert verdict.validity is not ActionValidity.INVALID, verdict.reason
    assert verdict.code is not ValidationCode.NOT_TURN_PLAYER
    assert verdict.code is not ValidationCode.WRONG_PHASE


@pytest.mark.real_card
def test_e02_a_full_spell_trap_zone_does_not_block_it(repository):
    """
    **빈 칸을 요구하지 않는다** — 세트해 둔 카드는 이미 제 칸에 있다
    (세트한 마법과 같은 이유 — Phase 3-E-14).
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    for _ in range(4):
        filler = duel.state.create_instance(RELOAD, owner=P0, zone=Zone.HAND)
        duel.state.move(filler, Zone.SZONE, to_player=P0, position=Position.FACEDOWN)
    assert len(duel.state.player(P0).spell_zone) == 5
    next_turn(duel, P1)
    next_turn(duel, P0)
    verdict = informed(duel).validate(made(P0, trap, GIFT_OF_GREED))
    assert verdict.validity is ActionValidity.VALID, verdict.reason
    assert [a.source for a in activations(duel, P0, GIFT_OF_GREED)] == [trap]


@pytest.mark.real_card
def test_e03_the_card_condition_still_refuses(repository):
    """
    🔴 **§12 — 카드별 발동 조건을 우회하지 않는다.**

    의적의 입문서는 상대 패가 5장 이상이어야 한다. 상대 패를 비우면
    검증기는 통과시키고 **발동 계층**이 막는다 — 두 관문이 따로다.
    """
    duel, (trap,), _ = staged(repository, mine=(PRIMER,), their_hand=6)
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    assert [a.source for a in activations(duel, P0, PRIMER)] == [trap]

    for card in list(duel.state.player(P1).zones[Zone.HAND]):
        duel.state.move(card, Zone.GRAVE, to_player=P1)
    assert len(duel.state.player(P1).zones[Zone.HAND]) == 0
    assert activations(duel, P0, PRIMER) == []
    #: 검증기는 여전히 통과시킨다 — 조건은 그쪽의 요구가 아니다.
    assert (
        informed(duel).validate(made(P0, trap, PRIMER)).validity
        is ActionValidity.VALID
    )


@pytest.mark.real_card
def test_e04_an_unexecutable_trap_is_still_refused(repository):
    """
    🔴 **ADR-006 — 등재가 실행 허가가 아니다.**

    로스트는 ``executable=False`` 다. 검증기는 통과시키지만 발동 계층이
    막으므로 후보가 되지 않는다. 6-Q 가 연 것은 **발동 타이밍 판정**이고
    실행 허가가 아니라는 증거다.
    """
    duel, (trap,), placed = staged(
        repository, mine=(LOST,), their_mzone=(LUSTER_DRAGON,)
    )
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    definition = DEFS.definition_for(EffectRef(LOST, 0))
    combos = target_combinations(duel.state, P0, definition, trap)
    assert len(combos) == 1, "대상은 찾는다"
    action = made(P0, trap, LOST, combos[0])
    assert informed(duel).validate(action).validity is ActionValidity.VALID
    assert activations(duel, P0, LOST) == []


@pytest.mark.real_card
def test_e05_the_bridge_never_branches_on_a_card_id():
    """
    🔴 **§3-6 · §16 — 카드 ID 와 카드명 분기 0건.**

    6-Q 가 건드린 세 파일에 함정 패스코드 리터럴이 하나도 없다.
    """
    for name in (
        "engine/action_validation.py",
        "engine/effect/definition.py",
    ):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        numbers = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        }
        assert not (numbers & set(ALL_TRAPS)), (name, numbers & set(ALL_TRAPS))


# ======================================================================
# F. 🔴 열기 전에 **있어야 했던 일곱 가지** (§10 · §18-6)
# ======================================================================


@pytest.mark.real_card
def test_f01_spell_speed_comes_from_the_card_type(repository):
    """① 스펠 스피드 — 함정은 2, 카운터 함정은 3. 카드 종류에서 나온다."""
    for card_id in ALL_TRAPS:
        card = repository.get(card_id)
        speed = classify_spell_speed(card)
        assert speed.speed is SpellSpeed.FAST, card.name
        assert speed.is_known


@pytest.mark.real_card
def test_f02_the_response_table_matches_the_rulebook():
    """② 응수 표 — 룰북의 ``chain.spell_speeds`` 와 같다."""
    import json

    from engine.activation_timing import RESPONSE_TABLE

    rulebook = json.loads(
        (ROOT / "data/rules/structured/sd-rulebook-en-v10.json").read_text(
            encoding="utf-8"
        )
    )
    rows = {row["speed"]: set(row["can_respond_to"]) for row in rulebook["chain"]["spell_speeds"]}
    for speed, allowed in RESPONSE_TABLE.items():
        assert {s.value for s in allowed} == rows[speed.value], speed


@pytest.mark.real_card
def test_f03_the_set_turn_record_exists_and_is_read(repository):
    """③ · ④ 세트 기록 — ``rule_uses`` 에 남고 ``Duel`` 이 읽는다."""
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    turn = duel.state.turn.turn_number
    set_down(duel, trap)
    assert duel.state.rule_uses.used_card(
        turn, P0, trap, RuleActionKind.SET_SPELL_TRAP
    )
    assert duel._set_this_turn(made(P0, trap, GIFT_OF_GREED)) is True


@pytest.mark.real_card
def test_f04_the_response_window_decides_who_may_activate(repository):
    """
    ⑤ 응답 창 · 우선권 — 창이 닫혀 있으면 턴 플레이어만 발동할 수 있다.

    🔴 그래서 **상대 턴에 아무 일도 없을 때는 후보가 아니다.** 함정이
    빠르다는 이유로 우선권을 무시하지 않는다 (§10). 이것은 6-Q 가 만든
    제약이 아니라 기존 우선권 모델이고, 그 사실을 여기서 못 박는다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    next_turn(duel, P1)
    assert not duel.priority.is_open
    assert duel.turn_player == P1
    assert activations(duel, P0, GIFT_OF_GREED) == []
    #: 그런데 발동 자체는 적법하다 — 막는 것이 **우선권**임을 보인다.
    assert (
        informed(duel).validate(made(P0, trap, GIFT_OF_GREED)).validity
        is ActionValidity.VALID
    )


@pytest.mark.real_card
def test_f05_the_activation_procedure_reveals_and_retires(repository):
    """⑦ 발동 절차 — 앞면으로 돌리고 해결 뒤 묘지로 간다 (RULE-SPELLTRAP-009)."""
    journal = EventJournal()
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,), journal=journal)
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    candidate = activations(duel, P0, GIFT_OF_GREED)[0]
    assert duel.apply(candidate).accepted
    assert duel.state.find_instance(trap).is_faceup, "앞면으로 돌아가지 않았다"
    settle_chain(duel)
    assert duel.state.find_instance(trap).zone is Zone.GRAVE


# ======================================================================
# G. 🔴 실제 수직 실행 (§11 · §18-12 · §18-13)
# ======================================================================


@pytest.mark.real_card
def test_g01_a_trap_resolves_on_my_own_turn(repository):
    """
    🔴 **legal_actions → apply → 체인 → EffectExecutor → GameState → Journal.**

    욕망의 선물 — "상대는 2장 드로우한다". 실측: 상대 패 0 → 2.
    """
    journal = EventJournal()
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,), journal=journal)
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)

    candidate = activations(duel, P0, GIFT_OF_GREED)[0]
    their_hand = len(duel.state.player(P1).zones[Zone.HAND])
    step = duel.apply(candidate)
    assert step.accepted, step.reason
    assert len(duel.chain.links) == 1, "체인 링크가 생기지 않았다"
    #: 🔴 체인 링크 생성과 효과 해결은 **다른 사실**이다 (§10).
    assert len(duel.state.player(P1).zones[Zone.HAND]) == their_hand

    settle_chain(duel)
    assert len(duel.state.player(P1).zones[Zone.HAND]) == their_hand + 2
    assert duel.state.find_instance(trap).zone is Zone.GRAVE

    effects = [e for e in journal if isinstance(e, EffectEvent)]
    assert [e.effect_ref for e in effects] == [EffectRef(GIFT_OF_GREED, 0)]
    assert effects[0].actor == P0
    assert effects[0].source == trap
    assert len(effects[0].applied) == 1


@pytest.mark.real_card
def test_g02_a_trap_resolves_on_the_opponents_turn_as_chain_two(repository):
    """
    🔴 **§11-F · §18-12 — 상대 턴의 응답 창에서 체인 2 로 발동하고 해결한다.**

    이것이 함정의 본질이고 (RULE-SPELLTRAP-008), 마법으로는 할 수 없다.

    실측 흐름:

    1. P0 가 자기 턴에 강제 탈출 장치를 세운다
    2. P1 의 턴 — P1 이 욕망의 항아리를 발동해 **체인 1** 을 만든다
    3. 응답 창이 열리고 P0 가 쥔다 → 함정이 **적법한 후보**다
    4. P0 가 **체인 2** 로 발동한다 (스펠 스피드 2 → 1, RULE-CHAIN-005)
    5. 체인이 **역순으로** 해결된다 — 체인 2 가 먼저다
    """
    journal = EventJournal()
    duel, (trap, spell_unused), placed = staged(
        repository,
        mine=(FORCEOUT, POT_OF_GREED),
        their_mzone=(LUSTER_DRAGON,),
        journal=journal,
    )
    set_down(duel, trap)
    victim = placed[0]

    #: 상대 턴으로 넘기고, 상대의 손에 통상 마법을 준다.
    next_turn(duel, P1)
    their_spell = duel.state.create_instance(
        POT_OF_GREED, owner=P1, zone=Zone.HAND
    ).instance_id
    opening = [
        a
        for a in activations(duel, P1, POT_OF_GREED)
        if a.source == their_spell
    ]
    assert opening, "상대가 체인 1 을 만들 수 없다"
    assert duel.apply(opening[0]).accepted
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holds(P0)
    assert duel.turn_player == P1, "턴 플레이어가 바뀌었다"

    #: 🔴 상대 턴의 응답 창에서 함정이 후보다.
    responses = activations(duel, P0, FORCEOUT)
    assert [a.source for a in responses] == [trap], responses
    assert [t.instance_id for t in responses[0].targets] == [victim]

    their_hand = len(duel.state.player(P1).zones[Zone.HAND])
    assert duel.apply(responses[0]).accepted
    assert len(duel.chain.links) == 2, "체인 2 가 되지 않았다"

    settle_chain(duel)

    #: 체인 2(함정)가 먼저, 체인 1(마법)이 나중에 해결된다.
    effects = [e for e in journal if isinstance(e, EffectEvent)]
    assert [e.effect_ref for e in effects] == [
        EffectRef(FORCEOUT, 0),
        EffectRef(POT_OF_GREED, 0),
    ], [str(e.effect_ref) for e in effects]

    #: GameState — 몬스터가 주인의 패로, 그리고 상대가 2장 뽑았다.
    assert duel.state.find_instance(victim).zone is Zone.HAND
    assert len(duel.state.player(P1).zones[Zone.HAND]) == their_hand + 1 + 2
    assert duel.state.find_instance(trap).zone is Zone.GRAVE


@pytest.mark.real_card
def test_g03_the_multi_target_trap_resolves_through_legal_actions(repository):
    """
    🔴 **§11-N · §18-14 — Phase 6-P 의 다중 선택이 ``legal_actions`` 로 온다.**

    6-P 는 조합 10개를 만들었지만 ``legal_actions`` 가 0건이었고, 그
    이유가 함정 관문이었다. 이제 **조합 10개가 적법한 행동 10개**이고,
    그중 하나를 실제로 발동해 해결한다 — 패 −2, 묘지 +3.
    """
    journal = EventJournal()
    duel, (trap,), _ = staged(repository, mine=(FINE,), fodder=5, journal=journal)
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)

    candidates = activations(duel, P0, FINE)
    assert len(candidates) == 10, len(candidates)
    chosen = candidates[0]
    picked = [t.instance_id for t in chosen.targets]
    assert len(picked) == 2

    before_hand = len(duel.state.player(P0).zones[Zone.HAND])
    before_grave = len(duel.state.player(P0).zones[Zone.GRAVE])
    assert duel.apply(chosen).accepted
    settle_chain(duel)

    assert len(duel.state.player(P0).zones[Zone.HAND]) == before_hand - 2
    assert len(duel.state.player(P0).zones[Zone.GRAVE]) == before_grave + 3
    for instance in picked:
        assert duel.state.find_instance(instance).zone is Zone.GRAVE
    assert duel.state.find_instance(trap).zone is Zone.GRAVE

    effects = [e for e in journal if isinstance(e, EffectEvent)]
    assert len(effects) == 1
    assert effects[0].applied[0].instances == tuple(picked)


@pytest.mark.real_card
def test_g04_two_duels_do_not_share_the_set_turn_record(repository):
    """
    **§11-O — 서로 다른 Duel 의 세트 기록이 섞이지 않는다.**

    기록은 ``GameState.rule_uses`` 에 있고 ``GameState`` 는 듀얼마다 하나다.
    """
    first, (trap_a,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    second, (trap_b,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(first, trap_a)
    next_turn(first, P1)
    next_turn(first, P0)

    assert [a.source for a in activations(first, P0, GIFT_OF_GREED)] == [trap_a]
    #: 두 번째 듀얼은 아직 세우지도 않았다 — 첫 듀얼의 기록이 새지 않는다.
    assert activations(second, P0, GIFT_OF_GREED) == []
    set_down(second, trap_b)
    assert activations(second, P0, GIFT_OF_GREED) == [], "세트한 턴이다"


# ======================================================================
# H. 기존 기능 회귀 (§11-L · §11-M · §18-15)
# ======================================================================


@pytest.mark.real_card
def test_h01_a_normal_spell_still_needs_its_own_turn_and_main_phase(repository):
    """
    🔴 **§11-L — 마법에 걸던 요구가 그대로다.** 함정에 걸지 않은 것이
    마법에서 풀린 것이 아니다.
    """
    duel, (spell,), _ = staged(repository, mine=(POT_OF_GREED,))
    next_turn(duel, P1, phase=Phase.BATTLE)
    verdict = informed(duel).validate(made(P0, spell, POT_OF_GREED))
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.NOT_TURN_PLAYER


@pytest.mark.real_card
def test_h02_a_set_quick_play_spell_is_unchanged(repository):
    """**세트한 속공 마법의 판정이 변하지 않았다** (Phase 3-E-15)."""
    duel, (reload_card,), _ = staged(repository, mine=(RELOAD,), fodder=2)
    set_down(duel, reload_card)
    assert activations(duel, P0, RELOAD) == [], "세트한 턴이다"
    next_turn(duel, P1)
    next_turn(duel, P0)
    assert [a.source for a in activations(duel, P0, RELOAD)] == [reload_card]


@pytest.mark.real_card
def test_h03_the_honest_monster_effect_is_unchanged(repository):
    """**§11-M — Phase 6-L 의 어니스트가 그대로다.**"""
    HONEST = 37742478
    definition = DEFS.definition_for(EffectRef(HONEST, 0))
    assert definition is not None
    assert definition.references_self
    #: 축을 적지 않았다 — 함정이 아니므로 읽히지 않는다.
    assert definition.activation_waits_for_event is None


@pytest.mark.real_card
def test_h04_reading_legal_actions_changes_nothing(repository):
    """**후보를 몇 번 만들어도 판이 바뀌지 않는다** (읽기만 한다)."""
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    before = (duel.state.state_hash(), duel.state.randomness.draws)
    for _ in range(3):
        duel.legal_actions(P0)
        duel.legal_actions(P1)
    assert (duel.state.state_hash(), duel.state.randomness.draws) == before


@pytest.mark.real_card
def test_h05_the_opponent_still_learns_nothing_about_a_set_trap(repository):
    """
    **§3-12 — 세트한 함정의 정체가 상대에게 새지 않는다.**

    발동 후보가 생겼다는 것이 정보 누출이 되어서는 안 된다 — 후보는
    **컨트롤러의** 목록이다.
    """
    duel, (trap,), _ = staged(repository, mine=(GIFT_OF_GREED,))
    set_down(duel, trap)
    next_turn(duel, P1)
    next_turn(duel, P0)
    assert activations(duel, P0, GIFT_OF_GREED)
    #: 상대의 목록에는 없다.
    assert activations(duel, P1, GIFT_OF_GREED) == []
    seen = [
        c
        for c in duel.view(P1).opponent.zone(Zone.SZONE).cards
        if c is not None
    ]
    assert [(c.card_id, c.name, c.definition) for c in seen] == [(None, None, None)]
