"""
engine/game_state_view.py — 카드 정의 스냅숏 (STRUCTURAL-1 해결).

조건이 "레벨 4 이상인가" 를 물으려면 카드 정의가 필요하다. 그렇다고
``ConditionEvaluator`` 가 ``CardRepository`` 를 들면 안 된다 — 저장소는
**전체 카드**를 알고 있으므로 상대의 뒷면 카드까지 조회할 수 있게 된다.

그래서 정의는 관측을 통해서만 들어오고, **정체가 공개된 카드에만** 붙는다.
"""

import dataclasses
import json

import pytest

from engine.condition import (
    AttackAtLeast,
    AttributeIs,
    ConditionContext,
    ConditionEvaluator,
    ConditionResult,
    IsMonster,
    LevelAtLeast,
)
from engine.game_state_view import (
    STAT_NONE,
    STAT_QUESTION,
    CardDefinitionView,
    GameStateView,
)
from engine.state.game_state import GameState
from engine.vocabulary import Position, Zone

from tests.conftest import requires_official_db

#: 실제 카드. 값이 바뀌면 테스트가 알려주는 편이 낫다.
BLUE_EYES = 89631139  # 푸른 눈의 백룡 — LIGHT / DRAGON / 레벨 8 / 3000 / 2500
DARK_MAGICIAN = 46986414  # 암흑 마법사 — DARK / SPELLCASTER / 레벨 7 / 2500
TEN_THOUSAND = 10000  # 텐사우전드 드래곤 — 공격력이 ``?``
RED_EYES = 74677422  # 붉은 눈의 흑룡 — 상대 전용
CHAOS_SOLDIER = 5405694  # 카오스 솔저 — 상대 전용

TRUE = ConditionResult.TRUE
FALSE = ConditionResult.FALSE
UNKNOWN = ConditionResult.UNKNOWN


@pytest.fixture
def state(repository) -> GameState:
    """
    앞면 몬스터 둘, 상대의 뒷면 카드 하나.

    두 덱은 **카드가 겹치지 않는다.** 겹치면 "상대 패의 카드 ID 가 샜는가"
    를 볼 때 내 카드에서 온 것과 구분할 수 없다.
    """
    game = GameState.create(
        repository,
        decks=(
            [BLUE_EYES, DARK_MAGICIAN] * 5,
            [TEN_THOUSAND, RED_EYES, CHAOS_SOLDIER] * 5,
        ),
    )
    game.draw(0, 3)
    game.draw(1, 4)  # 둘을 필드로 내보내고도 패에 카드가 남아야 한다
    game.move(game.player(0).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(1).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(1).hand[0], Zone.SZONE, position=Position.FACEDOWN)
    return game


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=0)


@pytest.fixture
def evaluator(view) -> ConditionEvaluator:
    return ConditionEvaluator(view)


@pytest.fixture
def context() -> ConditionContext:
    return ConditionContext(player=0)


@pytest.fixture
def blue_eyes(view):
    """내 앞면 푸른 눈."""
    return view.me.monster_zone.cards[0].instance_id


@pytest.fixture
def question_atk(view):
    """상대의 앞면 텐사우전드 드래곤 (공격력 ``?``)."""
    return view.opponent.monster_zone.cards[0].instance_id


@pytest.fixture
def face_down(view):
    """상대의 뒷면 세트 카드."""
    return view.opponent.spell_zone.cards[0].instance_id


# ----------------------------------------------------------------------
# CardDefinitionView 자체
# ----------------------------------------------------------------------


@requires_official_db
def test_definition_carries_the_values_conditions_need(repository):
    definition = CardDefinitionView.of(repository.get(BLUE_EYES))

    assert definition.card_id == BLUE_EYES
    assert definition.name == "푸른 눈의 백룡"
    assert definition.is_monster is True
    assert definition.is_spell is False
    assert definition.is_trap is False
    assert definition.monster_level == 8
    assert definition.atk == 3000
    assert definition.defense == 2500
    assert definition.attribute_name == "LIGHT"
    assert definition.race_name == "DRAGON"
    assert "MONSTER" in definition.type_names


