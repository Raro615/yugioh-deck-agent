"""
Phase 2-S — 발동 타이밍 / 스펠 스피드.

    ActivationTiming (체인 · 우선권 · 시점)
        ↓  ActivationTimingChecker.check(timing, action)
    ValidationResult        VALID · INVALID · UNKNOWN
        ↓  ResponseLoop.act()  ← 관문 하나가 더 생겼다
    EffectActivator (2-Q)  →  ChainLink

이 파일이 지키려는 것은 셋이다.

1. **규칙을 지어내지 않았다.** 스펠 스피드 표는 공식 룰북 구조화
   (``data/rules/structured/``) 에서 왔고, 엔진의 사본이 원본과 어긋나면
   테스트가 깨진다.
2. **모르는 것을 위반으로 접지 않는다.** 몬스터 효과의 스펠 스피드는
   이 엔진이 모르고, 그것은 ``UNKNOWN`` 이지 ``INVALID`` 가 아니다.
3. **``VALID`` 가 "발동해도 된다" 가 아니다.** 관문 하나를 통과했을 뿐이고,
   무엇을 보지 않았는지가 결과에 적혀 있다.
"""

import ast
import json
import pathlib

import pytest

from engine.action import PlayerAction
from engine.activation import EffectActivator
from engine.activation_timing import (
    MONSTER_CLASSIFICATION_MISSING,
    RESPONSE_TABLE,
    SPEED_RULES,
    UNRESOLVED_TIMING_RULES,
    ActivationTiming,
    ActivationTimingChecker,
    SpellSpeed,
    SpellSpeedClassification,
    classify_spell_speed,
)
from engine.chain import Chain
from engine.condition import IsMonster
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.executor import EffectImplementationRegistry
from engine.effect.operation import CardOperation
from engine.effect.resolution import TargetSelection
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityHolder, PriorityState, ResponseWindow
from engine.response import ResponseLoop, ResponseOutcome
from engine.state.game_state import GameState
from engine.trigger import TimingPoint
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

A_SEAT, B_SEAT = 0, 1

# --- 실제 카드 (§12) ---------------------------------------------------
TYPHOON = 5318639  # 싸이크론 — SPELL / QUICKPLAY. LUA_VERIFIED · executable
POT = 55144522  # 욕망의 항아리 — SPELL. LUA_VERIFIED · executable
JUDGMENT = 41420027  # 신의 심판 — TRAP / COUNTER. **분류에만** 쓴다
MIRROR_FORCE = 44095762  # 성스러운 방어막 거울의 힘 — TRAP
FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — MONSTER / NORMAL

LAB = 2511  # synthetic 정의의 껍데기
PRIMARY = PRIMARY_TARGET
EFFECT_X = EffectRef(LAB, 0)
EFFECT_Y = EffectRef(LAB, 1)

GRANTED = ValidationResult.valid("테스트가 발동 타이밍을 허가했다")

