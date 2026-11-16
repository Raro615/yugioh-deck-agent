"""
자율 탐색 결과의 비교와 추천 — **open-development v2** (Phase 6-BD ·
6-BE 에서 비교 규칙과 정보 부족 처리를 고쳤다).

왜 v2 인가
----------
v1 (:mod:`agent.open_evaluation`) 은 세 축으로 견줬다 — 필드 앞면 몬스터
수 · 남은 패 장수 · 일반 소환권. 실사용에서 그 세 축이 **장수만으로 우열을
확정**한다는 것이 드러났다 (세트한 쪽이 언제나 짐, 토큰과 효과 몬스터를
같은 1장으로 셈, 상대에게 준 것이 어느 축에도 없음).

Phase 6-BE 가 고친 것 — **장수 비교에서 구성 비교로**
-----------------------------------------------------
6-BD 의 v2 는 여전히 **장수**(``effect_bodies`` 등)를 축으로 썼다. 그래서
소재를 써서 몸이 줄어든 결과는 다른 조건이 같으면 **그대로 지배당했다** —
링크 전개가 장수 때문에 열등해지는 문제가 남아 있었다. 그리고 카드 정의를
모르는 카드는 집계에서 **빠져서** 사실상 0 으로 다뤄졌다.

지금 필드 축은 **장수가 아니라 구성의 포함 관계**다.

* 두 후보의 자기 필드 구성을 다중집합으로 적고, 한쪽이 다른 쪽을 **포함**
  하면 (= 같은 것을 다 가지고 더 가졌다) 그 축에서 앞선다.
* 포함도 역포함도 아니면 — 즉 **서로 다른 몬스터로 바뀌었으면** 그 축은
  🔴 **비교 불가**이고, 그러면 두 후보 사이에 **지배 관계를 확정하지
  않는다.**
* 🔴 그래서 "장수가 줄었다" 로 탈락시키지도, "링크 소환했다" 로 우월하다고
  하지도 않는다. 링크 수치 · 행동 수 같은 대체 기준도 쓰지 않는다.

**언제 비교가 가능한가** (모두 동률로 끝내지 않기 위해 명시한다)

1. 필드 구성이 **같거나** 한쪽이 다른 쪽을 포함할 때 — 그 축이 비교된다.
2. 구성 원소의 **정체를 알 때** — 가려진 카드가 있으면 그 축은 비교 불가다.
3. 나머지 축(쥔 카드 · 일반 소환권 · 상대 자리)은 장수·사실이므로 항상
   비교된다. 🔴 단 **한 축이라도 비교 불가면 지배 관계를 확정하지 않는다.**

무엇을 세고 무엇을 세지 않는가 — A · B · C
-------------------------------------------
🔴 **근거의 종류를 섞지 않는다.** 섞으면 "카드 정의에 효과가 있다" 가
"확정 방해 1회" 로 읽힌다.

**A. 확인된 것** — 지금 상태와 **구현된 판정**이 말하는 자원·행동.
  🔴 **우열 판정에 쓰는 것은 A 뿐이다.**

**B. 잠재 가치** — 카드 **정의**에서 알 수 있지만 **실제로 쓸 수 있는지는
  검증하지 못한** 것. 🔴 **표시만 하고 우열에 쓰지 않는다.**

**C. 판단 불가** — 엔진이 지원하지 않아 **후보조차 되지 못한** 수, 멈춘
  이유, 카드 정의를 못 읽은 자리. 🔴 **가치 0 으로 단정하지 않는다** —
  비교 불가로 남긴다.

🔴 **카드 이름도 정답 필드도 없다.** 이 모듈에 카드 ID 리터럴이 없고, 카드
이름별 점수표도 없다. 구성 비교에 쓰는 카드 ID 는 **같은 카드인가**를 묻는
동일성 비교일 뿐이고, 어느 카드가 좋다는 표가 아니다.

경계 (ADR-007)
--------------
``engine`` 과 ``agent`` 만 import 한다. 카드 저장소를 모른다 — 카드 정의
사실은 어댑터가 :class:`CardFacts` 로 바꿔 넘긴다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from engine.vocabulary import Zone

from agent.bounded_search import FLOW_ACTION_KINDS, RerunState
from agent.open_evaluation import OpenCandidate
from agent.result_ranking import Criterion, Exclusion

__all__ = [
    "CRITERIA_V2",
    "UNEXPLORED_NOTE",
    "CardFacts",
    "CardKnowledge",
    "Comparison",
    "MeasuresV2",
    "POLICY_NAME_V2",
    "POLICY_SCOPE_NOTE_V2",
    "POLICY_VERSION_V2",
    "RankingV2",
    "UNJUDGED_V2",
    "compare_v2",
    "core_key",
    "measure_v2",
    "rank_open_v2",
    "select_top_v2",
    "variant_key",
]

POLICY_NAME_V2: str = "open-development"
POLICY_VERSION_V2: str = "v2"

POLICY_SCOPE_NOTE_V2: str = (
    "목표 카드를 지정하지 않은 자율 탐색에서 **예산 안에 모은 후보**끼리의"
    " 비교입니다 — 🔴 전역 최적 전개도, 실전 최강도, 승률 평가도 아닙니다."
    " 🔴 **우열은 '확인된 것(A)' 으로만 가립니다**; 카드 정의로만 아는"
    " 잠재 가치(B)와 엔진이 판단하지 못한 것(C)은 **표시만** 하고 순서에"
    " 쓰지 않습니다. 🔴 **필드 구성이 서로 바뀐 후보끼리는 비교하지"
    " 않습니다** — 장수는 관측값이고 실전 우월성의 증명이 아닙니다."
)


# ======================================================================
# 카드 정의 사실 — 어댑터가 넘겨 준다
# ======================================================================
@dataclass(frozen=True, slots=True)
class CardFacts:
    """
    카드 **한 장의 정의**에서 읽은 사실들.

    🔴 **판정이 아니다.** "지금 발동할 수 있다" 도 "강하다" 도 아니고,
    카드 종류와 인쇄된 효과 수뿐이다. 지금 쓸 수 있는지는 ``legal_actions``
    의 일이고 이 모듈은 그것을 보지 않는다.

    🔴 **카드 정의를 아는 것과 엔진이 그 효과를 지원하는 것은 별개다**
    (Phase 6-BE §2). 이 그릇은 **정의**만 말한다 — 엔진이 그 수를 후보로
    만들 수 있는지는 ``legal_actions`` 의 미지원 목록이 말하고, 그것은
    C 로 따로 센다.

    🔴 **모르면 ``None`` 이다.** :meth:`CardKnowledge.get` 이 ``None`` 을
    돌려주면 이 모듈은 그 자리를 **C(판단 불가)** 로 센다 — 0 으로 메우지
    않고, 종류를 추측하지도 않는다.
    """

    is_token: bool = False
    """토큰인가. 🔴 **무가치라는 뜻이 아니다** — 소재 조건을 만족하면 링크
    소재로 쓸 수 있고, 실제로 그렇게 쓰인 경로가 탐색에 있다."""
    is_monster: bool = False
    is_effect_monster: bool = False
    """
    카드 종류에 ``EFFECT`` 가 있는가 (Phase 6-BE 정정).

    🔴 6-BD 는 "토큰이 아닌 앞면 몬스터" 를 전부 ``effect_bodies`` 에
    담고 **"효과 몬스터" 라고 불렀다** — 일반 몬스터·의식 몬스터도 거기
    들어갔다. 지금은 종류를 그대로 읽는다.
    """
    reactive_backrow: bool = False
    """세트해 두면 **상대 턴에 쓸 수 있는 종류**인가 (함정 · 속공마법).
    🔴 **확정 방해가 아니다** — 발동 조건도, 지금 유효한지도 보지 않았다."""
    effect_count: int = 0
    """
    인쇄된 효과 수.

    🔴 **남은 발동 횟수가 아니다** (Phase 6-BE §3). 효과 정의 수나 Lua
    블록 수를 남은 횟수로 세지 않는다 — 이 값은 "판단할 것이 있는가" 를
    가르는 데만 쓴다 (0 이면 애초에 쓸 효과가 없다).
    """
    is_extra_deck: bool = False


class CardKnowledge:
    """
    ``get(card_id) -> CardFacts | None`` 하나만 요구하는 자리.

    🔴 **비어 있어도 돈다.** 아무것도 모르면 종류 값이 전부 "판단 불가" 로
    남고, 구성 비교는 **동일성**으로 계속 돈다 — 카드 정의를 모른다고 해서
    비교가 멈추지도, 그 카드가 0 으로 세어지지도 않는다.
    """

    def __init__(self, facts: "dict[int, CardFacts] | None" = None) -> None:
        self._facts = dict(facts or {})

    def get(self, card_id) -> "CardFacts | None":
        return self._facts.get(card_id)


_EMPTY_KNOWLEDGE = CardKnowledge()

#: 구성 원소의 **종류 이름** — 🔴 점수가 아니고 이름이다.
BODY_EFFECT = "효과 몬스터"
BODY_PLAIN = "효과 없는 몬스터"
BODY_TOKEN = "토큰"
BODY_UNKNOWN_KIND = "종류 모름"
BODY_UNKNOWN_CARD = "정체 모름"


# ======================================================================
# 기준
# ======================================================================
CRITERIA_V2: "tuple[Criterion, ...]" = (
    Criterion(
        key="field_composition",
        label_ko="자기 필드 **구성** (포함 관계로만 비교)",
        reads_ko="검증된 상태의 자기 몬스터 존·엑스트라 몬스터 존의 앞면"
                 " 카드들을 **다중집합**으로 적는다 (카드 동일성 · 종류 ·"
                 " 그 개체의 사용 기록 유무).",
        limit_ko="🔴 **장수로 견주지 않는다.** 한쪽이 다른 쪽을 포함할 때만"
                 " 앞선다고 적고, 서로 다른 몬스터로 바뀌었으면 **비교"
                 " 불가**다 — 소재로 써서 몸이 줄어든 결과를 장수 때문에"
                 " 탈락시키지 않고, 링크 소환했다는 이유로 우월하다고도"
                 " 하지 않는다. 🔴 링크 수치 · 공격력 · 행동 수는 보지"
                 " 않는다.",
        role_ko="A · 비교 축 (비교 불가 가능)",
    ),
    Criterion(
        key="kept_cards",
        label_ko="손에 쥔 채 남긴 카드 (패 + 세트)",
        reads_ko="자기 패 장수 + 자기 마법·함정 존의 뒷면 카드 수.",
        limit_ko="🔴 **세트는 패에서 사라진 것이 아닙니다** — v1 이 그렇게"
                 " 세어서 '세트한 쪽' 이 언제나 졌습니다. 반대로 세트했다는"
                 " 사실만으로 **가산점을 주지도 않습니다**.",
        role_ko="A · 비교 축",
    ),
    Criterion(
        key="summon_right_kept",
        label_ko="일반 소환권을 남겼는가",
        reads_ko="그 상태의 일반 소환권 사용 기록.",
        limit_ko="🔴 남겼다는 사실뿐이고, 쓸 곳이 있는지는 보지 않았습니다.",
        role_ko="A · 비교 축",
    ),
    Criterion(
        key="opponent_gifts",
        label_ko="상대 자리에 생긴 카드 수",
        reads_ko="상대 몬스터 존·엑스트라 몬스터 존·마법함정 존의 카드 수.",
        limit_ko="🔴 **적을수록 앞서는 축입니다.** 다만 그것이 손해라는"
                 " 증명은 아닙니다 — 상대에게 준 토큰이 이쪽 전개의 비용인"
                 " 경우가 있습니다.",
        role_ko="A · 비교 축",
    ),
    Criterion(
        key="set_reactive",
        label_ko="세트한 카드 중 **상대 턴에 쓸 수 있는 종류**",
        reads_ko="마법함정 존의 뒷면 카드 가운데 카드 정의가 함정 또는"
                 " 속공마법인 것의 수. 정의를 모르는 자리는 **세지 않고**"
                 " C 로 넘긴다.",
        limit_ko="🔴 **B(잠재)입니다 — 우열에 쓰지 않습니다.** 발동 조건도,"
                 " 지금 유효한지도, 상대가 무엇을 하는지도 보지 않았습니다."
                 " **확정 방해 수로 합산하지 않습니다.**",
        role_ko="B · 표시만",
    ),
    Criterion(
        key="use_records",
        label_ko="필드 몬스터의 **사용 기록 유무**",
        reads_ko="엔진의 사용 제한 표(개체별 · 카드명별 · 효과별)에서"
                 " **자기 좌석**의 기록만 읽어, 앞면 몬스터마다 기록이"
                 " 있는지 없는지를 센다.",
        limit_ko="🔴 **B(잠재)이고 '남은 효과 수' 가 아닙니다.** 기록이"
                 " 없다는 것은 **'지금 발동할 수 있다' 가 아닙니다** (발동"
                 " 조건 · 타이밍 · 체인을 보지 않았습니다). 기록이 있다는"
                 " 것도 **그 카드의 모든 효과가 소진됐다는 뜻이 아닙니다** —"
                 " 카드명별 제한 한 건은 그 카드명으로 쓴 제한 하나를"
                 " 말할 뿐이고, 효과마다의 제한은 효과별 표가 따로"
                 " 셉니다. 인쇄된 효과 수를 남은 횟수로 세지 않습니다.",
        role_ko="B · 표시만",
    ),
    Criterion(
        key="unknown_facts",
        label_ko="카드 정의를 읽지 못한 자리 수",
        reads_ko="필드·세트 자리 가운데 카드 정의 사실을 받지 못한 수.",
        limit_ko="🔴 **C(판단 불가)입니다.** 0 으로 메우지 않고, 그 자리는"
                 " 구성 비교에서 **동일성으로만** 다룹니다 (정체를 아는"
                 " 경우). 정체조차 가려져 있으면 그 축을 **비교 불가**로"
                 " 둡니다.",
        role_ko="C · 표시만",
    ),
    Criterion(
        key="stop",
        label_ko="이 후보가 **왜 거기서 멈췄는가**",
        reads_ko="탐색이 적어 둔 멈춤 사유 (더 갈 수 있음 · 행동 상한 ·"
                 " 깊이 상한 · 허가된 수 없음 · 미지원 남음 · 예산).",
        limit_ko="🔴 **'전개 완료' 가 아닙니다.** 턴 종료는 이 범위 밖이므로"
                 " 어느 후보도 '턴 종료까지 검증' 되지 않았습니다.",
        role_ko="C · 표시만",
    ),
)

#: 🔴 **이 평가가 판정하지 않는 것** (v2).
UNJUDGED_V2: "tuple[str, ...]" = (
    "필드에 남은 몬스터가 **무엇을 할 수 있는지** 세지 않았습니다 — 종류와"
    " 사용 기록 유무까지입니다.",
    "서로 다른 몬스터 구성 사이의 **우열은 판정하지 않습니다** — 포함"
    " 관계가 아니면 비교 불가로 남깁니다. 🔴 그래서 '더 좋은 집' 을 고르지"
    " **못한** 경우가 있고, 그때는 공동 추천이 됩니다.",
    "세트한 카드가 **실제로 발동 가능한지** 판정하지 않았습니다 — 종류가"
    " 함정·속공마법이라는 것까지입니다 (B).",
    "**남은 효과 횟수를 판정하지 않습니다** — 사용 기록이 있는지 없는지만"
    " 봅니다 (B). 기록이 없다는 것은 '지금 발동 가능' 이 아닙니다.",
    "묘지·제외에 쌓인 장수는 **자원이 거기 있다**는 사실이고, 다음 턴에"
    " 쓸 수 있다는 증명이 아닙니다. 🔴 v2 는 그 장수를 **비교 축에서"
    " 뺐습니다**.",
    "상대 방해가 없다는 전제이고, 상대 턴의 일은 판정하지 않습니다.",
    "금지·제한(금제) 적법성은 **전혀 보지 않습니다**.",
    "전투(공격력 · 표시 형식)와 라이프는 **전혀 보지 않습니다**.",
    "링크 수치 · 레벨 · 랭크 · 속성으로 우열을 가르지 않습니다.",
    "🔴 **턴 종료를 처리하지 않았습니다.** 어느 후보도 '이 턴을 끝까지"
    " 검증' 한 것이 아닙니다.",
)


# ======================================================================
# 사용 기록 읽기 (Phase 6-BE §3)
# ======================================================================
@dataclass(frozen=True, slots=True)
class UseMarks:
    """
    **자기 좌석의** 사용 기록을 열쇠별로 가른 것.

    🔴 **세 표를 합치지 않는다** (``engine.use_limit`` 의 경고). 열쇠가
    다르므로 합치면 "이 카드 1장" 과 "이 카드명 전체" 가 같은 제약이 된다.

    🔴 **상대 좌석의 기록은 들어오지 않는다** — 같은 카드명을 상대가 썼다는
    이유로 내 카드가 소진된 것처럼 세지 않는다.
    """

    instances: frozenset = frozenset()
    """``per_card`` — 이 **개체 번호**로 쓴 기록이 있다."""
    card_names: frozenset = frozenset()
    """``per_card_name`` — 이 **카드명**으로 쓴 기록이 있다 (같은 이름의
    다른 개체도 이 제한을 함께 쓴다 — 엔진의 열쇠가 ``(좌석, 카드 ID)``)."""
    effects: frozenset = frozenset()
    """``per_effect`` — ``(카드 ID, 효과 서수)`` 로 쓴 기록이 있다."""

    def touched(self, card_id, instance) -> bool:
        """이 개체에 **닿는 기록이 하나라도 있는가.** 🔴 소진 여부가 아니다."""
        if instance is not None and instance in self.instances:
            return True
        if card_id is None:
            return False
        if card_id in self.card_names:
            return True
        return any(cid == card_id for cid, _ordinal in self.effects)


def _use_marks(resources) -> UseMarks:
    """
    요약의 사용 기록을 **자기 좌석만** 골라 열쇠별로 나눈다.

    🔴 **글자를 파싱하지 않는다** — :class:`~agent.bounded_search.UseRecord`
    가 ``card_id`` · ``instance`` · ``ordinal`` 을 값으로 들고 있다
    (Phase 6-BE 가 그 칸을 더했다).
    """
    seat = getattr(resources, "seat", 0)
    instances: set = set()
    names: set = set()
    effects: set = set()
    for record in getattr(resources, "uses", ()) or ():
        if getattr(record, "seat", None) not in (None, seat):
            #: 🔴 **상대의 기록은 버린다.**
            continue
        kind = getattr(record, "kind", "")
        if kind == "card":
            found = getattr(record, "instance", None)
            if found is not None:
                instances.add(found)
        elif kind == "card_name":
            found = getattr(record, "card_id", None)
            if found is not None:
                names.add(found)
        elif kind == "effect":
            card_id = getattr(record, "card_id", None)
            ordinal = getattr(record, "ordinal", None)
            if card_id is not None and ordinal is not None:
                effects.add((card_id, ordinal))
    return UseMarks(frozenset(instances), frozenset(names), frozenset(effects))


# ======================================================================
# 센 값
# ======================================================================
@dataclass(frozen=True, slots=True)
class MeasuresV2:
    """후보 하나의 **센 값들** — A · B · C 가 섞이지 않는다. 🔴 점수가 아니다."""

    #: --- A. 비교 축 ---
    bodies: "tuple[tuple[str, int, bool], ...]"
    """
    자기 필드 구성 — ``(종류 이름, 카드 ID, 사용 기록 있음)`` 의 **정렬된
    다중집합**. 🔴 장수가 아니라 **구성**이고, 포함 관계로만 비교한다.
    """
    bodies_identified: bool
    """구성 원소의 **정체를 전부 아는가.** 거짓이면 그 축은 비교 불가다."""
    hand_left: int
    set_cards: int
    normal_summon_used: bool
    opponent_gifts: int
    #: --- A. 참고 (축 아님) ---
    spend_actions: int
    flow_actions: int
    grave_cards: int
    banished_cards: int
    extra_left: int
    deck_left: int
    limits: "tuple[tuple[str, int], ...]" = ()
    #: --- B. 잠재 (표시만) ---
    set_reactive: int = 0
    set_reactive_unjudged: int = 0
    bodies_with_use_record: int = 0
    bodies_without_use_record: int = 0
    bodies_use_unjudged: int = 0
    #: --- C. 판단 불가 (표시만) ---
    unknown_facts: int = 0
    stop: str = ""
    unsupported_here: bool = False

    @property
    def kept_cards(self) -> int:
        """🔴 **패와 세트를 같은 1장으로 센다** — 세트는 사라진 것이 아니다."""
        return self.hand_left + self.set_cards

    @property
    def summon_right_kept(self) -> bool:
        return not self.normal_summon_used

    @property
    def body_counts(self) -> "dict[str, int]":
        """종류별 장수 — 🔴 **표시용이고 비교 축이 아니다.**"""
        counts: dict[str, int] = {}
        for kind, _card_id, _touched in self.bodies:
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    @property
    def token_bodies(self) -> int:
        """토큰 수 — 🔴 표시용. 토큰을 무가치로 보지 않는다는 증거가 이 값이다."""
        return self.body_counts.get(BODY_TOKEN, 0)

    @property
    def effect_monster_bodies(self) -> int:
        """🔴 **종류에 ``EFFECT`` 가 있는** 앞면 몬스터 수 (표시용)."""
        return self.body_counts.get(BODY_EFFECT, 0)

    @property
    def finished(self) -> bool:
        """🔴 **이 범위에서 더 할 수 있는 행동이 없는가** (턴 종료는 범위 밖)."""
        return self.stop == "no_legal"

    def describe_ko(self) -> str:
        used = "사용" if self.normal_summon_used else "미사용"
        shape = " + ".join(
            f"{kind}×{count}"
            for kind, count in sorted(self.body_counts.items())
        ) or "없음"
        line = (f"[A] 필드 구성 {shape} (몸 {len(self.bodies)}) · 쥔 카드"
                f" {self.kept_cards} (패 {self.hand_left} + 세트"
                f" {self.set_cards}) · 일반 소환권 {used} · 상대 자리"
                f" {self.opponent_gifts}")
        if not self.bodies_identified:
            line += " · 🔴 정체를 모르는 자리가 있어 **구성 비교 불가**"
        line += (f" · 비흐름 행동 {self.spend_actions} (흐름"
                 f" {self.flow_actions}) · 묘지 {self.grave_cards} · 제외"
                 f" {self.banished_cards} · 엑스트라 {self.extra_left} ·"
                 f" 덱 {self.deck_left}")
        if self.limits:
            line += (" · 특수 소환 제한 "
                     + ", ".join(f"{attribute}(출처 {source})"
                                 for attribute, source in self.limits))
        line += (f" / [B 잠재, 우열에 쓰지 않음] 상대 턴에 쓸 수 있는 종류의"
                 f" 세트 {self.set_reactive}"
                 + (f" (+정의 모름 {self.set_reactive_unjudged})"
                    if self.set_reactive_unjudged else "")
                 + f" · 사용 기록 있는 몬스터 {self.bodies_with_use_record}"
                 f" · 사용 기록 없는 몬스터 {self.bodies_without_use_record}"
                 " (🔴 지금 발동 가능하다는 뜻이 아님)")
        if self.bodies_use_unjudged:
            line += f" · 판단 불가 {self.bodies_use_unjudged}"
        line += f" / [C] 카드 정의 모름 {self.unknown_facts}"
        return line


def _zone_size(resources, zone) -> "int | None":
    try:
        return int(resources.size(resources.seat, zone))
    except Exception:  # pragma: no cover - 방어용
        return None


def _body_kind(facts) -> str:
    if facts is None:
        return BODY_UNKNOWN_KIND
    if facts.is_token:
        return BODY_TOKEN
    if facts.is_effect_monster:
        return BODY_EFFECT
    return BODY_PLAIN


def measure_v2(path, resources, *, knowledge=None,
               meta=None) -> "tuple[MeasuresV2 | None, str]":
    """
    후보 하나를 센다 — ``(MeasuresV2 | None, 못 센 이유)``.

    🔴 **하나라도 읽을 수 없으면 평가 불가다.** 유리한 기본값으로 메우지
    않는다. 🔴 **카드 정의를 모르는 것은 평가 불가가 아니다** — 그것은
    C 로 세고, 구성 비교는 동일성으로 계속 돈다.
    """
    if resources is None:
        return None, "검증된 상태의 자원 요약이 없습니다."
    know = knowledge if knowledge is not None else _EMPTY_KNOWLEDGE
    try:
        field = [slot for slot in resources.own_field if slot.face_up]
    except Exception:  # pragma: no cover - 방어용
        return None, "자기 필드를 읽을 수 없습니다."
    hand = _zone_size(resources, Zone.HAND)
    if hand is None:
        return None, "자기 패 장수를 읽을 수 없습니다."
    used = getattr(resources, "normal_summon_used", None)
    if not isinstance(used, bool):
        return None, "일반 소환권 사용 기록을 읽을 수 없습니다."
    if path is None:
        return None, "경로를 읽을 수 없습니다."
    try:
        kinds = [str(step.kind) for step in path]
    except Exception:  # pragma: no cover - 방어용
        return None, "경로의 걸음 종류를 읽을 수 없습니다."
    spells = resources.zone(resources.seat, Zone.SZONE)
    if spells is None:
        return None, "자기 마법·함정 존을 읽을 수 없습니다."
    set_slots = [slot for slot in spells.cards if not slot.face_up]

    marks = _use_marks(resources)
    bodies: list[tuple[str, int, bool]] = []
    identified = True
    unknown_facts = 0
    with_use = without_use = use_unjudged = 0
    for slot in field:
        card_id = slot.card_id
        if not isinstance(card_id, int):
            #: 🔴 **정체를 모르는 자리** — 구성 비교를 포기한다 (0 으로
            #: 메우지 않는다).
            identified = False
            continue
        facts = know.get(card_id)
        if facts is None:
            unknown_facts += 1
        touched = marks.touched(card_id, getattr(slot, "instance", None))
        bodies.append((_body_kind(facts), card_id, touched))
        #: 🔴 **"기록이 없다" 를 "쓸 수 있다" 로 바꾸지 않는다.** 그리고
        #: 쓸 효과가 정의에 없거나 정의를 모르면 **판단 불가**다.
        if facts is None or facts.is_token or facts.effect_count <= 0:
            use_unjudged += 1
        elif touched:
            with_use += 1
        else:
            without_use += 1

    set_reactive = set_reactive_unjudged = 0
    for slot in set_slots:
        known_id = isinstance(slot.card_id, int)
        facts = know.get(slot.card_id) if known_id else None
        if facts is None:
            unknown_facts += 1
            set_reactive_unjudged += 1
            continue
        if facts.reactive_backrow:
            set_reactive += 1

    their = getattr(resources, "their_field", ())
    flow = sum(1 for kind in kinds if kind in FLOW_ACTION_KINDS)
    stop = getattr(getattr(meta, "stop", None), "value", "") or ""
    return MeasuresV2(
        bodies=tuple(sorted(bodies)),
        bodies_identified=identified,
        hand_left=hand,
        set_cards=len(set_slots),
        normal_summon_used=used,
        opponent_gifts=len(their),
        spend_actions=len(kinds) - flow,
        flow_actions=flow,
        grave_cards=_zone_size(resources, Zone.GRAVE) or 0,
        banished_cards=_zone_size(resources, Zone.REMOVED) or 0,
        extra_left=_zone_size(resources, Zone.EXTRA) or 0,
        deck_left=_zone_size(resources, Zone.DECK) or 0,
        limits=tuple(getattr(resources, "own_limits", ())),
        set_reactive=set_reactive,
        set_reactive_unjudged=set_reactive_unjudged,
        bodies_with_use_record=with_use,
        bodies_without_use_record=without_use,
        bodies_use_unjudged=use_unjudged,
        unknown_facts=unknown_facts,
        stop=stop,
        unsupported_here=(stop == "unsupported_left"),
    ), ""


# ======================================================================
# 비교
# ======================================================================
class Comparison(str, Enum):
    """
    두 후보의 관계 — 🔴 **네 가지를 한 칸으로 뭉치지 않는다.**

    ``TIE`` 와 ``INCOMPARABLE`` 을 섞으면 "같다" 와 "모른다" 가 같은 말이
    된다 (Phase 6-BE §2).
    """

    LEFT = "left"
    """왼쪽이 앞선다 (지배)."""
    RIGHT = "right"
    """오른쪽이 앞선다 (지배)."""
    TIE = "tie"
    """모든 축에서 같다 — **비교했고 같다.**"""
    INCOMPARABLE = "incomparable"
    """🔴 **비교할 근거가 없다** — 같다는 뜻이 아니다."""


def _axis_order(mine: int, theirs: int) -> int:
    return (mine > theirs) - (mine < theirs)


def _body_axis(left: MeasuresV2, right: MeasuresV2) -> "int | None":
    """
    필드 구성 축 — ``1`` / ``0`` / ``-1``, 비교 불가면 ``None``.

    🔴 **포함 관계만 본다.** 한쪽이 다른 쪽의 모든 원소를 가지고 있으면
    그쪽이 앞선다(또는 같다). 서로 다른 몬스터로 바뀌었으면 ``None`` 이다 —
    장수로 억지로 줄 세우지 않는다.
    """
    if not (left.bodies_identified and right.bodies_identified):
        return None
    mine, theirs = Counter(left.bodies), Counter(right.bodies)
    if mine == theirs:
        return 0
    #: ``Counter`` 의 뺄셈은 음수를 버리므로 **빠진 것**만 남는다.
    missing_from_mine = theirs - mine
    missing_from_theirs = mine - theirs
    if not missing_from_mine:
        return 1
    if not missing_from_theirs:
        return -1
    return None


def compare_v2(left: MeasuresV2, right: MeasuresV2) -> Comparison:
    """
    두 후보를 **A 축으로만** 견준다.

    🔴 **B 와 C 는 들어오지 않는다.** 🔴 **한 축이라도 비교 불가면
    ``INCOMPARABLE``** 이고, 그러면 지배 관계를 확정하지 않는다 — 정보
    부족을 "같다" 로도, "진다" 로도 바꾸지 않는다.
    """
    orders: list[int] = []
    body = _body_axis(left, right)
    if body is None:
        return Comparison.INCOMPARABLE
    orders.append(body)
    orders.append(_axis_order(left.kept_cards, right.kept_cards))
    orders.append(_axis_order(int(left.summon_right_kept),
                              int(right.summon_right_kept)))
    #: 상대 자리는 **적을수록 앞선다** — 부호를 뒤집어 한 규칙으로 센다.
    orders.append(_axis_order(-left.opponent_gifts, -right.opponent_gifts))
    if all(order == 0 for order in orders):
        return Comparison.TIE
    if all(order >= 0 for order in orders):
        return Comparison.LEFT
    if all(order <= 0 for order in orders):
        return Comparison.RIGHT
    return Comparison.INCOMPARABLE


#: 🔴 **후속을 한 번도 탐색받지 못한 기준점**에 적는 말 (Phase 6-BE §4).
UNEXPLORED_NOTE: str = (
    "🔴 **이 자리는 기준점이고, 후속 행동을 한 번도 탐색받지 못했습니다** —"
    " 지배당한 것도, 재생이 실패한 것도 아닙니다. 탐색이 **가 보지 않은**"
    " 자리이므로 추천으로 내놓지 않습니다 (경로는 그대로 남습니다)."
)


def _path_signature(path) -> tuple:
    """
    경로를 값으로 — 🔴 **해결 중 선택까지** 넣는다.

    행동만 보면 같은 행동에서 다른 카드를 고른 변형이 **같은 경로**로
    읽히고, 그러면 "이 기준점의 후속" 을 셀 수 없다 (실측으로 그렇게
    셌다가 다섯 변형이 모두 20 개 후속을 가진 것처럼 나왔다).
    """
    try:
        return tuple(
            (step.action_key, tuple(ask.chosen for ask in step.choices))
            for step in path
        )
    except Exception:  # pragma: no cover - 방어용
        return ()


def _unexplored_stubs(items) -> "frozenset[int]":
    """
    **기준점뿐이고 후속이 탐색되지 않은** 자리들 (Phase 6-BE §4).

    ``items`` 는 ``(열쇠, 경로, 메타)`` 들이다. 어느 다른 경로도 이 경로를
    **접두사로 연장하지 않았고**, 그 자리에서 할 행동이 남아 있었으면
    (``stop`` 이 ``open``) 탐색이 가 보지 않은 자리다.

    🔴 **"더 할 수 없어 멈춘 자리" 와 가른다** — 그쪽은 ``stop`` 이
    ``no_legal`` · ``unsupported_left`` 이고 여기 들어오지 않는다.
    """
    signatures = [(key, _path_signature(path), meta)
                  for key, path, meta in items]
    out: set = set()
    for key, mine, meta in signatures:
        if meta is None:
            continue
        role = getattr(getattr(meta, "role", None), "value", "")
        if role != "first_arrival":
            continue
        if getattr(meta, "followup_actions", 0):
            continue
        if getattr(getattr(meta, "stop", None), "value", "") != "open":
            #: 🔴 더 할 수 없어 멈춘 기준점은 **가 보지 않은 자리가 아니다.**
            continue
        extended = any(
            other[:len(mine)] == mine and len(other) > len(mine)
            for _key2, other, _meta2 in signatures if other != mine
        )
        if not extended:
            out.add(key)
    return frozenset(out)


def _display_key(measures: MeasuresV2) -> tuple:
    """
    표시 순서 — 🔴 **점수가 아니다.** 우열은 :func:`compare_v2` 가 가리고,
    이 열쇠는 **같은 등급 안에서 무엇을 먼저 보여 줄지**만 정한다.
    """
    return (-len(measures.bodies), -measures.kept_cards,
            -int(measures.summon_right_kept), measures.opponent_gifts,
            measures.spend_actions)


def core_key(measures: MeasuresV2) -> tuple:
    """
    **핵심 전개**를 값으로 (Phase 6-BE §5).

    🔴 세트 유무·세트한 카드는 **들어오지 않는다** — 같은 몬스터 필드에
    세트만 다른 변형들이 재생 검증 슬롯을 전부 차지하는 일을 막으려고
    가른 열쇠다. 🔴 **그렇다고 그 차이를 지우지 않는다** —
    :func:`variant_key` 가 그대로 들고 있고, 보고도 그대로 적는다.

    🔴 **다양성은 재생 예산 배분 정책이고, 강함의 근거가 아니다.**
    """
    return (measures.bodies, measures.grave_cards, measures.banished_cards,
            measures.extra_left, measures.normal_summon_used,
            measures.opponent_gifts)


def variant_key(resources, measures: MeasuresV2) -> tuple:
    """
    같은 핵심 전개 안에서 **무엇이 다른가**를 값으로.

    🔴 세트한 카드의 **정체와 자리**, 패 장수, 사용 기록 유무를 그대로
    들고 있다 — 중요한 차이를 지우지 않는다. 같은 집에 **순서만 다른**
    변형은 같은 열쇠가 된다 (정렬한 다중집합이므로).
    """
    try:
        spells = resources.zone(resources.seat, Zone.SZONE)
        backs = tuple(sorted(
            (slot.card_id, slot.sequence if hasattr(slot, "sequence") else 0)
            for slot in (spells.cards if spells else ())
            if not slot.face_up
        ))
    except Exception:  # pragma: no cover - 방어용
        backs = ("unknown",)
    return (core_key(measures), backs, measures.hand_left,
            measures.bodies_with_use_record)


def select_top_v2(pool, count: int, *, knowledge=None) -> "frozenset[int]":
    """
    모아 둔 후보 풀에서 **재생할 자리 번호**를 고른다 (v2).

    🔴 **추천과 같은 기준으로 고른다** (:func:`compare_v2`) — 정보 부족
    처리도 같다. 재생 대상을 다른 기준으로 고르면 "검증된 것 중에서 추천"
    이라는 계약이 평가와 어긋난다.

    🔴 **배분 순서** (§5): ① 지배당하지 않은 후보를 **핵심 전개마다 하나**
    → ② 아직 자리가 남으면 지배당하지 않은 나머지(변형이 다른 것) →
    ③ 핵심 전개가 다른 나머지 → ④ 남은 것. 🔴 **평가가 불확실한 후보**
    (비교 불가로 남은 것)는 ① 에 들어온다 — 아무에게도 지배당하지 않았기
    때문이다.

    🔴 **고르지 않은 후보를 버리지 않는다.** 재생만 하지 않을 뿐이고, 경로는
    결과에 그대로 남는다 (``RerunState.NOT_SELECTED``).
    """
    want = max(1, int(count))
    rows = []
    stub_items = []
    for slot, item in enumerate(pool):
        path, resources = item[0], item[1]
        meta = item[3] if len(item) > 3 else None
        stub_items.append((slot, path, meta))
        measures, _why = measure_v2(path, resources, knowledge=knowledge,
                                    meta=meta)
        if measures is None:
            continue
        rows.append((slot, measures, core_key(measures),
                     variant_key(resources, measures)))
    if not rows:
        return frozenset(range(min(len(pool), want)))
    #: 🔴 **탐색이 가 보지 않은 기준점은 마지막 순서로 둔다** (§4) — 버리지
    #: 않는다. 자리가 남으면 그때 검증받는다.
    stubs = _unexplored_stubs(stub_items)
    best = {
        slot for slot, mine, _core, _variant in rows
        if not any(compare_v2(other, mine) is Comparison.LEFT
                   for slot2, other, _c2, _v2 in rows if slot2 != slot)
    }
    ordered = sorted(rows, key=lambda row: (row[0] in stubs,
                                            _display_key(row[1]), row[0]))

    chosen: list[int] = []
    cores: set = set()
    variants: set = set()

    def _take(only_best: bool, new_core: bool, new_variant: bool) -> None:
        for slot, _m, core, variant in ordered:
            if len(chosen) >= want:
                return
            if slot in chosen:
                continue
            if only_best and slot not in best:
                continue
            if new_core and core in cores:
                continue
            if new_variant and variant in variants:
                continue
            chosen.append(slot)
            cores.add(core)
            variants.add(variant)

    _take(True, True, True)
    _take(True, False, True)
    _take(False, True, True)
    _take(False, False, True)
    _take(False, False, False)
    return frozenset(chosen)


# ======================================================================
# 추천
# ======================================================================
@dataclass(frozen=True, slots=True)
class RankingV2:
    """한 자율 탐색 실행의 **추천 전부** (v2). v1 과 **같은 모양**을 내놓는다."""

    policy: str = POLICY_NAME_V2
    version: str = POLICY_VERSION_V2
    criteria: "tuple[Criterion, ...]" = CRITERIA_V2
    unjudged: "tuple[str, ...]" = UNJUDGED_V2
    candidates: "tuple[OpenCandidate, ...]" = ()
    note: str = ""
    incomparable: "dict | None" = None
    """🔴 **어느 후보와 비교할 수 없었는가** — 같다는 뜻이 아니다."""
    unexplored: "tuple[int, ...]" = ()
    """🔴 **후속을 한 번도 탐색받지 못한 기준점**들 (Phase 6-BE §4)."""

    @property
    def policy_label(self) -> str:
        return f"{self.policy} {self.version}"

    @property
    def eligible_candidates(self) -> "tuple[OpenCandidate, ...]":
        return tuple(one for one in self.candidates if one.eligible)

    @property
    def excluded(self) -> "tuple[OpenCandidate, ...]":
        return tuple(one for one in self.candidates if not one.eligible)

    @property
    def recommended(self) -> "tuple[OpenCandidate, ...]":
        """지배당하지 않은 후보들 — 표시 순서대로. 🔴 여럿이면 **공동 추천**."""
        return tuple(sorted(
            (one for one in self.candidates if one.recommended),
            key=lambda one: (one.order, one.index),
        ))

    @property
    def has_recommendation(self) -> bool:
        return bool(self.recommended)

    def candidate(self, index: int) -> "OpenCandidate | None":
        for one in self.candidates:
            if one.index == index:
                return one
        return None

    def reason_ko(self, index: int) -> str:
        """그 후보가 **왜 추천인가 / 왜 빠졌는가.**"""
        one = self.candidate(index)
        if one is None:
            return f"결과 {index} 를 찾지 못했습니다."
        if one.rerun_state == RerunState.NOT_SELECTED.value:
            return ("평가 상위에 들지 못해 재생하지 않았습니다 — 🔴 재생"
                    " 실패가 아니고, 경로는 그대로 남아 있습니다.")
        if one.exclusion is Exclusion.NOT_VERIFIED:
            return (f"재생 검증을 통과하지 못해 비교에서 뺐습니다"
                    f" (재생 상태 {one.rerun_state}). 🔴 경로 자체는"
                    f" 그대로 남아 있습니다.")
        if one.exclusion is Exclusion.UNMEASURABLE:
            return f"평가에 필요한 값을 읽지 못했습니다 — {one.unmeasurable_reason}"
        if one.measures is None:
            return "센 값이 없습니다."
        if one.index in self.unexplored:
            return UNEXPLORED_NOTE + " " + one.measures.describe_ko()
        unknown = (self.incomparable or {}).get(one.index, ())
        if one.nondominated:
            head = ("네 축(필드 구성 · 쥔 카드 · 일반 소환권 · 상대 자리)"
                    " 에서 **어느 후보에게도 지배당하지 않았습니다** — ")
            if unknown:
                head += (
                    "🔴 다만 결과 "
                    + ", ".join(str(other) for other in unknown)
                    + " 와는 **비교 불가**입니다 (필드 구성이 서로 바뀌어"
                    " 포함 관계가 아닙니다 — 같다는 뜻이 아니고 현재"
                    " 기준으로 **우열 불명**입니다). "
                )
            return head + one.measures.describe_ko()
        beaten = ", ".join(f"결과 {other}" for other in one.dominated_by)
        tail = ""
        if unknown:
            tail = (" 🔴 결과 "
                    + ", ".join(str(other) for other in unknown)
                    + " 와는 **비교 불가**입니다.")
        return (f"{beaten} 가 네 축 모두에서 뒤지지 않고 적어도 하나에서"
                f" 앞섭니다 — " + one.measures.describe_ko() + tail)

    def stop_note_ko(self, index: int) -> str:
        """🔴 **그 후보가 전개 완료인가** — 멈춘 이유를 그대로 적는다."""
        one = self.candidate(index)
        if one is None or one.measures is None:
            return ""
        return _STOP_NOTE.get(one.measures.stop, "")


#: 🔴 **멈춘 이유를 '완성' 으로 바꾸지 않는다** (§4).
_STOP_NOTE: dict = {
    "open": "🔴 **전개 완료가 아닙니다** — 이 자리에서 엔진이 허가한 행동이"
            " 아직 남아 있고, 예산이 끊겨 여기까지만 보았습니다.",
    "action_cap": "⏹ 후속 행동 상한에 닿아 멈췄습니다 — 🔴 더 할 수 없다는"
                  " 뜻이 아닙니다.",
    "depth_cap": "⏹ 깊이 상한에 닿아 멈췄습니다 (🔴 후속 행동 상한과 다른"
                 " 상한입니다).",
    "budget": "⏹ 전체 예산이 끊어 끝까지 보지 못했습니다.",
    "no_legal": "⏹ 이 범위(같은 턴 메인 페이즈)에서 엔진이 허가한 수가 더"
                " 없습니다 — 🔴 **턴 종료를 처리한 것이 아닙니다.**",
    "unsupported_left": "🔴 허가된 수는 없지만 **지원하지 않아 후보가 되지"
                        " 못한 수가 남아 있습니다** — 더 할 수 없다는 뜻이"
                        " 아닙니다 (C).",
}


def rank_open_v2(outcome, *, knowledge=None) -> "RankingV2 | None":
    """
    자율 탐색의 **검증된 결과**를 견주고 추천 후보를 고른다 (v2).

    🔴 **받은 것을 바꾸지 않는다.** 🔴 **검증된 결과만 추천 대상**이고,
    나머지는 원래 사유와 함께 남는다.
    """
    if outcome is None:
        return None
    results = tuple(getattr(outcome, "results", ()) or ())
    rows: list[OpenCandidate] = []
    measured: dict[int, MeasuresV2] = {}
    for result in results:
        state = getattr(result.rerun_state, "value", str(result.rerun_state))
        if not result.verified:
            rows.append(OpenCandidate(
                index=result.index, verified=False, rerun_state=state,
                exclusion=(
                    Exclusion.UNMEASURABLE
                    if result.rerun_state is RerunState.NOT_SELECTED
                    else Exclusion.NOT_VERIFIED
                ),
                unmeasurable_reason=(
                    "평가 상위에 들지 못해 재생하지 않았습니다 — 🔴 재생"
                    " 실패가 아니고, 경로는 그대로 남아 있습니다."
                    if result.rerun_state is RerunState.NOT_SELECTED else ""
                ),
            ))
            continue
        measures, why = measure_v2(result.path, result.resources,
                                   knowledge=knowledge, meta=result.meta)
        if measures is None:
            rows.append(OpenCandidate(
                index=result.index, verified=True, rerun_state=state,
                exclusion=Exclusion.UNMEASURABLE, unmeasurable_reason=why,
            ))
            continue
        measured[result.index] = measures
        rows.append(OpenCandidate(index=result.index, verified=True,
                                  rerun_state=state, measures=measures))

    #: 🔴 **탐색이 가 보지 않은 기준점**을 가린다 (§4).
    stubs = _unexplored_stubs([
        (result.index, result.path, result.meta) for result in results
    ])
    unknown_pairs: dict[int, tuple[int, ...]] = {}
    final: list[OpenCandidate] = []
    for one in rows:
        if one.index not in measured:
            final.append(one)
            continue
        mine = measured[one.index]
        beaten_by: list[int] = []
        unsure: list[int] = []
        for other, theirs in measured.items():
            if other == one.index:
                continue
            verdict = compare_v2(theirs, mine)
            if verdict is Comparison.LEFT:
                beaten_by.append(other)
            elif verdict is Comparison.INCOMPARABLE:
                unsure.append(other)
        if unsure:
            unknown_pairs[one.index] = tuple(sorted(unsure))
        final.append(OpenCandidate(
            index=one.index, verified=True, rerun_state=one.rerun_state,
            measures=mine, nondominated=not beaten_by,
            dominated_by=tuple(sorted(beaten_by)),
        ))

    #: 🔴 **가 보지 않은 기준점을 추천으로 내놓지 않는다** — 다만 **탐색된
    #: 후보가 하나라도 추천에 있을 때만** 뺀다. 전부 가 보지 않은 자리면
    #: 그대로 내놓고 그 사실을 적는다 (아무것도 추천하지 않으면 사용자가
    #: 무엇을 본 것인지 알 수 없다).
    held_back: list[int] = []
    explored_best = [
        one for one in final
        if one.recommended and one.index not in stubs
    ]
    if explored_best:
        shelved: list[OpenCandidate] = []
        for one in final:
            if one.recommended and one.index in stubs:
                held_back.append(one.index)
                shelved.append(OpenCandidate(
                    index=one.index, verified=one.verified,
                    rerun_state=one.rerun_state, measures=one.measures,
                    exclusion=one.exclusion,
                    unmeasurable_reason=one.unmeasurable_reason,
                    nondominated=False, dominated_by=one.dominated_by,
                ))
            else:
                shelved.append(one)
        final = shelved

    order = sorted(
        (one for one in final if one.measures is not None),
        key=lambda one: (_display_key(one.measures), one.index),
    )
    places = {one.index: place for place, one in enumerate(order, start=1)}
    final = [
        OpenCandidate(
            index=one.index, verified=one.verified,
            rerun_state=one.rerun_state, measures=one.measures,
            exclusion=one.exclusion,
            unmeasurable_reason=one.unmeasurable_reason,
            nondominated=one.nondominated, dominated_by=one.dominated_by,
            order=places.get(one.index, 0),
        )
        for one in final
    ]
    note = ""
    if not measured:
        note = ("검증된 결과가 없어 비교하지 않았습니다 — 🔴 경로는 그대로"
                " 남아 있습니다.")
    elif len(measured) == 1:
        note = "검증된 결과가 하나뿐이라 비교할 상대가 없습니다."
    recommended = [one for one in final if one.recommended]
    if len(recommended) > 1:
        note = (note + " " if note else "") + (
            f"🔴 **공동 추천 {len(recommended)}개** — 네 축으로는 우열이"
            " 가려지지 않았습니다 (동률이거나 **비교 불가**). 억지로 하나로"
            " 줄이지 않았습니다."
        )
    if unknown_pairs:
        note = (note + " " if note else "") + (
            f"🔴 **비교 불가 쌍이 {len(unknown_pairs)}개 후보에 있습니다** —"
            " 필드 구성이 서로 바뀌어 포함 관계가 아닌 경우입니다. 🔴 같다는"
            " 뜻이 아니고, **현재 기준으로 우열을 판정하지 못했다**는"
            " 뜻입니다."
        )
    if held_back:
        note = (note + " " if note else "") + (
            f"🔴 **기준점 {len(held_back)}개는 추천에서 보류했습니다** —"
            " 후속 행동을 한 번도 탐색받지 못한 자리입니다 (지배당한 것도,"
            " 실패한 것도 아닙니다)."
        )
    return RankingV2(candidates=tuple(final), note=note,
                     incomparable=unknown_pairs,
                     unexplored=tuple(sorted(held_back)))
