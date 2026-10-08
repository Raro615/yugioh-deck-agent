"""
Phase 3-E-18 — ``SetCode`` 의 부재 · 존재 · 파싱 실패를 구분할 수 있는가 (감사).

감사지만 **파서 한 분기를 고쳤다** — 읽지 못한 인자 뒤에 **앞 값이 남는** 블록
3개가 있었다. 아래 "틀린 값" 항목을 보라. 그 밖에는 아무것도 바꾸지 않았다.

E-17 의 162장은 **측정 방법이 틀린 숫자였다**
---------------------------------------------
E-17 은 "파일의 ``SetCode(`` 호출 수 > ``code`` 를 읽은 spec 수" 로 셌다. 그
방법이 두 가지 이유로 틀린다.

1. 파서는 ``Effect.CreateEffect`` / ``Clone()`` 으로 **묶인 변수**의 setter 만
   본다 (``if spec is None: continue``). 묶이지 않은 변수의 ``SetCode`` 는
   호출 수에는 들어가지만 spec 이 아예 없다 — "읽지 못했다" 가 아니라
   "효과로 모델링하지 않았다" 다.
2. 스크립트는 ``local e1=...`` 을 함수마다 다시 쓴다. 같은 이름의 spec 이
   여럿이면 호출 수와 spec 수가 서로 상쇄된다.

그래서 이번에는 **``parse_lua_source`` 의 결과**(= 진짜 ``spec.code``)와 "이
블록에 Code setter 가 붙었는가" 를 같이 보고 셌다. 수정 후 기준이다.

    A   SetCode 가 없다 (물려받은 값도 없다)       4,436  (12.79%)
    B   자기 SetCode 를 읽었다                   29,978  (86.44%)
    B'  Clone 이 물려받은 값만 있다                 148  ( 0.43%)
    C/E 호출은 있는데 이름을 못 붙였다               118  ( 0.34%)
    (별도) 묶이지 않은 변수의 setter              3,327

수정 전에는 B 29,981 · C/E 115 였다 (아래 3개 블록 차이). E-17 이 162 라고
적은 자리의 **실제 수는 115**(수정 전) 였다.

``corpus`` 수가 E-17 과 다른 이유도 측정 대상 차이다. E-17 은 ``all_cards()``
를 걸었고(34,631 블록 · 효과 있는 카드 12,504장), 이번에는 ``c*.lua`` 12,702개를
직접 걸었다(34,680 블록). 차이 49 블록은 **cards.cdb 에 없는 패스코드 15개**의
스크립트다 — 34,631 + 49 = 34,680 으로 정확히 맞는다. 두 수 모두 맞다.

**틀린 값** — 읽지 못했는데 앞 값이 남는 블록 3개 (고쳤다)
---------------------------------------------------------
``Clone()`` 은 부모의 ``code`` 를 물려받는다. 그 다음 스크립트가 ``SetCode`` 로
덮어썼는데 인자를 읽지 못하면, 수정 전 파서는 ``spec.code`` 를 **그대로 두었다**
— 스크립트가 분명히 지운 코드를 계속 주장한 셈이다.

    c4179255   e1:SetCode(EVENT_CHAINING) → local e2=e1:Clone() → e2:SetCode(id)
               ⇒ 수정 전 e2.code == "EVENT_CHAINING"  (틀렸다)
               ⇒ 수정 후 e2.code is None             (모른다)
    c73734821  같은 모양
    c64591429  EFFECT_CANNOT_SPECIAL_SUMMON ← SetCode(CARD_CLOCK_LIZARD)

이것은 "없는데 있다고 말한다" 가 아니라 **"다른 것을 있다고 말한다"** 이므로
``None`` 으로 되돌리는 쪽이 맞다 (UNKNOWN 은 값이 아니다). 블록 수는 그대로고
(34,680) ``effect_count`` 도 그대로이므로 관측은 바뀌지 않는다. 파서가 바뀌었기
때문에 캐시 서명을 ``v3`` → ``v4`` 로 올렸다 — 서명은 ``c*.lua`` 의 개수와
수정 시각만 보므로 **파서 변경으로는 저절로 무효화되지 않는다.**

상태 D — 한정자를 버린다 (1,430개, 수정하지 않음)
-------------------------------------------------
값을 읽은 29,978개 중 **1,430개(4.77%)는 인자가 읽은 이름보다 길다.** 파서는
첫 이름만 적고 **한정자를 버린다.**

    EVENT_PHASE+PHASE_END       751 →  "EVENT_PHASE"
    EVENT_PHASE|PHASE_STANDBY   394 →  "EVENT_PHASE"
    EVENT_PHASE|PHASE_BATTLE    131 →  "EVENT_PHASE"
    EVENT_CUSTOM+id              74 →  "EVENT_CUSTOM"

``EVENT_PHASE`` 는 **단독으로 쓰인 블록이 0개**다 (1,326개 전부 한정자가
있다). 즉 ``code == "EVENT_PHASE"`` 는 "어느 페이즈인지 모른다" 를 뜻하고,
서로 다른 1,326개의 유발 시점이 **한 값으로 합쳐진다.** 이것은 **틀린 값이
아니라 덜 읽은 값**이므로 이 Phase 에서 고치지 않았다 (읽는 곳이 없다).

한 블록에 ``SetCode`` 가 두 번 붙는 10건
----------------------------------------
파서는 블록마다 ``code`` 를 하나만 들고 **마지막으로 읽힌 값**을 남긴다.

    분기 (if/else)          3건  Lua 는 하나만 실행 → 뒤쪽만 남는다 (손실)
    Clone 후 원본 수정      4건  두 코드가 모두 남는다 (배정만 바뀜)
    덮어쓰기                2건  스크립트 자신의 재지정 → 마지막 값이 맞다
    비-``local`` 재생성      1건  앞선 spec 의 code 를 덮어쓴다 (귀속 오류)

마지막 1건(``c9839115``)은 ``_RE_CREATE_EFFECT`` 가 ``local`` 을 요구해서 생긴다.
``EVENT_SPSUMMON_SUCCESS`` 는 ``trigger_events`` 에 남으므로 **소실이 아니라 귀속
오류**이고, 고치면 corpus 블록이 34,680 → 34,682 로 바뀐다. 즉 관측
(``effect_count``)에 닿는 변경이므로 **이 감사에서 고치지 않는다.**

    SETCODE ≠ SETCODE  —  Lua 의 ``Effect:SetCode()`` 와 cards.cdb 의
    ``Card.setcodes``(카드군)는 **다른 것**이다. 뒤쪽만 관측에 나간다.
"""

