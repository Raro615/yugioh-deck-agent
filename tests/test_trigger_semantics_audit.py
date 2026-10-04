"""
Phase 3-E-17 — 유발 조건의 **의미**가 어디까지 보존되는가 (감사).

이 Phase 는 아무것도 구현하지 않았다. 네 상태를 구분할 수 있는지 재고, 설명이
허용하는 **거짓 추론**을 주석으로 막았다.

재려는 네 상태 (§5)
-------------------
    A  NO_TRIGGER          실제로 유발 조건이 없다
    B  TRIGGER_PRESENT     유발 조건이 있다
    C  TRIGGER_UNKNOWN     있을 수 있으나 지금 정보로 판정할 수 없다
    D  TRIGGER_UNRECORDED  원본에는 있는데 pipeline 이 보존하지 않았다

변환기가 **없다**는 것이 이 감사의 출발점이다
---------------------------------------------
``EffectDefinition(`` 을 만드는 자리는 repository 전체에서 **하나**다 —
``engine/effect/library.py`` 의 16건이고 전부 손으로 적은 것이다 (ADR-006).
그래서 "변환 중에 유발 정보가 사라진다" 는 틀린 그림이다. **변환이 없다.**
엔진의 정의는 독립적인 전사이고, 전사한 사람이 그 값을 적지 않았다.

``EVENT_FREE_CHAIN`` 은 유발 이벤트가 **아니다** (§6)
-----------------------------------------------------
그런데 **구문으로는 구분되지 않는다.** ``data/constants/constant.lua`` 가
``EVENT_FREE_CHAIN = 1002`` 로 적고 실제 유발 이벤트도 같은 번호대에 있다
(``EVENT_CHAINING = 1027`` · ``EVENT_DESTROYED = 1029``). 즉
``code.startswith("EVENT_")`` 로는 둘을 가를 수 없다.

가르는 것은 **함께 쓰인 ``EFFECT_TYPE_*``** 이고, 그것이 측정된다.

    EVENT_FREE_CHAIN   ACTIVATE 3638 · QUICK_O 1256 · IGNITION 58
                       → **TRIGGER_O · TRIGGER_F 가 0건**
    다른 EVENT_*        TRIGGER_O 6019 · TRIGGER_F 1963 · SINGLE 6024 · FIELD 4181

앞쪽은 **플레이어가 고르는** 발동이고 뒤쪽은 **무언가가 일어나서** 걸리는
효과다. 그래서 ``EVENT_FREE_CHAIN`` 은 "유발 조건이 없다" 를 적은 값이지
유발 이벤트가 아니다.

    TRIGGER ≠ ACTIVATION · TRIGGER EVENT ≠ EVENT_FREE_CHAIN
    NO TRIGGER ≠ NO TRIGGER DATA · UNKNOWN ≠ NONE · UNRECORDED ≠ ABSENT
"""

import ast
import pathlib
import re

import pytest

from analysis.effect_model import ActivationCondition, EffectAnalysis
from core.card_model import EffectSpec, LuaScriptInfo
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY

from tests.conftest import requires_official_db

pytestmark = requires_official_db

#: 공식 상수 파일. 숫자는 여기가 **출처**다 (손으로 적지 않는다).
CONSTANTS = pathlib.Path("data/constants/constant.lua")

#: ``code=None`` 이 **서로 다른 두 사실**을 뜻하는 실제 카드들 (측정 결과).
COLLAPSE_DATUM_LOST = 4064256  # 언데드 월드 — e5:SetCode(id) 가 있는데 못 읽었다
COLLAPSE_DATUM_ABSENT = 114932  # 플레이트 크래셔 — SetCode 자체가 없다
MIXED_SCRIPT = 3461403  # 불사무사의 애도 — FREE_CHAIN · EFFECT_* · None · 진짜 유발