STRUCTURED = pathlib.Path("data/rules/structured/sd-rulebook-en-v10.json")


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository) -> GameState:
    """
    양쪽이 **각 종류의 카드를 한 장씩** 앞면으로 들고 있는 판.

    p0(A) SZONE 싸이크론(속공) · 욕망의 항아리(일반 마법) · 신의 심판(카운터)
    p1(B) SZONE 싸이크론(속공) · 거울의 힘(일반 함정) · 뒷면 카드 1장
    양쪽 MZONE 페더맨 1장, A 의 패에 페더맨 1장
    """
    game = GameState.create(
        repository,
        decks=(
            [FEATHERMAN, TYPHOON, POT, JUDGMENT] + [FEATHERMAN] * 16,
            [FEATHERMAN, TYPHOON, MIRROR_FORCE, MIRROR_FORCE] + [FEATHERMAN] * 16,
        ),
    )
    game.draw(A_SEAT, 5)
    game.draw(B_SEAT, 5)
    for seat, faceups in ((A_SEAT, 3), (B_SEAT, 2)):
        game.move(
            game.player(seat).hand[0], Zone.MZONE, to_player=seat,
            position=Position.FACEUP_ATTACK,
        )
        for _ in range(faceups):
            game.move(
                game.player(seat).hand[0], Zone.SZONE, to_player=seat,
                position=Position.FACEUP,
            )
    # B 의 네 번째 카드는 **뒷면**으로 세트한다 — 정체를 모르는 경우용.
    game.move(
        game.player(B_SEAT).hand[0], Zone.SZONE, to_player=B_SEAT,
        position=Position.FACEDOWN,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def find(state: GameState, seat: int, card_id: int) -> InstanceId:
    for card in state.player(seat).spell_zone:
        if card.card_id == card_id:
            return card.instance_id
    raise AssertionError(f"P{seat} 의 마법/함정 존에 {card_id} 가 없습니다.")


def a_typhoon(state: GameState) -> InstanceId:
    return find(state, A_SEAT, TYPHOON)


def a_pot(state: GameState) -> InstanceId:
    return find(state, A_SEAT, POT)


def a_judgment(state: GameState) -> InstanceId:
    return find(state, A_SEAT, JUDGMENT)


def b_typhoon(state: GameState) -> InstanceId:
    return find(state, B_SEAT, TYPHOON)


def b_mirror(state: GameState) -> InstanceId:
    return find(state, B_SEAT, MIRROR_FORCE)


def b_facedown(state: GameState) -> InstanceId:
    return state.player(B_SEAT).spell_zone[-1].instance_id


def a_monster(state: GameState) -> InstanceId:
    return state.player(A_SEAT).monster_zone[0].instance_id


def b_monster(state: GameState) -> InstanceId:
    return state.player(B_SEAT).monster_zone[0].instance_id


def checker(state: GameState, seat: int = B_SEAT) -> ActivationTimingChecker:
    return ActivationTimingChecker(GameStateView.from_state(state, viewer=seat))


def timing(chain: Chain = Chain(), holder: int = B_SEAT) -> ActivationTiming:
    return ActivationTiming(
        chain,
        PriorityState.opened(
            ResponseWindow.RESPONSE, holder, turn_player=A_SEAT, phase=Phase.MAIN1
        ),
    )


def chain_with(source: InstanceId, actor: int = A_SEAT) -> Chain:
    """``source`` 가 발동한 링크 하나짜리 체인."""
    return Chain().activate(actor=actor, effect_ref=EFFECT_X, source=source)


def activation(seat: int, source: InstanceId) -> PlayerAction:
    return PlayerAction.activate_effect(
        actor=seat, source=source, effect_ref=EFFECT_Y
    )


def destroy_effect(ordinal: int) -> EffectDefinition:
    """synthetic 정의 — 어떤 실제 카드의 의미도 주장하지 않는다."""
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({Zone.MZONE}), owner=None, require=IsMonster()
                    )
                )
            )
        ),
        operations=(CardOperation.destroy(PRIMARY),),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(
            verified=True, note="Phase 2-S 타이밍 시험"
        ),
    )


def response_loop() -> ResponseLoop:
    held = EffectDefinitionRegistry((destroy_effect(0), destroy_effect(1)))
    return ResponseLoop(
        EffectActivator(
            held, EffectImplementationRegistry((EFFECT_X, EFFECT_Y))
        )
    )


def picked(*instances: InstanceId):
    return (TargetSelection(PRIMARY, Selection.of(*instances)),)


# ======================================================================
# A. 규칙의 출처 — 지어내지 않았다
# ======================================================================


def test_a_the_engine_table_matches_the_official_rulebook():
    """
    🔒 **엔진의 사본이 문서 계층과 어긋나면 여기서 깨진다.**

    ``engine`` 은 ``rules`` 를 import 하지 않는다 (실행 계층이 데이터 파일에
    묶이지 않게). 대신 이 테스트가 둘을 대조한다 —
    ``engine/effect/library.py`` 가 Lua 원문을 근거로 들고 다니는 것과 같은
    자리다.
    """
    raw = json.loads(STRUCTURED.read_text("utf-8"))["chain"]["spell_speeds"]
    official = {
        entry["speed"]: frozenset(entry["can_respond_to"]) for entry in raw
    }
    mine = {
        speed.value: frozenset(other.value for other in answers)
        for speed, answers in RESPONSE_TABLE.items()
    }

    assert mine == official
    assert set(official) == {1, 2, 3}