import ast
import pathlib
import random

import pytest

from core.card_model import Card, EffectSpec, LuaScriptInfo
from core.provenance import AnalysisStatus, FieldStatus, SourceKind
from sources.lua_loader import parse_lua_source

from tests.conftest import requires_official_db

pytestmark = requires_official_db

#: 다섯 상태의 실제 사례 (측정 결과).
ABSENT_CARD = 114932  # 플레이트 크래셔 — SetCode 호출이 없다
READ_CARD = 55144522  # 욕망의 항아리 — EVENT_FREE_CHAIN
UNNAMEABLE_CARD = 13599884  # 강철의 스콜피온 — e1:SetCode(id) · e2:SetCode(1082946)
QUALIFIER_CARD = 3461403  # 불사무사의 애도 — e4:SetCode(EVENT_PHASE+PHASE_END)

#: ``SetCode(1082946)`` 의 1082946 이 무엇인가 (§11).
PRIVATE_CODE = 1082946

SKELETON = """
local s,id=GetID()
function s.initial_effect(c)
\tlocal e1=Effect.CreateEffect(c)
\te1:SetType(EFFECT_TYPE_FIELD)
{setcode}
\tc:RegisterEffect(e1)
end
"""


def parsed_code(setcode_line: str) -> list[str | None]:
    """원문 한 조각을 **직접** 파싱한다 — 리포지토리 캐시를 거치지 않는다."""
    source = SKELETON.format(setcode=setcode_line)
    return [spec.code for spec in parse_lua_source(1, "c1.lua", source).effects]


# ======================================================================
# §7 · §10 — 다섯 상태
# ======================================================================


def test_01_state_a_no_setcode_call_at_all():
    """**A SETCODE_ABSENT** — 호출이 없으면 ``None`` 이다. 물어볼 것이 없다."""
    assert parsed_code("") == [None]


def test_02_state_b_a_nameable_argument_is_read():
    """**B SETCODE_PRESENT** — 이름을 댈 수 있으면 그대로 적는다."""
    assert parsed_code("\te1:SetCode(EVENT_FREE_CHAIN)") == ["EVENT_FREE_CHAIN"]
    assert parsed_code("\te1:SetCode(EVENT_DESTROYED)") == ["EVENT_DESTROYED"]
    assert parsed_code("\te1:SetCode(EFFECT_UPDATE_ATTACK)") == ["EFFECT_UPDATE_ATTACK"]


def test_03_state_c_and_e_an_unnameable_argument_becomes_none():
    """
    **C SETCODE_UNREAD / E SETCODE_MALFORMED — 둘이 구분되지 않는다.**

    세 가지 모양이 모두 ``None`` 이 된다. 그리고 ``None`` 은 **상태 A 와도**
    같은 값이다 (``test_01``) — 그것이 이 Phase 가 재려던 collapse 다.

    **"malformed" 는 아니다.** 셋 다 문법적으로 올바른 Lua 이고, 파서가
    ``EVENT_*`` / ``EFFECT_*`` 라는 **이름**만 찾기 때문에 값이 나오지 않는다.
    그래서 E(비정상 문법)는 실제로는 비어 있고, C(이름을 댈 수 없다)만 있다.
    """
    assert parsed_code("\te1:SetCode(id)") == [None]
    assert parsed_code(f"\te1:SetCode({PRIVATE_CODE})") == [None]
    assert parsed_code("\te1:SetCode(CARD_EHERO_BLAZEMAN)") == [None]

    # 그리고 A 와 같은 값이다 — 구분이 사라진다.
    assert parsed_code("\te1:SetCode(id)") == parsed_code("")


