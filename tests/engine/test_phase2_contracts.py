"""
Phase 2 계약 테스트 — ``docs/phase2-architecture-decisions.md``.

**Phase 2 코드는 아직 없다.** 그런데도 이 파일의 테스트는 전부 실행되고
통과한다. 계약이 "앞으로 지킬 약속"이 아니라 **현재 데이터와 코드에 이미
성립하는 불변식**이기 때문이다.

이 테스트들이 지키는 것은 구현이 아니라 **구분**이다. Phase 2 를 구현하다가
구분 하나를 무너뜨리면 여기서 걸린다.

계약 D 의 네트워크 수준 검증은 ``tests/rulings/test_identity_trust_boundary.py``
가 이미 하고 있다. 여기서는 중복하지 않고 API 수준만 확인한다.
"""

from collections import Counter

import pytest

from analysis.effect_model import ACTION_DESTINATION, ActionKind
from core.card_identity import CardIdentity, LinkSource, LinkStatus
from core.provenance import AnalysisStatus
from engine.ids import EffectRef, effect_refs
from engine.vocabulary import default_vocabulary

from tests.conftest import requires_official_db


@pytest.fixture(scope="module")
def cards(repository):
    """다른 일러스트까지 포함한 전체 카드. 실행 권위는 판본과 무관하다."""
    return repository.all_cards(include_alternates=True)


@pytest.fixture(scope="module")
def by_status(cards):
    grouped: dict[AnalysisStatus, list] = {}
    for card in cards:
        grouped.setdefault(card.provenance.analysis_status, []).append(card)
    return grouped


# ======================================================================
# Contract A — TEXT_DERIVED 는 실행될 수 없다
# ======================================================================


@requires_official_db
def test_contract_a_text_derived_effects_have_no_execution_identity(by_status):
    """
    ADR-003 / ADR-004.

    이것은 정책이 아니라 **구조**다. ``EffectRef`` 는 Lua 스크립트에서만
    나오므로 (``engine/ids.py`` 의 ``effect_refs``), TEXT_DERIVED 카드는
    실행 identity 공간에 **이름조차 없다.** EffectRegistry 의 키가
    ``EffectRef`` 인 한 등록도 조회도 불가능하다.

    런타임 ``if`` 문을 잊어버려도 뚫리지 않는 방어선이다.
    """
    text_derived = by_status.get(AnalysisStatus.TEXT_DERIVED, [])
    assert text_derived, "TEXT_DERIVED 카드가 하나도 없다. 데이터가 의심스럽다."

    addressable = [card for card in text_derived if effect_refs(card)]
    assert addressable == [], (
        f"TEXT_DERIVED 카드 {len(addressable)}장이 EffectRef 를 갖게 되었습니다. "
        "텍스트에서 유도한 효과가 실행 identity 를 얻으면 ADR-004 가 무너집니다."
    )


@requires_official_db
def test_contract_a_text_derived_is_not_the_same_status_as_lua(by_status):
    """두 상태가 같은 enum 값으로 합쳐지면 차단 자체가 성립하지 않는다."""
    assert AnalysisStatus.TEXT_DERIVED is not AnalysisStatus.LUA_VERIFIED
    assert AnalysisStatus.TEXT_DERIVED.value != AnalysisStatus.LUA_VERIFIED.value
    assert by_status.get(AnalysisStatus.TEXT_DERIVED)
    assert by_status.get(AnalysisStatus.LUA_VERIFIED)


# ======================================================================
# Contract B — NO_EFFECT 는 발동할 효과가 없다 (차단이 아니다)
# ======================================================================


@requires_official_db
def test_contract_b_no_effect_cards_have_no_effects(by_status):
    """ADR-003. 통상 몬스터 · 토큰에는 발동할 효과가 없다."""
    no_effect = by_status.get(AnalysisStatus.NO_EFFECT, [])
    assert no_effect, "NO_EFFECT 카드가 하나도 없다. 데이터가 의심스럽다."

    with_effects = [card for card in no_effect if effect_refs(card)]
    assert with_effects == [], (
        f"NO_EFFECT 카드 {len(with_effects)}장이 효과를 갖고 있습니다. "
        "효과가 있다면 NO_EFFECT 가 아닙니다."
    )