def _lua_constant(name: str) -> int:
    pattern = re.compile(rf"^{name}\s*=\s*(\d+)", re.MULTILINE)
    found = pattern.search(CONSTANTS.read_text(encoding="utf-8", errors="replace"))
    assert found is not None, name
    return int(found.group(1))


# ======================================================================
# §6 — EVENT_FREE_CHAIN 의 뜻
# ======================================================================


def test_01_free_chain_is_syntactically_an_event_code():
    """
    **§6 — 구문으로는 유발 이벤트와 구분되지 않는다.**

    같은 ``EVENT_*`` 이름이고 같은 번호대다. 그래서
    ``code.startswith("EVENT_")`` 를 "유발 조건이 있다" 로 읽으면 **4,909개
    효과 블록이 틀리게 분류된다.**

    숫자는 공식 상수 파일에서 읽는다 — 손으로 적으면 원본과 어긋난다.
    """
    free_chain = _lua_constant("EVENT_FREE_CHAIN")
    chaining = _lua_constant("EVENT_CHAINING")
    destroyed = _lua_constant("EVENT_DESTROYED")

    assert free_chain == 1002
    for value in (free_chain, chaining, destroyed):
        assert 1000 <= value < 1200, value
    assert free_chain not in (chaining, destroyed)


@pytest.mark.real_card
def test_02_free_chain_never_appears_with_a_trigger_effect_type(repository):
    """
    **§6 — 가르는 것은 함께 쓰인 ``EFFECT_TYPE_*`` 이다.**

    ``EVENT_FREE_CHAIN`` 은 **플레이어가 고르는** 발동에만 붙는다
    (``ACTIVATE`` · ``QUICK_O`` · ``IGNITION``). 유발 효과 종류
    (``TRIGGER_O`` · ``TRIGGER_F``) 와는 **한 번도** 같이 쓰이지 않는다.

    이것이 "유발 이벤트가 아니다" 의 근거다 — 의견이 아니라 전수 측정이다.
    """
    chooser_types = {"ACTIVATE", "QUICK_O", "IGNITION", "FIELD", "CONTINUOUS"}
    free_chain_types: set[str] = set()
    trigger_event_types: set[str] = set()

    for card in repository.all_cards():
        script = card.script
        if script is None or not script.effects:
            continue
        for spec in script.effects:
            if spec.code == "EVENT_FREE_CHAIN":
                free_chain_types.update(spec.effect_types)
            elif spec.code and spec.code.startswith("EVENT_"):
                trigger_event_types.update(spec.effect_types)

    assert free_chain_types, "측정 대상이 비었다"
    assert not (free_chain_types & {"TRIGGER_O", "TRIGGER_F"}), free_chain_types
    assert free_chain_types <= chooser_types, free_chain_types
    assert {"TRIGGER_O", "TRIGGER_F"} <= trigger_event_types


# ======================================================================
# §4 · §5 — 네 상태 중 무엇이 구분되는가
# ======================================================================


@pytest.mark.real_card
def test_03_states_a_and_b_are_distinguishable_at_the_source(repository):
    """
    **§5 A · B — 원본에서는 "유발 없음" 과 "유발 있음" 이 구분된다.**

    구분하는 값은 **효과별 ``SetCode``** (``EffectSpec.code``) 하나다.
    """
    mixed = repository.get(MIXED_SCRIPT)
    codes = [
        (spec.index, spec.code, tuple(spec.effect_types))
        for spec in mixed.script.effects
    ]

    assert ("e1", "EVENT_FREE_CHAIN", ("ACTIVATE",)) in codes
    assert any(
        code == "EVENT_PHASE" and "TRIGGER_O" in types for _, code, types in codes
    )
    assert any(code is not None and code.startswith("EFFECT_") for _, code, _ in codes)