def test_04_state_d_a_qualifier_is_silently_dropped():
    """
    **D SETCODE_UNRESOLVED — 값은 읽혔는데 의미가 덜 읽혔다.**

    파서는 첫 이름만 적고 뒤를 버린다. 그래서 서로 다른 유발 시점이 **한
    값**이 된다.

    이것이 ``C/E``(118개)보다 **열 배 넘게 많다** — 1,430개(4.77%). E-17 은
    이 쪽을 보지 못했다.
    """
    assert parsed_code("\te1:SetCode(EVENT_PHASE+PHASE_END)") == ["EVENT_PHASE"]
    assert parsed_code("\te1:SetCode(EVENT_PHASE|PHASE_STANDBY)") == ["EVENT_PHASE"]
    assert parsed_code("\te1:SetCode(EVENT_PHASE|PHASE_BATTLE)") == ["EVENT_PHASE"]
    # 엔드 페이즈와 스탠바이 페이즈가 **같은 값**이 된다.
    assert parsed_code("\te1:SetCode(EVENT_PHASE+PHASE_END)") == parsed_code(
        "\te1:SetCode(EVENT_PHASE|PHASE_STANDBY)"
    )
    # 어느 커스텀 이벤트인지도 잃는다.
    assert parsed_code("\te1:SetCode(EVENT_CUSTOM+id)") == ["EVENT_CUSTOM"]
    assert parsed_code("\te1:SetCode(EVENT_CUSTOM+id+1)") == ["EVENT_CUSTOM"]


@pytest.mark.real_card
def test_05_the_five_states_in_real_cards(repository):
    """**§10 — 다섯 상태를 실제 카드로 확인한다.**"""
    absent = repository.get(ABSENT_CARD)
    assert [s.code for s in absent.script.effects] == [None]
    assert "SetCode" not in pathlib.Path(f"c{ABSENT_CARD}.lua").read_text(
        encoding="utf-8"
    )

    read = repository.get(READ_CARD)
    assert [s.code for s in read.script.effects] == ["EVENT_FREE_CHAIN"]

    unnameable = repository.get(UNNAMEABLE_CARD)
    source = pathlib.Path(f"c{UNNAMEABLE_CARD}.lua").read_text(encoding="utf-8")
    assert f"SetCode({PRIVATE_CODE})" in source
    assert None in [s.code for s in unnameable.script.effects]

    qualifier = repository.get(QUALIFIER_CARD)
    qsource = pathlib.Path(f"c{QUALIFIER_CARD}.lua").read_text(encoding="utf-8")
    assert "SetCode(EVENT_PHASE+PHASE_END)" in qsource
    assert "EVENT_PHASE" in [s.code for s in qualifier.script.effects]
    # 한정자는 어디에도 남지 않는다.
    assert not [s for s in qualifier.script.effects if s.code == "EVENT_PHASE+PHASE_END"]


@pytest.mark.real_card
def test_06_event_phase_is_never_bare_so_the_value_always_means_unknown_phase(
    repository,
):
    """
    **§7 — ``EVENT_PHASE`` 는 단독으로 쓰이지 않는다.**

    전수 측정에서 단독 0개 · 한정자 포함 1,326개다. 그래서
    ``code == "EVENT_PHASE"`` 를 "페이즈 유발 효과다" 로는 읽을 수 있지만
    **"어느 페이즈인가" 는 영영 알 수 없다.**

    여기서는 표본으로 확인한다 (전수는 감사 보고서의 측정이다).
    """
    files = sorted(pathlib.Path(".").glob("c*.lua"))
    random.seed(18)
    bare = 0
    qualified = 0
    for path in random.sample(files, 1200):
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw in ("SetCode(EVENT_PHASE)", "SetCode(EVENT_PHASE+", "SetCode(EVENT_PHASE|"):
            count = text.count(raw)
            if raw.endswith(")"):
                bare += count
            else:
                qualified += count
    assert qualified > 0, "표본에 페이즈 유발이 없다"
    assert bare == 0, f"단독 EVENT_PHASE 가 나타났다: {bare}"


# ======================================================================
# §11 — SetCode(1082946) 의 정체
# ======================================================================


