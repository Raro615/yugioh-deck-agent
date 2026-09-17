"""구조화 규칙 — 모든 항목이 원문에 연결되는가, 값을 지어내지 않았는가."""

import pytest

from rules.concept_map import (
    CONCEPT_LINKS,
    ConceptSupport,
    link_for,
    rules_for,
    ungrounded_predicates,
)
from tests.rules.conftest import requires_rulebook


# ----------------------------------------------------------------------
# 구조화 <-> 원문 연결
# ----------------------------------------------------------------------
@requires_rulebook
def test_every_structured_item_cites_at_least_one_rule(structured_rules):
    for item in structured_rules:
        assert item.rules, f"근거 없는 구조화 항목: {item}"


@requires_rulebook
def test_every_cited_rule_exists(structured_rules, rule_repository):
    dangling = sorted(
        rule_id
        for rule_id in structured_rules.referenced_rule_ids()
        if rule_id not in rule_repository
    )
    assert dangling == []


@requires_rulebook
def test_structured_doc_id_matches_the_document(structured_rules, rule_repository):
    assert structured_rules.doc_id == rule_repository.documents[0].doc_id


@requires_rulebook
def test_not_stated_fields_are_actually_empty(structured_rules):
    """룰북이 말하지 않는다고 적어놓고 값을 채워두면 안 된다."""
    for item in structured_rules:
        for field_name in item.not_stated:
            value = getattr(item, field_name, None)
            assert not value, f"{item} 의 {field_name} 은 not_stated 인데 값이 있습니다: {value!r}"


# ----------------------------------------------------------------------
# 턴 구조
# ----------------------------------------------------------------------
@requires_rulebook
def test_turn_structure_matches_the_rulebook_order(structured_rules):
    assert structured_rules.turn_order() == [
        "Draw Phase",
        "Standby Phase",
        "Main Phase 1",
        "Battle Phase",
        "Main Phase 2",
        "End Phase",
    ]


@requires_rulebook
def test_phase_names_line_up_with_engine_vocabulary(structured_rules):
    from engine.vocabulary import Phase

    for phase in structured_rules.phases:
        if phase.engine_phase is None:
            continue
        assert phase.engine_phase in Phase.__members__, phase.name


@requires_rulebook
def test_first_turn_restrictions_are_quoted_from_the_rulebook(
    structured_rules, rule_repository
):
    draw = structured_rules.phase("Draw Phase")
    assert draw.first_turn_restriction
    source = rule_repository.require("RULE-TURN-002").normalized_text
    assert draw.first_turn_restriction in source

    battle = structured_rules.phase("Battle Phase")
    assert battle.first_turn_restriction
    assert battle.first_turn_restriction in rule_repository.require(
        "RULE-TURN-005"
    ).normalized_text


@requires_rulebook
def test_battle_phase_steps(structured_rules):
    battle = structured_rules.phase("Battle Phase")
    assert battle.steps == ("Start Step", "Battle Step", "Damage Step", "End Step")


# ----------------------------------------------------------------------
# 존
# ----------------------------------------------------------------------
@requires_rulebook
def test_zone_capacities_match_the_rulebook(structured_rules):
    assert structured_rules.zone("Main Monster Zone").capacity == 5
    assert structured_rules.zone("Spell & Trap Zone").capacity == 5
    assert structured_rules.zone("Field Zone").capacity == 1
    assert structured_rules.zone("Extra Deck").capacity == 15
    # 룰북이 말하지 않는 것은 비워 둔다.
    assert structured_rules.zone("Graveyard").capacity is None


@requires_rulebook
def test_graveyard_order_is_fixed(structured_rules):
    """'The order of the cards in the Graveyard should not be changed.'"""
    grave = structured_rules.zone("Graveyard")
    assert grave.ordering == "fixed"
    assert grave.visibility == "public"


@requires_rulebook
def test_zone_names_line_up_with_engine_vocabulary(structured_rules):
    from engine.vocabulary import Zone

    for zone in structured_rules.zones:
        if zone.engine_zone is None:
            continue
        assert zone.engine_zone in Zone.__members__, zone.name


@requires_rulebook
def test_banished_zone_leaves_unstated_fields_empty(structured_rules):
    """룰북은 제외 존의 공개 여부와 순서를 규정하지 않는다."""
    banished = structured_rules.zone("Banished")
    assert banished.visibility is None
    assert banished.ordering is None
    assert "visibility" in banished.not_stated