@requires_official_db
def test_definition_never_invents_a_value(repository):
    """
    ``Card`` 에 없는 값을 지어내지 않는다. 레벨이 없는 카드는 ``None`` 이다.
    """
    definition = CardDefinitionView.of(repository.get(BLUE_EYES))
    assert definition.rank is None  # 엑시즈가 아니다
    assert definition.link_rating is None  # 링크가 아니다
    assert definition.pendulum_scale_left is None


@requires_official_db
def test_xyz_has_a_rank_and_no_level(repository):
    """랭크는 레벨이 아니다. 합치면 "레벨 4 이상" 이 랭크 4 를 잡아 버린다."""
    xyz = next(c for c in repository.all_cards(include_alternates=True) if c.is_xyz)
    definition = CardDefinitionView.of(xyz)
    assert definition.is_xyz is True
    assert definition.monster_level is None
    assert definition.rank == definition.level


@requires_official_db
def test_link_monster_has_no_defence_value(repository):
    """링크 몬스터에는 수비력이 **없다.** 0 이 아니다."""
    link = next(c for c in repository.all_cards(include_alternates=True) if c.is_link)
    definition = CardDefinitionView.of(link)

    assert definition.is_link is True
    assert definition.defense == STAT_NONE
    assert definition.has_defense is False
    assert definition.defense_is_question is False
    assert definition.link_rating == definition.level
    assert definition.monster_level is None


@requires_official_db
def test_question_mark_attack_is_not_a_number(repository):
    """
    ``?`` 공격력은 **수치가 없는 것과 다르다.** 합치면 ``?`` 몬스터가
    공격력 0 으로 둔갑한다. 실측 90장이 이 값을 갖는다.
    """
    definition = CardDefinitionView.of(repository.get(TEN_THOUSAND))

    assert definition.atk == STAT_QUESTION
    assert definition.atk_is_question is True
    assert definition.has_atk is False
    assert STAT_QUESTION != STAT_NONE


def test_engine_stat_sentinels_agree_with_the_card_layer():
    """
    관측 계층은 런타임에 ``core`` 를 가져오지 않는다. 대신 값이 어긋나지
    않는지 테스트가 지킨다.
    """
    import core.constants as C

    assert STAT_NONE == C.STAT_NONE


@requires_official_db
def test_definition_view_is_immutable(repository):
    definition = CardDefinitionView.of(repository.get(BLUE_EYES))
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.atk = 9999
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.card_id = 1
    assert isinstance(definition.type_names, tuple)
    assert isinstance(definition.setcodes, tuple)
    with pytest.raises(AttributeError):
        definition.type_names.append("X")


@requires_official_db
def test_definition_view_exposes_no_mutation_path(repository):
    definition = CardDefinitionView.of(repository.get(BLUE_EYES))
    for forbidden in ("script", "provenance", "sources", "desc", "strings", "effects"):
        assert not hasattr(definition, forbidden), (
            f"CardDefinitionView 가 {forbidden} 를 노출합니다 — 조건 평가에 "
            "필요하지 않고, 엔진 내부 구현을 관측에 묶습니다."
        )


@requires_official_db
def test_the_snapshot_does_not_follow_the_card_definition(repository):
    """
    ``Card`` 는 가변이고 저장소가 같은 객체를 계속 돌려준다. 관측이 그것을
    참조로 들고 있으면 정의가 바뀔 때 옛 관측까지 바뀐다.
    """
    card = repository.get(BLUE_EYES)
    definition = CardDefinitionView.of(card)
    original = card.atk
    try:
        card.atk = 1
        assert definition.atk == original  # 스냅숏은 그대로다
    finally:
        card.atk = original


# ----------------------------------------------------------------------
# 1~3. 공개된 카드의 정의 조건
# ----------------------------------------------------------------------


@requires_official_db
def test_level_of_a_visible_monster(evaluator, context, blue_eyes):
    assert evaluator.result(LevelAtLeast(8, blue_eyes), context) is TRUE
    assert evaluator.result(LevelAtLeast(4, blue_eyes), context) is TRUE
    assert evaluator.result(LevelAtLeast(9, blue_eyes), context) is FALSE