@pytest.mark.real_card
def test_07_the_numeric_argument_is_a_real_passcode(repository):
    """
    **§11 — 1082946 은 실제 카드 패스코드다** (운명의 불시계 · 함정).

    그리고 그 값이 쓰인 자리는 **유발도 발동도 아니다** — ``강철의 스콜피온`` 의
    ``e2`` 는 ``EFFECT_TYPE_SINGLE`` 에 ``EFFECT_FLAG_CANNOT_DISABLE`` 등을
    달고 ``SetLabelObject`` 로 다른 효과를 가리키는 **기록용 효과**다.

    **그 이상은 UNKNOWN 으로 남긴다.** EDOPro 가 이 숫자를 "그 카드의 코드"
    로 쓰는지 단지 겹치지 않는 정수로 쓰는지는 repository 자료로 결정할 수
    없고, 추측해서 의미를 만들지 않는다.
    """
    card = repository.get(PRIVATE_CODE)
    assert card is not None, "패스코드가 아니다"
    assert "TRAP" in card.type_names

    # 같은 숫자를 쓰는 쪽은 그 카드와 무관한 카드다.
    user = repository.get(UNNAMEABLE_CARD)
    assert user is not None
    source = pathlib.Path(f"c{UNNAMEABLE_CARD}.lua").read_text(encoding="utf-8")
    assert f"e2:SetCode({PRIVATE_CODE})" in source
    assert "SetLabelObject" in source
    # 자기 자신의 패스코드를 쓰는 모양도 있다 — 같은 관용구다.
    own = pathlib.Path("c16317140.lua").read_text(encoding="utf-8")
    assert "SetCode(16317140)" in own


# ======================================================================
# §9 — 캐시는 stale 하지 않다
# ======================================================================


@pytest.mark.real_card
def test_08_the_cache_agrees_with_a_fresh_parse(repository):
    """
    **§9 — 캐시 때문에 틀린 값을 보고 있는 것이 아니다.**

    ``data/cache/lua_scripts.json`` 이 파싱 결과를 들고 있다. 그 캐시가
    **오래되어** 원문과 다른 것인지 확인했다 — 표본에서 불일치 0건이다.

    그래도 한 가지는 사실이다: **캐시는 세션 안에서 파서 변경을 가린다.**
    E-17 에서 파서에 고의 위반을 넣었을 때 아무 테스트도 잡지 못한 이유가
    그것이었고, 그래서 이 파일의 파서 시험들은 ``parse_lua_source`` 를 직접
    부른다.
    """
    assert pathlib.Path("data/cache/lua_scripts.json").is_file()

    files = sorted(pathlib.Path(".").glob("c*.lua"))
    random.seed(99)
    mismatch = []
    for path in random.sample(files, 150):
        card_id = int(path.stem[1:])
        card = repository.get(card_id)
        if card is None or card.script is None:
            continue
        fresh = parse_lua_source(
            card_id, path.name, path.read_text(encoding="utf-8", errors="replace")
        )
        if [s.code for s in card.script.effects] != [s.code for s in fresh.effects]:
            mismatch.append(card_id)
    assert mismatch == [], mismatch


# ======================================================================
# §8 — provenance 는 어휘를 갖고 있으나 여기까지 오지 않는다
# ======================================================================


def test_09_provenance_vocabulary_exists_but_not_at_the_script_layer():
    """
    **§8 — 새 enum 을 만들 필요가 없다. 다만 지금은 닿지 않는다.**

    ``core/provenance.py`` 에 이미 "어디에서 왔는가" 와 "있는가 · 모르는가" 를
    적을 어휘가 있다.

        SourceKind     LUA · OFFICIAL_DB · DERIVED · **UNKNOWN**
        FieldStatus    CONFIRMED · SUPPLEMENTARY · **MISSING** · CONFLICTED
        AnalysisStatus LUA_VERIFIED · TEXT_DERIVED · NO_EFFECT · UNAVAILABLE · UNKNOWN

    즉 "SetCode 가 없다(MISSING)" 와 "읽지 못했다(UNKNOWN)" 를 **구분할 어휘는
    이미 있다.** 그런데 그 어휘가 ``EffectSpec`` 에는 붙어 있지 않다 —
    provenance 는 **카드 단위 필드**에만 쓰인다.

    그래서 §8 의 답은 "새 enum 이 필요하다" 가 아니라 **"있는 어휘를 효과
    단위까지 내려야 한다"** 다. 고칠 자리가 전혀 다르다.
    """
    assert SourceKind.UNKNOWN.value == "unknown"
    assert SourceKind.LUA.value == "lua"
    assert FieldStatus.MISSING.value == "missing"
    assert AnalysisStatus.UNKNOWN.value == "unknown"

    # provenance 는 카드에 붙는다.
    assert "provenance" in Card.__dataclass_fields__
    # 효과 단위에는 붙지 않는다 — 그것이 지금의 공백이다.
    assert not [f for f in EffectSpec.__dataclass_fields__ if "proven" in f or "status" in f]
    assert not [
        f for f in LuaScriptInfo.__dataclass_fields__ if "proven" in f or "status" in f
    ]


# ======================================================================
# §12 · §14 — Engine 과 관측
# ======================================================================