@requires_official_db
def test_contract_b_no_effect_is_distinct_from_text_derived(by_status):
    """
    ADR-003 의 핵심.

    NO_EFFECT 는 **차단 대상이 아니다.** 푸른 눈의 백룡은 듀얼에 나오고,
    소환되고, 공격한다. 단지 발동할 효과가 없을 뿐이다.

    이 둘을 합치면 통상 몬스터가 통째로 듀얼에서 사라진다. 커밋 9bf690a
    이전에 실제로 그럴 뻔했고, 그래서 NO_EFFECT 가 분리되었다.
    """
    assert AnalysisStatus.NO_EFFECT is not AnalysisStatus.TEXT_DERIVED
    assert AnalysisStatus.NO_EFFECT is not AnalysisStatus.UNAVAILABLE

    no_effect = by_status.get(AnalysisStatus.NO_EFFECT, [])
    assert len(no_effect) > 500, (
        f"NO_EFFECT 가 {len(no_effect)}장뿐입니다. 통상 몬스터가 "
        "TEXT_DERIVED 로 흘러들어가고 있는지 확인하세요."
    )


# ======================================================================
# Contract C — LUA_VERIFIED 만으로는 실행 가능하지 않다
# ======================================================================


@requires_official_db
def test_contract_c_lua_verified_does_not_imply_addressable_effects(by_status):
    """
    ADR-006.

    ``if status is LUA_VERIFIED: execute`` 를 쓰면 여기서 깨진다.

    일부 카드는 효과를 공유 라이브러리 팩토리 안에서 만든다
    (``Fusion.CreateSummonEff``, ``Fusion.AddProcMix`` 등). 스크립트는
    분명히 있으므로 LUA_VERIFIED 지만, 파서가 효과 블록을 찾지 못해
    **지목할 수 있는 효과가 하나도 없다.**

    "스크립트가 있다" 와 "실행할 효과를 지목할 수 있다" 는 다른 명제다.
    """
    lua_verified = by_status.get(AnalysisStatus.LUA_VERIFIED, [])
    assert lua_verified

    not_addressable = [card for card in lua_verified if not effect_refs(card)]
    assert not_addressable, (
        "LUA_VERIFIED 카드가 전부 EffectRef 를 갖게 되었습니다. "
        "좋은 변화일 수 있지만, ADR-006 의 근거가 사라졌으므로 "
        "CardExecutionAvailability 의 NOT_ADDRESSABLE 상태가 여전히 "
        "필요한지 다시 판단하세요."
    )
    # 정확한 장수는 파서가 좋아지면 줄어든다. 줄어드는 것은 정상이다.
    assert len(not_addressable) < len(lua_verified) * 0.05, (
        f"{len(not_addressable)}장이 지목 불가입니다. 5% 를 넘으면 "
        "파서 회귀를 의심해야 합니다."
    )


@requires_official_db
def test_contract_c_execution_availability_is_not_stored_on_the_card(cards):
    """
    ADR-006.

    실행 가능성은 **EffectRegistry 의 내용**에 따라 달라진다. 카드 데이터에
    저장하면 registry 가 커질 때마다 낡는다. ``CardProvenance`` 는 출처만
    기록해야 한다.
    """
    provenance = cards[0].provenance
    for forbidden in ("executable", "execution_status", "implemented", "registry"):
        assert not hasattr(provenance, forbidden), (
            f"CardProvenance 에 {forbidden} 가 생겼습니다. 실행 가능성은 "
            "엔진의 질문이지 카드 데이터의 속성이 아닙니다 (ADR-006)."
        )


# ======================================================================
# Contract D — UNVERIFIED identity 로 공식 재정을 얻을 수 없다
# ======================================================================


def test_contract_d_unverified_identity_is_not_trusted():
    """
    ADR 전제 1.

    네트워크 수준 검증은 tests/rulings/test_identity_trust_boundary.py 가
    이미 한다. 여기서는 그 검증이 딛고 선 API 불변식만 확인한다:
    ``trusted`` 는 ``VERIFIED`` 하나에만 참이어야 하고,
    "CONFLICT 가 아니면 신뢰" 같은 형태여서는 안 된다.
    """
    def identity(status: LinkStatus) -> CardIdentity:
        return CardIdentity(
            card_id=1,
            cid=2,
            link_source=LinkSource.YGOPRODECK_KONAMI_ID,
            status=status,
        )

    assert identity(LinkStatus.VERIFIED).trusted is True
    assert identity(LinkStatus.UNVERIFIED).trusted is False
    assert identity(LinkStatus.CONFLICT).trusted is False

    # UNVERIFIED 는 후보로는 남는다 — 틀렸다는 뜻이 아니기 때문이다.
    assert identity(LinkStatus.UNVERIFIED).is_candidate is True
    assert identity(LinkStatus.CONFLICT).is_candidate is False