@requires_official_db
def test_attack_of_a_visible_monster(evaluator, context, blue_eyes):
    assert evaluator.result(AttackAtLeast(3000, blue_eyes), context) is TRUE
    assert evaluator.result(AttackAtLeast(2000, blue_eyes), context) is TRUE
    assert evaluator.result(AttackAtLeast(3001, blue_eyes), context) is FALSE


@requires_official_db
def test_attribute_of_a_visible_monster(evaluator, context, blue_eyes):
    assert evaluator.result(AttributeIs("LIGHT", blue_eyes), context) is TRUE
    assert evaluator.result(AttributeIs("DARK", blue_eyes), context) is FALSE


@requires_official_db
def test_attribute_name_is_case_normalised(evaluator, context, blue_eyes):
    """대소문자로 같은 조건이 두 표현을 갖지 않게 한다."""
    assert AttributeIs("light").attribute == "LIGHT"
    assert (
        AttributeIs("light", blue_eyes).canonical_state()
        == AttributeIs("LIGHT", blue_eyes).canonical_state()
    )
    assert evaluator.result(AttributeIs("light", blue_eyes), context) is TRUE


@requires_official_db
def test_is_monster_of_a_visible_card(evaluator, context, blue_eyes):
    assert evaluator.result(IsMonster(blue_eyes), context) is TRUE


@requires_official_db
def test_the_predicate_reads_the_context_source_when_no_instance_is_given(
    view, blue_eyes
):
    context = ConditionContext(player=0, source=blue_eyes)
    assert LevelAtLeast(8).evaluate(view, context) is TRUE
    assert AttributeIs("LIGHT").evaluate(view, context) is TRUE


# ----------------------------------------------------------------------
# 없는 값은 FALSE, 정해지지 않은 값은 UNKNOWN
# ----------------------------------------------------------------------


@requires_official_db
def test_a_question_mark_attack_is_unknown_not_zero(evaluator, context, question_atk):
    """
    카드가 **완전히 공개되어 있는데도** 모른다. 정의상 수치가 정해져 있지
    않기 때문이고, 이것은 정보 은닉과 다른 종류의 UNKNOWN 이다.
    """
    verdict = evaluator.evaluate(AttackAtLeast(2000, question_atk), context)
    assert verdict.result is UNKNOWN
    assert verdict.result is not FALSE
    assert "?" in verdict.unknown_reasons[0]

    # 낮은 기준에 대해서도 참이라고 하지 않는다.
    assert evaluator.result(AttackAtLeast(0, question_atk), context) is UNKNOWN


@requires_official_db
def test_an_xyz_monster_has_no_level_which_is_decidably_false(repository, context):
    """
    랭크는 레벨이 아니다. "레벨이 없다" 는 확정된 사실이므로 UNKNOWN 이
    아니라 FALSE 다.
    """
    xyz = next(c for c in repository.all_cards(include_alternates=True) if c.is_xyz)
    game = GameState.create(repository, decks=([], []))
    card = game.create_instance(xyz.id, owner=0, zone=Zone.MZONE)
    card.set_position(Position.FACEUP_ATTACK)
    view = GameStateView.from_state(game, viewer=0)

    assert view.find(card.instance_id).definition.rank is not None
    assert LevelAtLeast(1, card.instance_id).evaluate(view, context) is FALSE


@requires_official_db
def test_a_spell_card_has_no_level_or_attack(repository, context):
    spell = next(
        c for c in repository.all_cards(include_alternates=True) if c.is_spell
    )
    game = GameState.create(repository, decks=([], []))
    card = game.create_instance(spell.id, owner=0, zone=Zone.SZONE)
    card.set_position(Position.FACEUP)
    view = GameStateView.from_state(game, viewer=0)
    instance = card.instance_id

    assert IsMonster(instance).evaluate(view, context) is FALSE
    assert LevelAtLeast(1, instance).evaluate(view, context) is FALSE
    assert AttackAtLeast(0, instance).evaluate(view, context) is FALSE
    assert AttributeIs("DARK", instance).evaluate(view, context) is FALSE


