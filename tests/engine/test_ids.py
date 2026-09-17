"""engine/ids.py — InstanceId 유일성, EffectRef 동등성/해시."""

import pytest

from core.card_model import Card, EffectSpec, LuaScriptInfo
from engine.ids import (
    EffectRef,
    InstanceId,
    InstanceIdAllocator,
    effect_refs,
    iter_effects,
)
from tests.conftest import requires_official_db


def test_allocator_gives_unique_increasing_ids():
    allocator = InstanceIdAllocator()
    ids = [allocator.allocate() for _ in range(100)]
    assert len(set(ids)) == 100
    assert [i.value for i in ids] == list(range(100))


def test_allocator_clone_is_independent():
    allocator = InstanceIdAllocator()
    allocator.allocate()
    copy = allocator.clone()
    copy.allocate()
    assert allocator.next_value == 1
    assert copy.next_value == 2


def test_instance_id_is_hashable_and_comparable():
    assert InstanceId(3) == InstanceId(3)
    assert hash(InstanceId(3)) == hash(InstanceId(3))
    assert InstanceId(1) < InstanceId(2)
    assert {InstanceId(1), InstanceId(1)} == {InstanceId(1)}
    assert str(InstanceId(7)) == "#7"


def test_instance_id_rejects_negative():
    with pytest.raises(ValueError):
        InstanceId(-1)


def test_effect_ref_equality_and_hashing():
    assert EffectRef(2511, 0) == EffectRef(2511, 0)
    assert EffectRef(2511, 0) != EffectRef(2511, 1)
    assert EffectRef(2511, 0) != EffectRef(9999, 0)
    assert hash(EffectRef(2511, 0)) == hash(EffectRef(2511, 0))
    assert len({EffectRef(2511, 0), EffectRef(2511, 1), EffectRef(2511, 0)}) == 2


def test_effect_ref_is_immutable():
    ref = EffectRef(2511, 0)
    with pytest.raises(Exception):
        ref.ordinal = 5  # type: ignore[misc]


def test_effect_ref_rejects_negative_ordinal():
    with pytest.raises(ValueError):
        EffectRef(2511, -1)


def _card_with_duplicate_index() -> Card:
    """``EffectSpec.index`` 가 중복되는 카드 (실측 4,883장이 이런 모양이다)."""
    script = LuaScriptInfo(
        card_id=2511,
        file_name="c2511.lua",
        effects=[
            EffectSpec(index="e1", categories=["TOHAND"]),
            EffectSpec(index="e2", categories=["DESTROY"]),
            EffectSpec(index="e1", categories=["SPSUMMON"]),
        ],
    )
    return Card(id=2511, name="테스트 카드", script=script)


def test_effect_ref_separates_effects_that_share_an_index():
    card = _card_with_duplicate_index()
    indexes = [spec.index for spec in card.script.effects]
    assert len(set(indexes)) < len(indexes)  # 전제: index 가 중복된다

    refs = effect_refs(card)
    assert len(set(refs)) == 3  # 그래도 참조는 충돌하지 않는다
    assert refs[0].resolve(card).categories == ["TOHAND"]
    assert refs[2].resolve(card).categories == ["SPSUMMON"]


def test_effect_ref_resolve_rejects_other_cards_and_out_of_range():
    card = _card_with_duplicate_index()
    assert EffectRef(9999, 0).resolve(card) is None
    assert EffectRef(2511, 99).resolve(card) is None
    assert EffectRef(2511, 0).resolve(Card(id=2511)) is None  # 스크립트 없음


def test_effect_refs_of_scriptless_card_is_empty():
    assert effect_refs(Card(id=1)) == []
    assert list(iter_effects(Card(id=1))) == []


def test_iter_effects_keeps_source_order():
    card = _card_with_duplicate_index()
    pairs = list(iter_effects(card))
    assert [ref.ordinal for ref, _ in pairs] == [0, 1, 2]
    assert [spec.index for _, spec in pairs] == ["e1", "e2", "e1"]


@requires_official_db
def test_real_cards_have_duplicate_effect_index(repository):
    """설계의 전제(결함 1)가 실제 데이터에서 성립하는지 확인한다."""
    offenders = 0
    for card in repository:
        if card.script is None:
            continue
        indexes = [spec.index for spec in card.script.effects]
        if len(indexes) != len(set(indexes)):
            offenders += 1
    assert offenders > 0, "index 중복이 사라졌다면 EffectRef 근거를 다시 확인해야 한다."


@requires_official_db
def test_effect_refs_are_unique_for_every_real_card(repository):
    for card in repository:
        refs = effect_refs(card)
        assert len(refs) == len(set(refs))