@pytest.mark.real_card
def test_04_none_collapses_datum_lost_and_datum_absent(repository):
    """
    **§8 — ``code is None`` 이 서로 다른 두 사실을 뜻한다 (SEMANTIC COLLAPSE).**

    두 카드 모두 어떤 효과의 ``code`` 가 ``None`` 이다. 그런데 원문이 다르다.

    ``언데드 월드 (4064256)``
        ``e5:SetCode(id)`` 가 **있다.** 파서가 ``EVENT_*`` 도 ``EFFECT_*`` 도
        아닌 인자를 읽지 못해 ``None`` 으로 남겼다 → **상태 D (미기록)**
    ``플레이트 크래셔 (114932)``
        ``SetCode`` 호출이 **아예 없다** → 그 효과에는 물어볼 것이 없다
        (상태 A 에 가깝다 · "해당 없음")

    ``None`` 하나로는 이 둘을 가를 수 없다. 전수 측정에서 **162장**이 앞쪽이다
    (``docs/phase3e17-trigger-semantics-audit.md``). 그래서 상태 **C 와 D 가
    구분되지 않는다.**

    **이것이 지금 잘못된 동작을 만들지는 않는다** (``test_09``) — 그러나
    "유발 조건이 없다" 를 ``code is None`` 으로 읽기 시작하는 날 162장이
    조용히 틀린다.
    """
    lost = repository.get(COLLAPSE_DATUM_LOST)
    absent = repository.get(COLLAPSE_DATUM_ABSENT)

    lost_none = [s for s in lost.script.effects if s.code is None]
    absent_none = [s for s in absent.script.effects if s.code is None]
    assert lost_none and absent_none

    # 둘의 **구조화 결과는 같다** — 구분이 사라졌다.
    assert {s.code for s in lost_none} == {s.code for s in absent_none} == {None}

    # 그런데 원문은 다르다.
    lost_source = pathlib.Path(f"c{COLLAPSE_DATUM_LOST}.lua").read_text(
        encoding="utf-8"
    )
    absent_source = pathlib.Path(f"c{COLLAPSE_DATUM_ABSENT}.lua").read_text(
        encoding="utf-8"
    )
    assert "SetCode(id)" in lost_source, "원본에 데이터가 있다"
    assert "SetCode" not in absent_source, "원본에 데이터가 없다"


def test_05_the_parser_drops_a_setcode_it_cannot_name():
    """
    **§8 — 왜 D 가 ``None`` 이 되는지 파서를 **직접 돌려** 고정한다.**

    파서는 ``SetCode`` 인자에서 ``EVENT_*`` → ``EFFECT_*`` 순으로 찾고, 둘 다
    아니면 **아무것도 적지 않는다.** 그래서 ``SetCode(id)`` 는 "SetCode 가
    없었다" 와 같은 모양이 된다.

    **리포지토리를 거치지 않는다.** ``CardRepository`` 는 ``data/cache`` 에
    파싱 결과를 캐시하므로, 캐시된 카드로 재면 파서가 바뀌어도 테스트가 알지
    못한다. 실제로 그랬다 — "읽지 못한 ``SetCode`` 를 ``EVENT_FREE_CHAIN`` 으로
    메꾸는" 고의 위반을 넣었을 때 **아무 테스트도 잡지 못했다.** 그래서
    ``parse_lua_source`` 를 직접 부른다.

    이 지름길이 왜 위험한가: 상태 **D(미기록)를 상태 A(유발 없음)로 조용히
    승격**시키는 일이고, 그러면 162장이 "아무 때나 쓸 수 있는 효과" 가 된다.
    """
    from sources.lua_loader import parse_lua_source

    # ① 이름을 댈 수 없는 인자 → ``None`` 이어야 한다 (메꾸지 않는다).
    unnameable = """
local s,id=GetID()
function s.initial_effect(c)
\tlocal e1=Effect.CreateEffect(c)
\te1:SetType(EFFECT_TYPE_FIELD)
\te1:SetCode(id)
\tc:RegisterEffect(e1)
end
"""
    info = parse_lua_source(1, "c1.lua", unnameable)
    assert [spec.code for spec in info.effects] == [None], info.effects

    # ② 이름을 댈 수 있으면 그대로 적는다 — 둘을 가르는 것이 이 값 하나다.
    named = unnameable.replace("SetCode(id)", "SetCode(EVENT_FREE_CHAIN)")
    assert [s.code for s in parse_lua_source(2, "c2.lua", named).effects] == [
        "EVENT_FREE_CHAIN"
    ]
    triggered = unnameable.replace("SetCode(id)", "SetCode(EVENT_DESTROYED)")
    assert [s.code for s in parse_lua_source(3, "c3.lua", triggered).effects] == [
        "EVENT_DESTROYED"
    ]

    # ③ 그리고 "읽지 못했다" 를 적어 두는 자리가 **없다** — D 가 사라지는 이유다.
    source = pathlib.Path("sources/lua_loader.py").read_text(encoding="utf-8")
    assigned = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
    }
    assert "code" in assigned
    for sentinel in ("code_unparsed", "code_raw", "unknown_code"):
        assert sentinel not in assigned, sentinel


