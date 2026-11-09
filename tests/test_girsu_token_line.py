"""
Phase 6-AF — **기르수 ③ 의 토큰으로 갈라테아까지 가는 경로가 도는가.**

이 파일이 재는 것
-----------------
``deck.combo_policy.ORCUST_GIRSU_TOKEN_LINE`` 의 네 단계가 **실제 엔진
행동으로** 수행되는지, 그리고 그 네 단계를 가능하게 한 네 계약이 **범위
밖에서는 열리지 않는지**.

    1  「잭나이츠 오르페골 기르수」 일반 소환
    2  기르수 ③ — 서로의 필드에 「성유물 토큰」 1장씩
    3  **자신의** 토큰 → 「오르페골 갈라테아i」 링크 소환 (토큰은 소멸)
    4  기르수 + 갈라테아i → 「오르페골 갈라테아」 링크 소환

====================================  =================================
새 계약                                 어디에 있는가
====================================  =================================
토큰 생성 · 소멸                         :mod:`engine.token`
링크 몬스터를 소재로 (링크 수치 기여)      :func:`~engine.link_rules.
                                       material_contribution`
턴당 링크 소환 제한                       :data:`~engine.link_rules.
                                       LINK_SUMMON_ONCE_PER_TURN`
발동 조건과 해결 시점 재검사의 분리        ``EffectDefinition.
                                       resolution_condition``
====================================  =================================

실제와 합성
-----------
========================================================  ==============
``69811710`` · ``46647145`` · ``48835607`` · ``30741503``   🔴 실제 카드
``42009836`` 파슬 다이너 파키세팔로 (특수 소환 금지)          🔴 실제 카드
``59822133`` 청안의 정령룡 (동시 다수 특수 소환 금지)          🔴 실제 카드
``21844576`` 엘리멘틀 히어로 페더맨 (통상 몬스터)              🔴 실제 카드
초기 판 구성 (필드 · 엑스트라 덱에 카드 놓기)                 **구성**
발동과 해결 사이의 상태 변화를 만드는 합성 효과                **격리 등록소**
========================================================  ==============

🔴 **초기 판 구성 뒤의 변화는 전부 엔진이 만든다.** 이 파일에 전개를
``state.move`` 로 재현하는 자리는 없고, 판정 결과를 주입하는 자리도 없다.

🔴 **합성 효과는 격리된 등록소에만 등록한다** (§F). production 의
:data:`~engine.effect.library.EFFECT_LIBRARY` 는 한 줄도 바뀌지 않는다.
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from deck.combo_policy import (
    COMBO_LINES,
    ORCUST_GIRSU_LINE,
    ORCUST_GIRSU_TOKEN_HAND,
    ORCUST_GIRSU_TOKEN_LINE,
    ORCUST_VERIFICATION_RECIPE,
    line_named,
    line_progress,
)
from deck.opening import build_opening, execute_opening
from deck.recipe import parse_recipe
from engine.action import PlayerAction, PlayerActionKind
from engine.condition import ConditionResult, PlayerRef
from engine.duel import Duel, duel_components
from engine.effect.delta import (
    MonsterSummoned,
    SummonKind,
    TokenCreated,
    TokenVanished,
    ZoneMoved,
)
from engine.effect.definition import EffectDefinitionRegistry
from engine.effect.library import (
    EFFECT_LIBRARY,
    WORLD_LEGACY_TOKEN,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import CreateTokenOperation, OperationKind, TokenSpec
from engine.effect.resolution import ResolutionStatus
from engine.ids import EffectRef
from engine.link_rules import (
    LINK_MATERIAL_RULE_MISSING,
    LINK_SUMMON_KIND,
    LINK_SUMMON_ONCE_PER_TURN,
    LinkMaterialEligibility,
    assess_link_materials,
    material_contribution,
    material_rule_for,
    turn_limit_for,
)
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.summon_restriction import (
    SIMULTANEOUS_SUMMON_PROHIBITIONS,
    SpecialSummonPermission,
    assess_simultaneous_special_summon_permission,
    prohibition_for,
)
from engine.token import (
    TOKEN_AS_OVERLAY_RULE,
    TOKEN_OPERATION_BLIND_SPOTS,
    TOKEN_RULES,
    TOKEN_TO_MAIN_DECK_RULE,
    TOKEN_ZONE,
    TokenError,
    is_token,
    token_operation_refusal,
    token_rule_for,
    vanish_token,
    verify_token_definition,
)
from engine.use_limit import LimitScope
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db

GIRSU = 69811710
TOKEN = 46647145
GALATEA = 30741503
GALATEA_I = 48835607
PACHY = 42009836
BLUE_EYES_SPIRIT = 59822133
FEATHERMAN = 21844576
LONGIRSU = 76145142
#: 🔴 **소재 조건을 읽지 않은** 링크 몬스터 (잭나이츠 오르페골 엔릴기르수,
#: LINK-4). Phase 6-AN 이 롱기르수를 등록했으므로 ``test_d05`` 의 미등록
#: 예시가 이 카드로 옮겨졌다.
ENLILGIRSU = 74820316
#: 🔴 **판을 채우는 몬스터**. 특수 소환 금지 신호가 ``()`` 인 **실제 카드**를
#: 쓴다 — 스크립트가 없는 통상 몬스터를 쓰면 금지 판정이 ``UNDETERMINED``
#: 가 되고 (``special_summon_restriction_signals is None``), 재려는 사실이
#: 그 모름에 가려진다. ``test_a06`` 이 그 선택의 근거를 센다.
FILLER = GIRSU
#: 🔴 **신호를 적었는데 손으로 읽은 표에 없는** 실제 카드 — 오르페골
#: 트로이메어 (LINK-2, ``EFFECT_CANNOT_SPECIAL_SUMMON`` 신호 있음).
#:
#: 🔴 **이 자리의 카드는 표가 늘 때마다 바뀐다.** 6-AF 는 「오르페골
#: 디베르」(57835716)가 이 자리였고, Phase 6-AO 가 디베르의 묘지 효과 ① 을
#: 등재하면서 **그 신호가 무엇이었는지**를 손으로 읽어 표에 적었다
#: (``prohibits=False`` — 「① 을 쓴 **그 턴에만** 어둠 속성으로 제한한다」
#: 는 뜻이고 「필드에 있으면 특수 소환할 수 없다」 가 아니다). 그래서
#: 디베르는 더 이상 "읽지 않은" 예시가 아니다. **이전 단언이 틀렸던 것이
#: 아니라, 그때는 그 카드가 정말 표에 없었다** — 재는 것은 "읽지 않은
#: 신호는 ``UNDETERMINED`` 다" 이고 특정 카드가 아니다.
#:
#: 실측 (``scratchpad/ao/probe_unjudged3.py``): 신호를 적었고 표에 없는
#: 몬스터가 536장이며, 그중 「오르페골」 계열은 이 카드 하나다.
UNJUDGED = 4055337
P0, P1 = 0, 1

#: 기르수 ③ 의 ordinal. **추측이 아니다** — ``test_a01`` 이 파싱 결과와
#: 대조한다.
TOKEN_ORDINAL = 2
TOKEN_EFFECT = EffectRef(GIRSU, TOKEN_ORDINAL)
GRAVE_EFFECT = EffectRef(GIRSU, 0)

pytestmark = requires_official_db


# ======================================================================
# 공용 — 판을 만들고 경로를 돌린다
# ======================================================================
def _board(
    repository,
    *,
    mine=(GIRSU,),
    theirs=(),
    extra=(),
    emzone=(),
    their_mzone_fill=0,
    turn_number=3,
):
    """
    **시작 상태**를 만든다.

    🔴 **Phase 6-AG 가 이 설명을 정정했다.** 6-AF 는 여기에 "이 뒤의 변화는
    전부 엔진이 만든다" 고 적었는데, 이 파일의 ``F`` 절(``test_f01`` ·
    ``test_f02``)은 그렇지 않다 — 해결 직전 판을 ``state.create_instance`` ·
    ``state.move`` 로 **직접** 만들고 ``executor.execute`` 를 부른다. 그
    둘은 **단위 검증**이고 각자의 docstring 이 그렇게 적는다.

    나머지 절(``B`` · ``C`` · ``D`` · ``E`` · ``H``)은 첫 행동 뒤의 변화를
    ``Duel.apply`` 에만 맡긴다. **실제 체인을 지나는 통합 검증**은
    ``tests/test_girsu_token_chain_integration.py`` 가 따로 들고 있다.

    ``their_mzone_fill`` 은 상대 몬스터 존을 통상 몬스터로 채운다 — 기르수
    ③ 의 ``Duel.GetLocationCount(1-tp,LOCATION_MZONE)>0`` 를 거짓으로
    만드는 유일한 길이다 (칸이 5개이므로 5장).
    """
    state = GameState.create(
        repository,
        decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20),
        turn_player=P0,
        seed=1,
        shuffle=False,
    )
    field = []
    for index, card_id in enumerate(mine):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field.append(instance.instance_id)
    for index, card_id in enumerate(emzone):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.EMZONE)
        state.move(
            instance,
            Zone.EMZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field.append(instance.instance_id)
    for index, card_id in enumerate(
        tuple(theirs) + (FILLER,) * their_mzone_fill
    ):
        instance = state.create_instance(card_id, owner=P1, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P1,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
    extra_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.EXTRA).instance_id
        for card_id in extra
    ]
    state.turn.turn_number = turn_number
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )
    return duel, field, extra_ids


def _activate(duel, source, ref=TOKEN_EFFECT):
    return duel.apply(
        PlayerAction.activate_effect(actor=P0, source=source, effect_ref=ref)
    )


def _settle(duel):
    """체인을 풀 때까지 ``PASS`` 를 지나간다. 다른 행동은 고르지 않는다."""
    for _ in range(8):
        duel.advance()
        legal = duel.legal_actions(duel.to_act)
        passes = [
            a for a in legal.allowed if a.kind is PlayerActionKind.PASS
        ]
        if not passes:
            return
        duel.apply(passes[0])


def _pick_link(duel, source, materials):
    """
    **엔진이 낸 후보에서** 그 링크 소환을 고른다.

    🔴 소재의 **순서**는 엔진이 정한다 — 손으로 만든 순서가 다르면
    ``Duel.apply`` 가 "허가된 행위가 아니다" 로 거절한다 (실측). 시험이
    재려는 것은 순서가 아니라 그 소환이 일어나는가다.
    """
    duel.advance()
    legal = duel.legal_actions(P0)
    want = set(materials)
    for action in legal.allowed:
        if (
            action.kind is PlayerActionKind.LINK_SUMMON
            and action.source == source
            and set(action.materials) == want
        ):
            return duel.apply(action)
    held = [
        f"{w.code.value}/{w.missing}"
        for w in legal.withheld
        if w.kind is PlayerActionKind.LINK_SUMMON
    ]
    raise AssertionError(f"후보에 없습니다: {source} ← {materials} / 보류 {held}")


def _tokens(state, seat):
    return [c for c in state.zone(seat, Zone.MZONE) if c.card_id == TOKEN]


def _run_token_line(repository, *, hand=None, line=None):
    """
    경로를 ``/combo`` 와 **같은 배선**으로 돌린다.
    """
    from app.main import opening_wiring

    line = line if line is not None else ORCUST_GIRSU_TOKEN_LINE
    draft = parse_recipe(line.recipe_ydk, repository).draft
    assert draft is not None
    chooser, triggers = opening_wiring(repository, line)
    setup = build_opening(
        repository,
        draft,
        list(hand if hand is not None else line.hand),
        chooser=chooser,
        triggers=triggers,
    )
    assert setup.can_run, setup.blockers
    return setup, execute_opening(setup, repository, choose=line.policy())


# ======================================================================
# A. 카드 데이터 · 정의 — 추측하지 않았다
# ======================================================================


@pytest.mark.real_card
def test_a01_the_ordinal_and_the_token_id_come_from_the_data(repository):
    """
    🔴 **effect ordinal 과 토큰 ID 를 추측하지 않았다** (§1 금지).

    ordinal 은 파싱 결과의 세 번째 항이고, 토큰 ID 는 상수 파일의
    ``TOKEN_WORLD_LEGACY`` 다 — 같은 이름의 69811711 이 **아니다.**
    """
    blocks = repository.get(GIRSU).script.effects
    assert blocks[TOKEN_ORDINAL].effect_types == ["IGNITION"]
    assert list(blocks[TOKEN_ORDINAL].ranges) == ["MZONE"]
    assert set(blocks[TOKEN_ORDINAL].categories) == {
        "SPECIAL_SUMMON",
        "TOKEN",
    }

    #: ① · ② 와 **다른 사용 제한 칸**이다.
    assert blocks[0].count_limit == "1,id"
    assert blocks[1].count_limit == "1,id"
    assert blocks[TOKEN_ORDINAL].count_limit == "1,{id,1}"

    #: 토큰 ID — 상수 파일이 가리키는 번호.
    assert WORLD_LEGACY_TOKEN == TOKEN
    constant_line = (
        pathlib.Path(__file__).resolve().parents[1]
        / "data"
        / "constants"
        / "card_counter_constants.lua"
    ).read_text(encoding="utf-8")
    assert f"TOKEN_WORLD_LEGACY={TOKEN}" in constant_line.replace(" ", "")
    #: 🔴 같은 이름의 다른 번호가 **실제로 있다.**
    import sqlite3

    from tests.conftest import CARDS_CDB

    connection = sqlite3.connect(f"file:{CARDS_CDB}?mode=ro", uri=True)
    try:
        names = dict(
            connection.execute(
                "SELECT id, name FROM texts WHERE id IN (?, ?)",
                (TOKEN, 69811711),
            )
        )
    finally:
        connection.close()
    assert names[TOKEN] == names[69811711]
    assert token_rule_for(69811711) is None


@pytest.mark.real_card
def test_a02_the_token_data_is_checked_against_the_database(repository):
    """
    🔴 **토큰의 이름 · 카드군 · 종족 · 속성 · 레벨 · 공수에 근거가 있다.**

    손으로 적은 표와 ``cards.cdb`` 를 대조하고, 어긋나면 그 사실이 문장으로
    나온다.
    """
    rule = token_rule_for(TOKEN)
    assert rule is not None
    assert verify_token_definition(rule, repository.get(TOKEN)) is None

    definition = repository.get(TOKEN)
    assert definition.is_token is True
    assert definition.setcodes == [0xFE]
    assert (definition.race_name, definition.attribute_name) == (
        "MACHINE",
        "DARK",
    )
    assert (definition.level, definition.atk, definition.defense) == (1, 0, 0)

    #: 표가 데이터와 달라지면 **그 사실이 문장으로 나온다** (조용히 통과하지
    #: 않는다).
    wrong = dataclasses.replace(rule, level=7)
    said = verify_token_definition(wrong, definition)
    assert said is not None and "레벨" in said


@pytest.mark.real_card
def test_a03_a_token_has_no_script_and_that_is_a_fact_not_a_gap(repository):
    """
    🔴 **토큰의 "제약 상수 없음" 은 확인된 사실이다** (``()``, ``None`` 아님).

    합치면 토큰이 필드에 놓인 것만으로 그 뒤의 모든 특수 소환 판정이
    ``UNDETERMINED`` 가 된다 — 규칙이 막지 않는 판이 엔진 미지원으로
    집계되는 자리다.
    """
    definition = repository.get(TOKEN)
    assert definition.script is None
    assert definition.special_summon_restriction_signals == ()
    assert definition.normal_summon_restriction_signals == ()
    assert definition.has_printed_effect is False

    #: 🔴 **스크립트가 없는 다른 카드는 여전히 ``None`` 이다** — 토큰만
    #: 예외이고, 그 근거는 토큰에 카드 텍스트가 없다는 것이다.
    others = [
        card
        for card in repository.all_cards()
        if card.script is None and card.has_printed_effect
    ]
    assert others, "스크립트 없는 효과 카드가 하나도 없으면 이 대조가 무의미하다"
    assert others[0].special_summon_restriction_signals is None


@pytest.mark.real_card
def test_a04_the_token_is_not_in_the_search_list(repository):
    """
    🔴 **검색 · 덱 구축이 보는 목록은 늘지 않았다.** 토큰은 덱에 넣을 수
    없으므로 (공식 규칙) 거기 섞이면 "넣을 수 있다" 로 읽힌다.

    정의는 **ID 로 묻는 길**에서만 나온다 (듀얼 중의 토큰 개체가 그 길을
    쓴다).
    """
    assert [c for c in repository.all_cards() if c.is_token] == []
    assert repository.get(TOKEN) is not None
    assert repository.token(TOKEN) is not None
    assert repository.token(GIRSU) is None
    assert set(repository.tokens) >= {TOKEN}


@pytest.mark.real_card
def test_a05_the_definition_separates_activation_from_resolution(repository):
    """
    🔴 **발동 조건과 해결 시점 재검사가 다르다** (§1).

    ``s.tkop`` 은 ``s.tktg`` 의 다섯만 다시 보고 ``SetCondition`` 은 보지
    않는다. 그래서 ``activation`` 이 ``resolution_condition`` 보다 **한 항
    많다.**
    """
    entry = entry_for(TOKEN_EFFECT)
    assert entry is not None and entry.executable is True
    definition = entry.definition

    assert definition.activation is not None
    assert definition.resolution_condition is not None
    inner = definition.activation.children
    assert definition.resolution_condition.children == inner[1:]
    assert len(inner) == len(definition.resolution_condition.children) + 1
    #: 빠진 한 항이 ``SetCondition`` — "이 카드 외의 몬스터가 없다" 다.
    assert "이 카드 말고" in inner[0].describe_ko()

    #: 발동 자리를 적었다 — 묘지 · 덱의 기르수로는 발동할 수 없다.
    assert definition.activation_zones == frozenset({Zone.MZONE})

    #: 사용 제한의 열쇠가 ① 과 **겹치지 않는다.**
    assert definition.use_limit.scope is LimitScope.PER_EFFECT
    grave = entry_for(GRAVE_EFFECT).definition
    assert grave.use_limit.scope is LimitScope.PER_CARD_NAME
    assert definition.use_limit.key_for(
        P0, TOKEN_EFFECT, None
    ) != grave.use_limit.key_for(P0, GRAVE_EFFECT, None)
    #: 🔴 **카드명 단위다** — 열쇠가 개체 번호에 달려 있지 않다
    #: (``{id,1}`` 의 ``id`` 가 카드명이다).
    from engine.ids import InstanceId

    assert definition.use_limit.key_for(
        P0, TOKEN_EFFECT, InstanceId(7)
    ) == definition.use_limit.key_for(P0, TOKEN_EFFECT, InstanceId(99))
    assert definition.use_limit.key_for(P0, TOKEN_EFFECT, None) == (
        P0,
        GIRSU,
        TOKEN_ORDINAL,
    )
    #: 플레이어가 다르면 다른 열쇠다.
    assert definition.use_limit.key_for(
        P1, TOKEN_EFFECT, None
    ) != definition.use_limit.key_for(P0, TOKEN_EFFECT, None)


# ======================================================================
# B. 토큰 생성 — 양쪽에 한 장씩
# ======================================================================


@pytest.mark.real_card
def test_b01_both_tokens_are_created_on_both_fields(repository):
    """
    🔴 **서로의 필드에 한 장씩, 앞면 수비 표시로** (공식 텍스트).

    그리고 **덱 · 패 · 엑스트라 덱의 장수가 변하지 않는다** — 토큰은 어느
    자리에서도 오지 않는다.
    """
    duel, field, _extra = _board(repository)
    before = tuple(
        (
            len(duel.state.zone(seat, Zone.DECK)),
            len(duel.state.zone(seat, Zone.HAND)),
            len(duel.state.zone(seat, Zone.EXTRA)),
        )
        for seat in (P0, P1)
    )
    step = _activate(duel, field[0])
    assert step.accepted is True, step.reason
    _settle(duel)

    state = duel.state
    mine, theirs = _tokens(state, P0), _tokens(state, P1)
    assert len(mine) == 1 and len(theirs) == 1
    for seat, cards in ((P0, mine), (P1, theirs)):
        card = cards[0]
        assert card.position is Position.FACEUP_DEFENSE
        assert (card.owner, card.controller) == (seat, seat)
        assert card.zone is TOKEN_ZONE
        #: 개체 번호가 **서로 다르다.**
    assert mine[0].instance_id != theirs[0].instance_id

    after = tuple(
        (
            len(state.zone(seat, Zone.DECK)),
            len(state.zone(seat, Zone.HAND)),
            len(state.zone(seat, Zone.EXTRA)),
        )
        for seat in (P0, P1)
    )
    assert after == before


@pytest.mark.real_card
def test_b02_the_summoner_and_the_controller_are_recorded_separately(
    repository,
):
    """
    🔴 **해결한 사람과 놓인 쪽을 가른다.** 상대 필드의 토큰은 P0 가
    해결했지만 P1 의 것이다 — 한 칸에 두 사실을 담으면 상대 토큰이 자신의
    것으로 읽힌다.

    그리고 **실제 소환 사건**이 함께 남는다 (토큰은 특수 소환된다).
    """
    duel, field, _extra = _board(repository)
    _activate(duel, field[0])
    _settle(duel)

    deltas = [d for event in duel.journal for d in event.deltas]
    created = [d for d in deltas if isinstance(d, TokenCreated)]
    summoned = [
        d
        for d in deltas
        if isinstance(d, MonsterSummoned) and d.from_zone is None
    ]
    assert len(created) == 2 and len(summoned) == 2
    assert {d.summoner for d in created} == {P0}
    assert {d.controller for d in created} == {P0, P1}
    assert {d.owner for d in created} == {P0, P1}
    #: 생성 관계 — **누가 만들었는가.**
    assert {d.creator_card_id for d in created} == {GIRSU}
    assert {d.creator for d in created} == {field[0]}
    #: 소환 사건은 특수 소환이고 **출발 자리가 없다.**
    assert {d.summon for d in summoned} == {SummonKind.SPECIAL}
    assert {d.position for d in summoned} == {Position.FACEUP_DEFENSE}


@pytest.mark.real_card
def test_b03_another_monster_on_my_field_refuses_the_activation(repository):
    """
    🔴 **자신 필드에 이 카드 외의 몬스터가 있으면 발동할 수 없다**
    (``e3:SetCondition``). 규칙이 막은 것이고 미지원이 아니다.
    """
    duel, field, _extra = _board(repository, mine=(GIRSU, FILLER))
    before = duel.state.state_hash()
    legal = duel.legal_actions(P0)
    refs = {
        a.effect_ref
        for a in legal.allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    }
    assert TOKEN_EFFECT not in refs

    step = _activate(duel, field[0])
    assert step.accepted is False
    #: 🔴 **규칙이 막은 것**이고 미지원이 아니다.
    assert step.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert duel.state.state_hash() == before
    assert _tokens(duel.state, P0) == [] and _tokens(duel.state, P1) == []


@pytest.mark.real_card
def test_b04_a_full_zone_on_either_side_refuses_the_activation(repository):
    """
    🔴 **양쪽 몬스터 존에 빈 칸이 있어야 한다** (``s.tktg`` 의 둘).

    상대 쪽이 꽉 찬 판에서도 거절되고, 그때 **자신 쪽에도 토큰이 생기지
    않는다** (한 장만 만들고 멈추지 않는다).
    """
    duel, field, _extra = _board(repository, their_mzone_fill=5)
    before = duel.state.state_hash()
    step = _activate(duel, field[0])
    assert step.accepted is False
    assert duel.state.state_hash() == before
    assert _tokens(duel.state, P0) == []
    assert "빈 칸" in step.reason or "빈 칸" in str(step.notes)


@pytest.mark.real_card
def test_b05_a_confirmed_special_summon_ban_refuses_the_activation(
    repository,
):
    """
    🔴 **확인된 특수 소환 금지가 걸린 판에서는 발동할 수 없다.**

    파슬 다이너 파키세팔로가 **상대** 필드에 있는 판이다 — 「서로 특수
    소환할 수 없다」 이므로 자신에게도 걸린다.
    """
    duel, field, _extra = _board(repository, theirs=(PACHY,))
    before = duel.state.state_hash()
    step = _activate(duel, field[0])
    assert step.accepted is False
    assert duel.state.state_hash() == before
    assert _tokens(duel.state, P0) == [] and _tokens(duel.state, P1) == []


@pytest.mark.real_card
def test_b06_a_simultaneous_summon_ban_is_judged_not_guessed(repository):
    """
    🔴 **「2장 이상 동시 특수 소환 금지」 는 특수 소환 금지와 다른 질문이다.**

    청안의 정령룡의 공식 텍스트가 "2 or more monsters at the same time" 이고,
    그 금지는 **한 장짜리 특수 소환을 막지 않는다.**
    """
    assert [r.card_id for r in SIMULTANEOUS_SUMMON_PROHIBITIONS] == [
        BLUE_EYES_SPIRIT
    ]
    duel, field, _extra = _board(repository, theirs=(BLUE_EYES_SPIRIT,))
    view = duel.view(P0)

    two = assess_simultaneous_special_summon_permission(view, P0, 2)
    assert two.permission is SpecialSummonPermission.FORBIDDEN
    assert two.blocker_card_id == BLUE_EYES_SPIRIT
    #: 🔴 한 장은 막지 않는다 — 규칙에 없는 금지를 만들지 않는다.
    one = assess_simultaneous_special_summon_permission(view, P0, 1)
    assert one.permission is SpecialSummonPermission.ALLOWED

    #: 그래서 토큰 두 장은 발동할 수 없고, 판은 그대로다.
    before = duel.state.state_hash()
    step = _activate(duel, field[0])
    assert step.accepted is False
    assert duel.state.state_hash() == before


@pytest.mark.real_card
def test_b07_an_unjudgeable_restriction_stays_unknown(repository):
    """
    🔴 **판정하지 못한 제약을 허가로 바꾸지 않는다** (§1 금지).

    「오르페골 트로이메어」(4055337)는 특수 소환 금지 신호를 적었고 손으로
    읽은 표에 없다 — 그때 답은 ``UNDETERMINED`` 이고 ``ALLOWED`` 가 아니다.
    (6-AF 는 디베르가 이 예시였다 — 왜 옮겼는지는 ``UNJUDGED`` 주석에
    적었다.)
    """
    definition = repository.get(UNJUDGED)
    assert definition.special_summon_restriction_signals
    assert prohibition_for(UNJUDGED) is None

    duel, field, _extra = _board(repository, theirs=(UNJUDGED,))
    before = duel.state.state_hash()
    step = _activate(duel, field[0])
    assert step.accepted is False
    #: 🔴 **모름이다** — 규칙이 금지한다고 적지 않는다.
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert duel.state.state_hash() == before
    assert _tokens(duel.state, P0) == []


@pytest.mark.real_card
def test_b08_the_same_turn_reuse_is_refused_but_the_other_effect_is_not(
    repository,
):
    """
    🔴 **1턴에 1번이고, 그 칸이 ① 과 다르다** (``SetCountLimit(1,{id,1})``).

    ③ 을 쓴 뒤 ③ 은 막히고, ``UseRegistry`` 의 ① 칸은 **비어 있다.**
    """
    duel, field, _extra = _board(repository)
    assert _activate(duel, field[0]).accepted is True
    _settle(duel)
    assert len(_tokens(duel.state, P0)) == 1

    #: ③ 을 다시 발동하려 하면 거절된다 (판은 그대로).
    before = duel.state.state_hash()
    again = _activate(duel, field[0])
    assert again.accepted is False
    assert duel.state.state_hash() == before
    assert len(_tokens(duel.state, P0)) == 1

    #: 🔴 **① 의 칸은 쓰이지 않았다.**
    uses = duel.state.uses
    assert uses.per_effect.get((P0, GIRSU, TOKEN_ORDINAL)) == 1
    assert uses.per_card_name == {}
    assert uses.card_name_used(P0, GIRSU) is False


# ======================================================================
# C. 토큰의 생명주기 — 떠나면 사라진다
# ======================================================================


@pytest.mark.real_card
def test_c01_a_token_used_as_link_material_vanishes_without_a_grave_event(
    repository,
):
    """
    🔴 **토큰은 묘지로 가지 않는다** — 그리고 「묘지로 보내짐」 사건을
    **만들지 않는다.**

    ``ZoneMoved(send_to_grave)`` 로 적으면 묘지에 가지도 않은 카드의 유발이
    발화할 자리가 된다.
    """
    duel, field, extra = _board(repository, extra=[GALATEA_I])
    assert _activate(duel, field[0]).accepted is True
    _settle(duel)
    token = _tokens(duel.state, P0)[0]
    token_id = token.instance_id

    step = _pick_link(duel, extra[0], (token_id,))
    assert step.accepted is True, step.reason

    state = duel.state
    #: 어느 존에도 남지 않는다.
    assert state.find_instance(token_id) is None
    assert [c.card_id for c in state.zone(P0, Zone.GRAVE)] == []
    assert [c.card_id for c in state.zone(P0, Zone.HAND)] == []
    assert [c.card_id for c in state.zone(P0, Zone.DECK)].count(TOKEN) == 0
    #: 🔴 상대의 토큰은 **그대로 남는다.**
    assert len(_tokens(state, P1)) == 1

    deltas = [d for event in duel.journal for d in event.deltas]
    vanished = [d for d in deltas if isinstance(d, TokenVanished)]
    assert len(vanished) == 1
    assert vanished[0].card == token_id and vanished[0].card_id == TOKEN
    assert vanished[0].from_zone is Zone.MZONE
    #: 🔴 **허위 묘지행 사건이 없다.**
    moved = [
        d
        for d in deltas
        if isinstance(d, ZoneMoved) and d.card == token_id
    ]
    assert moved == []


@pytest.mark.real_card
def test_c02_the_opponents_token_is_not_my_material(repository):
    """
    🔴 **남의 토큰을 자신의 링크 소재로 쓸 수 없다** — 규칙이 막은 것이다.
    """
    duel, field, extra = _board(repository, extra=[GALATEA_I])
    assert _activate(duel, field[0]).accepted is True
    _settle(duel)
    theirs = _tokens(duel.state, P1)[0].instance_id

    verdict = assess_link_materials(duel.view(P0), P0, extra[0], (theirs,))
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "몬스터입니다" in verdict.reason

    before = duel.state.state_hash()
    duel.advance()
    step = duel.apply(PlayerAction.link_summon(P0, extra[0], (theirs,)))
    assert step.accepted is False
    assert duel.state.state_hash() == before


@pytest.mark.real_card
def test_c03_unimplemented_token_operations_are_blocked_by_name(repository):
    """
    🔴 **지원하지 않는 토큰 조작을 조용히 통과시키지 않는다** (§2).

    그리고 그 범위가 **이름으로** 적혀 있다.
    """
    assert token_operation_refusal(Zone.DECK) == TOKEN_TO_MAIN_DECK_RULE
    assert token_operation_refusal(Zone.HAND) == TOKEN_TO_MAIN_DECK_RULE
    assert token_operation_refusal(Zone.EXTRA) == TOKEN_TO_MAIN_DECK_RULE
    assert token_operation_refusal(Zone.OVERLAY) == TOKEN_AS_OVERLAY_RULE
    #: 묘지 · 제외는 거절할 것이 아니다 — 결과가 **소멸**이다.
    assert token_operation_refusal(Zone.GRAVE) is None
    assert token_operation_refusal(Zone.REMOVED) is None
    assert len(TOKEN_OPERATION_BLIND_SPOTS) >= 3


@pytest.mark.real_card
def test_c04_vanishing_refuses_what_it_cannot_judge(repository):
    """
    🔴 **모르는 개체를 소멸시키지 않는다**, 그리고 **필드 밖의 카드도**.
    """
    duel, field, _extra = _board(repository)
    assert _activate(duel, field[0]).accepted is True
    _settle(duel)
    state = duel.state

    #: 토큰이 아니다.
    with pytest.raises(TokenError):
        vanish_token(state, field[0])
    #: 판에 없다.
    token = _tokens(state, P0)[0]
    assert is_token(token) is True
    assert is_token(state.find_instance(field[0])) is False
    assert is_token(None) is None


@pytest.mark.real_card
def test_c05_a_fork_does_not_share_tokens_or_use_limits(repository):
    """
    🔴 **원본과 사본이 토큰 개체 · 사용 제한 · 판을 공유하지 않는다.**
    """
    duel, field, _extra = _board(repository)
    assert _activate(duel, field[0]).accepted is True
    _settle(duel)
    original = duel.state
    fork = original.clone()

    assert fork.state_hash() == original.state_hash()
    #: 사본의 토큰을 소멸시켜도 원본은 그대로다.
    token = _tokens(fork, P0)[0].instance_id
    vanish_token(fork, token, reason="시험")
    assert fork.find_instance(token) is None
    assert original.find_instance(token) is not None
    assert fork.state_hash() != original.state_hash()

    #: 사용 제한도 따로다.
    fork.uses.mark_card_name_used(P0, GIRSU)
    assert original.uses.card_name_used(P0, GIRSU) is False
    assert fork.uses.card_name_used(P0, GIRSU) is True


# ======================================================================
# D. 링크 소재와 배치
# ======================================================================


@pytest.mark.real_card
def test_d01_the_token_satisfies_galatea_i_but_not_galatea(repository):
    """
    🔴 **토큰은 갈라테아i 의 소재가 되고 갈라테아의 소재가 되지 않는다.**

    갈라테아는 「효과 몬스터 2장」 을 요구하고 (``Card.IsType(TYPE_EFFECT)``)
    토큰은 통상 몬스터다 — 그 차이가 이 경로에 3 단계가 필요한 이유다.
    """
    assert material_rule_for(GALATEA_I) is not None
    assert material_rule_for(GALATEA_I).each.effect_monster is False
    assert material_rule_for(GALATEA).each.effect_monster is True

    duel, field, extra = _board(repository, extra=[GALATEA_I, GALATEA])
    assert _activate(duel, field[0]).accepted is True
    _settle(duel)
    token = _tokens(duel.state, P0)[0].instance_id
    view = duel.view(P0)

    ok = assess_link_materials(view, P0, extra[0], (token,))
    assert ok.eligibility is LinkMaterialEligibility.LEGAL

    #: 🔴 **직접 소재로 쓰려 하면 거절된다** (갈라테아).
    direct = assess_link_materials(view, P0, extra[1], (token, field[0]))
    assert direct.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "효과 몬스터" in direct.reason

    #: 그리고 **실행 경로도 같은 답을 낸다** — 판은 그대로다.
    before = duel.state.state_hash()
    duel.advance()
    step = duel.apply(
        PlayerAction.link_summon(P0, extra[1], (token, field[0]))
    )
    assert step.accepted is False
    assert step.code is ValidationCode.LINK_MATERIAL_INVALID
    assert duel.state.state_hash() == before


@pytest.mark.real_card
def test_d02_a_link_monster_counts_as_one_or_its_link_rating(repository):
    """
    🔴 **소재 장수와 기여를 가른다** (공식 규칙).

    🔴 **Phase 6-AG 가 이 시험의 설명과 단언을 정정했다.** 6-AF 는 여기에
    "링크 몬스터를 소재로 쓰면 그 링크 수치**만큼** 센다" 고 적었고, 그것은
    공식 규칙의 절반이다 — 룰북(RULE-SUMMON-002)은 *"you can count it as
    either 1 monster, or as a number of monsters equal to its Link Rating"*
    이다. **고르는 쪽이 1 을 택할 수 있다.**

    그래서 이 시험이 재는 것도 바뀌었다.

    - :func:`material_contribution` 은 **최대 기여**다 (판정이 쓰지 않는다).
      고를 수 있는 값 전부는 ``material_contribution_options`` 가 돌려주고,
      그 분리는 ``tests/test_link_material_count_and_rating.py`` 가 잰다.
    - 롱기르수(LINK-3) **한 장**이 갈라테아의 소재가 되지 못하는 이유는
      "기여가 3이라 넘친다" 가 아니라 **고른 카드가 1장**이라는 것이다
      (공식 3 조건의 둘째). 6-AF 의 거절 문장은 기여를 장수로 읽은
      문장이었다.
    """
    assert material_contribution(repository.get(GIRSU)) == 1
    assert material_contribution(repository.get(TOKEN)) == 1
    assert material_contribution(repository.get(GALATEA_I)) == 1
    assert material_contribution(repository.get(LONGIRSU)) == 3
    assert material_contribution(None) is None

    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA_I,), extra=[GALATEA]
    )
    materials = (field[0], field[1])
    verdict = assess_link_materials(duel.view(P0), P0, extra[0], materials)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL

    #: 🔴 **고른 카드가 한 장이면 규칙이 막는다** — 기여를 3 으로 세든
    #: 1 로 세든 「효과 몬스터 2장」 은 두 장을 요구한다.
    duel2, field2, extra2 = _board(
        repository, mine=(), emzone=(LONGIRSU,), extra=[GALATEA]
    )
    over = assess_link_materials(
        duel2.view(P0), P0, extra2[0], (field2[0],)
    )
    assert over.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "1장" in over.reason, over.reason
    assert "3장" not in over.reason, (
        "기여 3 을 장수로 적으면 6-AF 의 혼용이 문장에 남는다: " + over.reason
    )

    #: 🔴 **그리고 두 장이면 합법이다** — LINK-3 을 **1 로 세는 길**이
    #: 열려 있다는 것을 같은 판에서 못 박는다 (6-AF 는 4장이라며 막았다).
    duel3, field3, extra3 = _board(
        repository, mine=(GIRSU,), emzone=(LONGIRSU,), extra=[GALATEA]
    )
    pair = assess_link_materials(
        duel3.view(P0), P0, extra3[0], (field3[0], field3[1])
    )
    assert pair.eligibility is LinkMaterialEligibility.LEGAL, pair.reason


@pytest.mark.real_card
def test_d03_the_zone_freed_by_the_material_is_judged(repository):
    """
    🔴 **소재가 떠난 뒤의 판으로 자리를 센다.** 엑스트라 몬스터 존은 한
    칸이므로, 갈라테아i 를 소재로 보내야 갈라테아가 놓인다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA_I,), extra=[GALATEA]
    )
    assert len(duel.state.zone(P0, Zone.EMZONE)) == 1
    step = _pick_link(duel, extra[0], (field[0], field[1]))
    assert step.accepted is True, step.reason
    emzone = [c.card_id for c in duel.state.zone(P0, Zone.EMZONE)]
    assert emzone == [GALATEA]
    assert [c.card_id for c in duel.state.zone(P0, Zone.GRAVE)] == [
        GALATEA_I,
        GIRSU,
    ]