@requires_official_db
def test_a_trap_monster_card_is_still_a_trap(repository, context):
    """
    ``cards.cdb`` 는 함정 23장에 **0 이 아닌 공격력**을 저장한다 — 발동하면
    몬스터가 되는 함정(버제스토마 등)이 그때의 수치를 들고 있기 때문이다.

    ``atk`` 값만 보고 판정하면 그 함정이 함정인 채로 공격력을 갖게 된다.
    그래서 공격력 조건은 ``is_monster`` 를 먼저 본다.
    """
    trap = next(
        c
        for c in repository.all_cards(include_alternates=True)
        if c.is_trap and c.atk > 0
    )
    game = GameState.create(repository, decks=([], []))
    card = game.create_instance(trap.id, owner=0, zone=Zone.SZONE)
    card.set_position(Position.FACEUP)
    view = GameStateView.from_state(game, viewer=0)
    instance = card.instance_id

    assert view.find(instance).definition.atk > 0  # 수치는 실려 있지만
    assert IsMonster(instance).evaluate(view, context) is FALSE
    assert AttackAtLeast(1, instance).evaluate(view, context) is FALSE  # 공격력은 없다
    assert AttackAtLeast(0, instance).evaluate(view, context) is FALSE


# ----------------------------------------------------------------------
# 4~5. 가려진 카드
# ----------------------------------------------------------------------


@requires_official_db
def test_a_face_down_card_exposes_neither_id_nor_definition(view, face_down):
    """
    가장 중요한 경계. 정의를 실어 준다고 해서 뒷면 카드의 정체가 새면 안 된다.
    레벨 · 속성 · 공격력만 보고도 어느 카드인지 거의 특정할 수 있기 때문이다.
    """
    card = view.find(face_down)
    assert card is not None
    assert card.card_id is None
    assert card.definition is None
    assert card.has_definition is False
    assert card.name is None


@requires_official_db
def test_definition_conditions_on_a_face_down_card_are_unknown(
    evaluator, context, face_down
):
    for condition in (
        IsMonster(face_down),
        LevelAtLeast(4, face_down),
        AttackAtLeast(2000, face_down),
        AttributeIs("DARK", face_down),
    ):
        verdict = evaluator.evaluate(condition, context)
        assert verdict.result is UNKNOWN, condition.describe_ko()
        assert verdict.result is not FALSE
        assert "뒷면" in verdict.unknown_reasons[0]


@requires_official_db
def test_the_controller_of_a_set_card_can_read_its_definition(state, face_down):
    """자기가 세트한 카드가 무엇인지는 당연히 안다."""
    owner_view = GameStateView.from_state(state, viewer=1)
    card = owner_view.find(face_down)

    assert card.card_id is not None
    assert card.definition is not None
    assert (
        IsMonster(face_down).evaluate(owner_view, ConditionContext(player=1)) is not UNKNOWN
    )


@requires_official_db
def test_a_card_in_a_hidden_zone_gives_no_definition(state, context):
    """상대 패 · 덱은 카드 자체가 관측에 없다."""
    in_hand = state.player(1).hand[0].instance_id
    in_deck = state.player(1).deck[0].instance_id
    view = GameStateView.from_state(state, viewer=0)

    for instance in (in_hand, in_deck):
        assert view.find(instance) is None
        verdict = ConditionEvaluator(view).evaluate(LevelAtLeast(4, instance), context)
        assert verdict.result is UNKNOWN
        assert "보이지 않" in verdict.unknown_reasons[0]


@requires_official_db
def test_no_hidden_card_id_appears_anywhere_in_the_serialised_view(state):
    """
    관측 전체를 직렬화해서, 가려진 카드의 ID 와 이름이 단 하나도 새지
    않는지 본다. 정의를 실은 뒤에도 유지되어야 하는 성질이다.
    """
    view = GameStateView.from_state(state, viewer=0)
    text = json.dumps(view.to_dict(), ensure_ascii=False)

    hidden = (
        list(state.player(1).hand)
        + list(state.player(1).deck)
        + [state.player(1).spell_zone[0]]
    )
    # 상대의 앞면 몬스터는 정당하게 보이므로 뺀다.
    on_show = {state.player(1).monster_zone[0].card_id}
    secret_ids = {card.card_id for card in hidden} - on_show
    assert secret_ids, "숨겨야 할 카드가 없으면 테스트가 헛돕니다."

    for card_id in secret_ids:
        assert str(card_id) not in text, f"카드 ID {card_id} 가 샜습니다."
    set_card = state.player(1).spell_zone[0]
    assert set_card.name not in text  # 이름도 새면 안 된다