def test_10_the_engine_addresses_effects_but_never_reads_their_setcode():
    """
    **§12 — 엔진은 ``EffectSpec`` 을 **지목**하거나 **세기**만 하고 ``code`` 를
    읽지 않는다.**

    ``card.script.effects`` 를 만지는 엔진 모듈은 두 곳이고, 둘 다 내용을 읽지
    않는다.

    * ``engine/ids.py`` — ``EffectRef(card_id, ordinal)`` 로 **몇 번째 효과인가**
      를 지목한다 (``spec_in`` 이 ordinal 로 꺼내 주지만, 꺼낸 다음 ``code`` 를
      보는 호출자는 없다).
    * ``engine/game_state_view.py`` — ``len(card.script.effects)`` 로 **개수만**
      싣는다. 내용은 관측에 나가지 않는다 (test_11 이 고정한다).

    ``spec.code`` 를 읽는 자리는 엔진 어디에도 없다. 그래서 이 Phase 의 collapse
    가 지금 어떤 판정도 틀리게 만들지 않는다 — ``ENGINE CHANGE = NO`` 의 근거다.
    """
    touches_effects: dict[str, list[bool]] = {}
    for module in pathlib.Path("engine").rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        # ``len(<...>.script.effects)`` 안에 들어 있는 노드를 먼저 표시한다.
        counted = {
            id(node.args[0])
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and node.args
        }
        for node in ast.walk(tree):
            # ``<something>.script.effects`` 를 찾는다.
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "effects"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "script"
            ):
                touches_effects.setdefault(module.as_posix(), []).append(
                    id(node) in counted
                )
    assert sorted(touches_effects) == [
        "engine/game_state_view.py",
        "engine/ids.py",
    ], sorted(touches_effects)

    # 관측은 **세기만** 한다 — 꺼내서 들여다보는 자리가 하나도 없다.
    assert all(touches_effects["engine/game_state_view.py"]), "관측이 효과를 꺼낸다"
    # 주소 지정은 꺼낸다 (``spec_in``) — 그래서 여기만 False 가 섞인다.
    assert not all(touches_effects["engine/ids.py"])

    # 그리고 ``spec.code`` 를 읽는 자리가 없다 — EffectSpec 을 import 하지 않는다.
    for module in pathlib.Path("engine").rglob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert "from core.card_model import EffectSpec" not in text, module.name


def test_11_the_observed_setcodes_are_the_database_archetype_not_the_lua_code():
    """
    **§14 — 이름이 같은 **다른 것** 둘을 혼동하지 않는다.**

    ``CardDefinitionView.setcodes`` 가 관측에 **있다.** 그런데 그 값의 출처는
    cards.cdb 의 ``Card.setcodes`` — 카드가 어느 **카드군**인지이고, 카드
    이름에 적혀 있는 공개 정보다.

    Lua 의 ``Effect:SetCode()`` 는 **효과의 코드**이고 관측에 나가지 않는다.
    둘을 같은 것으로 읽으면 "SetCode 가 이미 공개되어 있다" 는 거짓이 된다.

        Card.setcodes            카드군 (cards.cdb) · 공개 · 관측에 있다
        EffectSpec.code          효과 코드 (Lua) · 비공개 · 관측에 없다
    """
    from engine.game_state_view import CardDefinitionView

    fields = CardDefinitionView.__dataclass_fields__
    assert "setcodes" in fields
    # 효과 내용은 **개수만** 나간다.
    assert "effect_count" in fields
    assert not [name for name in fields if name in {"code", "effect_codes", "script"}]

    view_source = pathlib.Path("engine/game_state_view.py").read_text(encoding="utf-8")
    assert "setcodes=tuple(card.setcodes)" in view_source, "출처가 카드 단위 필드다"
    assert "spec.code" not in view_source
    assert "script.effects" in view_source  # 개수를 세는 데만 쓴다


@pytest.mark.real_card
def test_12_an_opponent_set_card_reveals_neither_identity_nor_setcodes(repository):
    """**§14 · §18-D — 상대 세트 카드의 정체도 카드군도 보이지 않는다.**"""
    from engine.duel import Duel
    from engine.priority import PriorityState
    from engine.state.game_state import GameState
    from engine.vocabulary import Phase, Position, Zone

    state = GameState.create(
        repository, decks=([11091375] * 20, [11091375] * 20), turn_player=0, seed=1
    )
    state.create_instance(
        UNNAMEABLE_CARD, owner=0, zone=Zone.SZONE, position=Position.FACEDOWN
    )
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state, priority=PriorityState.idle(turn_player=0, phase=Phase.MAIN1)
    )

    theirs = duel.view(1)
    [seen] = [c for c in theirs.opponent.zone(Zone.SZONE).cards if c is not None]
    assert seen.card_id is None
    assert seen.definition is None, "정의가 보이면 setcodes 도 보인다"

    # 내 쪽에서는 보이고, 그 값은 **카드군**이다 (Lua 코드가 아니다).
    mine = duel.view(0)
    [owned] = [c for c in mine.me.zone(Zone.SZONE).cards if c is not None]
    assert owned.definition is not None
    assert owned.definition.setcodes == tuple(repository.get(UNNAMEABLE_CARD).setcodes)