# ======================================================================
# Contract E — Action 과 Effect 는 다른 개념이다
# ======================================================================


#: Phase 2 가 쓰게 될 **플레이어 행위** 이름. ADR-001 의 Action.
PLAYER_ACTION_NAMES = frozenset(
    {
        "activate",
        "normal_summon",
        "tribute_summon",
        "set",
        "flip_summon",
        "change_position",
        "declare_attack",
        "end_phase",
        "pass",
    }
)

#: 이름이 겹치지만 **의미가 다른** 것. 아래 테스트가 이유를 설명한다.
KNOWN_NAME_COLLISIONS = frozenset({"normal_summon"})


def test_contract_e_action_and_effect_vocabularies_are_not_interchangeable():
    """
    ADR-001.

    ``analysis.ActionKind`` 는 이름이 Action 이지만 **Effect semantics** 다.
    18개 멤버 중 17개는 플레이어가 고를 수 없는 것들이다 (destroy, banish,
    to_grave …).

    그런데 ``normal_summon`` **하나가 겹친다.** 그리고 이것이 이 ADR 의
    가장 좋은 증거다 — 같은 이름이 두 가지를 뜻한다.

    - ``analysis.ActionKind.NORMAL_SUMMON``
      효과 해결 중 ``Duel.Summon`` 이 호출된다는 뜻이다 (실측 74개 효과).
      예: 교차하는 혼, 아르카나 리딩 — 효과가 일반 소환을 **수행**한다.
    - Phase 2 의 ``PlayerActionKind.NORMAL_SUMMON`` (예정)
      플레이어가 이번 턴의 일반 소환권을 **쓰기로 고르는 것**이다.

    두 번째는 반드시 소환권을 소비하고, 첫 번째는 소비할 수도 안 할 수도
    있다. 이름이 같다고 합치면 **서로 다른 두 규칙이 하나가 된다.**

    그래서 Phase 2 는 이 enum 을 재사용하지 않고 별도 어휘를 만든다.
    """
    members = {member.value for member in ActionKind}
    overlap = members & PLAYER_ACTION_NAMES

    assert overlap == KNOWN_NAME_COLLISIONS, (
        f"analysis.ActionKind 와 플레이어 행위 이름의 겹침이 {sorted(overlap)} "
        f"로 바뀌었습니다 (알려진 값: {sorted(KNOWN_NAME_COLLISIONS)}). "
        "겹침이 늘었다면 두 어휘가 섞이고 있다는 신호입니다 (ADR-001)."
    )

    # 나머지는 전부 효과의 결과다 — 플레이어가 고를 수 있는 것이 아니다.
    assert {"destroy", "banish", "to_grave", "to_hand", "discard"} <= members
    assert len(members - PLAYER_ACTION_NAMES) == len(members) - 1


def test_contract_e_engine_does_not_borrow_the_analysis_action_vocabulary():
    """
    ADR-001.

    Phase 2-A 는 ``engine/`` 안에 자기 Action 어휘를 만들어야 한다.
    ``from analysis.effect_model import ActionKind`` 한 줄이면 두 개념이
    합쳐진다.
    """
    import engine

    assert not hasattr(engine, "ActionKind"), (
        "engine 이 ActionKind 를 노출합니다. analysis 의 것을 재수출한 것인지 "
        "확인하세요 — 엔진 Action 은 PlayerActionKind 라는 별도 이름을 씁니다."
    )

    import pathlib

    root = pathlib.Path(engine.__file__).parent
    offenders = [
        path.relative_to(root.parent)
        for path in root.rglob("*.py")
        if "ActionKind" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"{offenders} 가 ActionKind 를 언급합니다. analysis 의 Effect 어휘를 "
        "엔진 Action 으로 쓰면 ADR-001 이 무너집니다."
    )


# ======================================================================
# Contract F — Destroy 와 Send 는 자동으로 같지 않다
# ======================================================================