@pytest.mark.real_card
def test_d04_galatea_i_can_only_be_link_summoned_once_per_turn(repository):
    """
    🔴 **갈라테아i 는 1턴에 1번만 링크 소환할 수 있다** (``s.regop``).

    카드가 소재로 떠난 뒤에도 그 기록이 남는다 — 공식 효과도 플레이어에게
    걸리므로 카드가 사라져도 턴 끝까지 남는다.
    """
    limit = turn_limit_for(GALATEA_I)
    assert limit is not None and limit.times == 1
    assert [r.card_id for r in LINK_SUMMON_ONCE_PER_TURN] == [GALATEA_I]
    assert turn_limit_for(GALATEA) is None

    duel, field, extra = _board(
        repository, mine=(GIRSU, FILLER), extra=[GALATEA_I, GALATEA_I]
    )
    first = _pick_link(duel, extra[0], (field[0],))
    assert first.accepted is True, first.reason
    turn = duel.state.turn.turn_number
    assert duel.state.summon_uses.count(turn, P0, GALATEA_I, LINK_SUMMON_KIND) == 1
    assert duel.view(P0).summons_of(P0, GALATEA_I, LINK_SUMMON_KIND) == 1

    #: 두 번째 장은 **규칙이 막는다** (판은 그대로).
    before = duel.state.state_hash()
    verdict = assess_link_materials(
        duel.view(P0), P0, extra[1], (field[1],)
    )
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "이미" in verdict.reason
    duel.advance()
    again = duel.apply(PlayerAction.link_summon(P0, extra[1], (field[1],)))
    assert again.accepted is False
    assert duel.state.state_hash() == before