# ======================================================================
# §18 — 의도적 경계 테스트
# ======================================================================


@pytest.mark.real_card
def test_13_none_must_not_be_reported_as_setcode_absent(repository):
    """
    **§18-A — ``code is None`` 을 "SetCode 가 없다" 로 단정하면 안 된다.**

    ``강철의 스콜피온`` 은 ``SetCode(id)`` 와 ``SetCode(1082946)`` 를 **갖고 있다.**
    그런데 그 두 효과의 ``code`` 는 ``None`` 이다. 그래서 ``None`` 을 "없음"
    으로 읽으면 이 카드에 대해 **거짓**을 말한다.

    실패해야 하는 이유: 그 거짓이 118개 블록에 퍼진다. 그리고 지금 그런 변환을
    하는 production 코드가 **없다**는 것을 함께 고정한다.
    """
    source = pathlib.Path(f"c{UNNAMEABLE_CARD}.lua").read_text(encoding="utf-8")
    card = repository.get(UNNAMEABLE_CARD)
    none_specs = [s for s in card.script.effects if s.code is None]

    assert none_specs, "측정 대상이 사라졌다"
    assert "SetCode(id)" in source or f"SetCode({PRIVATE_CODE})" in source
    # 즉 "None 이면 SetCode 가 없다" 는 이 카드에서 거짓이다.

    for root in ("core", "sources", "analysis", "engine", "agent"):
        for module in pathlib.Path(root).rglob("*.py"):
            text = module.read_text(encoding="utf-8")
            for forbidden in (
                "has_setcode = spec.code is not None",
                "if spec.code is None: return False",
                'code is None: return "absent"',
            ):
                assert forbidden not in text, (module.as_posix(), forbidden)


def test_14_a_failed_read_must_not_be_recorded_as_a_successful_one():
    """
    **§18-B — 읽지 못한 것을 읽었다고 적으면 안 된다.**

    가장 솔깃한 지름길 둘을 파서로 직접 재서 막는다.

    ① 이름을 댈 수 없는 인자를 ``EVENT_FREE_CHAIN`` 으로 메꾸기
       → 상태 D/C 를 A 로 승격시킨다 (E-17 이 이 위반을 처음에 놓쳤다)
    ② 인자 원문을 그대로 ``code`` 에 넣기
       → ``EVENT_*`` 이름이라는 계약이 깨지고 downstream 비교가 전부 어긋난다
    """
    assert parsed_code("\te1:SetCode(id)") == [None]
    assert parsed_code(f"\te1:SetCode({PRIVATE_CODE})") == [None]

    # ②: 읽은 값은 **이름**이어야 한다 — 원문이 아니다.
    assert parsed_code("\te1:SetCode(EVENT_PHASE+PHASE_END)") == ["EVENT_PHASE"]
    for code in parsed_code("\te1:SetCode(EVENT_PHASE+PHASE_END)"):
        assert code is None or code.replace("_", "").isalnum(), code


def test_15_no_archetype_judgment_is_made_from_an_unknown_setcode():
    """
    **§18-C — SetCode 를 모르는 채로 카드군 판정을 하지 않는다.**

    엔진에 ``IsSetCard`` 류의 판정이 **아예 없다.** 그래서 "모르는데 판정한다"
    는 상태가 생길 수 없다. 생기는 날 이 시험이 깨지고, 그때 ``UNKNOWN`` 을
    돌려주는지 다시 봐야 한다.
    """
    for root in ("engine", "agent"):
        for module in pathlib.Path(root).rglob("*.py"):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            names = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            }
            for forbidden in ("is_set_card", "IsSetCard", "matches_archetype"):
                assert forbidden not in names, (module.as_posix(), forbidden)


def test_16_this_phase_touched_no_behaviour():
    """**§15 — 평가 · 탐색 · 정책에 SetCode 가 들어가지 않았다.**"""
    for path in (
        "agent/evaluation.py",
        "agent/search.py",
        "agent/policy.py",
        "agent/simulation.py",
    ):
        source = pathlib.Path(path).read_text(encoding="utf-8")
        for forbidden in ("SetCode", "EffectSpec", "setcodes", "trigger_events"):
            assert forbidden not in source, (path, forbidden)


# ======================================================================
# §7 추가 — 한 블록에 ``SetCode`` 가 **두 번** 붙는 경우 (측정 10건)
# ======================================================================