@requires_official_db
def test_the_three_reasons_for_not_knowing_are_distinguished(state, context):
    """
    "안 보인다" · "뒷면이다" · "정의를 못 읽는다" 는 전부 UNKNOWN 이지만
    원인이 다르다. 부르는 쪽이 다음 단계를 정하려면 구분이 필요하다.
    """
    view = GameStateView.from_state(state, viewer=0)
    evaluator = ConditionEvaluator(view)

    hidden = state.player(1).hand[0].instance_id
    face_down = state.player(1).spell_zone[0].instance_id

    assert "보이지 않" in evaluator.evaluate(IsMonster(hidden), context).unknown_reasons[0]
    assert "뒷면" in evaluator.evaluate(IsMonster(face_down), context).unknown_reasons[0]
    assert "source" in evaluator.evaluate(IsMonster(), context).unknown_reasons[0]


def test_no_repository_means_unknown_not_a_crash(context):
    """
    저장소 없이 만든 상태에서도 관측이 만들어져야 하고, 조건은 예외 대신
    ``UNKNOWN`` 을 돌려줘야 한다.
    """
    game = GameState.create(decks=([1000], []))
    card = game.player(0).deck[0]
    card.set_position(Position.FACEUP)
    game.move(card, Zone.MZONE)
    view = GameStateView.from_state(game, viewer=0)

    seen = view.find(card.instance_id)
    assert seen.card_id == 1000  # 정체는 공개다
    assert seen.definition is None  # 그런데 정의를 조회할 수 없다

    verdict = ConditionEvaluator(view).evaluate(LevelAtLeast(4, card.instance_id), context)
    assert verdict.result is UNKNOWN
    assert "저장소" in verdict.unknown_reasons[0]


# ----------------------------------------------------------------------
# 7. 평가가 상태를 바꾸지 않는다
# ----------------------------------------------------------------------


def _snapshot(state: GameState) -> tuple:
    return (
        state.state_hash(),
        state.allocator.next_value,
        len(state.uses),
        state.turn.canonical_state(),
    )


@requires_official_db
def test_definition_conditions_do_not_change_the_state(state, context, blue_eyes, face_down):
    before = _snapshot(state)
    evaluator = ConditionEvaluator(GameStateView.from_state(state, viewer=0))

    for condition in (
        IsMonster(blue_eyes),
        LevelAtLeast(4, blue_eyes),
        AttackAtLeast(3000, blue_eyes),
        AttributeIs("LIGHT", blue_eyes),
        LevelAtLeast(4, face_down),
        AttackAtLeast(1, face_down),
    ):
        evaluator.evaluate(condition, context)
        evaluator.result(condition, context)

    assert _snapshot(state) == before


@requires_official_db
def test_building_a_view_with_definitions_does_not_change_the_state(state):
    """정의를 조회하는 경로가 카드 정의나 판을 건드리지 않는지 확인한다."""
    before = _snapshot(state)
    GameStateView.from_state(state, viewer=0)
    GameStateView.from_state(state, viewer=1)
    assert _snapshot(state) == before


@requires_official_db
def test_card_definitions_are_not_polluted_by_view_building(state, repository):
    """
    ``Card`` 는 가변이고 전역 공유다. 관측을 만드는 것만으로 정의가 바뀌면
    검색 결과까지 틀어진다.
    """
    def snapshot(card):
        return (card.id, card.name, card.atk, card.defense, card.level, card.type_mask)

    before = [snapshot(repository.get(cid)) for cid in (BLUE_EYES, DARK_MAGICIAN, TEN_THOUSAND)]
    for _ in range(3):
        GameStateView.from_state(state, viewer=0)
        GameStateView.from_state(state, viewer=1)
    after = [snapshot(repository.get(cid)) for cid in (BLUE_EYES, DARK_MAGICIAN, TEN_THOUSAND)]
    assert before == after