@pytest.mark.real_card
def test_d05_duplicate_and_unread_materials_are_still_separated(repository):
    """
    🔴 **중복 소재는 규칙이 막고, 읽지 않은 소재 조건은 모른다** (ADR-006).
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU,), extra=[GALATEA_I, ENLILGIRSU]
    )
    duplicate = assess_link_materials(
        duel.view(P0), P0, extra[0], (field[0], field[0])
    )
    assert duplicate.eligibility is LinkMaterialEligibility.ILLEGAL

    #: 🔴 **미등록 예시가 롱기르수에서 엔릴기르수로 옮겨졌다** (Phase 6-AN).
    #: 그때까지 롱기르수가 미등록이었던 것은 사실이고, 6-AN 이 ``count_max``
    #: 를 더해 ``2+`` 모양을 적을 수 있게 되자 등록되었다. 재는 것은 "읽지
    #: 않은 소재 조건은 모른다" 이므로, **여전히 읽지 않은** 카드로 잰다.
    assert material_rule_for(LONGIRSU) is not None
    assert material_rule_for(ENLILGIRSU) is None
    unread = assess_link_materials(
        duel.view(P0), P0, extra[1], (field[0],)
    )
    assert unread.eligibility is LinkMaterialEligibility.UNDETERMINED
    assert unread.missing_rule == LINK_MATERIAL_RULE_MISSING


# ======================================================================
# E. 전체 경로 — 실제 엔진으로 끝까지
# ======================================================================


@pytest.mark.real_card
def test_e01_the_new_line_runs_end_to_end(repository):
    """
    🔴 **『성장』 없는 시작 패에서 토큰 생성과 후속 링크 소환이 이어진다.**

    이 Phase 의 완료 기준이고, 재는 것은 테스트 통과가 아니라 **최종 판**
    이다.
    """
    setup, run = _run_token_line(repository)
    progress = line_progress(run, ORCUST_GIRSU_TOKEN_LINE)
    assert progress.completed is True, progress.describe_ko()
    assert progress.done == 4

    state = setup.duel.state
    ids = lambda seat, zone: [c.card_id for c in state.zone(seat, zone)]

    #: 자신 — 갈라테아가 엑스트라 몬스터 존에 있다.
    assert ids(P0, Zone.EMZONE) == [GALATEA]
    assert ids(P0, Zone.MZONE) == []
    #: 실제 이동 기록 — 기르수와 갈라테아i 는 묘지에 있다.
    assert sorted(ids(P0, Zone.GRAVE)) == sorted([GALATEA_I, GIRSU])
    #: 🔴 **자신의 토큰은 소멸했고 묘지에 없다.**
    assert TOKEN not in ids(P0, Zone.GRAVE)
    #: 🔴 **상대의 토큰은 남는다.**
    assert ids(P1, Zone.MZONE) == [TOKEN]

    #: 패 · 덱의 장수가 보존된다 (40장 덱에서 5장을 뽑았다).
    assert len(ids(P0, Zone.HAND)) == 4
    assert len(ids(P0, Zone.DECK)) == 35
    #: 엑스트라 덱이 두 장 줄었다.
    assert len(ids(P0, Zone.EXTRA)) == 4

    #: 사용 제한 기록 — ③ 만 썼고, 링크 소환 둘이 카드명으로 적혔다.
    assert state.uses.per_effect == {(P0, GIRSU, TOKEN_ORDINAL): 1}
    assert state.uses.per_card_name == {}
    turn = state.turn.turn_number
    assert state.summon_uses.count(turn, P0, GALATEA_I, LINK_SUMMON_KIND) == 1
    assert state.summon_uses.count(turn, P0, GALATEA, LINK_SUMMON_KIND) == 1


@pytest.mark.real_card
def test_e02_the_line_passes_the_optional_trigger_it_declines(repository):
    """
    🔴 **기르수 ① 의 발동 기회를 적법한 절차로 지나간다.**

    조용히 넘기지 않는다 — 실행 기록에 ``pass`` 걸음이 남는다.
    """
    _setup, run = _run_token_line(repository)
    kinds = [step.kind for step in run.steps if step.accepted]
    assert kinds[:5] == [
        "normal_summon",
        "pass",
        "activate_effect",
        "link_summon",
        "link_summon",
    ]
    assert ORCUST_GIRSU_TOKEN_LINE.declines == ((GIRSU, 0),)
    #: 지나간 걸음은 **판을 바꾸지 않았다.**
    passed = next(s for s in run.steps if s.kind == "pass")
    assert passed.state_changed is False


@pytest.mark.real_card
def test_e03_the_recipe_really_contains_the_hand_and_the_extra_deck(
    repository,
):
    """
    🔴 **지정한 패와 필요한 엑스트라 덱 카드가 레시피에 실제로 있다.**
    """
    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    main = [card.card_id for card in draft.main]
    extra = [card.card_id for card in draft.extra]
    for card_id in ORCUST_GIRSU_TOKEN_HAND:
        assert card_id in main, card_id
    for card_id in (GALATEA, GALATEA_I):
        assert card_id in extra, card_id
    assert ORCUST_GIRSU_TOKEN_LINE.hand == ORCUST_GIRSU_TOKEN_HAND
    #: 🔴 『성장』 이 **패에 없다** — 이 경로의 요점이다.
    assert 93920420 not in ORCUST_GIRSU_TOKEN_HAND


@pytest.mark.real_card
def test_e04_the_existing_line_still_runs(repository):
    """
    🔴 **기존 ``orcust-girsu`` 경로가 그대로 4/4 다.** 새 경로가 그것을
    바꾸지 않았다.
    """
    from app.main import opening_wiring

    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    chooser, triggers = opening_wiring(repository, ORCUST_GIRSU_LINE)
    setup = build_opening(
        repository,
        draft,
        list(ORCUST_GIRSU_LINE.hand),
        chooser=chooser,
        triggers=triggers,
    )
    run = execute_opening(
        setup, repository, choose=ORCUST_GIRSU_LINE.policy()
    )
    progress = line_progress(run, ORCUST_GIRSU_LINE)
    assert progress.completed is True, progress.describe_ko()
    assert progress.done == 4
    assert [c.card_id for c in setup.duel.state.zone(P0, Zone.EMZONE)] == [
        GALATEA
    ]
    #: 토큰이 하나도 만들어지지 않았다 (그 경로는 ③ 을 쓰지 않는다).
    assert [
        c for c in setup.duel.state.all_instances() if c.card_id == TOKEN
    ] == []


@pytest.mark.real_card
def test_e05_both_lines_are_registered_separately(repository):
    """🔴 **새 경로를 따로 등록했다.** 기존 이름은 그대로다."""
    #: 🔴 **Phase 6-AO 가 또 하나를 따로 등록했다** (디베르 경로). 기존 두
    #: 이름은 그대로다.
    assert sorted(COMBO_LINES) == [
        "orcust-girsu",
        "orcust-girsu-token",
        "orcust-harp-horror",
    ]
    assert line_named("orcust-girsu") is ORCUST_GIRSU_LINE
    assert line_named("orcust-girsu-token") is ORCUST_GIRSU_TOKEN_LINE
    assert ORCUST_GIRSU_LINE.declines == ()
    for line in COMBO_LINES.values():
        assert line.reproduction_ready is True


# ======================================================================
# F. 발동과 해결 사이에 판이 바뀌면 — **격리된 등록소**
# ======================================================================


def _isolated(definition):
    """
    그 정의 하나만 든 **격리 등록소**와 실행기 (Phase 6-AD 후속2 와 같은 자리).

    🔴 production 의 :data:`~engine.effect.library.EFFECT_LIBRARY` 를 건드리지
    않는다 — 합성 정의가 실제 전개에 새지 않게 한다.
    """
    registry = EffectDefinitionRegistry((definition,))
    implementations = implementation_registry()
    return registry, implementations


@pytest.mark.real_card
def test_f01_only_the_rechecked_conditions_are_rechecked(repository):
    """
    🔴 **발동 이후 다른 몬스터가 생겼다는 이유만으로 불발로 만들지 않는다.**

    ``s.tkop`` 은 ``SetCondition`` 을 다시 보지 않으므로, 발동 뒤에 자신
    필드에 몬스터가 늘어도 토큰은 만들어진다.

    🔴 **이것은 단위 검증이다 — 실제 체인 검증이 아니다.** 판을
    ``state.create_instance`` · ``state.move`` 로 직접 바꿔 해결 직전
    상태를 만들고 ``executor.execute`` 를 **직접** 부른다. 판정 결과를
    주입하지는 않지만 (바뀐 판에서 엔진이 내는 답을 읽는다), **발동 수락 ·
    체인 등록 · 역순 해결 · 우선권 복귀는 지나지 않는다.**

    그 통합 검증은 ``tests/test_girsu_token_chain_integration.py`` 의
    ``test_o01`` 이 한다 — 거기서는 **체인 링크 2 가 실제로 특수 소환해서**
    같은 판을 만든다 (Phase 6-AG).
    """
    from engine.effect.resolution import ResolutionContext

    definition = entry_for(TOKEN_EFFECT).definition
    duel, field, _extra = _board(repository)
    state = duel.state
    executor = build_executor(implementations=implementation_registry())

    #: 발동 조건은 지금 참이다.
    from engine.condition import ConditionEvaluator
    from engine.game_state_view import GameStateView

    view = GameStateView.from_state(state, viewer=P0)
    context = ResolutionContext(
        effect_ref=TOKEN_EFFECT, controller=P0, source=field[0]
    )
    assert (
        ConditionEvaluator(view)
        .evaluate(definition.activation, context.condition_context())
        .result
        is ConditionResult.TRUE
    )

    #: 🔴 **발동 뒤에 다른 몬스터가 생긴 판을 만든다.**
    extra_monster = state.create_instance(
        FILLER, owner=P0, zone=Zone.MZONE
    )
    state.move(
        extra_monster,
        Zone.MZONE,
        to_player=P0,
        index=1,
        position=Position.FACEUP_ATTACK,
    )
    view = GameStateView.from_state(state, viewer=P0)
    assert (
        ConditionEvaluator(view)
        .evaluate(definition.activation, context.condition_context())
        .result
        is ConditionResult.FALSE
    )
    #: 🔴 그런데 **해결 시점에 다시 보는 조건은 여전히 참이다.**
    assert (
        ConditionEvaluator(view)
        .evaluate(
            definition.resolution_condition, context.condition_context()
        )
        .result
        is ConditionResult.TRUE
    )

    result = executor.execute(state, definition, context)
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert len(_tokens(state, P0)) == 1
    assert len(_tokens(state, P1)) == 1


@pytest.mark.real_card
def test_f02_a_resolution_condition_that_turns_false_is_a_normal_no_op(
    repository,
):
    """
    🔴 **해결 시점의 조건이 거짓이면 정상 불발이다** (``s.tkop`` 의 ``if``).

    미지원도 오류도 아니고, 토큰도 만들어지지 않는다.

    🔴 **이것도 단위 검증이다** (``test_f01`` 과 같은 구분 — Phase 6-AG).
    상대 몬스터 존을 ``state.move`` 로 채우고 ``executor.execute`` 를 직접
    부른다. 같은 사실을 **실제 체인**으로 재는 것은
    ``tests/test_girsu_token_chain_integration.py`` 의 ``test_p01`` 이고,
    거기서는 체인 링크 2(함정)가 그 칸을 채운다.
    """
    from engine.effect.resolution import ResolutionContext

    definition = entry_for(TOKEN_EFFECT).definition
    duel, field, _extra = _board(repository)
    state = duel.state
    executor = build_executor(implementations=implementation_registry())

    #: 🔴 상대 몬스터 존을 채워 **해결 시점에** 재검사가 거짓이 되게 한다.
    for index in range(5):
        instance = state.create_instance(
            FILLER, owner=P1, zone=Zone.MZONE
        )
        state.move(
            instance,
            Zone.MZONE,
            to_player=P1,
            index=index,
            position=Position.FACEUP_ATTACK,
        )

    context = ResolutionContext(
        effect_ref=TOKEN_EFFECT, controller=P0, source=field[0]
    )
    result = executor.execute(state, definition, context)
    assert result.status is ResolutionStatus.RESOLVED_WITHOUT_EFFECT
    assert result.resolved is True
    assert result.applied_any is False
    assert result.missing is None
    assert _tokens(state, P0) == []
    assert _tokens(state, P1) == []


@pytest.mark.real_card
def test_f03_an_unread_token_is_refused_in_an_isolated_registry(repository):
    """
    🔴 **공식 데이터를 읽지 않은 토큰을 만들지 않는다** (ADR-006).

    합성 정의를 **격리 등록소**에만 넣는다 — production 목록은 그대로다.
    """
    from engine.effect.resolution import ResolutionContext

    base = entry_for(TOKEN_EFFECT).definition
    synthetic = dataclasses.replace(
        base,
        operations=(
            CreateTokenOperation(
                tokens=(
                    TokenSpec(
                        card_id=69811711,  # 같은 이름의 **다른** 번호
                        to=PlayerRef.CONTROLLER,
                        position=Position.FACEUP_DEFENSE,
                    ),
                ),
            ),
        ),
    )
    registry, implementations = _isolated(synthetic)
    assert registry.definition_for(TOKEN_EFFECT) is synthetic
    assert entry_for(TOKEN_EFFECT).definition is base

    duel, field, _extra = _board(repository)
    state = duel.state
    before = state.state_hash()
    executor = build_executor(implementations=implementations)
    result = executor.execute(
        state, synthetic, ResolutionContext(
        effect_ref=TOKEN_EFFECT, controller=P0, source=field[0]
    )
    )
    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
    assert result.missing is not None
    assert state.state_hash() == before
    assert [
        c for c in state.all_instances() if c.card_id == 69811711
    ] == []


# ======================================================================
# G. 경계 — 어휘와 계층
# ======================================================================


def test_g01_the_token_operation_is_in_the_shared_table():
    """
    🔴 **새 일은 계획기와 수행기를 함께 등록한다** (한 표에 둘).
    """
    from engine.effect.executor import OPERATION_HANDLERS, SUPPORTED

    assert OperationKind.CREATE_TOKEN in OPERATION_HANDLERS
    assert OperationKind.CREATE_TOKEN in SUPPORTED
    handler = OPERATION_HANDLERS[OperationKind.CREATE_TOKEN]
    assert handler.plan is not None and handler.apply is not None


def test_g02_link_rules_does_not_import_the_effect_layer():
    """
    🔴 **판정은 효과 계층을 모른다** (그 모듈 머리말의 import 고리).
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    source = (root / "engine" / "link_rules.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any(name.startswith("engine.effect") for name in imported), (
        sorted(imported)
    )
    assert not any(name.startswith("core") for name in imported), sorted(
        imported
    )
    #: 그래서 소환법 이름을 **문자열로** 들고 있고, 같은 값인지 여기서 센다.
    assert LINK_SUMMON_KIND == SummonKind.LINK.value