def test_06_the_file_wide_list_is_not_a_per_effect_trigger_list():
    """
    **§3 · §5 — ``LuaScriptInfo.trigger_events`` 는 유발 목록이 아니다.**

    이름은 그렇게 읽히지만 실제로는 **스크립트 전체에서 정규식으로 긁은
    ``EVENT_*``** 이고, 거기에는 ``EVENT_FREE_CHAIN`` 도 들어간다. 효과마다
    무엇이 붙었는지는 ``EffectSpec.code`` 만 안다.

    두 자리를 섞으면 "이 카드는 유발 효과를 갖는다" 가 거짓이 된다.
    """
    loader = pathlib.Path("sources/lua_loader.py").read_text(encoding="utf-8")
    assert "info.trigger_events = [" in loader
    assert "_RE_EVENT.findall(source)" in loader, "파일 전체를 긁는다"

    assert "trigger_events" in LuaScriptInfo.__dataclass_fields__
    assert "code" in EffectSpec.__dataclass_fields__
    assert not [f for f in EffectSpec.__dataclass_fields__ if "trigger" in f]


@pytest.mark.real_card
def test_07_the_file_wide_list_mixes_free_chain_with_real_events(repository):
    """**§6 — 섞인다는 것을 실제 카드로 보인다.**"""
    card = repository.get(MIXED_SCRIPT)
    assert "EVENT_FREE_CHAIN" in card.script.trigger_events
    assert "EVENT_PHASE" in card.script.trigger_events
    assert len(card.script.trigger_events) >= 2


# ======================================================================
# §4 · §9 — EffectDefinition 과 Engine
# ======================================================================


def test_08_there_is_no_converter_so_nothing_is_lost_in_conversion():
    """
    **§4-Q4 — "변환 중 사라진다" 는 틀린 그림이다. 변환이 없다.**

    ``EffectDefinition`` 을 만드는 자리는 ``engine/effect/library.py`` 하나이고
    전부 손으로 적은 것이다 (ADR-006). 그래서 이 감사의 결론은 "pipeline 이
    값을 흘린다" 가 아니라 **"전사가 그 값을 적지 않았다"** 다. 고칠 자리가
    전혀 다르다.
    """
    builders = sorted(
        path.as_posix()
        for path in pathlib.Path(".").rglob("*.py")
        if "__pycache__" not in path.as_posix()
        and not path.as_posix().startswith("tests/")
        and "EffectDefinition(" in path.read_text(encoding="utf-8", errors="replace")
    )
    assert builders == ["engine/effect/library.py"], builders

    fields = set(EffectDefinition.__dataclass_fields__)
    assert not [f for f in fields if "trigger" in f or "event" in f or "timing" in f]

    # 엔진의 어떤 실행 코드도 유발 필드를 **읽지** 않는다 (AST — 주석은 세지 않는다).
    for module in pathlib.Path("engine").rglob("*.py"):
        read = {
            node.attr
            for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute)
        }
        assert "trigger_events" not in read, module.name
        assert "trigger_event" not in read, module.name