# ----------------------------------------------------------------------
# 체인 · 스펠 스피드
# ----------------------------------------------------------------------
@requires_rulebook
def test_spell_speed_response_table(structured_rules):
    speeds = {s.speed: s for s in structured_rules.chain.spell_speeds}
    assert set(speeds) == {1, 2, 3}
    assert speeds[1].can_respond_to == ()       # 어떤 효과에도 응수할 수 없다
    assert speeds[2].can_respond_to == (1, 2)
    assert speeds[3].can_respond_to == (1, 2, 3)
    assert "Counter Trap" in speeds[3].card_types


@requires_rulebook
def test_effect_type_spell_speeds_agree_with_the_chain_table(structured_rules):
    """'Quick Effect 만 스펠 스피드 2, 나머지 몬스터 효과는 1' — 룰북 본문."""
    speeds = {e.name: e.spell_speed for e in structured_rules.effect_types}
    assert speeds == {
        "Continuous Effect": 1,
        "Ignition Effect": 1,
        "Quick Effect": 2,
        "Trigger Effect": 1,
        "Flip Effect": 1,
    }


@requires_rulebook
def test_cannot_chain_to_list_is_quoted(structured_rules, rule_repository):
    source = rule_repository.require("RULE-CHAIN-011").normalized_text
    for action in structured_rules.chain.cannot_chain_to:
        assert action in source, action


@requires_rulebook
def test_simultaneous_chain_order_is_turn_player_mandatory_first(structured_rules):
    order = structured_rules.chain.simultaneous_order
    assert order[0].startswith("turn player's mandatory")
    assert order[-1].startswith("opponent's optional")


# ----------------------------------------------------------------------
# 소환
# ----------------------------------------------------------------------
@requires_rulebook
def test_once_per_turn_summons(structured_rules):
    once = {s.summon_type for s in structured_rules.summons if s.once_per_turn}
    assert once == {"Normal Summon", "Normal Set", "Tribute Summon", "Pendulum Summon"}


@requires_rulebook
def test_special_summon_family(structured_rules):
    special = {s.summon_type for s in structured_rules.summons if s.is_special_summon}
    assert {"Xyz Summon", "Synchro Summon", "Fusion Summon", "Ritual Summon",
            "Pendulum Summon", "Link Summon"} <= special
    assert "Normal Summon" not in special


@requires_rulebook
def test_summon_types_line_up_with_engine_vocabulary(structured_rules):
    from engine.vocabulary import default_vocabulary

    vocabulary = default_vocabulary()
    if not vocabulary.summon_types:
        pytest.skip("엔진 상수 없음")
    for summon in structured_rules.summons:
        if summon.engine_summon_type is None:
            continue
        assert summon.engine_summon_type in vocabulary.summon_types, summon.summon_type


@requires_rulebook
def test_tribute_summon_counts(structured_rules):
    tribute = structured_rules.summon("Tribute Summon")
    joined = " ".join(tribute.procedure)
    assert "Level 5 or 6 require 1 Tribute" in joined
    assert "Level 7 or higher require 2 Tributes" in joined


@requires_rulebook
def test_win_conditions(structured_rules, rule_repository):
    conditions = [w.condition for w in structured_rules.win_conditions]
    assert len(conditions) == 3
    source = rule_repository.require("RULE-GAME-004").normalized_text
    for condition in conditions:
        assert condition in source, condition


# ----------------------------------------------------------------------
# 개념 연결표
# ----------------------------------------------------------------------
def test_concept_map_covers_every_predicate_kind():
    from analysis.predicate_model import PredicateKind

    mapped = {link.predicate for link in CONCEPT_LINKS}
    assert mapped == {kind.value for kind in PredicateKind}


@requires_rulebook
def test_concept_map_references_resolve(rule_repository):
    for link in CONCEPT_LINKS:
        for ref in link.rules:
            assert ref.rule_id in rule_repository, f"{link.predicate} -> {ref}"


def test_grounded_links_cite_rules_and_ungrounded_ones_do_not():
    for link in CONCEPT_LINKS:
        if link.support is ConceptSupport.NO_RULEBOOK_BASIS:
            assert link.rules == (), f"{link.predicate} 는 근거가 없다고 했는데 인용이 있습니다."
        else:
            assert link.rules, f"{link.predicate} 가 근거를 인용하지 않았습니다."


def test_previous_location_is_honestly_marked_as_unsupported():
    """
    이 룰북은 '직전 위치' 를 정의하지 않는다. 비슷해 보이는 절에 억지로 붙이면
    나중에 잘못된 판정을 그 절 근거로 구현하게 된다.
    """
    assert "previous_location" in ungrounded_predicates()
    link = link_for("previous_location")
    assert link.support is ConceptSupport.NO_RULEBOOK_BASIS
    assert rules_for("previous_location") == ()
    assert "Lua" in link.note


def test_battle_predicate_points_at_the_glossary_definition():
    assert any(ref.rule_id == "RULE-TERM-003" for ref in rules_for("battle"))