def test_17_a_second_setcode_overwrites_the_first_in_three_different_ways():
    """
    **파서는 블록마다 ``code`` 를 하나만 들고, 마지막 ``SetCode`` 를 남긴다.**

    전 corpus 34,680 블록 중 ``SetCode`` 가 두 번 적용되는 블록은 **10개**다.
    세 가지 모양이 섞여 있고, **의미 손실은 하나뿐이다.**

    1. **분기** — ``if … then SetCode(A) else SetCode(B) end``. Lua 는 **둘 중
       하나만** 실행하지만 파서는 **뒤에 쓰인 쪽**을 적는다. A 는 사라진다.
       (``c50789693`` · ``c86198326`` · ``c50237654``)
    2. **Clone 후 원본 수정** — ``local e3=e2:Clone()`` 다음에 ``e2`` 를 바꾼다.
       두 코드가 **둘 다 남고** 변수 배정만 뒤바뀐다 — 손실이 아니다.
       (``c62171834`` · ``c75047173``)
    3. **비-``local`` 재생성** — ``e1=Effect.CreateEffect(c)`` (``local`` 없음).
       ``_RE_CREATE_EFFECT`` 가 ``local`` 을 요구하므로 새 spec 이 생기지
       않고, **앞선 spec 의 ``code`` 가 덮어쓰인다.** (``c9839115``)

    3번은 전 corpus 에서 **1장**이다 (``local`` 없는 생성을 쓰는 스크립트 2장
    중 덮어쓰기가 실제로 일어나는 것 1장). 이 Phase 는 파서를 바꾸지 않으므로
    **현재 상태를 그대로 고정**한다 — 고치는 Phase 는 이 테스트를 **의도적으로**
    갱신해야 하고, 그 이유를 보고서에 적어야 한다.

    고쳐도 ``EVENT_SPSUMMON_SUCCESS`` 자체가 사라진 것은 아니다 —
    ``LuaScriptInfo.trigger_events`` 는 파일 전체에서 긁으므로 **남아 있다.**
    그래서 이것은 "정보 소실" 이 아니라 **"귀속 오류"** 다.
    """
    # 1. 분기 — else 쪽만 남는다.
    branch = _parse_file(50789693)
    assert ("e1", "EFFECT_UPDATE_DEFENSE") in [(s.index, s.code) for s in branch.effects]
    assert "EFFECT_UPDATE_ATTACK" in pathlib.Path("c50789693.lua").read_text(
        encoding="utf-8"
    )
    assert "EFFECT_UPDATE_ATTACK" not in [s.code for s in branch.effects]

    # 2. Clone 후 원본 수정 — 두 코드가 모두 남는다 (배정만 바뀐다).
    cloned = _parse_file(62171834)
    codes = [(s.index, s.code, s.cloned_from) for s in cloned.effects]
    assert ("e2", "EFFECT_UPDATE_DEFENSE", None) in codes
    assert ("e3", "EFFECT_UPDATE_ATTACK", "e2") in codes

    # 3. 비-local 재생성 — 앞선 spec 의 code 가 덮어쓰인다.
    poisoned = _parse_file(9839115)
    source = pathlib.Path("c9839115.lua").read_text(encoding="utf-8")
    creations = [
        line.strip() for line in source.splitlines() if "e1=Effect.CreateEffect" in line
    ]
    #: 두 번째 생성에 ``local`` 이 없다 — 그래서 새 spec 이 생기지 않는다.
    assert creations == ["local e1=Effect.CreateEffect(c)", "e1=Effect.CreateEffect(c)"]
    assert "e1:SetCode(EVENT_SPSUMMON_SUCCESS)" in source
    #: 유발은 ``e1`` 의 것이었는데 지금 ``e1`` 에 적힌 것은 나중 값이다.
    assert ("e1", "EFFECT_UPDATE_ATTACK") in [(s.index, s.code) for s in poisoned.effects]
    assert "EVENT_SPSUMMON_SUCCESS" not in [s.code for s in poisoned.effects]
    #: 그래도 파일 단위 목록에는 남아 있다 — 소실이 아니라 귀속 오류다.
    assert "EVENT_SPSUMMON_SUCCESS" in poisoned.trigger_events


def _parse_file(card_id: int) -> LuaScriptInfo:
    """캐시를 거치지 않고 **원문을 직접** 파싱한다 (E-17 의 교훈)."""
    path = pathlib.Path(f"c{card_id}.lua")
    return parse_lua_source(card_id, path.name, path.read_text(encoding="utf-8"))


# ======================================================================
# §16 — 이 Phase 가 고친 하나: 읽지 못한 인자가 **앞 값을 남기면 안 된다**
# ======================================================================


