"""
자율 탐색 결과의 비교와 추천 — **open-development v2** (Phase 6-BD).

왜 v2 인가
----------
v1 (:mod:`agent.open_evaluation`) 은 세 축으로 견줬다 — 필드 앞면 몬스터
수 · 남은 패 장수 · 일반 소환권. 실사용에서 그 세 축이 **장수만으로 우열을
확정**한다는 것이 드러났다:

* **패에서 세트 존으로 옮긴 카드가 사라진 것으로 세졌다.** 마법·함정을
  세트하면 ``hand_left`` 가 1 줄고 ``set_cards`` 는 비교 축이 아니므로,
  "세트한 쪽" 이 언제나 "세트하지 않은 쪽" 에 **지배당했다.**
* **토큰과 효과 몬스터를 같은 1장으로 셌다.**
* **상대에게 준 토큰**은 어느 축에도 없었다.

🔴 **v1 을 지우지 않는다.** v1 은 그대로 남아 비교 기준이 된다
(:mod:`agent.open_evaluation`). 이 모듈은 **다른 정책**이고, 어느 것을
쓸지는 부르는 쪽이 고른다.

무엇을 세고 무엇을 세지 않는가 — A · B · C
-------------------------------------------
🔴 **근거의 종류를 섞지 않는다.** 섞으면 "카드 정의에 효과가 있다" 가
"확정 방해 1회" 로 읽힌다.

**A. 확인된 것** — 지금 상태와 **구현된 판정**이 말하는 자원·행동.
  장수, 일반 소환권, 엔진이 적어 둔 사용 기록, 걸린 특수 소환 제한,
  상대 자리에 생긴 것. 🔴 **우열 판정에 쓰는 것은 A 뿐이다.**

**B. 잠재 가치** — 카드 **정의**에서 알 수 있지만 **실제로 쓸 수 있는지는
  검증하지 못한** 것. 세트한 카드가 함정·속공마법이라는 사실, 필드 몬스터의
  정의된 효과를 이번 턴 아직 쓰지 않았다는 사실. 🔴 **표시만 하고 우열에
  쓰지 않는다.** 확정 방해 수로 합산하지 않는다.

**C. 판단 불가** — 엔진이 지원하지 않아 **후보조차 되지 못한** 수, 그리고
  그 자리에서 멈춘 이유. 🔴 **가치 0 으로 단정하지 않는다.** 미지원이 남은
  후보를 "더 할 것이 없는 완성" 으로도, "실패" 로도 적지 않는다.

🔴 **카드 이름도 정답 필드도 없다.** 이 모듈에 카드 ID 리터럴이 없고, 카드
이름별 점수표도 없다 — 센 것은 장수와 엔진 기록, 그리고 부르는 쪽이 카드
정의에서 읽어 넘겨 준 **종류 사실**뿐이다 (:class:`CardFacts`).

경계 (ADR-007)
--------------
``engine`` 과 ``agent`` 만 import 한다. 카드 저장소를 모른다 — 카드 정의
사실은 어댑터가 :class:`CardFacts` 로 바꿔 넘긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.vocabulary import Zone

from agent.bounded_search import FLOW_ACTION_KINDS, RerunState
from agent.open_evaluation import OpenCandidate
from agent.result_ranking import Criterion, Exclusion

__all__ = [
    "CRITERIA_V2",
    "CardFacts",
    "MeasuresV2",
    "POLICY_NAME_V2",
    "POLICY_SCOPE_NOTE_V2",
    "POLICY_VERSION_V2",
    "RankingV2",
    "UNJUDGED_V2",
    "diversity_key",
    "measure_v2",
    "rank_open_v2",
    "select_top_v2",
]

POLICY_NAME_V2: str = "open-development"
POLICY_VERSION_V2: str = "v2"

POLICY_SCOPE_NOTE_V2: str = (
    "목표 카드를 지정하지 않은 자율 탐색에서 **예산 안에 모은 후보**끼리의"
    " 비교입니다 — 🔴 전역 최적 전개도, 실전 최강도, 승률 평가도 아닙니다."
    " 🔴 **우열은 '확인된 것(A)' 으로만 가립니다**; 카드 정의로만 아는"
    " 잠재 가치(B)와 엔진이 판단하지 못한 것(C)은 **표시만** 하고 순서에"
    " 쓰지 않습니다."
)


# ======================================================================
# 카드 정의 사실 — 어댑터가 넘겨 준다
# ======================================================================
@dataclass(frozen=True, slots=True)
class CardFacts:
    """
    카드 **한 장의 정의**에서 읽은 사실들 (Phase 6-BD).

    🔴 **판정이 아니다.** "지금 발동할 수 있다" 도 "강하다" 도 아니고,
    카드 종류와 인쇄된 효과 수뿐이다. 지금 쓸 수 있는지는 ``legal_actions``
    의 일이고 이 모듈은 그것을 보지 않는다.

    🔴 **모르면 ``None`` 이다.** 저장소에 없는 카드, 가려진 카드는
    :meth:`CardKnowledge.get` 이 ``None`` 을 돌려주고, 그러면 이 모듈은
    **C(판단 불가)** 로 센다 — 0 으로 메우지 않는다.
    """

    is_token: bool = False
    """토큰인가. 🔴 **무가치라는 뜻이 아니다** — 소재 조건을 만족하면 링크
    소재로 쓸 수 있고, 실제로 그렇게 쓰인 경로가 탐색에 있다. 여기서는
    효과 몬스터와 **같은 1장으로 합치지 않기 위해** 가른다."""
    reactive_backrow: bool = False
    """세트해 두면 **상대 턴에 쓸 수 있는 종류**인가 (함정 · 속공마법).
    🔴 **확정 방해가 아니다** — 발동 조건도, 지금 유효한지도 보지 않았다."""
    effect_count: int = 0
    """인쇄된 효과 수. 🔴 **남은 효과 수가 아니다.**"""
    is_monster: bool = False
    is_extra_deck: bool = False


class CardKnowledge:
    """
    ``get(card_id) -> CardFacts | None`` 하나만 요구하는 자리.

    🔴 **비어 있어도 돈다.** 아무것도 모르면 모든 B 값이 "판단 불가" 로
    남고, A 축은 그대로 돈다 — 카드 정의를 모른다고 해서 비교가 멈추지
    않는다.
    """

    def __init__(self, facts: "dict[int, CardFacts] | None" = None) -> None:
        self._facts = dict(facts or {})

    def get(self, card_id) -> "CardFacts | None":
        return self._facts.get(card_id)


_EMPTY_KNOWLEDGE = CardKnowledge()


# ======================================================================
# 기준
# ======================================================================
CRITERIA_V2: "tuple[Criterion, ...]" = (
    Criterion(
        key="effect_bodies",
        label_ko="필드에 남은 **효과 몬스터** 수 (토큰 제외)",
        reads_ko="검증된 상태의 자기 몬스터 존·엑스트라 몬스터 존의 앞면"
                 " 카드 중 토큰이 아닌 것의 수.",
        limit_ko="🔴 **장수뿐입니다.** 그 몬스터가 지금 무엇을 할 수 있는지,"
                 " 공격력이 얼마인지, 상대 턴에 쓸 효과가 있는지 세지"
                 " 않았습니다. 토큰이 아니라는 사실만 가렸습니다.",
        role_ko="A · 비교 축",
    ),
    Criterion(
        key="token_bodies",
        label_ko="필드에 남은 **토큰** 수",
        reads_ko="같은 자리의 앞면 카드 중 토큰인 것의 수.",
        limit_ko="🔴 **따로 셉니다.** 토큰을 무가치로 보지 않습니다 — 소재"
                 " 조건을 만족하면 링크 소재로 쓸 수 있습니다. 다만 효과"
                 " 몬스터와 **같은 1장으로 합치지도** 않습니다.",
        role_ko="A · 비교 축",
    ),
    Criterion(
        key="kept_cards",
        label_ko="손에 쥔 채 남긴 카드 (패 + 세트)",
        reads_ko="자기 패 장수 + 자기 마법·함정 존의 뒷면 카드 수.",
        limit_ko="🔴 **세트는 패에서 사라진 것이 아닙니다** — v1 이 그렇게"
                 " 세어서 '세트한 쪽' 이 언제나 졌습니다. 반대로 세트했다는"
                 " 사실만으로 **가산점을 주지도 않습니다**: 두 장소의 카드를"
                 " 같은 1장으로 셀 뿐이고, 어느 쪽이 쓸모 있는지는 이"
                 " 축이 말하지 않습니다.",
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
                 " 경우가 있습니다. 세는 이유는 **어느 축에도 없어서 아예"
                 " 보이지 않던 것**을 보이게 하려는 것입니다.",
        role_ko="A · 비교 축",
    ),
    Criterion(
        key="set_reactive",
        label_ko="세트한 카드 중 **상대 턴에 쓸 수 있는 종류**",
        reads_ko="마법함정 존의 뒷면 카드 가운데 카드 정의가 함정 또는"
                 " 속공마법인 것의 수.",
        limit_ko="🔴 **B(잠재)입니다 — 우열에 쓰지 않습니다.** 발동 조건도,"
                 " 지금 유효한지도, 상대가 무엇을 하는지도 보지 않았습니다."
                 " **확정 방해 수로 합산하지 않습니다.**",
        role_ko="B · 표시만",
    ),
    Criterion(
        key="unused_effect_bodies",
        label_ko="효과를 **아직 쓰지 않은** 필드 몬스터 수",
        reads_ko="앞면 비토큰 몬스터 가운데, 카드 정의에 효과가 있고 그"
                 " 개체·그 카드 ID 의 사용 기록이 엔진에 **없는** 것의 수.",
        limit_ko="🔴 **B(잠재)입니다 — 우열에 쓰지 않습니다.** '쓰지 않았다'"
                 " 는 '지금 쓸 수 있다' 가 아닙니다 (발동 조건·타이밍을 보지"
                 " 않았습니다). 사용 기록이 있는 쪽을 '효과가 없다' 로 적지"
                 " 않으려고 가른 값입니다.",
        role_ko="B · 표시만",
    ),
    Criterion(
        key="unknown_cards",
        label_ko="카드 정의를 읽지 못한 자리 수",
        reads_ko="필드·세트 자리 가운데 카드 정의 사실을 받지 못한 수"
                 " (가려진 카드, 저장소에 없는 ID).",
        limit_ko="🔴 **C(판단 불가)입니다.** 0 으로 메우지 않고, 그렇다고"
                 " 그 후보를 실패로도 적지 않습니다.",
        role_ko="C · 표시만",
    ),
    Criterion(
        key="stop",
        label_ko="이 후보가 **왜 거기서 멈췄는가**",
        reads_ko="탐색이 적어 둔 멈춤 사유 (더 갈 수 있음 · 행동 상한 ·"
                 " 깊이 상한 · 허가된 수 없음 · 미지원 남음 · 예산).",
        limit_ko="🔴 **'전개 완료' 가 아닙니다.** 더 갈 수 있는 자리에서"
                 " 멈춘 후보와, 이 범위에서 더 할 수 없는 후보를 **같은"
                 " 최종 필드로 적지 않습니다.** 턴 종료는 이 범위 밖이므로"
                 " 어느 후보도 '턴 종료까지 검증' 되지 않았습니다.",
        role_ko="C · 표시만",
    ),
)

#: 🔴 **이 평가가 판정하지 않는 것** (v2).
UNJUDGED_V2: "tuple[str, ...]" = (
    "필드에 남은 몬스터가 **무엇을 할 수 있는지** 세지 않았습니다 — 토큰과"
    " 효과 몬스터를 가르고, 효과를 이미 썼는지를 가를 뿐입니다.",
    "세트한 카드가 **실제로 발동 가능한지** 판정하지 않았습니다 — 종류가"
    " 함정·속공마법이라는 것까지입니다 (B).",
    "묘지·제외에 쌓인 장수는 **자원이 거기 있다**는 사실이고, 다음 턴에"
    " 쓸 수 있다는 증명이 아닙니다. 🔴 v2 는 그 장수를 **비교 축에서"
    " 뺐습니다** — 셀 근거가 없는 값으로 우열을 가르지 않기 위해서입니다.",
    "상대 방해가 없다는 전제이고, 상대 턴의 일은 판정하지 않습니다.",
    "금지·제한(금제) 적법성은 **전혀 보지 않습니다**.",
    "전투(공격력·표시 형식)와 라이프는 **전혀 보지 않습니다**.",
    "링크 수치·레벨·속성으로 우열을 가르지 않습니다 — 세는 것은 장수와"
    " 종류뿐입니다.",
    "🔴 **턴 종료를 처리하지 않았습니다.** 어느 후보도 '이 턴을 끝까지"
    " 검증' 한 것이 아닙니다.",
)


# ======================================================================
# 세기
# ======================================================================
def _zone_size(resources, zone) -> "int | None":
    try:
        return int(resources.size(resources.seat, zone))
    except Exception:  # pragma: no cover - 방어용
        return None


def _used_marks(resources) -> "tuple[frozenset, frozenset]":
    """엔진이 적어 둔 사용 기록을 ``(개체 번호, 카드 ID)`` 로 가른다."""
    instances: set = set()
    card_ids: set = set()
    for record in getattr(resources, "uses", ()) or ():
        kind = getattr(record, "kind", "")
        label = str(getattr(record, "label", ""))
        if kind == "card" and label.startswith("#"):
            try:
                instances.add(int(label[1:]))
            except ValueError:  # pragma: no cover - 방어용
                continue
        elif kind == "effect" and ":e[" in label:
            try:
                card_ids.add(int(label.split(":e[", 1)[0]))
            except ValueError:  # pragma: no cover - 방어용
                continue
    return frozenset(instances), frozenset(card_ids)


@dataclass(frozen=True, slots=True)
class MeasuresV2:
    """후보 하나의 **센 값들** — A · B · C 가 섞이지 않는다. 🔴 점수가 아니다."""

    #: --- A. 확인된 것 (비교 축) ---
    effect_bodies: int
    token_bodies: int
    hand_left: int
    set_cards: int
    normal_summon_used: bool
    opponent_gifts: int
    #: --- A. 확인된 것 (참고, 축 아님) ---
    spend_actions: int
    flow_actions: int
    grave_cards: int
    banished_cards: int
    extra_left: int
    deck_left: int
    limits: "tuple[tuple[str, int], ...]" = ()
    #: --- B. 잠재 (표시만) ---
    set_reactive: int = 0
    unused_effect_bodies: int = 0
    #: --- C. 판단 불가 (표시만) ---
    unknown_cards: int = 0
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
    def axes(self) -> "tuple[int, int, int, int, int]":
        """
        🔴 **비교에 쓰는 다섯 축 (A 뿐)** — 나머지는 참고와 표시다.

        마지막 축은 **적을수록 좋은 값**이라 음수로 뒤집어 둔다. 그래야
        지배 판정이 "모두 크거나 같고 하나가 크다" 하나로 끝난다.
        """
        return (self.effect_bodies, self.token_bodies, self.kept_cards,
                int(self.summon_right_kept), -self.opponent_gifts)

    @property
    def finished(self) -> bool:
        """🔴 **이 범위에서 더 할 수 있는 행동이 없는가** (턴 종료는 범위 밖)."""
        return self.stop in ("no_legal",)

    def describe_ko(self) -> str:
        used = "사용" if self.normal_summon_used else "미사용"
        line = (f"[A] 효과 몬스터 {self.effect_bodies} · 토큰"
                f" {self.token_bodies} · 쥔 카드 {self.kept_cards}"
                f" (패 {self.hand_left} + 세트 {self.set_cards}) ·"
                f" 일반 소환권 {used} · 상대 자리 {self.opponent_gifts}")
        line += (f" · 비흐름 행동 {self.spend_actions} (흐름"
                 f" {self.flow_actions}) · 묘지 {self.grave_cards} · 제외"
                 f" {self.banished_cards} · 엑스트라 {self.extra_left} ·"
                 f" 덱 {self.deck_left}")
        if self.limits:
            line += (" · 특수 소환 제한 "
                     + ", ".join(f"{attr}(출처 {src})"
                                 for attr, src in self.limits))
        line += (f" / [B 잠재, 우열에 쓰지 않음] 상대 턴에 쓸 수 있는 종류의"
                 f" 세트 {self.set_reactive} · 효과 미사용 몬스터"
                 f" {self.unused_effect_bodies}")
        line += f" / [C] 카드 정의 모름 {self.unknown_cards}"
        return line


def measure_v2(path, resources, *, knowledge=None,
               meta=None) -> "tuple[MeasuresV2 | None, str]":
    """
    후보 하나를 센다 — ``(MeasuresV2 | None, 못 센 이유)``.

    🔴 **하나라도 읽을 수 없으면 평가 불가다.** 유리한 기본값으로 메우지
    않는다. 🔴 **카드 정의를 모르는 것은 평가 불가가 아니다** — 그것은
    C 로 세고 A 축은 그대로 돈다.
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

    unknown = 0
    effect_bodies = token_bodies = 0
    for slot in field:
        facts = know.get(slot.card_id)
        if facts is None:
            unknown += 1
            #: 🔴 **모르는 카드를 토큰으로도 효과 몬스터로도 단정하지
            #: 않는다** — 어느 축에도 넣지 않고 C 로만 센다.
            continue
        if facts.is_token:
            token_bodies += 1
        else:
            effect_bodies += 1

    set_reactive = 0
    for slot in set_slots:
        facts = know.get(slot.card_id)
        if facts is None:
            unknown += 1
            continue
        if facts.reactive_backrow:
            set_reactive += 1

    instances, used_ids = _used_marks(resources)
    unused_bodies = 0
    for slot in field:
        facts = know.get(slot.card_id)
        if facts is None or facts.is_token or facts.effect_count <= 0:
            continue
        if slot.instance in instances or slot.card_id in used_ids:
            continue
        unused_bodies += 1

    their = getattr(resources, "their_field", ())
    flow = sum(1 for kind in kinds if kind in FLOW_ACTION_KINDS)
    stop = getattr(getattr(meta, "stop", None), "value", "") or ""
    return MeasuresV2(
        effect_bodies=effect_bodies,
        token_bodies=token_bodies,
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
        unused_effect_bodies=unused_bodies,
        unknown_cards=unknown,
        stop=stop,
        unsupported_here=(stop == "unsupported_left"),
    ), ""