@pytest.mark.real_card
def test_09_no_registered_effect_needs_a_trigger_event(repository):
    """
    **§9 — 지금 엔진 범위에서는 이 구분이 필요하지 않다.**

    등재된 16개 효과가 **전부** ``EVENT_FREE_CHAIN`` + ``EFFECT_TYPE_ACTIVATE``
    다. 즉 "플레이어가 고르는 발동" 하나뿐이고, 유발 이벤트를 쓰는 효과가
    **한 건도 없다.**

    그래서 ``test_04`` 의 collapse 가 지금 잘못된 판정을 만들지 않는다 —
    판정에 쓰이지 않기 때문이다. 이것이 이 Phase 를 **AUDIT ONLY** 로 끝낼 수
    있게 하는 사실이고, 그래서 세어서 고정한다. 유발 효과가 하나라도 등재되는
    날 이 시험이 깨지고, 그때 다시 읽어야 한다.
    """
    codes: set[str | None] = set()
    types: set[str] = set()
    for entry in EFFECT_LIBRARY:
        card = repository.get(entry.definition.source_card_id)
        spec = card.script.effects[entry.definition.effect_ref.ordinal]
        codes.add(spec.code)
        types.update(spec.effect_types)

    assert codes == {"EVENT_FREE_CHAIN"}, codes
    assert types == {"ACTIVATE"}, types
    assert len(EFFECT_LIBRARY) == 16


def test_10_analysis_can_say_it_failed_on_conditions_but_not_on_triggers():
    """
    **§5 — 같은 모듈 안에서 두 태도가 다르다.**

    ``ActivationCondition`` 에는 ``has_condition_function`` · ``unparsed`` ·
    ``raw`` 가 있다 — "조건 함수가 있었는데 읽어내지 못했다" 를 말할 수 있다.
    즉 **조건** 쪽에서는 C 와 D 가 구분된다.

    유발 쪽(``trigger_event``)에는 그 짝이 **없다.** 그 비대칭이 이 감사의
    결론이고, 고쳐야 할 날 어디를 보면 되는지를 가리킨다.
    """
    condition_fields = set(ActivationCondition.__dataclass_fields__)
    assert {"has_condition_function", "unparsed", "raw"} <= condition_fields

    analysis_fields = set(EffectAnalysis.__dataclass_fields__)
    assert "trigger_event" in analysis_fields
    for sentinel in (
        "has_trigger_code",
        "trigger_unparsed",
        "trigger_raw",
        "trigger_unknown",
    ):
        assert sentinel not in analysis_fields, sentinel
    # 다만 원본은 남아 있다 — 되짚을 수는 있다.
    assert "raw" in analysis_fields


# ======================================================================
# §16 — 의도적 경계 테스트
# ======================================================================


@pytest.mark.real_card
def test_11_free_chain_must_not_be_read_as_a_trigger_event(repository):
    """
    **§16-C — ``EVENT_FREE_CHAIN`` 을 유발 이벤트로 읽으면 안 된다.**

    가장 쉬운 오독이다. ``code.startswith("EVENT_")`` 를 "유발 효과다" 로 읽으면
    **욕망의 항아리가 유발 효과가 된다.** 그러면 플레이어가 고를 수 없는 효과가
    되고, 아무 일도 일어나지 않았으므로 영영 발동하지 못한다.

    실패해야 하는 이유: 이 오독은 **등재된 16개 전부**를 못 쓰게 만든다.
    """
    naive_trigger = []
    correct_trigger = []
    for entry in EFFECT_LIBRARY:
        card = repository.get(entry.definition.source_card_id)
        spec = card.script.effects[entry.definition.effect_ref.ordinal]
        if spec.code and spec.code.startswith("EVENT_"):
            naive_trigger.append(card.id)
        if (
            spec.code
            and spec.code.startswith("EVENT_")
            and spec.code != "EVENT_FREE_CHAIN"
        ):
            correct_trigger.append(card.id)

    assert len(naive_trigger) == 16, "틀린 읽기는 전부를 유발로 본다"
    assert correct_trigger == [], "맞는 읽기는 하나도 유발로 보지 않는다"


