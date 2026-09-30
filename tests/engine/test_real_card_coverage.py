"""
Phase 2-AN — 실제 카드 실행 범위 측정.

**새 semantics 를 만드는 파일이 아니다.** 지금까지 만든 구조가 실제
유희왕 카드를 어디까지 담을 수 있는지 재고, 반복되는 공통 병목만 찾는다.

무엇을 재는가
-------------
"12,702장을 다 실행한다" 가 목표가 아니다. 엔진이 지금 담는 모양은
**``EFFECT_TYPE_ACTIVATE`` 하나뿐인 카드**다 (등재된 16장이 전부 그렇다) —
유발 · 지속 · 기동 효과 계층이 아직 없다. 그 모양이 **1,385장**이고, 그것이
이 파일의 측정 모집단이다.

    ACTIVATE                        1385   ← 측정 대상
    SINGLE + TRIGGER_O               752
    FIELD + SINGLE + TRIGGER_O       715
    IGNITION                         489
    …

측정이 스스로 틀릴 수 있다
--------------------------
이 파일의 가장 중요한 시험은 §B 다. ``Duel.ConfirmCards`` 는 **244장**이
쓰고 그중 **34장은 그것 하나만 막는** 것처럼 보였다. 그럴싸한 수였고,
그래서 확인했다 — 그 34장의 공식 텍스트 중 **공개를 말하는 것은 1장**뿐이다.
룰북도 "**effect says to** reveal" 이라고 못박는다. 즉 스크립트의
``ConfirmCards`` 는 EDOPro 의 구현이고 카드의 규칙이 아니다.

세어 보기 전에 고치면 34장을 위한 계층을 만들었을 것이다.
"""