def test_18_an_unreadable_argument_must_clear_the_inherited_value():
    """
    **§16 — parser bug 로 증명된 단 하나.**

    왜 bug 인가 (원문 + 파서 코드 대조):

    * 원문 ``c4179255.lua`` — ``e1:SetCode(EVENT_CHAINING)`` 다음
      ``local e2=e1:Clone()`` 다음 ``e2:SetCode(id)``. Lua 에서 ``e2`` 의 코드는
      ``id``(자기 패스코드)다. ``EVENT_CHAINING`` **이 아니다.**
    * 파서 ``sources/lua_loader.py`` — ``Clone`` 분기가 ``spec.code =
      parent.code`` 로 물려주고, ``setter == "Code"`` 분기는 인자를 읽지 못하면
      수정 전에 **아무것도 하지 않았다.** 그래서 물려받은 값이 남았다.

    결과는 "모른다" 가 아니라 **틀린 주장**이다 — 스크립트가 지운 유발 코드를
    계속 들고 있었다. corpus 전체에서 3개 블록이다.

    수정은 분기 하나에 ``else: spec.code = None`` 을 더한 것뿐이다. schema ·
    Engine · API · 블록 수(34,680) · ``effect_count`` 모두 그대로다.
    """
    #: 합성 — Clone 이 물려받은 값이 읽지 못한 인자로 지워진다.
    source = """
local s,id=GetID()
function s.initial_effect(c)
\tlocal e1=Effect.CreateEffect(c)
\te1:SetCode(EVENT_CHAINING)
\tc:RegisterEffect(e1)
\tlocal e2=e1:Clone()
\te2:SetCode(id)
\tc:RegisterEffect(e2)
end
"""
    specs = parse_lua_source(1, "c1.lua", source).effects
    assert [(s.index, s.code, s.cloned_from) for s in specs] == [
        ("e1", "EVENT_CHAINING", None),
        ("e2", None, "e1"),
    ]

    #: 실제 카드 3장 — 그 블록(ordinal 고정)의 값이 ``None`` 이어야 한다.
    #: 같은 변수 이름이 여러 번 나오므로 **위치**로 지목한다 (``EffectRef`` 와 같다).
    for card_id, ordinal, var, overwritten in (
        (4179255, 1, "e2", "EVENT_CHAINING"),
        (73734821, 1, "e2", "EVENT_CHAINING"),
        (64591429, 4, "e3", "EFFECT_CANNOT_SPECIAL_SUMMON"),
    ):
        info = _parse_file(card_id)
        text = pathlib.Path(f"c{card_id}.lua").read_text(encoding="utf-8")
        assert f"{var}:SetCode(" in text  # 덮어쓰기가 원문에 있다
        assert overwritten in text  # 물려받은 값도 원문에 있다
        spec = info.effects[ordinal]
        assert spec.index == var and spec.cloned_from, (card_id, spec)
        assert spec.code is None, (card_id, spec.code)

    #: 물려받기 자체는 살아 있다 — 덮어쓰기가 **없을 때는** 값이 남는다.
    inherited = parse_lua_source(
        1,
        "c1.lua",
        """
local s,id=GetID()
function s.initial_effect(c)
\tlocal e1=Effect.CreateEffect(c)
\te1:SetCode(EVENT_CHAINING)
\tc:RegisterEffect(e1)
\tlocal e2=e1:Clone()
\tc:RegisterEffect(e2)
end
""",
    ).effects
    assert [s.code for s in inherited] == ["EVENT_CHAINING", "EVENT_CHAINING"]


def test_19_the_cache_signature_must_change_when_the_parser_changes():
    """
    **캐시 서명은 ``c*.lua`` 만 본다 — 파서 변경으로는 무효화되지 않는다.**

    ``LuaScriptSource._signature`` 는 ``f"v4:{개수}:{최신 mtime}"`` 이다. 데이터가
    바뀌면 서명이 바뀌지만 **파서가 바뀌어도 서명은 그대로다.** 그래서 파서를
    고치는 Phase 는 접두사를 손으로 올려야 한다. 이 Phase 는 ``v3`` → ``v4``
    로 올렸다 (test_18 의 수정이 캐시 경로에도 닿게 하려면 필요하다).

    E-17 이 고의 위반 A 를 놓친 이유가 정확히 이것이다 — 캐시가 이전 파서의
    결과를 돌려주고 있었다.

    .. note::
       🔴 **Phase 3-F-27 이 ``v4`` → ``v5`` 로 올렸다.** 그 Phase 가
       ``SetType`` 의 ``Clone`` 노후값을 고쳤고, 올리지 않으면 고친 파서가
       옛 캐시를 계속 읽는다는 것을 실험으로 확인했다 (수정 전 캐시가
       ``c324483`` ``e2`` 를 ``['IGNITION', 'QUICK_O']`` 로 들고 있었다).
       **이 테스트가 설계대로 작동해 그 상승을 요구했다.**
    """
    source = pathlib.Path("sources/lua_loader.py").read_text(encoding="utf-8")
    assert 'return f"v5:{count}:{newest:.0f}"' in source
    #: 되돌아가지 않았는지도 본다.
    assert 'return f"v4:{count}:{newest:.0f}"' not in source
    #: 서명 계산에 파서 버전·코드 해시가 들어가지 않는다 — 그래서 손으로 올린다.
    signature_body = source.split("def _signature(self)")[1].split("def ")[0]
    for token in ("parse_lua_source", "__version__", "md5", "sha"):
        assert token not in signature_body, token