def _dominates_v2(better: MeasuresV2, worse: MeasuresV2) -> bool:
    """
    **A 축에서만** 앞의 것이 뒤의 것을 지배하는가.

    🔴 **B 와 C 는 들어오지 않는다** — 잠재 가치로 우열을 확정하면 "세트했다"
    가 곧 "더 좋다" 가 된다. 🔴 지배당한 후보가 **실제로 더 좋을 수 있다.**
    """
    mine, theirs = better.axes, worse.axes
    if any(a < b for a, b in zip(mine, theirs)):
        return False
    return any(a > b for a, b in zip(mine, theirs))


def _display_key(measures: MeasuresV2) -> tuple:
    """표시 순서 — A 축을 크게, 그다음 **짧은 경로**를 먼저. 🔴 점수가 아니다."""
    return (-measures.effect_bodies, -measures.kept_cards,
            -measures.token_bodies, -int(measures.summon_right_kept),
            measures.opponent_gifts, measures.spend_actions)


def diversity_key(resources, measures: MeasuresV2) -> tuple:
    """
    두 후보가 **의미 있게 다른 집인가**를 값으로 (Phase 6-BD §6).

    🔴 **카드 이름도 정답 경로도 하드코딩하지 않는다.** 보는 것은 최종
    자리의 **구성**이다 — 앞면 몬스터의 카드 ID 다중집합, 뒷면 세트의 카드
    ID 다중집합, 패 장수. 같은 집에 **순서만 다른** 변형(예: 두 장을 어느
    쪽 먼저 세트했는가)은 같은 열쇠가 되고, 집이 다르면 다른 열쇠가 된다.
    """
    try:
        faces = tuple(sorted(
            slot.card_id for slot in resources.own_field if slot.face_up
        ))
        spells = resources.zone(resources.seat, Zone.SZONE)
        backs = tuple(sorted(
            slot.card_id for slot in (spells.cards if spells else ())
            if not slot.face_up
        ))
    except Exception:  # pragma: no cover - 방어용
        return ("unknown", measures.axes)
    return (faces, backs, measures.hand_left)