def test_contract_f_action_destination_really_does_collapse_destroy_and_send():
    """
    ADR-002.

    이 테스트는 **함정을 박제한다.**

    ``ACTION_DESTINATION`` 은 Destroy · Send · Discard · Release 를 전부
    ``"GRAVE"`` 로 매핑한다. 콤보 탐색 휴리스틱으로는 맞다 — 네 경우 모두
    결국 묘지에 있게 되므로. 그러나 **실행 의미로 쓰면 안 된다.**

    목적지가 같다는 사실을 테스트로 남겨 두면, 나중에 누군가 이 표를
    EffectOperation 의 근거로 쓰려 할 때 왜 안 되는지 즉시 알 수 있다.
    """
    assert ACTION_DESTINATION[ActionKind.DESTROY] == "GRAVE"
    assert ACTION_DESTINATION[ActionKind.TO_GRAVE] == "GRAVE"
    assert ACTION_DESTINATION[ActionKind.DISCARD] == "GRAVE"
    assert ACTION_DESTINATION[ActionKind.RELEASE] == "GRAVE"

    # 즉, 목적지만으로는 네 가지를 구분할 수 없다.
    collapsed = Counter(
        ACTION_DESTINATION[kind]
        for kind in (
            ActionKind.DESTROY,
            ActionKind.TO_GRAVE,
            ActionKind.DISCARD,
            ActionKind.RELEASE,
        )
    )
    assert collapsed == {"GRAVE": 4}


@requires_official_db
def test_contract_f_reason_bits_are_what_keeps_destroy_and_send_apart():
    """
    ADR-002.

    구분은 목적지가 아니라 ``REASON_DESTROY`` 비트 하나다. 이 비트에
    "파괴되었을 때" 트리거 · 파괴 내성 · 파괴 대체 효과가 전부 달려 있다.
    """
    reasons = default_vocabulary().reasons
    destroy = reasons.value("DESTROY")
    effect = reasons.value("EFFECT")
    battle = reasons.value("BATTLE")

    assert destroy is not None and effect is not None and battle is not None
    assert destroy != effect

    # 비트마스크다 — 겹치지 않으므로 조합할 수 있다.
    assert destroy & effect == 0
    assert destroy & battle == 0

    # "효과로 파괴" 와 "전투로 파괴" 가 둘 다 표현되고 서로 다르다.
    by_effect = destroy | effect
    by_battle = destroy | battle
    assert by_effect != by_battle
    assert by_effect & destroy and by_battle & destroy

    # "효과로 묘지로 보냄" 은 파괴 비트가 없다 — 여기가 구분점이다.
    send_to_grave = effect
    assert send_to_grave & destroy == 0


def test_contract_f_phase1_zone_move_carries_no_reason():
    """
    ADR-002.

    저수준 이동은 이유를 모른다. 그것이 맞다 — 이유는 이동 하나가 아니라
    사건 전체의 속성이고, Phase 1 에 넣으면 상태 계층이 규칙 어휘를 갖는다.
    """
    import inspect

    from engine.state.zones import move_card

    params = set(inspect.signature(move_card).parameters)
    assert "reason" not in params, (
        "move_card 가 reason 을 받게 되었습니다. 의미는 EffectOperation 이 "
        "들고 있어야 합니다 (ADR-002)."
    )
    assert params == {"card", "source", "destination", "index", "position"}


# ======================================================================
# Contract G — EffectRef(card_id, ordinal) 이 효과 identity 다
# ======================================================================


@requires_official_db
def test_contract_g_effect_spec_index_is_not_unique_within_a_card(cards):
    """
    ADR-005.

    ``EffectSpec.index`` 는 Lua 변수명(``"e1"``)이고 한 카드 안에서 중복된다.
    이것을 키로 쓰면 중복된 효과가 조용히 사라진다.
    """
    duplicated_cards = 0
    shadowed_effects = 0
    for card in cards:
        if card.script is None or not card.script.effects:
            continue
        counts = Counter(spec.index for spec in card.script.effects)
        extra = sum(n - 1 for n in counts.values() if n > 1)
        if extra:
            duplicated_cards += 1
            shadowed_effects += extra

    assert duplicated_cards > 1000, (
        f"index 중복 카드가 {duplicated_cards}장뿐입니다. ADR-005 의 근거가 "
        "달라졌는지 확인하세요."
    )
    assert shadowed_effects > 0


