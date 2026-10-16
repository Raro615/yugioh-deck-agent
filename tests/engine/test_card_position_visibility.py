"""
Phase 6-N — **표시 형식과 정보 가시성.**

    CardInstance.position (여덟 값)
        ↓  is_faceup                      ← 앞뒷면만 답한다
    FACE_SENSITIVE_ZONES                  ← 그 질문이 뜻을 갖는 자리
        ↓                       ↓
    _face_visibility        BoardRuling._interference
    (정체가 보이는가)          (그 카드가 효과를 적용하는가)

이 파일이 지키는 것
-------------------
🔴 **같은 판이 같은 답을 낸다.** 6-N 전에는 묘지의 미등록 카드가 **어떻게
거기 갔는지**에 따라 판정이 갈렸다 — 필드에서 앞면으로 간 카드는
``UNKNOWN``, 패에서 버려진 카드는 ``TRUE`` 였다. 버려진 카드는
``position`` 이 ``FACEDOWN`` 인 채 묘지에 있고, ``_interference`` 가 그것을
"세트된 카드" 로 읽어 **건너뛰었다** (§D).

🔴 **한 사실을 두 벌로 적지 않는다.** "이 자리에서 앞뒷면이 뜻을 갖는가" 를
묻는 곳이 둘이고, 둘이 **같은 목록**을 읽는다 (§E).

🔴 **표시 형식과 공개 범위는 다른 축이다.** 패와 덱은 **자리**로 가려지고
(앞뒷면과 무관하다), 필드와 제외 구역은 **앞뒷면**으로 가려진다 (§C).

🔴 **모르는 것을 앞면으로 읽지 않는다.** ``Position.ATTACK`` ·
``Position.DEFENSE`` 는 앞뒷면을 말하지 않는 값이고, ``is_faceup`` 이
거짓을 돌려준다 — 그것이 공백이고, 공백을 수치로 적는다 (§A).

🔴 **지원하지 않는 행동을 실행하지 않는다.** 표시 형식 변경과 리버스
소환은 미지원이고 6-N 이 그것을 바꾸지 않았다 (§B).
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.condition import CardIsFaceUp, ConditionContext, ConditionResult
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.condition import PlayerRef
from engine.duel import Duel
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    HONEST,
    OPERATION_RULINGS,
    definition_registry,
)
from engine.effect.operation import CardOperation, OperationKind
from engine.effect.resolution import ResolutionContext, ResolutionStatus
from engine.effect.ruling import BoardRuling, INTERFERENCE_ZONES
from engine.effect.semantics import (
    FIELD_ZONES,
    MISSING_SAME_ZONE_MOVEMENT,
    RuleQuestion,
)
from engine.effect.target import (
    PRIMARY_TARGET,
    SELF_TARGET,
    TargetBinding,
    TargetSelection,
    TargetSpec,
)
from engine.game_state_view import FACE_SENSITIVE_ZONES, GameStateView
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.spell_activation import ACTIVATION_POSITION, duel_components
from engine.state.card_instance import CardInstance
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

HONEST_REF = EffectRef(HONEST, 0)
#: 엘리멘틀 히어로 페더맨 — 통상 몬스터이고 ``OPERATION_RULINGS`` 에 **있다.**
FEATHERMAN = 21844576
#: 사파이어 드래곤 — ``OPERATION_RULINGS`` 에 **없다.** 간섭 사례에 쓴다.
UNREGISTERED = 11091375

#: 앞면을 말하는 값들 — ``CardInstance.is_faceup`` 이 참인 셋.
FACE_UP_POSITIONS = (
    Position.FACEUP,
    Position.FACEUP_ATTACK,
    Position.FACEUP_DEFENSE,
)
#: 뒷면을 말하는 값들.
FACE_DOWN_POSITIONS = (
    Position.FACEDOWN,
    Position.FACEDOWN_ATTACK,
    Position.FACEDOWN_DEFENSE,
)
#: 🔴 **앞뒷면을 말하지 않는** 값들. 공백이다 (§A-03).
FACE_SILENT_POSITIONS = (Position.ATTACK, Position.DEFENSE)


# ======================================================================
# 판 만들기
# ======================================================================


def new_state(repository, deck_card: int = FEATHERMAN) -> GameState:
    return GameState.create(
        repository, decks=([deck_card] * 20, [deck_card] * 20), seed=1
    )


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def honest_verdict(state, honest_instance) -> "tuple":
    """그 판에서 어니스트 ① 의 이동 판정과 실제 해결 결과."""
    view = GameStateView.from_state(state, viewer=MINE)
    verdict = BoardRuling(view, OPERATION_RULINGS).explain(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, honest_instance
    )
    definition = definition_registry().definition_for(HONEST_REF)
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((HONEST_REF,)),
        rulings=OPERATION_RULINGS,
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=HONEST_REF, controller=MINE, source=honest_instance
        ),
    )
    return verdict, result


# ======================================================================
# A. 표시 형식 모델 — 무엇을 말하고 무엇을 말하지 않는가 (§4-A · §5)
# ======================================================================


def test_a01_position_has_exactly_eight_values():
    """
    **§4-A 1 · 2 · 3** — 표시 형식 필드가 **있고**, 앞뒷면과 공격·수비를
    한 값에 함께 담는다.

    6-N 은 여기에 값을 더하지도 빼지도 않았다 (§3-4).
    """
    assert [p.value for p in Position] == [
        "FACEUP_ATTACK",
        "FACEDOWN_ATTACK",
        "FACEUP_DEFENSE",
        "FACEDOWN_DEFENSE",
        "FACEUP",
        "FACEDOWN",
        "ATTACK",
        "DEFENSE",
    ]
    assert "position" in CardInstance.__dataclass_fields__


@pytest.mark.parametrize("position", FACE_UP_POSITIONS)
def test_a02_the_face_up_values_read_as_face_up(position):
    """세 값이 앞면이다 — 몬스터의 둘과 마법·함정의 하나."""
    card = CardInstance(
        instance_id=None, card_id=1, owner=MINE, controller=MINE,
        zone=Zone.MZONE, position=position,
    )
    assert card.is_faceup is True


@pytest.mark.parametrize("position", FACE_DOWN_POSITIONS)
def test_a03_the_face_down_values_read_as_face_down(position):
    """셋이 뒷면이다."""
    card = CardInstance(
        instance_id=None, card_id=1, owner=MINE, controller=MINE,
        zone=Zone.MZONE, position=position,
    )
    assert card.is_faceup is False


@pytest.mark.parametrize("position", FACE_SILENT_POSITIONS)
def test_a04_two_values_say_nothing_about_the_face(position):
    """
    🔴 **남은 공백을 수치로 적는다** (§13-1).

    ``ATTACK`` · ``DEFENSE`` 는 **공격·수비만** 말하고 앞뒷면을 말하지
    않는다. 그런데 ``is_faceup`` 은 두 값을 돌려주는 함수이므로 **거짓**을
    준다 — 즉 "모른다" 가 "뒷면" 으로 읽힌다.

    6-N 이 이것을 고치지 않은 이유: production 이 그 두 값을 **아무 데서도
    만들지 않는다** (``test_a05``). 고치려면 ``is_faceup`` 의 반환형을
    세 값으로 넓혀야 하고, 그것은 그 속성을 읽는 모든 자리의 계약 변경이다
    (§3-1). 공백으로 적어 둔다 (보고서 §17).
    """
    card = CardInstance(
        instance_id=None, card_id=1, owner=MINE, controller=MINE,
        zone=Zone.MZONE, position=position,
    )
    #: 현재 동작을 **사실로** 적는다 — 바람직하다는 뜻이 아니다.
    assert card.is_faceup is False


def test_a05_production_never_creates_a_face_silent_position():
    """
    🔴 ``test_a04`` 의 공백이 **왜 닿지 않는가.**

    표시 형식을 정하는 production 상수를 전수로 센다. 넷뿐이고 넷 다
    앞뒷면을 말한다.
    """
    from engine.normal_summon import SUMMON_POSITION
    from engine.set_card import SET_MONSTER_POSITION
    from engine.special_summon import SPECIAL_SUMMON_POSITION

    assigned = {
        "normal_summon": SUMMON_POSITION,
        "set_card": SET_MONSTER_POSITION,
        "special_summon": SPECIAL_SUMMON_POSITION,
        "spell_activation": ACTIVATION_POSITION,
    }
    for name, position in assigned.items():
        assert position not in FACE_SILENT_POSITIONS, (name, position)
        assert position in FACE_UP_POSITIONS + FACE_DOWN_POSITIONS, name

    #: AST — production 에서 그 두 이름을 **대입하는** 자리가 없다.
    for module in (
        "engine/normal_summon.py",
        "engine/set_card.py",
        "engine/special_summon.py",
        "engine/spell_activation.py",
        "engine/effect/executor.py",
    ):
        tree = ast.parse(source_of(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name) or node.value.id != "Position":
                continue
            assert node.attr not in {"ATTACK", "DEFENSE"}, (module, node.attr)


def test_a06_the_default_position_is_face_down_not_face_up():
    """
    🔴 **§10 — "기존 상태를 알 수 없는데 무조건 앞면 공격 표시로 기본값을
    설정하지 않는다."**

    기본값은 ``FACEDOWN_ATTACK`` 이다. 앞면이 아니므로 그 금지선을 지킨다 —
    모르는 카드가 조용히 앞면이 되지 않는다.

    🔴 그런데 그 값은 **필드에서는 불법 상태**다 (뒷면 공격 표시). 필드에
    놓는 자리들이 ``position`` 을 **명시적으로** 주기 때문에 닿지 않는다
    (``test_a05``). 사실만 적는다.
    """
    default = CardInstance.__dataclass_fields__["position"].default
    assert default is Position.FACEDOWN_ATTACK
    assert default not in FACE_UP_POSITIONS


@pytest.mark.real_card
def test_a07_cards_in_hidden_zones_start_face_down(repository):
    """
    **§5** — 덱과 패의 카드는 ``FACEDOWN`` 이다. 그 자리에서 앞뒷면은
    뜻이 없지만, 기본값이 앞면이 아닌 것은 ``test_a06`` 과 같은 이유다.
    """
    state = new_state(repository)
    state.draw(MINE, 3)
    for zone in (Zone.DECK, Zone.HAND):
        cards = state.player(MINE).zones[zone]
        assert cards, zone
        assert all(c.position is Position.FACEDOWN for c in cards), zone
        assert all(c.is_faceup is False for c in cards), zone


# ======================================================================
# B. 행동이 만드는 표시 형식 (§6)
# ======================================================================


def test_b01_each_action_declares_the_position_it_creates():
    """
    **§6 A · B · E** — 소환 · 세트 · 특수 소환 · 발동이 각자 상수로 적는다.

    공식 규칙 그대로다: 일반 소환은 앞면 공격, 세트는 뒷면 수비, 마법의
    발동은 앞면이다.
    """
    from engine.normal_summon import SUMMON_POSITION
    from engine.set_card import SET_MONSTER_POSITION
    from engine.special_summon import SPECIAL_SUMMON_POSITION

    assert SUMMON_POSITION is Position.FACEUP_ATTACK
    assert SET_MONSTER_POSITION is Position.FACEDOWN_DEFENSE
    assert SPECIAL_SUMMON_POSITION is Position.FACEUP_ATTACK
    assert ACTIVATION_POSITION is Position.FACEUP


def test_b02_position_change_and_flip_summon_stay_unsupported():
    """
    🔴 **§6 C · D — 미지원을 보존한다.**

    ``CHANGE_POSITION`` 은 행동 종류로 **있지만** 규칙이 없다고 이름으로
    적혀 있고, 리버스 소환은 행동 종류 자체가 없다. 6-N 이 둘 중 아무것도
    실행하지 않았다 (§3-13).
    """
    import engine.action_validation as av

    assert PlayerActionKind.CHANGE_POSITION in av._MISSING_RULE
    assert (
        av._MISSING_RULE[PlayerActionKind.CHANGE_POSITION]
        == "position-change-legality (Phase 2-G)"
    )
    assert PlayerActionKind.CHANGE_POSITION not in av._COMPLETE_RULES

    #: 리버스 소환은 행동 종류가 **없다** — 흉내 내지 않는다.
    assert not any("FLIP" in kind.name for kind in PlayerActionKind)


@pytest.mark.real_card
def test_b03_changing_position_is_refused_as_unknown_not_applied(repository):
    """
    **§6 C** — 요청하면 ``UNKNOWN`` 이고, 판은 바뀌지 않는다.

    "안 된다" 가 아니라 "규칙을 아직 옮기지 않았다" 다.
    """
    state = new_state(repository)
    monster = state.create_instance(
        FEATHERMAN, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
        **duel_components(),
    )
    before = state.state_hash()
    action = PlayerAction(
        kind=PlayerActionKind.CHANGE_POSITION, actor=MINE,
        source=monster.instance_id,
    )
    verdict = duel.legal_actions(MINE)
    assert action not in verdict.allowed
    assert state.find_instance(monster.instance_id).position is (
        Position.FACEUP_ATTACK
    )
    assert state.state_hash() == before


# ======================================================================
# C. 표시 형식과 정보 공개 범위는 다른 축이다 (§7 · §11-I)
# ======================================================================


@pytest.mark.real_card
def test_c01_an_opponents_face_down_field_card_keeps_its_identity_hidden(
    repository,
):
    """
    🔴 **§7 · §11-I — 상대 뒷면 카드의 카드 ID 가 내 관측에 오지 않는다.**

    EDOPro 듀얼에서 이것이 깨지면 갈라테아가 **치트**가 된다.
    """
    state = new_state(repository)
    theirs_down = state.create_instance(
        HONEST, owner=THEIRS, zone=Zone.MZONE, position=Position.FACEDOWN_DEFENSE
    )
    theirs_up = state.create_instance(
        FEATHERMAN, owner=THEIRS, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    mine_down = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEDOWN_DEFENSE
    )
    view = GameStateView.from_state(state, viewer=MINE)

    hidden = view.find(theirs_down.instance_id)
    assert hidden is not None, "자리는 보인다"
    assert hidden.card_id is None, "정체는 보이지 않는다"
    assert hidden.definition is None
    #: 🔴 앞뒷면 **자체는** 보인다 — 뒷면이라는 사실은 공개 정보다.
    assert hidden.face_up is False

    shown = view.find(theirs_up.instance_id)
    assert shown is not None and shown.card_id == FEATHERMAN

    #: 자기 세트 카드는 자기가 안다.
    own = view.find(mine_down.instance_id)
    assert own is not None and own.card_id == HONEST


@pytest.mark.real_card
def test_c02_hand_and_deck_are_concealed_by_zone_not_by_face(repository):
    """
    🔴 **§3-5 · §3-6 — 표시 형식과 공개 범위를 혼동하지 않는다.**

    패와 덱은 **자리**로 가려진다. 거기 있는 카드의 ``position`` 이
    무엇이든 상대에게 보이지 않는다 — 그래서 필드에서 앞면으로 패에 돌아간
    카드가 ``FACEUP_ATTACK`` 을 들고 있어도 **누출되지 않는다.**
    """
    state = new_state(repository)
    #: 앞면 값을 들고 패와 덱에 있는 카드를 억지로 만든다.
    in_hand = state.create_instance(
        HONEST, owner=THEIRS, zone=Zone.HAND, position=Position.FACEUP_ATTACK
    )
    in_deck = state.create_instance(
        HONEST, owner=THEIRS, zone=Zone.DECK, position=Position.FACEUP_ATTACK
    )
    assert in_hand.is_faceup is True and in_deck.is_faceup is True

    view = GameStateView.from_state(state, viewer=MINE)
    for instance, zone in ((in_hand, Zone.HAND), (in_deck, Zone.DECK)):
        assert view.find(instance.instance_id) is None, zone
        observed = view.player(THEIRS).zone(zone)
        assert observed.concealed is True, zone
        assert all(c is None or c.card_id is None for c in observed.cards), zone

    #: 🔴 그 자리들은 앞뒷면이 뜻을 갖는 목록에 **없다.**
    assert Zone.HAND not in FACE_SENSITIVE_ZONES
    assert Zone.DECK not in FACE_SENSITIVE_ZONES


@pytest.mark.real_card
def test_c03_the_removed_zone_is_concealed_by_face(repository):
    """
    **§5** — 제외 구역은 **앞뒷면**으로 갈린다. 뒷면 제외가 실제로 있다.

    여기서는 표시 형식 이월이 **일을 한다** — 앞면으로 제외된 카드와
    뒷면으로 제외된 카드를 구분하는 유일한 값이다.
    """
    state = new_state(repository)
    face_up = state.create_instance(
        HONEST, owner=THEIRS, zone=Zone.REMOVED, position=Position.FACEUP
    )
    face_down = state.create_instance(
        HONEST, owner=THEIRS, zone=Zone.REMOVED, position=Position.FACEDOWN
    )
    view = GameStateView.from_state(state, viewer=MINE)

    assert view.find(face_up.instance_id).card_id == HONEST
    assert view.find(face_down.instance_id).card_id is None
    assert Zone.REMOVED in FACE_SENSITIVE_ZONES


@pytest.mark.real_card
def test_c04_the_graveyard_is_public_whatever_the_position_says(repository):
    """
    🔴 **묘지는 앞뒷면으로 가려지지 않는다.** 묘지에 뒷면은 없다.

    이것이 §D 가 고친 결함의 전제다 — 관측은 그 카드의 **정체를 보여
    주는데**, 판정 쪽은 ``position`` 을 보고 건너뛰었다.
    """
    state = new_state(repository)
    buried = state.create_instance(
        UNREGISTERED, owner=THEIRS, zone=Zone.GRAVE, position=Position.FACEDOWN
    )
    view = GameStateView.from_state(state, viewer=MINE)
    seen = view.find(buried.instance_id)
    assert seen is not None
    #: 정체가 보인다.
    assert seen.card_id == UNREGISTERED
    #: 그런데 앞뒷면은 "뒷면" 이라고 말한다 — 그 자리에서 뜻이 없는 값이다.
    assert seen.face_up is False
    assert Zone.GRAVE not in FACE_SENSITIVE_ZONES


# ======================================================================
# D. 🔴 고친 결함 — 판정이 "어떻게 거기 갔는가" 에 의존하지 않는다
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "grave_position",
    [Position.FACEUP_ATTACK, Position.FACEUP, Position.FACEDOWN,
     Position.FACEDOWN_DEFENSE],
)
def test_d01_the_graveyard_verdict_does_not_depend_on_the_position(
    repository, grave_position
):
    """
    🔴 **§9 의 실제 차단 사례.** 구현 전 측정:

    | 묘지의 미등록 카드 | ``BoardRuling`` | 어니스트 ① |
    |---|---|---|
    | 필드에서 앞면으로 갔다 (``FACEUP_ATTACK``) | ``UNKNOWN`` | 막혔다 |
    | 패에서 버려졌다 (``FACEDOWN``) | **``TRUE``** | **해결됐다** |

    같은 판이 두 답을 냈다. 원인은 ``_interference`` 가 **자리를 보지 않고**
    앞뒷면만 보고 "세트된 카드" 로 건너뛴 것이다. 묘지에 뒷면은 없다.

    지금은 네 값 모두 **같은 답**이다.
    """
    state = new_state(repository)
    honest = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    state.create_instance(
        UNREGISTERED, owner=MINE, zone=Zone.GRAVE, position=grave_position
    )
    verdict, result = honest_verdict(state, honest.instance_id)

    assert verdict.answer is ConditionResult.UNKNOWN, grave_position
    assert str(UNREGISTERED) in verdict.reason
    assert result.status is ResolutionStatus.UNCHECKED_RULES, grave_position
    #: 판은 그대로다.
    assert state.find_instance(honest.instance_id).zone is Zone.MZONE


@pytest.mark.real_card
def test_d02_a_discarded_card_is_the_reachable_path(repository):
    """
    🔴 **§9-1 도달 가능성** — 등재되고 실행 가능한 효과가 그 상태를 만든다.

    패의 카드는 ``FACEDOWN`` 이고 (덱에서 왔다), 버리기는 표시 형식을
    건드리지 않는다. 그래서 **묘지에 ``FACEDOWN`` 카드가 실제로 생긴다.**

    등재된 효과 중 ``discard`` · ``send_to_grave`` 를 하는 것이 다섯이다
    (``test_d03``). 손으로 만든 상태가 아니라 이 엔진이 실제로 만드는
    상태다.
    """
    state = new_state(repository, deck_card=UNREGISTERED)
    state.draw(MINE, 1)
    victim = state.player(MINE).zones[Zone.HAND][0]
    assert victim.position is Position.FACEDOWN
    assert victim.card_id == UNREGISTERED

    ref = EffectRef(FEATHERMAN, 0)
    definition = EffectDefinition(
        effect_ref=ref,
        source_card_id=FEATHERMAN,
        targets=TargetBinding.single(
            TargetSpec.choosing(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({Zone.HAND}), owner=PlayerRef.CONTROLLER
                    ),
                    minimum=1,
                    maximum=1,
                )
            )
        ),
        operations=(CardOperation.discard(PRIMARY_TARGET),),
        provenance=EffectProvenance.hand_written(
            verified=True, note="Phase 6-N 도달 가능성 시험"
        ),
    )
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((ref,)), rulings=OPERATION_RULINGS
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=ref,
            controller=MINE,
            selections=(
                TargetSelection(
                    PRIMARY_TARGET, Selection(chosen=(victim.instance_id,))
                ),
            ),
        ),
    )
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    buried = state.find_instance(victim.instance_id)
    #: 🔴 묘지에 뒷면 값이 그대로 남는다 — 이것이 그 결함의 입구였다.
    assert buried.zone is Zone.GRAVE
    assert buried.position is Position.FACEDOWN
    assert buried.is_faceup is False

    #: 그리고 지금은 그 카드가 **보인다** — 건너뛰지 않는다.
    honest = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    verdict, outcome = honest_verdict(state, honest.instance_id)
    assert verdict.answer is ConditionResult.UNKNOWN
    assert outcome.status is ResolutionStatus.UNCHECKED_RULES


def test_d03_five_registered_effects_put_cards_in_the_graveyard(repository):
    """🔴 **§9-1** — 그 경로를 만드는 등재 효과를 센다."""
    from engine.effect.library import EFFECT_LIBRARY

    movers = sorted(
        entry.definition.effect_ref.card_id
        for entry in EFFECT_LIBRARY
        if entry.executable
        and any(
            operation.kind
            in (OperationKind.DISCARD, OperationKind.SEND_TO_GRAVE)
            for operation in entry.definition.operations
        )
    )
    #: 실측 (Phase 6-N). 육신보살 · 무정한 말살 · 의적의 입문서 ·
    #: 어리석은 매장 · 벌금.
    assert movers == [15103313, 69091732, 73148972, 81439173, 92595643], movers


@pytest.mark.real_card
def test_d04_a_set_card_on_the_field_is_still_skipped(repository):
    """
    🔴 **고친 것이 "앞뒷면을 무시한다" 가 아니다.**

    필드의 세트 카드는 효과를 적용하지 않으므로 **여전히 건너뛴다.** 그
    사실을 잃지 않았는지 센다 — 미등록 카드를 필드에 **뒷면으로** 두면
    판정이 지나가야 한다.
    """
    state = new_state(repository)
    honest = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    state.create_instance(
        UNREGISTERED, owner=THEIRS, zone=Zone.MZONE,
        position=Position.FACEDOWN_DEFENSE,
    )
    verdict, result = honest_verdict(state, honest.instance_id)
    assert verdict.answer is ConditionResult.TRUE, verdict.reason
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert state.find_instance(honest.instance_id).zone is Zone.HAND

    #: 대조 — 같은 카드를 **앞면으로** 두면 막힌다.
    other = new_state(repository)
    honest2 = other.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    other.create_instance(
        UNREGISTERED, owner=THEIRS, zone=Zone.MZONE,
        position=Position.FACEUP_ATTACK,
    )
    verdict2, result2 = honest_verdict(other, honest2.instance_id)
    assert verdict2.answer is ConditionResult.UNKNOWN
    assert result2.status is ResolutionStatus.UNCHECKED_RULES


# ======================================================================
# E. 한 사실을 두 벌로 적지 않는다 (§3-4 · §10)
# ======================================================================


def test_e01_both_callers_read_the_same_list():
    """
    🔴 **§3-4** — "이 자리에서 앞뒷면이 뜻을 갖는가" 를 묻는 곳이 둘이고,
    둘이 **같은 객체**를 읽는다.

    복사해 두면 한쪽만 고치는 날이 오고, 그날 같은 판이 다시 두 답을 낸다.
    """
    import engine.effect.ruling as ruling
    import engine.game_state_view as view_module

    assert ruling.FACE_SENSITIVE_ZONES is view_module.FACE_SENSITIVE_ZONES
    assert FACE_SENSITIVE_ZONES == frozenset(
        {Zone.MZONE, Zone.EMZONE, Zone.SZONE, Zone.FZONE, Zone.PZONE, Zone.REMOVED}
    )
    #: 필드 전부 + 제외 구역이다. 필드 목록과의 관계를 못박는다.
    assert FIELD_ZONES < FACE_SENSITIVE_ZONES
    assert FACE_SENSITIVE_ZONES - FIELD_ZONES == {Zone.REMOVED}


def test_e02_the_interference_sweep_covers_the_graveyard_too():
    """
    **두 목록의 차이가 정확히 묘지 하나**다.

    훑는 자리에는 묘지가 있고 (묘지 효과가 막을 수 있다), 앞뒷면을 묻는
    자리에는 없다 (묘지에 뒷면이 없다). 그 차이가 §D 의 결함이 살던 틈이다.
    """
    assert Zone.GRAVE in INTERFERENCE_ZONES
    assert Zone.GRAVE not in FACE_SENSITIVE_ZONES
    assert INTERFERENCE_ZONES - FACE_SENSITIVE_ZONES == {Zone.GRAVE}
    assert FACE_SENSITIVE_ZONES - INTERFERENCE_ZONES == frozenset()


def test_e03_the_face_question_is_asked_in_exactly_one_place_per_caller():
    """AST — 각 호출자가 그 목록을 **한 번씩만** 본다."""
    for module, function in (
        #: ``_card_view`` 가 그 판정을 하는 함수다 (공개 존의 카드 한 장이
        #: 얼마나 보이는가).
        ("engine/game_state_view.py", "_card_view"),
        ("engine/effect/ruling.py", "_interference"),
    ):
        tree = ast.parse(source_of(module))
        target = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function
        )
        body = ast.unparse(target)
        assert body.count("FACE_SENSITIVE_ZONES") == 1, (module, function)
        #: 자리 이름을 손으로 나열하지 않는다.
        for literal in ("Zone.MZONE", "Zone.GRAVE", "Zone.REMOVED"):
            assert literal not in body, (module, function, literal)


# ======================================================================
# F. 조건 AST — 있는 것과 없는 것 (§4-D · §8)
# ======================================================================


def test_f01_the_condition_ast_can_already_ask_about_the_face():
    """
    **§4-D 1** — ``CardIsFaceUp`` 이 **이미 있다.** 6-N 이 만들지 않았다.
    """
    assert CardIsFaceUp().canonical_state() == ("card_is_face_up", None)


def test_f02_there_is_no_attack_or_defense_predicate():
    """
    🔴 **§4-D 2 — 공격·수비 표시를 묻는 조건이 하나도 없다** (0건).

    §9 에 따라 그것을 **만들지 않았다**: 등재된 효과 중 그 질문을 하는
    것이 하나도 없다 (``test_f04``). 실제 차단 사례가 없는데 새 조건을
    더하지 않는다.
    """
    import engine.condition.model as model

    names = [
        node.name
        for node in ast.walk(ast.parse(source_of("engine/condition/model.py")))
        if isinstance(node, ast.ClassDef)
    ]
    assert "CardIsFaceUp" in names
    for absent in (
        "CardIsAttackPosition",
        "CardIsDefensePosition",
        "PositionIs",
        "CardPositionIs",
    ):
        assert absent not in names, absent
    assert not hasattr(model, "PositionIs")


@pytest.mark.real_card
def test_f03_the_face_question_is_unknown_when_the_card_is_not_observed(
    repository,
):
    """
    **§4-D 3 · §8** — 관측에 없으면 ``UNKNOWN`` 이다. 추측하지 않는다.
    """
    state = new_state(repository)
    theirs_in_hand = state.create_instance(
        HONEST, owner=THEIRS, zone=Zone.HAND, position=Position.FACEDOWN
    )
    view = GameStateView.from_state(state, viewer=MINE)
    context = ConditionContext(player=MINE, source=theirs_in_hand.instance_id)

    assert CardIsFaceUp().evaluate(view, context) is ConditionResult.UNKNOWN
    reasons = CardIsFaceUp().unknown_reasons(view, context)
    assert reasons and "가려진 존" in reasons[0]


def test_f04_no_registered_effect_asks_about_the_face():
    """
    🔴 **§9 — 후보 생성 축에는 실제 차단 사례가 없다.**

    등재된 효과 17건 중 **앞면 조건을 쓰는 것이 0건**이다. 그리고
    ``CandidateSource.require`` 가 이미 ``Condition`` 을 받으므로, 쓸 카드가
    생기면 **모델을 바꾸지 않고** 적을 수 있다 (``test_f05``).
    """
    from engine.effect.library import EFFECT_LIBRARY

    with_face = [
        entry.definition.effect_ref
        for entry in EFFECT_LIBRARY
        if "CardIsFaceUp" in repr(entry.definition)
    ]
    assert with_face == [], with_face

    #: production 에서 그 조건을 **쓰는** 자리도 없다.
    for module in ("engine/effect/library.py", "engine/duel.py",
                   "engine/action_validation.py"):
        assert "CardIsFaceUp" not in source_of(module), module


@pytest.mark.real_card
def test_f05_a_face_up_only_filter_needs_no_new_field(repository):
    """
    🔴 **§5 · §10 — 기존 모델이 표현할 수 있으면 새 필드를 더하지 않는다.**

    "앞면 몬스터만" 을 ``require=CardIsFaceUp()`` 으로 적어 보고, 후보가
    실제로 걸러지는지 센다. 후보마다 문맥의 ``source`` 가 그 후보로 바뀌므로
    ``instance=None`` 이 후보 자신을 가리킨다.
    """
    from engine.cost.resolver import CandidateResolver

    state = new_state(repository)
    face_up = state.create_instance(
        FEATHERMAN, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    face_down = state.create_instance(
        FEATHERMAN, owner=MINE, zone=Zone.MZONE,
        position=Position.FACEDOWN_DEFENSE,
    )
    view = GameStateView.from_state(state, viewer=MINE)

    plain = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE}), owner=PlayerRef.CONTROLLER
        ),
        minimum=1,
        maximum=1,
    )
    only_face_up = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.MZONE}),
            owner=PlayerRef.CONTROLLER,
            require=CardIsFaceUp(),
        ),
        minimum=1,
        maximum=1,
    )
    resolver = CandidateResolver(view)
    context = ConditionContext(player=MINE)

    everything = resolver.resolve(plain, context)
    filtered = resolver.resolve(only_face_up, context)
    assert set(everything.eligible) == {
        face_up.instance_id,
        face_down.instance_id,
    }
    #: 🔴 앞면만 남는다 — 모델 변경 없이.
    assert set(filtered.eligible) == {face_up.instance_id}


# ======================================================================
# G. 이동 뒤의 표시 형식 (§6-F · §11-G)
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "factory, destination",
    [
        (CardOperation.send_to_grave, Zone.GRAVE),
        (CardOperation.banish, Zone.REMOVED),
        (CardOperation.return_to_deck, Zone.DECK),
    ],
)
def test_g01_a_move_does_not_touch_the_position(repository, factory, destination):
    """
    🔴 **§11-G — 현재 동작을 사실로 적는다.**

    ``GameState.move`` 는 표시 형식을 **건드리지 않는다.** 그래서 필드를
    떠난 카드가 ``FACEUP_ATTACK`` 을 들고 묘지 · 덱으로 간다.

    이것을 6-N 이 **고치지 않았다**. 자리마다 뜻이 다르기 때문이다 —
    제외 구역에서는 그 값이 **일을 하고** (``test_c03``), 묘지 · 덱 ·
    패에서는 뜻이 없다. 값을 지우면 앞면 제외와 뒷면 제외를 구분할 수
    없게 된다. 6-N 이 고친 것은 **그 값을 뜻이 없는 자리에서 묻던 쪽**이다.
    """
    state = new_state(repository)
    instance = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    ref = EffectRef(HONEST, 0)
    definition = EffectDefinition(
        effect_ref=ref,
        source_card_id=HONEST,
        operations=(factory(SELF_TARGET),),
        provenance=EffectProvenance.official_lua("Phase 6-N 시험용"),
    )
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((ref,)), rulings=OPERATION_RULINGS
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=ref, controller=MINE, source=instance.instance_id
        ),
    )
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    after = state.find_instance(instance.instance_id)
    assert after.zone is destination
    #: 표시 형식이 그대로다.
    assert after.position is Position.FACEUP_ATTACK
    #: 🔴 직전 상태는 **남는다** — 필드를 떠난 뒤의 사건이 읽을 수 있다 (§4-A 6).
    assert after.previous.location is Zone.MZONE
    assert after.previous.position is Position.FACEUP_ATTACK


# ======================================================================
# H. 같은 카드 ID 의 복수 인스턴스 (§11-H)
# ======================================================================


@pytest.mark.real_card
def test_h01_three_instances_keep_their_own_positions(repository):
    """같은 카드 ID 셋의 표시 형식이 섞이지 않는다."""
    state = new_state(repository)
    wanted = (
        Position.FACEUP_ATTACK,
        Position.FACEDOWN_DEFENSE,
        Position.FACEUP_DEFENSE,
    )
    placed = [
        state.create_instance(HONEST, owner=MINE, zone=Zone.MZONE, position=p)
        for p in wanted
    ]
    assert [c.position for c in placed] == list(wanted)
    assert [c.is_faceup for c in placed] == [True, False, True]

    #: 하나를 뒤집어도 나머지는 그대로다.
    placed[0].set_position(Position.FACEDOWN_DEFENSE)
    assert [
        state.find_instance(c.instance_id).position for c in placed
    ] == [Position.FACEDOWN_DEFENSE, Position.FACEDOWN_DEFENSE,
          Position.FACEUP_DEFENSE]

    #: 관측도 인스턴스마다 따로다.
    view = GameStateView.from_state(state, viewer=THEIRS)
    faces = [view.find(c.instance_id).face_up for c in placed]
    assert faces == [False, False, True]


# ======================================================================
# I. 어니스트 회귀 (§11-J)
# ======================================================================


@pytest.mark.real_card
def test_i01_honest_still_resolves_through_the_real_duel(repository):
    """🔴 **§11-J** — Phase 6-L 이 확보한 경로가 그대로다."""
    journal = EventJournal()
    state = new_state(repository)
    placed = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
        **duel_components(journal=journal),
    )
    candidates = [
        action
        for action in duel.legal_actions(MINE).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(candidates) == 1
    assert candidates[0].effect_ref == HONEST_REF

    step = duel.apply(candidates[0])
    assert step.accepted, step.reason
    assert duel.state.find_instance(placed.instance_id).zone is Zone.MZONE
    settled = settle_chain(duel)
    assert settled is not None and settled.accepted
    assert duel.state.find_instance(placed.instance_id).zone is Zone.HAND

    events = [e for e in journal.events if e.effect_ref == HONEST_REF]
    assert len(events) == 1
    assert events[0].deltas[0].destination_zone is Zone.HAND


@pytest.mark.real_card
def test_i02_a_face_down_honest_is_still_refused_at_activation(repository):
    """
    🔴 **§11-D — 뒷면 몬스터의 효과 발동이 통과하지 않는다.**

    Phase 6-K 가 세운 관문이고 6-N 이 그것을 바꾸지 않았다. 그래서
    「앞면 표시의」 를 **해결 시점에** 묻는 길이 아직 없어도 (보고서 §17)
    발동 쪽에서 막힌다.
    """
    state = new_state(repository)
    placed = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEDOWN_DEFENSE
    )
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
        **duel_components(),
    )
    verdict = duel.legal_actions(MINE)
    assert not [
        a for a in verdict.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    refused = duel.apply(
        PlayerAction.activate_effect(
            MINE, placed.instance_id, effect_ref=HONEST_REF
        )
    )
    assert not refused.accepted
    assert state.find_instance(placed.instance_id).zone is Zone.MZONE


# ======================================================================
# J. 카드 이동 회귀 (§11-K)
# ======================================================================


@pytest.mark.real_card
def test_j01_the_phase_6m_origin_rule_still_holds(repository):
    """🔴 **§11-K** — 어니스트 ① 이 필드 밖에서는 여전히 거절된다."""
    definition = definition_registry().definition_for(HONEST_REF)
    assert definition.operations[0].origin_zones == FIELD_ZONES

    for zone in (Zone.GRAVE, Zone.DECK, Zone.REMOVED):
        state = new_state(repository)
        instance = state.create_instance(
            HONEST, owner=MINE, zone=zone, position=Position.FACEUP_ATTACK
        )
        journal = EventJournal()
        executor = EffectExecutor(
            lookup=EffectImplementationRegistry((HONEST_REF,)),
            rulings=OPERATION_RULINGS,
            journal=journal,
        )
        result = executor.execute(
            state,
            definition,
            ResolutionContext(
                effect_ref=HONEST_REF, controller=MINE, source=instance.instance_id
            ),
        )
        assert result.status is ResolutionStatus.INVALID_TARGET, zone
        assert result.code is ValidationCode.SOURCE_WRONG_ZONE, zone
        assert state.find_instance(instance.instance_id).zone is zone
        assert journal.events == ()


# ======================================================================
# K. §12 감사 — 상태 변화 없는 이동
# ======================================================================


@pytest.mark.real_card
def test_k01_a_move_that_changes_nothing_is_already_refused(repository):
    """
    **§12 감사** — Phase 6-M 이 이미 막았다. 6-N 이 손대지 않았다.

    §12 의 다섯 질문에 답한다.

    1. 인스턴스 정보가 변했는가 — **아니다** (판이 비트 단위로 그대로다).
    2. 규칙상 의미 있는 이동인가 — **아니다** (주인도 자리도 같다).
    3. ``RESOLVED`` 로 처리되는가 — **아니다** (6-M 이후).
    4. journal 에 생기는가 — **아니다**.
    5. 콤보 탐색에서 같은 상태를 반복 방문할 위험 — **그 입구가 닫혔다.**
    """
    state = new_state(repository)
    instance = state.create_instance(
        HONEST, owner=MINE, zone=Zone.HAND, position=Position.FACEDOWN
    )
    before = state.state_hash()
    ref = EffectRef(HONEST, 0)
    definition = EffectDefinition(
        effect_ref=ref,
        source_card_id=HONEST,
        operations=(CardOperation.return_to_hand(SELF_TARGET, gated=True),),
        provenance=EffectProvenance.official_lua("Phase 6-N 시험용"),
    )
    journal = EventJournal()
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((ref,)),
        rulings=OPERATION_RULINGS,
        journal=journal,
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=ref, controller=MINE, source=instance.instance_id
        ),
    )
    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.missing == MISSING_SAME_ZONE_MOVEMENT
    assert result.deltas == ()
    assert journal.events == ()
    assert state.state_hash() == before


# ======================================================================
# L. 금지 사항 — 새 모델을 만들지 않았다 (§3 · §9)
# ======================================================================


def test_l01_no_new_position_model_was_created():
    """**§3-4 · §9** — 실제 차단 사례가 없는 축에는 아무것도 더하지 않았다."""
    assert len(list(Position)) == 8
    #: ``CardInstance`` 의 칸이 그대로다 — 표시 형식 칸은 하나뿐이다.
    fields = set(CardInstance.__dataclass_fields__)
    assert "position" in fields
    for absent in ("face_up", "is_face_up", "face", "orientation", "battle_position"):
        assert absent not in fields, absent


def test_l02_the_change_is_two_files_and_no_new_module():
    """
    **§6 보고** — 6-N 이 바꾼 production 은 두 파일이고, 새 모듈은 없다.

    AST 로 센다: ``_interference`` 가 자리를 먼저 보고, 그 목록이 공개
    이름이다.
    """
    ruling_tree = ast.parse(source_of("engine/effect/ruling.py"))
    interference = next(
        node
        for node in ast.walk(ruling_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_interference"
    )
    body = ast.unparse(interference)
    assert "zone.zone in FACE_SENSITIVE_ZONES and (not card.face_up)" in body

    view_source = source_of("engine/game_state_view.py")
    assert "FACE_SENSITIVE_ZONES: frozenset[Zone]" in view_source
    #: 사설 이름이 남아 있지 않다 — 두 벌이 되지 않게.
    assert "_FACE_SENSITIVE_ZONES" not in view_source


def test_l03_no_card_id_branch_decides_the_face():
    """**§3-9** — 카드 ID 로 앞뒷면을 정하는 자리가 없다."""
    for module in ("engine/effect/ruling.py", "engine/game_state_view.py"):
        tree = ast.parse(source_of(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            text = ast.unparse(node)
            if "card_id" in text and "face" in text:
                raise AssertionError((module, text))