def select_top_v2(pool, count: int, *, knowledge=None) -> "frozenset[int]":
    """
    모아 둔 후보 풀에서 **재생할 자리 번호**를 고른다 (v2).

    🔴 **추천과 같은 기준으로 고른다** — 재생 대상을 다른 기준으로 고르면
    "검증된 것 중에서 추천" 이라는 계약이 평가와 어긋난다.

    🔴 **같은 집의 변형이 검증 슬롯을 독차지하지 않게 한다** (§6). 비지배
    후보를 표시 순서로 넣되, 이미 고른 것과 **집 구성이 같은** 후보는 자리가
    남을 때까지 미룬다 — 카드 이름이 아니라 :func:`diversity_key` 로 가른다.

    🔴 **고르지 않은 후보를 버리지 않는다.** 재생만 하지 않을 뿐이고, 경로는
    결과에 그대로 남는다 (``RerunState.NOT_SELECTED``).
    """
    want = max(1, int(count))
    rows = []
    for slot, item in enumerate(pool):
        path, resources = item[0], item[1]
        meta = item[3] if len(item) > 3 else None
        measures, _why = measure_v2(path, resources, knowledge=knowledge,
                                    meta=meta)
        if measures is None:
            continue
        rows.append((slot, measures, diversity_key(resources, measures)))
    if not rows:
        return frozenset(range(min(len(pool), want)))
    best = {
        slot for slot, mine, _key in rows
        if not any(_dominates_v2(other, mine)
                   for slot2, other, _k2 in rows if slot2 != slot)
    }
    ordered = sorted(rows, key=lambda row: (_display_key(row[1]), row[0]))

    chosen: list[int] = []
    taken_keys: set = set()

    def _take(only_best: bool, only_new_key: bool) -> None:
        for slot, _m, key in ordered:
            if len(chosen) >= want:
                return
            if slot in chosen:
                continue
            if only_best and slot not in best:
                continue
            if only_new_key and key in taken_keys:
                continue
            chosen.append(slot)
            taken_keys.add(key)

    #: ① 비지배 + 서로 다른 집 → ② 비지배(같은 집이라도) → ③ 서로 다른 집
    #: → ④ 남은 것. 🔴 네 단계 모두 **표시 순서**를 지킨다.
    _take(True, True)
    _take(True, False)
    _take(False, True)
    _take(False, False)
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
        """비지배 후보들 — 표시 순서대로. 🔴 여럿이면 **공동 추천**이다."""
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
        head = (
            "다섯 축(효과 몬스터 · 토큰 · 쥔 카드 · 일반 소환권 ·"
            " 상대 자리) 가운데 어느 후보에게도 모두 뒤지지 않습니다 — "
            if one.nondominated else
            (", ".join(f"결과 {other}" for other in one.dominated_by)
             + " 가 다섯 축 모두에서 뒤지지 않고 적어도 하나에서 앞섭니다 — ")
        )
        return head + one.measures.describe_ko()

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

    final: list[OpenCandidate] = []
    for one in rows:
        if one.index not in measured:
            final.append(one)
            continue
        mine = measured[one.index]
        beaten_by = tuple(sorted(
            other for other, theirs in measured.items()
            if other != one.index and _dominates_v2(theirs, mine)
        ))
        final.append(OpenCandidate(
            index=one.index, verified=True, rerun_state=one.rerun_state,
            measures=mine, nondominated=not beaten_by,
            dominated_by=beaten_by,
        ))

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
            f"🔴 **공동 추천 {len(recommended)}개** — 다섯 축으로는 우열이"
            " 가려지지 않았습니다. 억지로 하나로 줄이지 않았습니다."
        )
    return RankingV2(candidates=tuple(final), note=note)
