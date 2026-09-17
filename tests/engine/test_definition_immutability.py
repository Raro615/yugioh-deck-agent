"""
회귀 테스트 — 듀얼 상태를 아무리 바꿔도 **카드 정의는 변하지 않는다.**

설계 문서의 "결함 2" 가 이것이다. ``CardRepository`` 는 같은 ``Card`` 객체를
계속 돌려주고 (``r.get(2511) is r.get(2511)`` -> ``True``) ``Card`` 는 가변
dataclass 다. 엔진이 정의를 건드리면 검색 결과까지 오염된다.

여기서 검증하는 것은 "엔진이 정의를 건드리지 않는다" 뿐이다. 정의를 불변으로
만드는 것은 ``core/`` 수정이라 이번 범위 밖이다.
"""

import pytest

from core.card_model import Card
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Position, Zone
from tests.conftest import requires_official_db


def snapshot(card: Card) -> tuple:
    """카드 정의의 모든 값을 값 타입으로 펼친다."""
    script = card.script
    return (
        card.id,
        card.name,
        card.name_en,
        card.name_ja,
        card.name_ko,
        card.type_mask,
        card.attribute_mask,
        card.race_mask,
        card.level,
        card.atk,
        card.defense,
        card.pendulum_scale_left,
        card.pendulum_scale_right,
        card.link_marker_mask,
        tuple(card.setcodes),
        card.category_mask,
        card.alias,
        card.ot,
        card.desc,
        card.desc_en,
        tuple(card.strings),
        tuple(sorted(source.value for source in card.sources)),
        None
        if script is None
        else (
            script.card_id,
            script.file_name,
            script.name_ja,
            script.name_en,
            tuple(script.listed_names),
            tuple(script.listed_series),
            tuple(script.trigger_events),
            tuple(script.locations),
            tuple(script.categories),
            tuple(
                (
                    spec.index,
                    tuple(spec.effect_types),
                    spec.code,
                    tuple(spec.ranges),
                    tuple(spec.target_ranges),
                    tuple(spec.categories),
                    tuple(spec.properties),
                    spec.count_limit,
                    spec.cloned_from,
                )
                for spec in script.effects
            ),
        ),
    )


@requires_official_db
def test_repository_returns_the_same_shared_mutable_object(repository):
    """전제 확인 — 이것이 참이기 때문에 CardInstance 분리가 필수다."""
    card_id = next(iter(repository)).id
    assert repository.get(card_id) is repository.get(card_id)


@requires_official_db
def test_card_definitions_survive_a_full_duel_state_workout(repository):
    card_ids = [card.id for card in repository.all_cards()[:60]]
    assert len(card_ids) == 60

    before = {card_id: snapshot(repository.get(card_id)) for card_id in card_ids}

    state = GameState.create(
        repository,
        decks=(card_ids[:40], card_ids[20:60]),
        extra_decks=(card_ids[40:55], []),
    )

    # 상태를 쥐어짜듯 바꾼다.
    state.draw(0, 5)
    state.draw(1, 5)
    for card in list(state.player(0).hand):
        state.move(card, Zone.MZONE, position=Position.FACEUP_ATTACK)
    for card in list(state.player(0).monster_zone):
        card.add_counter("SPELL", 3)
        card.set_status(0xFF)
        card.materials.append(InstanceId(999))
        card.set_controller(1)
    state.move(state.player(1).hand[0], Zone.GRAVE, to_player=0)
    state.player(0).change_life(-4000)
    state.uses.mark_effect_used(0, EffectRef(card_ids[0], 0))
    state.uses.mark_card_name_used(0, card_ids[0])
    state.turn.begin_next_turn()
    state.clone().draw(1, 10)

    after = {card_id: snapshot(repository.get(card_id)) for card_id in card_ids}

    changed = [card_id for card_id in card_ids if before[card_id] != after[card_id]]
    assert changed == [], f"카드 정의가 변경되었습니다: {changed}"


@requires_official_db
def test_instance_reads_the_live_definition_rather_than_a_copy(repository):
    card = repository.all_cards()[0]
    state = GameState.create(repository, decks=([card.id], []))
    instance = state.player(0).deck[0]

    assert instance.definition is repository.get(card.id)
    assert instance.name == card.name

    instance.place(Zone.GRAVE)
    assert instance.definition is repository.get(card.id)


@requires_official_db
def test_clone_shares_definitions_but_not_state(repository):
    card_ids = [card.id for card in repository.all_cards()[:40]]
    state = GameState.create(repository, decks=(card_ids, []))
    copy = state.clone()

    original_card = state.player(0).deck[0]
    cloned_card = copy.player(0).deck[0]

    assert original_card is not cloned_card
    assert original_card.definition is cloned_card.definition

    cloned_card.add_counter("SPELL")
    assert original_card.counter("SPELL") == 0


@requires_official_db
def test_effect_ref_resolves_against_the_live_definition(repository):
    card = next(
        (c for c in repository if c.script and len(c.script.effects) >= 2), None
    )
    if card is None:  # pragma: no cover - 데이터가 있으면 도달하지 않는다
        pytest.skip("효과가 2개 이상인 카드가 없습니다.")

    state = GameState.create(repository, decks=([card.id], []))
    instance = state.player(0).deck[0]

    ref = EffectRef(card.id, 1)
    assert ref.resolve(instance.definition) is card.script.effects[1]