def test_g03_the_summon_usage_registry_is_a_separate_table():
    """
    🔴 **카드명 단위 소환 기록이 효과의 1턴 1회와 섞이지 않는다.**

    갈라테아i 의 ① 이 ``UseRegistry`` 의 ``(player, card_id)`` 칸을 이미
    쓰므로, 같은 칸에 링크 소환을 적으면 둘이 서로를 막는다.
    """
    from engine.state.summon_usage import SummonUsageRegistry

    registry = SummonUsageRegistry()
    registry.record(1, P0, GALATEA_I, LINK_SUMMON_KIND)
    assert registry.used(1, P0, GALATEA_I, LINK_SUMMON_KIND) is True
    #: 턴 번호 · 플레이어 · 소환법이 전부 열쇠에 들어간다.
    assert registry.used(2, P0, GALATEA_I, LINK_SUMMON_KIND) is False
    assert registry.used(1, P1, GALATEA_I, LINK_SUMMON_KIND) is False
    assert registry.used(1, P0, GALATEA_I, "special") is False
    #: 사본이 따로 산다.
    fork = registry.clone()
    fork.record(1, P0, GALATEA, LINK_SUMMON_KIND)
    assert registry.used(1, P0, GALATEA, LINK_SUMMON_KIND) is False


def test_g04_no_card_id_branch_was_added_to_the_token_module():
    """
    🔴 **``engine/token.py`` 에 카드 ID 분기가 없다.** 번호가 나타나는
    자리는 :data:`~engine.token.TOKEN_RULES` 의 **선언 한 곳**뿐이다.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    tree = ast.parse(
        (root / "engine" / "token.py").read_text(encoding="utf-8")
    )
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and isinstance(
            node.left, ast.Attribute
        ):
            for comparator in node.comparators:
                if (
                    isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, int)
                    and comparator.value > 1000
                ):
                    found.append(ast.dump(node))
    assert found == [], found


# ======================================================================
# H. 어댑터 — 요약과 상세가 같은 말을 한다
# ======================================================================


@pytest.mark.real_card
def test_h01_the_discord_summary_and_detail_agree_on_the_new_line(repository):
    """
    🔴 **기본 요약과 상세 첨부가 같은 전개를 적는다** (Phase 6-AE 의 계약).

    🔴 **실제 Discord 전송은 하지 않는다** — 응답 값만 본다.
    """
    import app.discord_bot as bot

    response = bot.combo_response(
        _agent(repository),
        hand_text=ORCUST_GIRSU_TOKEN_LINE.hand_text(),
        recipe_text=ORCUST_VERIFICATION_RECIPE,
        line_text=ORCUST_GIRSU_TOKEN_LINE.name,
    )

    assert response.messages, "기본 요약이 비어 있습니다"
    summary = "\n".join(response.messages)
    #: 요약이 **경로를 끝냈다**고 적는다.
    assert ORCUST_GIRSU_TOKEN_LINE.name in summary
    assert "4/4" in summary

    #: 상세가 전부 담겼고 (누락 0줄), 같은 전개를 적는다.
    assert response.complete_detail is True
    assert response.detail_omitted == 0
    detail = "\n".join(item.text for item in response.attachments)
    for token in ("오르페골 갈라테아i", "오르페골 갈라테아", "World Legacy Token"):
        assert token in detail, token
    #: 🔴 요약과 상세가 **같은 걸음 수**를 적는다.
    assert "5걸음" in detail or "실행 5걸음" in detail


def _agent(repository):
    """``/combo`` 가 쓰는 것과 같은 Agent."""
    from app.main import DeckAgent

    return DeckAgent(repository)