@requires_official_db
def test_contract_g_effect_ref_ordinal_is_unique_within_a_card(cards):
    """``ordinal`` 은 리스트 인덱스이므로 구조적으로 유일하다."""
    for card in cards[:3000]:
        refs = effect_refs(card)
        assert len(set(refs)) == len(refs), f"{card.id} 의 EffectRef 가 중복됩니다."


def test_contract_g_effect_ref_is_hashable_ordered_and_integer_only():
    """
    ``EffectRef`` 는 state_hash 와 UseRegistry 키로 쓰인다. 파이썬 객체
    identity 나 ``hash()`` 에 의존하면 결정론이 깨진다.
    """
    ref = EffectRef(2511, 1)
    assert ref == EffectRef(2511, 1)
    assert ref != EffectRef(2511, 0)
    assert {ref: "ok"}[EffectRef(2511, 1)] == "ok"
    assert EffectRef(2511, 0) < EffectRef(2511, 1) < EffectRef(2512, 0)
    assert isinstance(ref.card_id, int) and isinstance(ref.ordinal, int)

    with pytest.raises(Exception):
        ref.ordinal = 5  # frozen


@requires_official_db
def test_contract_g_use_registry_already_keys_effects_by_effect_ref():
    """Phase 1 이 이미 이 identity 를 쓰고 있다. Phase 2 가 바꾸지 않는다."""
    from engine.state.use_registry import UseRegistry

    assert UseRegistry.effect_key(0, EffectRef(2511, 3)) == (0, 2511, 3)


# ======================================================================
# Contract H — AI 는 분석 데이터로 상태를 바꿀 수 없다
# ======================================================================


def test_contract_h_engine_borrows_exactly_one_symbol_from_analysis():
    """
    ADR-007.

    ``engine`` 이 ``analysis`` 에서 가져오는 것은 ``LimitScope`` 하나뿐이다.
    이 목록이 늘어나면 분석 데이터가 실행 경로로 새어 들어오고 있다는
    신호다. 늘리려면 ADR-007 을 먼저 고쳐야 한다.
    """
    import pathlib
    import re

    import engine

    root = pathlib.Path(engine.__file__).parent
    imported: set[str] = set()
    pattern = re.compile(r"^\s*from\s+analysis[.\w]*\s+import\s+(.+)$", re.MULTILINE)
    for path in root.rglob("*.py"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            for name in match.group(1).split(","):
                imported.add(name.strip().split(" as ")[0].strip())

    assert imported == {"LimitScope"}, (
        f"engine 이 analysis 에서 {sorted(imported)} 를 가져옵니다. "
        "ADR-007 은 LimitScope 하나만 허용합니다."
    )


def test_contract_h_game_state_accepts_no_analysis_objects():
    """
    ADR-007.

    ``GameState`` 에 분석 결과를 넘겨 상태를 바꾸는 경로가 있으면,
    파서의 추론 오류가 곧바로 state_hash 에 들어간다.
    """
    import inspect

    from engine.state.game_state import GameState

    for name, member in inspect.getmembers(GameState, inspect.isfunction):
        if name.startswith("__"):
            continue
        annotations = inspect.get_annotations(member, eval_str=False)
        for param, annotation in annotations.items():
            text = str(annotation)
            assert "EffectAnalysis" not in text and "EffectAction" not in text, (
                f"GameState.{name} 의 {param} 이 분석 객체를 받습니다 (ADR-007)."
            )


def test_contract_h_game_state_has_no_ai_facing_mutation_shortcut():
    """
    ADR-007.

    Phase 1 의 ``move`` / ``draw`` / ``change_life`` 는 **테스트와 셋업용**
    이고 계속 남는다. 다만 AI 에게는 읽기 전용 뷰만 넘어가야 하므로,
    Phase 2-A 가 ``GameStateView`` 를 만들기 전까지 AI 가 붙을 진입점이
    생기지 않았는지 확인한다.
    """
    from engine.state.game_state import GameState

    for forbidden in ("apply_ai_action", "execute", "resolve", "apply_effect"):
        assert not hasattr(GameState, forbidden), (
            f"GameState.{forbidden} 이 생겼습니다. 실행 경로는 Engine 안에 "
            "있어야 하고 AI 는 Action 만 돌려줍니다 (ADR-007)."
        )