def test_a_every_speed_cites_the_rule_it_came_from():
    raw = json.loads(STRUCTURED.read_text("utf-8"))["chain"]["spell_speeds"]
    official = {entry["speed"]: set(entry["rules"]) for entry in raw}

    for speed, rules in SPEED_RULES.items():
        assert set(rules) == official[speed.value]


def test_a_the_engine_does_not_import_the_document_layer():
    """실행 계층이 문서 계층을 읽으면 런타임이 데이터 파일에 묶인다."""
    tree = ast.parse(pathlib.Path("engine/activation_timing.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not any(module.startswith("rules") for module in imported)


def test_a_spell_speed_one_cannot_respond_to_anything():
    """
    RULE-CHAIN-004 — 숫자 비교(``>=``)로 대신할 수 없는 규칙이다. 비교식만
    쓰면 "1 은 1 에 응수할 수 있다" 가 되어 버린다.
    """
    assert SpellSpeed.NORMAL.can_respond_to == frozenset()
    assert SpellSpeed.NORMAL.responds_to(SpellSpeed.NORMAL) is False
    assert SpellSpeed.FAST.responds_to(SpellSpeed.NORMAL) is True


def test_a_there_is_no_unknown_member_in_the_enum():
    """
    ``UNKNOWN`` 을 멤버로 두면 ``speed >= other`` 같은 비교에 조용히 섞인다.
    모른다는 것은 ``speed=None`` 이 말한다.
    """
    assert [s.name for s in SpellSpeed] == ["NORMAL", "FAST", "COUNTER"]
    assert [s.value for s in SpellSpeed] == [1, 2, 3]


# ======================================================================
# B. 분류 — 실제 카드 (§12)
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "card_id, expected, basis_fragment",
    [
        (TYPHOON, SpellSpeed.FAST, "QUICKPLAY"),
        (POT, SpellSpeed.NORMAL, "SPELL"),
        (JUDGMENT, SpellSpeed.COUNTER, "COUNTER"),
        (MIRROR_FORCE, SpellSpeed.FAST, "TRAP"),
    ],
)
def test_b_a_real_cards_type_decides_its_speed(
    repository, card_id, expected, basis_fragment
):
    from engine.game_state_view import CardDefinitionView

    found = classify_spell_speed(
        CardDefinitionView.of(repository.get(card_id))
    )

    assert found.speed is expected
    assert basis_fragment in found.basis
    assert found.rules  # 근거 규칙 번호가 붙어 있다
    assert found.missing is None


@requires_official_db
def test_b_a_monsters_speed_is_unknown_not_guessed(repository):
    """
    **추측하지 않는다.** 기동 효과면 1, 유발즉시면 2 인데 그 분류가 이
    엔진에 없다 — 1 로 만들면 퀵 이펙트가 영영 응수하지 못하고, 2 로 만들면
    기동 효과가 상대 턴에 발동한다.
    """
    from engine.game_state_view import CardDefinitionView

    found = classify_spell_speed(
        CardDefinitionView.of(repository.get(FEATHERMAN))
    )

    assert found.speed is None
    assert found.is_known is False
    assert found.missing == MONSTER_CLASSIFICATION_MISSING


def test_b_a_classification_cannot_be_half_known():
    with pytest.raises(ValueError):
        SpellSpeedClassification(None, "모르겠다")  # missing 없음
    with pytest.raises(ValueError):
        SpellSpeedClassification(SpellSpeed.FAST, "안다", missing="무언가")


@requires_official_db
def test_b_a_face_down_card_has_no_readable_speed(state):
    """뒷면은 **정체를 모르는 것**이지 "속도가 없는 것" 이 아니다."""
    found = checker(state, A_SEAT).spell_speed(b_facedown(state))

    assert found.speed is None
    assert found.missing == "face-down card identity"


@requires_official_db
def test_b_a_card_outside_the_observation_is_not_a_missing_card(state):
    found = checker(state).spell_speed(InstanceId(9999))

    assert found.speed is None
    assert found.missing == "hidden card identity"


@requires_official_db
def test_b_the_owner_can_read_their_own_face_down_card(state):
    """같은 판이라도 **누가 보는가**에 따라 답이 다르다. 정보 경계다."""
    theirs = checker(state, B_SEAT).spell_speed(b_facedown(state))

    assert theirs.speed is SpellSpeed.FAST  # 거울의 힘 = 일반 함정


# ======================================================================
# C. §9 시나리오 A~G
# ======================================================================


@requires_official_db
def test_c_scenario_a_an_empty_chain_puts_no_speed_constraint(state):
    """A — 체인이 없으면 응수가 아니므로 스펠 스피드가 걸리지 않는다."""
    verdict = checker(state, A_SEAT).check(
        timing(Chain(), A_SEAT), activation(A_SEAT, a_pot(state))
    )

    assert verdict.validity is ActionValidity.VALID
    assert verdict.code is ValidationCode.OK


@requires_official_db
def test_c_scenario_b_a_quickplay_may_answer_a_quickplay(state):
    """B — 속공 마법(2)이 속공 마법(2)에 응수한다."""
    verdict = checker(state).check(
        timing(chain_with(a_typhoon(state))), activation(B_SEAT, b_typhoon(state))
    )

    assert verdict.validity is ActionValidity.VALID
    assert "스펠 스피드 2" in verdict.reason


@requires_official_db
def test_c_scenario_c_a_normal_spell_may_not_answer_anything(state):
    """C — 일반 마법(1)은 무엇에도 응수할 수 없다."""
    verdict = checker(state, A_SEAT).check(
        timing(chain_with(b_typhoon(state), actor=B_SEAT), A_SEAT),
        activation(A_SEAT, a_pot(state)),
    )

    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SPELL_SPEED_TOO_LOW


@requires_official_db
def test_c_scenario_d_a_counter_trap_may_answer_a_counter_trap(state):
    """D — 카운터 함정(3)만이 카운터 함정(3)에 응수할 수 있다."""
    counter_chain = chain_with(a_judgment(state))

    by_counter = checker(state, A_SEAT).check(
        counter_chain and timing(counter_chain, A_SEAT),
        activation(A_SEAT, a_judgment(state)),
    )
    by_quickplay = checker(state).check(
        timing(counter_chain), activation(B_SEAT, b_typhoon(state))
    )

    assert by_counter.validity is ActionValidity.VALID
    assert by_quickplay.validity is ActionValidity.INVALID
    assert by_quickplay.code is ValidationCode.SPELL_SPEED_TOO_LOW


@requires_official_db
def test_c_scenario_e_priority_is_a_different_question(state):
    """
    E — 차례가 아닌 사람의 응답은 **우선권** 계층이 막는다. 타이밍 판정은
    그것을 다시 하지 않는다 — 두 벌이 갈린다.
    """
    machine = response_loop()
    response = ResponseLoop.opened(
        chain_with(a_typhoon(state)),
        PriorityHolder.of(B_SEAT),
        turn_player=A_SEAT,
        phase=Phase.MAIN1,
    )
    before = state.state_hash()

    result = machine.act(
        state,
        response,
        activation(A_SEAT, a_typhoon(state)),  # A 차례가 아니다
        picked(b_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.REFUSED
    assert result.code is ValidationCode.NOT_PRIORITY_HOLDER
    assert result.timing is None  # 타이밍 관문까지 가지도 않았다
    assert state.state_hash() == before


@requires_official_db
def test_c_scenario_f_an_unreadable_link_is_unknown_not_illegal(state):
    """
    F — 응수할 링크의 정체를 모르면 **모른다.** 뒷면 카드가 발동한 링크다.
    """
    verdict = checker(state, A_SEAT).check(
        timing(chain_with(b_facedown(state), actor=B_SEAT), A_SEAT),
        activation(A_SEAT, a_typhoon(state)),
    )

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert verdict.missing_rule == "face-down card identity"


@requires_official_db
def test_c_scenario_g_a_monster_response_is_unknown_not_illegal(state):
    """
    G — 몬스터 효과로 응수하려 한다. 스펠 스피드를 모르므로 ``UNKNOWN`` 이고,
    **위반으로 접지 않는다.**
    """
    verdict = checker(state).check(
        timing(chain_with(a_typhoon(state))),
        activation(B_SEAT, b_monster(state)),
    )

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == MONSTER_CLASSIFICATION_MISSING


# ======================================================================
# D. VALID 는 "발동해도 된다" 가 아니다
# ======================================================================


@requires_official_db
def test_d_a_passing_verdict_carries_what_it_did_not_check(state):
    verdict = checker(state).check(
        timing(chain_with(a_typhoon(state))), activation(B_SEAT, b_typhoon(state))
    )

    assert verdict.validity is ActionValidity.VALID
    assert set(UNRESOLVED_TIMING_RULES) <= set(verdict.notes)
    assert "판정하지 않았습니다" in verdict.reason


def test_d_the_checker_lists_what_it_cannot_answer():
    """미구현은 **숨기지 않고** 적어 둔다."""
    for rule in ("페이즈", "1턴에 1번", "타이밍 놓침", "데미지 스텝"):
        assert any(rule in line for line in UNRESOLVED_TIMING_RULES)


@requires_official_db
def test_d_the_gate_narrows_and_never_widens(state):
    """
    타이밍 관문을 통과해도 **허가는 여전히 따로 받아야 한다.** 통과가 곧
    발동 허가라면 이 관문이 규칙을 넓히는 것이 된다.
    """
    machine = response_loop()
    response = ResponseLoop.opened(
        chain_with(a_typhoon(state)),
        PriorityHolder.of(B_SEAT),
        turn_player=A_SEAT,
        phase=Phase.MAIN1,
    )

    allowed = machine.check_timing(
        state, response, activation(B_SEAT, b_typhoon(state))
    )
    without_grant = machine.act(
        state,
        response,
        activation(B_SEAT, b_typhoon(state)),
        picked(a_monster(state)),
    )

    assert allowed.validity is ActionValidity.VALID  # 관문은 통과했는데
    assert without_grant.outcome is ResponseOutcome.REFUSED  # 발동은 안 된다


@requires_official_db
def test_d_the_checker_never_touches_the_board(state):
    before = state.state_hash()
    judge = checker(state)

    for _ in range(3):
        judge.check(
            timing(chain_with(a_typhoon(state))), activation(B_SEAT, b_typhoon(state))
        )
        judge.spell_speed(b_typhoon(state))

    assert state.state_hash() == before


@requires_official_db
def test_d_the_checker_refuses_a_mutable_board(state):
    with pytest.raises(TypeError):
        ActivationTimingChecker(state)


# ======================================================================
# E. ResponseLoop 연결 (§7)
# ======================================================================


@requires_official_db
def test_e_a_quickplay_response_reaches_the_chain(state):
    machine = response_loop()
    response = ResponseLoop.opened(
        chain_with(a_typhoon(state)),
        PriorityHolder.of(B_SEAT),
        turn_player=A_SEAT,
        phase=Phase.MAIN1,
    )

    result = machine.act(
        state,
        response,
        activation(B_SEAT, b_typhoon(state)),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.LINK_ADDED
    assert len(result.chain) == 2
    assert result.timing is not None
    assert result.timing.validity is ActionValidity.VALID


@requires_official_db
def test_e_a_spell_speed_violation_never_reaches_the_activator(state):
    """
    **비용을 치르기 전에** 멈춘다. 발동 계층을 부르지도 않는다.
    """
    machine = response_loop()
    response = ResponseLoop.opened(
        chain_with(b_typhoon(state), actor=B_SEAT),
        PriorityHolder.of(A_SEAT),
        turn_player=A_SEAT,
        phase=Phase.MAIN1,
    )
    before = state.state_hash()

    result = machine.act(
        state,
        response,
        activation(A_SEAT, a_pot(state)),  # 일반 마법으로 응수
        picked(b_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.REFUSED
    assert result.code is ValidationCode.SPELL_SPEED_TOO_LOW
    assert result.timing is not None
    assert result.activation is None  # 발동 계층까지 가지 않았다
    assert len(result.chain) == 1
    assert state.state_hash() == before


@requires_official_db
def test_e_the_two_gates_are_distinguishable(state):
    """
    §5 — 어느 관문이 막았는지 결과에서 읽힌다. 하나로 뭉개면 무엇을 고쳐야
    하는지 알 수 없다.
    """
    machine = response_loop()
    response = ResponseLoop.opened(
        chain_with(a_typhoon(state)),
        PriorityHolder.of(B_SEAT),
        turn_player=A_SEAT,
        phase=Phase.MAIN1,
    )

    by_timing = machine.act(
        state,
        response,
        activation(B_SEAT, b_monster(state)),  # 몬스터 → UNKNOWN
        picked(a_monster(state)),
        authorization=GRANTED,
    )
    by_activation = machine.act(
        state,
        response,
        activation(B_SEAT, b_typhoon(state)),  # 타이밍은 통과
        authorization=GRANTED,  # 대상 없음 → 발동에서 거절
    )

    assert by_timing.timing is not None and by_timing.activation is None
    assert by_activation.timing is not None and by_activation.activation is not None
    assert by_activation.code is ValidationCode.TOO_FEW_SELECTED


@requires_official_db
def test_e_an_unknown_speed_is_not_a_permission(state):
    """
    **``UNKNOWN`` 은 허가가 아니다.** 몬스터 효과로는 아직 응수할 수 없다 —
    할 수 없어서가 아니라, 할 수 있는지 모르기 때문이다.
    """
    machine = response_loop()
    response = ResponseLoop.opened(
        chain_with(a_typhoon(state)),
        PriorityHolder.of(B_SEAT),
        turn_player=A_SEAT,
        phase=Phase.MAIN1,
    )
    before = state.state_hash()

    result = machine.act(
        state,
        response,
        activation(B_SEAT, b_monster(state)),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.REFUSED
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing == MONSTER_CLASSIFICATION_MISSING
    assert len(result.chain) == 1
    assert state.state_hash() == before


@requires_official_db
def test_e_passing_is_untouched_by_the_new_gate(state):
    """§8 — 패스는 여전히 효과가 아니다. 타이밍 관문을 지나지도 않는다."""
    machine = response_loop()
    response = ResponseLoop.opened(
        chain_with(a_typhoon(state)),
        PriorityHolder.of(B_SEAT),
        turn_player=A_SEAT,
        phase=Phase.MAIN1,
    )
    before = state.state_hash()

    result = machine.act(state, response, PlayerAction.passing(B_SEAT))

    assert result.outcome is ResponseOutcome.PASSED
    assert result.timing is None
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_e_the_loop_still_does_not_execute_effects():
    """§7 — 관문이 하나 늘었다고 실행기를 부르게 되지 않는다."""
    tree = ast.parse(pathlib.Path("engine/response.py").read_text("utf-8"))
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert "EffectExecutor" not in used
    assert "execute" not in used
    assert "resolve_all" in used  # 해결은 여전히 기존 해결기에 넘긴다


# ======================================================================
# F. 트리거와 응답은 여전히 별개다 (§10)
# ======================================================================


def test_f_the_timing_checker_knows_nothing_about_triggers():
    tree = ast.parse(pathlib.Path("engine/activation_timing.py").read_text("utf-8"))
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for name in ("TriggerCollector", "TriggerChainIntegrator", "TriggerOrderer"):
        assert name not in used
    # ``TimingPoint`` 는 **시점의 이름**으로만 쓴다 — 트리거 수집은 하지 않는다.
    assert "TimingPoint" in used


def test_f_the_trigger_layer_does_not_ask_about_spell_speed():
    """반대 방향도 막혀 있다."""
    for path in ("engine/trigger.py", "engine/trigger_chain.py", "engine/trigger_order.py"):
        tree = ast.parse(pathlib.Path(path).read_text("utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "engine.activation_timing" not in imported, path


def test_f_no_second_timing_system_was_built():
    """§19 — 새 Timing / Priority / Chain 시스템을 만들지 않았다."""
    tree = ast.parse(pathlib.Path("engine/activation_timing.py").read_text("utf-8"))
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert defined == {
        "SpellSpeed",
        "SpellSpeedClassification",
        "ActivationTiming",
        "ActivationTimingChecker",
    }
    for forbidden in ("TimingEvent", "TimingWindow", "PriorityState", "Chain"):
        assert forbidden not in defined


def test_f_the_context_stores_nothing_twice():
    """
    §4 — ``ActivationTiming`` 은 세 값을 **참조로만** 담는다. 페이즈 ·
    턴 플레이어는 관측이 이미 들고 있으므로 여기 없다.
    """
    fields = set(ActivationTiming.__dataclass_fields__)

    assert fields == {"chain", "priority", "point"}
    for copied in ("phase", "turn_player", "holder", "actor"):
        assert copied not in fields


@requires_official_db
def test_f_the_context_holds_references_not_copies(state):
    chain = chain_with(a_typhoon(state))
    priority = PriorityState.idle(turn_player=A_SEAT)

    context = ActivationTiming(chain, priority, TimingPoint.CARD_MOVED)

    assert context.chain is chain
    assert context.priority is priority
    assert context.responding_to is chain[0]


# ======================================================================
# G. 실패 안전성 · 결정론 · 정보 경계
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "name, seat, source_of, holder",
    [
        ("우선권 없음", A_SEAT, "a_typhoon", B_SEAT),
        ("스펠 스피드 위반", A_SEAT, "a_pot", A_SEAT),
        ("스펠 스피드 미상", B_SEAT, "b_monster", B_SEAT),
    ],
)
def test_g_a_refused_response_changes_nothing(state, name, seat, source_of, holder):
    sources = {
        "a_typhoon": a_typhoon,
        "a_pot": a_pot,
        "b_monster": b_monster,
    }
    machine = response_loop()
    chain = chain_with(b_typhoon(state), actor=B_SEAT) if seat == A_SEAT else (
        chain_with(a_typhoon(state))
    )
    response = ResponseLoop.opened(
        chain, PriorityHolder.of(holder), turn_player=A_SEAT, phase=Phase.MAIN1
    )
    before = state.state_hash()

    result = machine.act(
        state,
        response,
        activation(seat, sources[source_of](state)),
        picked(a_monster(state)),
        authorization=GRANTED,
    )

    assert result.outcome is ResponseOutcome.REFUSED, name
    assert result.link is None, name
    assert len(result.chain) == 1, name
    assert result.chain is chain, name
    assert state.state_hash() == before, name


@requires_official_db
def test_g_the_same_inputs_give_the_same_verdict(repository):
    first, second = new_state(repository), new_state(repository)

    left = checker(first).check(
        timing(chain_with(a_typhoon(first))), activation(B_SEAT, b_typhoon(first))
    )
    right = checker(second).check(
        timing(chain_with(a_typhoon(second))), activation(B_SEAT, b_typhoon(second))
    )

    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_g_unknown_verdicts_are_deterministic_too(repository):
    first, second = new_state(repository), new_state(repository)

    left = checker(first).check(
        timing(chain_with(a_typhoon(first))), activation(B_SEAT, b_monster(first))
    )
    right = checker(second).check(
        timing(chain_with(a_typhoon(second))), activation(B_SEAT, b_monster(second))
    )

    assert left.canonical_state() == right.canonical_state()
    assert left.validity is ActionValidity.UNKNOWN


@requires_official_db
def test_g_a_clone_answers_the_same_way(state):
    copy = state.clone()

    here = checker(state).check(
        timing(chain_with(a_typhoon(state))), activation(B_SEAT, b_typhoon(state))
    )
    there = checker(copy).check(
        timing(chain_with(a_typhoon(copy))), activation(B_SEAT, b_typhoon(copy))
    )

    assert here.canonical_state() == there.canonical_state()
    assert state.state_hash() == copy.state_hash()


@requires_official_db
def test_g_a_refusal_names_no_hidden_card(state):
    """§15 — 판정 결과가 상대의 뒷면 카드 정체를 말하지 않는다."""
    verdict = checker(state, A_SEAT).check(
        timing(chain_with(b_facedown(state), actor=B_SEAT), A_SEAT),
        activation(A_SEAT, a_typhoon(state)),
    )
    text = str(verdict.to_dict())

    assert str(MIRROR_FORCE) not in text
    assert "거울" not in text


@requires_official_db
def test_g_the_classification_leaks_no_card_id(state):
    found = checker(state, A_SEAT).spell_speed(b_facedown(state))

    assert str(MIRROR_FORCE) not in str(found.to_dict())


def test_g_the_checker_makes_no_decision_of_its_own():
    """§16 — 발동할 것인가는 이 계층의 질문이 아니다."""
    source = pathlib.Path("engine/activation_timing.py").read_text("utf-8")
    tree = ast.parse(source)
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for forbidden in ("choose", "decide", "score", "policy", "best"):
        assert not any(forbidden in name for name in functions)
    assert "random" not in source