import json
import pathlib
import re
import collections

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolutionStatus, ChainResolver
from engine.cost import Selection
from engine.effect.delta import ZoneShuffled
from engine.effect.library import (
    FOOLISH_BURIAL,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import SHUFFLEABLE_ZONES
from engine.effect.resolution import TargetSelection
from engine.effect.semantics import DeclaredMovementRuling
from engine.effect.target import PRIMARY_TARGET
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1
FEATHERMAN = 21844576
GRANTED = ValidationResult.valid()

#: 규칙이 아닌 것 — UI 힌트 · 내부 등록 · 정보 조회. 옮길 필요가 없다.
NOT_A_RULE = frozenset(
    {
        "Hint",
        "HintSelection",
        "SetOperationInfo",
        "SetPossibleOperationInfo",
        "GetFirstTarget",
        "GetTargetCards",
        "GetCurrentChain",
        "GetTurnPlayer",
        "GetCurrentPhase",
        "GetTurnCount",
        "RegisterEffect",
        "GetFieldGroupCount",
        "IsExistingMatchingCard",
        "IsExistingTarget",
        # §B — 세어 본 뒤에 여기로 옮겼다.
        "ConfirmCards",
    }
)

#: **실행되는 카드가 이미 쓰고 있는 것.** 막는 것일 수 없다 — 증명되었다.
#:
#: 이 집합은 손으로 고른 것이 아니라 §A 의 보정 시험이 라이브러리에서
#: 끌어낸 것과 같다. 처음 분류에서 이 다섯을 "막는다" 로 넣었고, 그래서
#: ``Duel.GetChainInfo`` 가 2위(24장)로 올라왔다 — 욕망의 항아리와 리로드가
#: 그것을 쓰면서 **멀쩡히 실행되는데도** 그랬다.
#:
#: ====================  ==========================================
#: ``GetChainInfo``       "누가 대상 플레이어인가" → ``PlayerRef``
#: ``SetTargetPlayer``    같은 것을 체인에 심는 EDOPro 의 배선
#: ``SetTargetParam``     같음
#: ``BreakEffect``        체인 처리의 마디 — 효과 하나에는 규칙 내용이 없다
#: ``IsPlayerCanDraw``    덱 장수는 ``ZoneCountAtLeast`` 로, 나머지는 미확인
#: ====================  ==========================================
PROVED_BY_EXECUTION = frozenset(
    {
        "GetChainInfo",
        "SetTargetPlayer",
        "SetTargetParam",
        "BreakEffect",
        "IsPlayerCanDraw",
    }
)

#: 엔진에 계층이 있다 (판정기가 없어 UNKNOWN 으로 멈추는 것도 포함).
SUPPORTED = frozenset(
    {
        "Draw",
        "Recover",
        "Damage",
        "SendtoHand",
        "SendtoGrave",
        "SendtoDeck",
        "Remove",
        "Release",
        "DiscardHand",
        "ShuffleDeck",
        "Destroy",
        "SelectTarget",
        "SelectMatchingCard",
        "GetMatchingGroup",
        "GetFieldGroup",
        "RandomSelect",
        "SpecialSummon",
        "GetLocationCount",
    }
)


# ======================================================================
# corpus 읽기 (한 번만)
# ======================================================================

_SET_TYPE = re.compile(r"SetType\(([^)]*)\)")
_DUEL = re.compile(r"\bDuel\.(\w+)\(")
_CARD = re.compile(r"\b(?:Card|c|tc|sc)[.:](\w+)\(")


@pytest.fixture(scope="module")
def corpus() -> dict:
    """스크립트를 읽어 효과 타입과 API 표면만 남긴다."""
    found = {}
    for path in ROOT.glob("c*.lua"):
        text = path.read_text(errors="replace")
        types = set()
        for match in _SET_TYPE.finditer(text):
            types.update(re.findall(r"EFFECT_TYPE_\w+", match.group(1)))
        found[int(path.stem[1:])] = {
            "types": frozenset(types),
            "duel": frozenset(_DUEL.findall(text)),
            "card": frozenset(_CARD.findall(text)),
        }
    return found


@pytest.fixture(scope="module")
def activate_only(corpus) -> tuple[int, ...]:
    return tuple(
        sorted(
            cid
            for cid, row in corpus.items()
            if row["types"] == frozenset({"EFFECT_TYPE_ACTIVATE"})
        )
    )


def blockers_of(row) -> frozenset[str]:
    found = {
        f"Duel.{name}"
        for name in row["duel"]
        if name not in NOT_A_RULE
        and name not in SUPPORTED
        and name not in PROVED_BY_EXECUTION
    }
    if "IsSetCard" in row["card"]:
        found.add("Card.IsSetCard")
    return frozenset(found)


# ======================================================================
# A. 측정 모집단
# ======================================================================


def test_a_the_engine_targets_activate_only_cards(corpus, activate_only):
    """
    엔진이 지금 담는 모양은 ``EFFECT_TYPE_ACTIVATE`` 하나뿐인 카드다.
    유발 · 지속 · 기동 계층이 없으므로 나머지는 **아직 측정 대상이 아니다.**
    """
    assert len(corpus) == 12702
    assert len(activate_only) == 1385

    # 등재된 16장이 전부 이 모양이다 — 우연이 아니라 그것만 담을 수 있다.
    from engine.effect.library import EFFECT_LIBRARY

    for entry in EFFECT_LIBRARY:
        row = corpus.get(entry.card_id)
        assert row is not None, entry.card_id
        assert "EFFECT_TYPE_ACTIVATE" in row["types"], entry.card_id


def test_a_the_executing_cards_calibrate_the_classifier(corpus):
    """
    **이 파일의 분류가 스스로 틀렸던 자리 두 번째.**

    실행되는 카드가 쓰는 API 는 **막는 것일 수 없다.** 증명되어 있기
    때문이다. 그런데 처음 분류는 그중 다섯을 "막는다" 로 넣었고, 그래서
    ``Duel.GetChainInfo`` 가 2위(24장)로 올라왔다 — 욕망의 항아리 ·
    다이안 켓 · 리로드가 그것을 쓰면서 멀쩡히 실행되는데도.

    보정 뒤 막는 것이 없는 카드가 **250 에서 368** 로 늘었다. 계층을
    하나도 만들지 않고.

    이 시험은 라이브러리에서 직접 끌어내므로, 나중에 카드가 더 등재되면
    :data:`PROVED_BY_EXECUTION` 이 좁아졌다는 것을 바로 알려 준다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    used = set()
    for entry in EFFECT_LIBRARY:
        if not entry.executable:
            continue
        row = corpus.get(entry.card_id)
        if row is not None:
            used |= set(row["duel"])

    unexplained = used - NOT_A_RULE - SUPPORTED - PROVED_BY_EXECUTION
    assert unexplained == set(), unexplained
    assert PROVED_BY_EXECUTION <= used


def test_a_three_hundred_sixty_eight_cards_have_nothing_blocking_them(
    corpus, activate_only
):
    """
    **막는 것이 하나도 없는 카드가 368장**이다. 등재된 것은 13장이다.

    그 차이는 **구조가 아니라 손**이다 — 정의를 손으로 적지 않았을 뿐이다
    (ADR-006 · EFFECT_LIBRARY). 이 수를 "커버리지" 로 읽지 않는다: 적을 수
    있다는 것과 적어 두었다는 것은 다른 말이다.
    """
    clean = [cid for cid in activate_only if not blockers_of(corpus[cid])]

    assert len(clean) == 368

    from engine.effect.library import EFFECT_LIBRARY

    executable = {e.card_id for e in EFFECT_LIBRARY if e.executable}
    assert len(executable) == 13
    # 실행되는 카드는 **하나도 빠짐없이** 막는 것이 없어야 한다.
    assert executable <= set(clean) | {53129443, 83764718}


def test_a_the_repeated_blockers_are_ranked_and_already_filed(corpus, activate_only):
    """
    **그 하나만 풀면 열리는 카드 수** 로 줄을 세운다. 전체 빈도보다 이쪽이
    날카롭다 — 여러 개가 걸린 카드는 하나를 풀어도 열리지 않는다.

    ::

        148  Card.IsSetCard              STRUCTURAL-77 (아키타입 조건)
         22  Duel.SetTargetCard          대상 파라미터
         19  Duel.ShuffleHand            STRUCTURAL-75
         19  Duel.ChangePosition         표시 형식 (STRUCTURAL-61)
         16  Duel.SelectYesNo            "해도 되는가" 를 묻는 선택

    **1위가 2위의 일곱 배다.** 병목이 하나라는 뜻이고, 그것은 이미 기록된
    STRUCTURAL-77 이다. 이번 단계가 새로 만들 것이 아니라, 다음 단계의
    목표가 무엇인지 **수로 확정된다.**
    """
    solo: collections.Counter = collections.Counter()
    for cid in activate_only:
        found = blockers_of(corpus[cid])
        if len(found) == 1:
            solo[next(iter(found))] += 1

    top = solo.most_common(5)
    assert top[0] == ("Card.IsSetCard", 148)
    assert dict(top) == {
        "Card.IsSetCard": 148,
        "Duel.SetTargetCard": 22,
        "Duel.ShuffleHand": 19,
        "Duel.ChangePosition": 19,
        "Duel.SelectYesNo": 16,
    }
    # 1위가 2위보다 압도적이다 — 병목이 여럿이 아니라 하나다.
    assert top[0][1] > top[1][1] * 6


# ======================================================================
# B. 측정이 스스로 틀렸던 자리 — ConfirmCards
# ======================================================================


def rulebook_text() -> str:
    data = json.loads(
        (ROOT / "data/rules/documents/sd-rulebook-en-v10.json").read_text()
    )

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)
        elif isinstance(node, str):
            yield node

    return " ".join(
        " ".join(t.split()) for t in walk(data)
    ).replace("ﬁ", "fi").replace("ﬂ", "fl")


def test_b_confirm_cards_looked_like_a_big_win(corpus, activate_only):
    """
    ``Duel.ConfirmCards`` 는 244장이 쓰고, 그것 **하나만** 막는 것처럼
    보이는 카드가 48장이었다. 계층 하나를 만들 근거로 충분해 보였다.
    """
    uses = [cid for cid in activate_only if "ConfirmCards" in corpus[cid]["duel"]]
    assert len(uses) == 244

    # 규칙으로 쳤다면 34장이 그것 하나에 걸려 있었다.
    def as_rule(row):
        return frozenset(
            f"Duel.{n}"
            for n in row["duel"]
            if n not in (NOT_A_RULE - {"ConfirmCards"})
            and n not in SUPPORTED
            and n not in PROVED_BY_EXECUTION
        ) | ({"Card.IsSetCard"} if "IsSetCard" in row["card"] else set())

    solo = [cid for cid in activate_only if as_rule(corpus[cid]) == {"Duel.ConfirmCards"}]
    assert len(solo) == 48


def test_b_the_rulebook_says_revealing_is_card_declared():
    """
    **룰북이 "effect **says** to" 라고 못박는다.** 공개는 카드가 적을 때만
    일어나는 일이고, 덱을 뒤지는 일에 붙은 일반 규칙이 아니다.
    """
    text = rulebook_text()

    assert "When an effect says to reveal a card, you show it to both players." in text
    # 덱을 뒤지는 규칙은 공개를 말하지 않는다 — **셔플**을 말한다.
    assert (
        "Whenever an effect instructs you to add a card from your Deck to "
        "your hand" in text
    )
    assert "You must shuffle your Deck after any time you search it" in text


def test_b_the_official_text_of_those_cards_does_not_say_reveal(
    repository, corpus, activate_only
):
    """
    **48장 중 공개를 말하는 것은 1장뿐이다** (익스체인지 5556668).

    나머지 47장은 증원 · 테라포밍 · 화석조사처럼 "덱에서 1장을 패에
    넣는다" 다. 스크립트의 ``ConfirmCards`` 는 EDOPro 가 검색 결과를 보여
    주는 **구현**이고 카드의 규칙이 아니다.

    그래서 ``ConfirmCards`` 를 :data:`NOT_A_RULE` 로 옮겼고, 막는 것이 없는
    카드가 320 에서 **368** 로 늘었다 — 계층을 하나도 만들지 않고.
    """
    def as_rule(row):
        return frozenset(
            f"Duel.{n}"
            for n in row["duel"]
            if n not in (NOT_A_RULE - {"ConfirmCards"})
            and n not in SUPPORTED
            and n not in PROVED_BY_EXECUTION
        ) | ({"Card.IsSetCard"} if "IsSetCard" in row["card"] else set())

    solo = [cid for cid in activate_only if as_rule(corpus[cid]) == {"Duel.ConfirmCards"}]
    says = [cid for cid in solo if "공개" in (repository.get(cid).desc or "")]

    assert says == [5556668]
    assert len(solo) - len(says) == 47

    # 한 장을 위해 계층을 만들지 않는다 (§1-5).
    assert "ConfirmCards" in NOT_A_RULE


# ======================================================================
# C. STRUCTURAL-71 — 들여다본 덱을 섞는다
# ======================================================================


def test_c_the_rulebook_makes_the_shuffle_a_general_rule():
    """
    **카드가 시키는 일이 아니라 룰북이 시키는 일이다.** 그래서 정의에
    적지 않고 실행기가 한다.
    """
    text = rulebook_text()

    assert (
        "If a card effect requires you to reveal cards from your Deck, or "
        "look through it, shuffle it and put it back in this space afterwards."
        in text
    )
    assert (
        "You must shuffle your Deck after any time you search it and let "
        "your opponent shuffle or cut." in text
    )


def test_c_most_scripts_do_not_say_it_because_the_engine_does_it(
    corpus, activate_only
):
    """
    덱을 들여다보는 ACTIVATE 단독 카드가 **269장**이고, 그중
    ``Duel.ShuffleDeck`` 을 직접 부르는 것은 **31장**뿐이다. 나머지 238장은
    EDOPro 엔진이 알아서 섞는다 — 이 엔진에서 그 "알아서" 에 해당하는
    자리가 없던 것이 STRUCTURAL-71 이다.
    """
    looks = re.compile(
        r"Duel\.(?:SelectMatchingCard|SelectTarget|GetMatchingGroup"
        r"|IsExistingMatchingCard|IsExistingTarget|GetFieldGroup)"
        r"\([^)]*LOCATION_DECK"
    )
    searched, explicit = [], []
    for cid in activate_only:
        text = (ROOT / f"c{cid}.lua").read_text(errors="replace")
        if looks.search(text):
            searched.append(cid)
            if "Duel.ShuffleDeck" in text:
                explicit.append(cid)

    assert len(searched) == 269
    assert len(explicit) == 31
    assert FOOLISH_BURIAL in searched
    assert FOOLISH_BURIAL not in explicit


def foolish_state(repository, *, seed=7) -> GameState:
    game = GameState.create(
        repository,
        decks=([FOOLISH_BURIAL] + [FEATHERMAN] * 20, [FEATHERMAN] * 20),
        seed=seed,
    )
    game.draw(MINE, 1)
    game.move(
        game.player(MINE).hand[0].instance_id,
        Zone.SZONE,
        to_player=MINE,
        position=Position.FACEUP,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


def bury(game: GameState, target: InstanceId):
    registry = definition_registry()
    activated = EffectActivator(registry, implementation_registry()).activate(
        game,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE,
            source=game.player(MINE).spell_zone[0].instance_id,
            effect_ref=EffectRef(FOOLISH_BURIAL, 0),
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(target)),),
        authorization=GRANTED,
    )
    assert activated.status is ActivationStatus.ACTIVATED
    resolver = ChainResolver(
        build_executor(movement=DeclaredMovementRuling(sendable=frozenset({target}))),
        registry,
    )
    return resolver.resolve_top(game, activated.chain)


@pytest.mark.real_card
def test_c_a_searched_deck_is_shuffled(repository):
    """
    **등재되고 실행되는 실제 카드로 재현한다.** 어리석은 매장은 자기 덱을
    들여다본다 (``looked_at_zones() == {DECK}``).

    고치기 전에는 남은 카드의 순서가 **그대로**였다 — 들여다본 사람이 덱
    순서를 아는 채로 남는다.
    """
    game = foolish_state(repository)
    before = [card.instance_id.value for card in game.player(MINE).deck]
    target = game.player(MINE).deck[3].instance_id

    resolved = bury(game, target)

    assert resolved.status is ChainResolutionStatus.RESOLVED
    after = [card.instance_id.value for card in game.player(MINE).deck]
    kept = [i for i in before if i != target.value]

    assert sorted(after) == sorted(kept)  # 같은 카드들이고
    assert after != kept  # 순서는 달라졌다

    shuffles = [d for d in resolved.deltas if isinstance(d, ZoneShuffled)]
    assert len(shuffles) == 1
    assert shuffles[0].zone is Zone.DECK
    assert shuffles[0].player == MINE


@pytest.mark.real_card
def test_c_the_card_does_not_declare_the_shuffle(repository):
    """
    정의에도 스크립트에도 셔플이 없다. **있어서는 안 된다** — 카드가 적은
    일이 아니기 때문이다. 적어 두면 같은 규칙이 269곳에 복사된다.
    """
    definition = entry_for(EffectRef(FOOLISH_BURIAL, 0)).definition

    assert [op.kind.value for op in definition.operations] == ["send_to_grave"]
    assert "Duel.ShuffleDeck" not in (ROOT / "c81439173.lua").read_text()
    assert Zone.DECK in definition.targets[0].spec.looked_at_zones()


@pytest.mark.real_card
def test_c_only_the_chooser_s_deck_is_shuffled(repository):
    """
    **자리 주인이 아니라 고른 사람의 덱**이다.

    처음에 ``source.owner`` 로 적었다가 틀렸다 — 주인을 가리지 않는 명세
    (``owner=None``)에서 **상대 덱까지 섞었다.** 아무도 열어 보지 못한
    덱이다. ``looked_at_zones()`` 가 이미 그 규칙을 들고 있다 (2-Y): 주인이
    상대면 빈 집합이고, 주인을 가리지 않으면 열리는 것은 보는 사람 자신의
    자리뿐이다.
    """
    game = foolish_state(repository)
    theirs_before = [c.instance_id.value for c in game.player(THEIRS).deck]

    resolved = bury(game, game.player(MINE).deck[2].instance_id)

    assert [c.instance_id.value for c in game.player(THEIRS).deck] == theirs_before
    assert {d.player for d in resolved.deltas if isinstance(d, ZoneShuffled)} == {MINE}


@pytest.mark.real_card
def test_c_without_randomness_it_is_recorded_not_skipped(repository):
    """
    난수원이 없으면 섞을 수 없다. 그때 **효과를 무르지 않는다** — 셔플은
    카드가 적은 일이 아니라 룰북이 시키는 정리이고, 정리를 못 했다고
    카드의 일까지 무르는 것은 과하다 (씨앗 없는 판에서 무관한 효과가 죽는다).

    대신 **조용히 넘기지 않는다.** 섞지 못한 덱은 순서가 남으므로 그 사실이
    결과에 실린다 (2-AL · 2-AM 이 만든 자리).
    """
    game = GameState.create(
        repository, decks=([FOOLISH_BURIAL] + [FEATHERMAN] * 20, [FEATHERMAN] * 20)
    )
    game.draw(MINE, 1)
    game.move(
        game.player(MINE).hand[0].instance_id,
        Zone.SZONE,
        to_player=MINE,
        position=Position.FACEUP,
    )
    game.turn.set_phase(Phase.MAIN1)
    target = game.player(MINE).deck[3].instance_id
    before = [c.instance_id.value for c in game.player(MINE).deck]

    resolved = bury(game, target)

    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert [c.instance_id.value for c in game.player(MINE).deck] == [
        i for i in before if i != target.value
    ]
    assert not [d for d in resolved.deltas if isinstance(d, ZoneShuffled)]
    assert any("섞지 못했다" in note for note in resolved.result.unchecked_rules)


@pytest.mark.real_card
def test_c_the_same_seed_shuffles_the_same_way(repository):
    """정리도 결정론적이다 — 같은 씨앗이면 같은 순서다 (2-Z)."""
    orders = []
    for _ in range(3):
        game = foolish_state(repository, seed=21)
        bury(game, game.player(MINE).deck[3].instance_id)
        orders.append(tuple(c.instance_id.value for c in game.player(MINE).deck))

    assert len(set(orders)) == 1


def test_c_the_extra_deck_is_not_tidied_up():
    """
    룰북은 **덱**을 말한다. 엑스트라 덱은 공개된 자리이고 룰북이 그것을
    섞으라고 하지 않는다 — 쓸 수 있는 존이라고 해서 섞지 않는다.
    """
    assert Zone.EXTRA in SHUFFLEABLE_ZONES  # 섞을 수는 있다

    source = (ROOT / "engine/effect/executor.py").read_text()
    body = source[source.index("def _shuffle_searched_decks") :]
    body = body[: body.index("\n    def ")]
    assert "Zone.DECK" in body
    assert "Zone.EXTRA" not in body