# ----------------------------------------------------------------------
# 8. 결정론
# ----------------------------------------------------------------------


@requires_official_db
def test_the_same_snapshot_always_gives_the_same_answer(evaluator, context, blue_eyes):
    condition = AttackAtLeast(3000, blue_eyes)
    first = evaluator.result(condition, context)
    for _ in range(10):
        assert evaluator.result(condition, context) is first


@requires_official_db
def test_two_views_of_the_same_state_carry_identical_definitions(state):
    a = GameStateView.from_state(state, viewer=0)
    b = GameStateView.from_state(state, viewer=0)
    assert a == b
    assert a.canonical_state() == b.canonical_state()
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        b.to_dict(), sort_keys=True
    )


@requires_official_db
def test_the_view_snapshot_does_not_follow_later_state_changes(state, context, blue_eyes):
    """Phase 2-A 의 스냅숏 의미론이 정의를 실은 뒤에도 유지된다."""
    evaluator = ConditionEvaluator(GameStateView.from_state(state, viewer=0))
    assert evaluator.result(LevelAtLeast(8, blue_eyes), context) is TRUE

    state.move(state.player(0).monster_zone[0], Zone.GRAVE, to_player=0)

    # 옛 관측에는 그 카드가 여전히 필드에 있고, 정의도 그대로다.
    assert evaluator.result(LevelAtLeast(8, blue_eyes), context) is TRUE


@requires_official_db
def test_definition_serialization_holds_only_value_types(view, blue_eyes):
    definition = view.find(blue_eyes).definition

    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    for value in leaves(definition.to_dict()):
        assert value is None or isinstance(value, (int, str, bool)), value
    for value in leaves(definition.canonical_state()):
        assert value is None or isinstance(value, (int, str, bool)), value


@requires_official_db
def test_definition_predicates_serialize_deterministically(blue_eyes):
    for condition, twin in (
        (IsMonster(blue_eyes), IsMonster(blue_eyes)),
        (LevelAtLeast(4, blue_eyes), LevelAtLeast(4, blue_eyes)),
        (AttackAtLeast(2000, blue_eyes), AttackAtLeast(2000, blue_eyes)),
        (AttributeIs("DARK", blue_eyes), AttributeIs("DARK", blue_eyes)),
    ):
        assert condition is not twin
        assert condition == twin
        assert condition.canonical_state() == twin.canonical_state()
        assert json.dumps(condition.to_dict(), sort_keys=True) == json.dumps(
            twin.to_dict(), sort_keys=True
        )

    assert (
        LevelAtLeast(4, blue_eyes).canonical_state()
        != LevelAtLeast(5, blue_eyes).canonical_state()
    )


def test_definition_predicates_are_immutable():
    condition = LevelAtLeast(4)
    with pytest.raises(dataclasses.FrozenInstanceError):
        condition.level = 5


def test_level_refuses_a_negative_threshold():
    with pytest.raises(ValueError):
        LevelAtLeast(-1)
    with pytest.raises(ValueError):
        AttributeIs("")


# ----------------------------------------------------------------------
# 경계가 그대로인지
# ----------------------------------------------------------------------


def test_the_condition_package_still_never_imports_the_repository():
    """
    ``ConditionEvaluator`` 가 ``CardRepository`` 를 들면 상대의 뒷면 카드까지
    조회할 수 있게 된다. 정의는 오직 관측을 통해서만 온다.
    """
    import ast
    import pathlib

    offenders: list[str] = []
    for path in sorted(pathlib.Path("engine/condition").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "core"
            ):
                offenders.append(f"{path}: {node.module}")
            if isinstance(node, ast.Name) and node.id in {"CardRepository", "Card"}:
                offenders.append(f"{path}: {node.id}")
    assert offenders == [], f"조건 계층이 카드 저장소를 만집니다: {offenders}"