@pytest.mark.real_card
def test_12_absent_trigger_data_must_not_be_reported_as_no_trigger(repository):
    """
    **§16-A · §16-B — "정보 없음" 을 "유발 없음" 으로 바꾸면 안 된다.**

    ``언데드 월드`` 의 ``e5`` 는 원문에 ``SetCode(id)`` 가 **있다.**
    ``code is None`` 을 "유발 조건이 없다" 로 읽으면 이 효과가 "아무 때나 쓸 수
    있는 효과" 로 승격된다 — 그것이 ``UNKNOWN`` 을 허가로 바꾸는 일이다.

    그래서 **지금 그런 변환을 하는 코드가 없다**는 것을 고정한다. 생기는 날
    이 시험이 깨진다.
    """
    lost = repository.get(COLLAPSE_DATUM_LOST)
    assert [s for s in lost.script.effects if s.code is None], "측정 대상이 사라졌다"

    for root in ("engine", "core", "analysis", "sources", "agent"):
        for module in pathlib.Path(root).rglob("*.py"):
            text = module.read_text(encoding="utf-8")
            for forbidden in (
                "code is None: return True",
                "trigger_event is None and",
                "not trigger_event:",
            ):
                assert forbidden not in text, (module.as_posix(), forbidden)


@pytest.mark.real_card
def test_13_trigger_metadata_never_reaches_the_observation(repository):
    """
    **§12 · §16-D — 유발 메타데이터가 관측으로 나가지 않는다.**

    내부에 데이터가 있다는 것과 AI 가 그것을 볼 수 있다는 것은 다른 일이다.
    상대의 세트 카드는 정체도 유발 조건도 보이지 않아야 한다.
    """
    from engine.duel import Duel
    from engine.game_state_view import CardDefinitionView, GameStateView
    from engine.priority import PriorityState
    from engine.state.game_state import GameState
    from engine.vocabulary import Phase, Position, Zone

    state = GameState.create(
        repository, decks=([11091375] * 20, [11091375] * 20), turn_player=0, seed=1
    )
    state.create_instance(
        5915629, owner=0, zone=Zone.SZONE, position=Position.FACEDOWN
    )
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state, priority=PriorityState.idle(turn_player=0, phase=Phase.MAIN1)
    )

    for viewer in (0, 1):
        payload = duel.view(viewer).to_dict()
        assert not [
            key
            for key in payload
            if "trigger" in key or "event" in key or "set_turn" in key
        ]

    # 상대는 정체조차 모른다.
    theirs = duel.view(1)
    seen = [c for c in theirs.opponent.zone(Zone.SZONE).cards if c is not None]
    assert [(c.card_id, c.definition) for c in seen] == [(None, None)]

    # 관측의 카드 정의 스냅숏에도 유발 자리가 없다.
    for holder in (CardDefinitionView, GameStateView):
        assert not [
            name
            for name in holder.__dataclass_fields__
            if "trigger" in name or "event" in name
        ], holder.__name__


def test_14_this_phase_touched_no_behaviour():
    """
    **§13 · §14 — 평가 · 탐색 · 엔진 동작을 건드리지 않았다.**

    이 Phase 의 산출물은 측정과 문장이다. 그래서 유발 관련 이름이 ``agent/`` 에
    들어가지 않았음을 고정한다.
    """
    for path in (
        "agent/evaluation.py",
        "agent/search.py",
        "agent/policy.py",
        "agent/simulation.py",
    ):
        source = pathlib.Path(path).read_text(encoding="utf-8")
        for forbidden in (
            "trigger_event",
            "trigger_events",
            "EVENT_FREE_CHAIN",
            "EffectSpec",
        ):
            assert forbidden not in source, (path, forbidden)
