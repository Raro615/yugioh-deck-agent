"""
**검증용 전개 정책** (Phase 6-AC) — 적어 둔 한 경로를 엔진으로 따라간다.

    ComboLine (적어 둔 경로)
        ↓
    VerificationLinePolicy  ← ``execute_opening(..., choose=이것)``
        ↓  Duel.legal_actions 가 **매 상태마다** 낸 후보
        ↓  그중 **이번 단계와 맞는 것** 하나
    Duel.apply                ← 판을 바꾸는 것은 엔진뿐이다

이것이 **무엇이 아닌가**
------------------------
🔴 **최선 전개 탐색이 아니다.** 경로를 **사람이 적어 두었고**, 이 정책은
그것을 따라가기만 한다.

🔴 **범용 오르페골 AI 가 아니다.** 적혀 있지 않은 판에서는 아무것도 고르지
못하고 ``None`` 을 돌려준다.

🔴 **LLM 이 스스로 찾은 전개가 아니다.** :data:`ORCUST_GIRSU_LINE` 의 네
단계는 공식 카드 텍스트와 공식 스크립트를 대조해 손으로 적은 것이다.

🔴 **:func:`~deck.opening.first_meaningful` 을 바꾸지 않는다.** 그것은
``choose`` 의 기본값이고 다른 요청의 행동 선택이므로, 이 정책은 **옆에**
붙는다 — 주지 않으면 예전과 한 글자도 다르지 않다.

무엇을 지키는가
---------------
1. **엔진이 낸 후보에서만 고른다.** 이 모듈에는 ``PlayerAction`` 을 **만드는
   코드가 없다** — ``legal.allowed`` 를 걸러 내는 것이 전부다. 그래서 정책이
   엔진을 우회해 상태를 바꿀 길이 구조적으로 없다.
2. **매 상태마다 다시 묻는다.** 정책은 ``(duel, legal)`` 을 받을 때마다
   그 자리의 후보만 보고, 앞 자리의 목록을 기억하지 않는다.
3. **상태를 갖지 않는다.** :class:`VerificationLinePolicy` 는 frozen 이고
   cursor 도 trace 도 없다 — 어느 단계인지는 **후보 목록이 말한다**
   (:meth:`VerificationLinePolicy.__call__` 의 설명). 그래서 사본
   (``Simulator._fork``)에 같은 정책을 그대로 써도 원본이 오염되지 않는다.
4. **대상과 소재는 기존 계약을 따른다.** 효과의 대상은
   :func:`~engine.target_bridge.target_combinations` 가 만든 조합이고 링크
   소재는 :func:`~engine.link_summon.assess_link_materials` 가 판정한 것이다 —
   이 모듈은 그 안에서 **카드 ID 로 하나를 고르기만** 한다.
5. **기대한 행동이 없으면 조용히 넘기지 않는다.** ``None`` 을 돌려주면
   ``execute_opening`` 이 그 자리에서 멈추고 이유를 적는다. 어디까지 갔는지는
   :func:`line_progress` 가 **실행 기록과 경로를 대조해** 답한다.

왜 카드 ID 로 적는가
--------------------
인스턴스 번호(``InstanceId``)는 판을 만들 때마다 달라진다. 경로를 번호로
적으면 같은 레시피로도 재현되지 않는다. 카드 ID 는 입력(레시피 · 패)의
일부이므로 **같은 입력이면 같은 경로**가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 경로 단계가 쓸 수 있는 행위 종류 이름들. **import 시점에 확인한다.**
#:
#: 문자열로 적는 이유: :mod:`deck` 은 모듈 위에서 ``engine`` 을 읽지 않는다
#: (:mod:`deck.opening` 과 같은 규율). 그래도 오타를 런타임까지 미루지 않으려고
#: 여기서 한 번 맞춰 본다.
def _known_kinds() -> frozenset[str]:
    from engine.action import PlayerActionKind

    return frozenset(kind.value for kind in PlayerActionKind)


@dataclass(frozen=True, slots=True)
class PlannedAction:
    """
    경로의 한 단계 — **무엇을 고를 것인가**를 카드 ID 로 적는다.

    비어 있는 칸은 "그 축으로 거르지 않는다" 는 뜻이다. ``kind`` 만 적으면
    그 종류의 **첫 후보**를 고르고, 그것은 :func:`~deck.opening.first_meaningful`
    과 같은 수준의 근거 없는 선택이다 — 경로를 적을 때는 가능한 한 채운다.
    """

    kind: str
    """행위 종류 이름 (``PlayerActionKind`` 의 값)."""
    card_id: "int | None" = None
    """``source`` 카드의 ID."""
    effect_ref: "tuple[int, int] | None" = None
    """``(card_id, ordinal)``. ``EffectRef`` 를 쓰지 않는 이유는 모듈 머리말."""
    target_card_ids: tuple[int, ...] = ()
    """대상들의 카드 ID. **다중집합으로 비교한다** (순서는 보지 않는다)."""
    material_card_ids: tuple[int, ...] = ()
    """링크 소재들의 카드 ID. 같은 규칙으로 비교한다."""
    label: str = ""
    """사람이 읽는 한 줄. 보고서와 설명에 그대로 쓴다."""

    def __post_init__(self) -> None:
        if self.kind not in _known_kinds():
            raise ValueError(
                f"알 수 없는 행위 종류입니다: {self.kind!r}. "
                f"가능한 값: {sorted(_known_kinds())}"
            )
        if self.effect_ref is not None and len(self.effect_ref) != 2:
            raise ValueError(
                f"effect_ref 는 (card_id, ordinal) 입니다: {self.effect_ref!r}"
            )

    # ------------------------------------------------------------------
    def matches(self, duel, action) -> bool:
        """
        이 단계가 그 후보를 가리키는가. **판을 읽기만 한다.**

        인스턴스를 카드 ID 로 바꾸는 일만 판에 묻는다 (``find_instance``).
        적법성은 보지 않는다 — 받은 것이 이미 ``legal.allowed`` 의 하나이므로
        엔진이 허가한 행위다.
        """
        if action.kind.value != self.kind:
            return False
        if self.card_id is not None:
            if self._card_id(duel, action.source) != self.card_id:
                return False
        if self.effect_ref is not None:
            ref = action.effect_ref
            if ref is None or (ref.card_id, ref.ordinal) != tuple(self.effect_ref):
                return False
        if self.target_card_ids:
            got = sorted(
                self._card_id(duel, instance)
                for instance in action.instance_targets()
            )
            if got != sorted(self.target_card_ids):
                return False
        if self.material_card_ids:
            got = sorted(
                self._card_id(duel, instance) for instance in action.materials
            )
            if got != sorted(self.material_card_ids):
                return False
        return True

    @staticmethod
    def _card_id(duel, instance) -> "int | None":
        if instance is None:
            return None
        card = duel.state.find_instance(instance)
        return card.card_id if card is not None else None

    def describe_ko(self) -> str:
        if self.label:
            return self.label
        bits = [self.kind]
        if self.card_id is not None:
            bits.append(f"카드 {self.card_id}")
        if self.effect_ref is not None:
            bits.append(f"효과 {self.effect_ref[0]}:e[{self.effect_ref[1]}]")
        if self.target_card_ids:
            bits.append("대상 " + " · ".join(str(c) for c in self.target_card_ids))
        if self.material_card_ids:
            bits.append("소재 " + " · ".join(str(c) for c in self.material_card_ids))
        return " / ".join(bits)

    def canonical_state(self) -> tuple:
        return (
            self.kind,
            self.card_id,
            tuple(self.effect_ref) if self.effect_ref is not None else None,
            tuple(sorted(self.target_card_ids)),
            tuple(sorted(self.material_card_ids)),
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class ComboLine:
    """
    적어 둔 전개 한 경로. **근거를 함께 들고 다닌다.**

    :class:`~engine.effect.library.LibraryEntry` 와 같은 규율이다 — 근거
    없이 적힌 경로는 검증된 전개가 아니라 추측이다.
    """

    name: str
    """``/combo`` 가 받는 짧은 이름."""
    title_ko: str
    steps: tuple[PlannedAction, ...]
    basis: str = ""
    """이 경로의 각 단계를 어느 카드 텍스트 · 스크립트에서 읽었는가."""
    note: str = ""
    hand: tuple[int, ...] = ()
    """
    이 경로를 재현하는 **시작 패**의 카드 ID.

    🔴 **자동으로 쓰이지 않는다.** ``/combo`` 는 사용자가 적은 패로 돌고,
    이 칸은 **보고서와 시험이 읽는 재현 입력**이다. 경로가 요구하는 패를
    사용자 모르게 끼워 넣으면 "이 패로 됐다" 가 거짓이 된다.
    """
    recipe_ydk: str = ""
    """
    이 경로를 재현하는 **검증용 레시피** (YDK 모양).

    🔴 **검증 자료이고 추천 덱이 아니다.** ``recipe:`` 를 생략한 요청에서
    이 값이 조용히 쓰이는 길은 없다 — ``_executed_lines`` 는 레시피가 없으면
    "하지 않았습니다" 를 적는다 (Phase 6-T 부터의 규율).

    🔴 **금제 · 포맷 적법성을 주장하지 않는다.** 확인한 금지 · 제한 목록이
    없으므로 "대회 합법 덱" 이라고 부르지 않는다.
    """

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("경로에는 이름이 필요합니다.")
        if not self.steps:
            raise ValueError(f"{self.name}: 단계가 없는 경로는 경로가 아닙니다.")
        if not self.basis.strip():
            raise ValueError(
                f"{self.name}: 각 단계를 어디서 읽었는지 적어야 합니다 — "
                "근거 없는 경로는 추측입니다."
            )

    @property
    def reproduction_ready(self) -> bool:
        """재현 입력(패 · 레시피)이 **둘 다** 적혀 있는가."""
        return bool(self.hand) and bool(self.recipe_ydk.strip())

    def hand_text(self) -> str:
        """``/combo hand:`` 에 그대로 붙여 넣을 문자열."""
        return ",".join(str(card_id) for card_id in self.hand)

    def policy(self, then=None) -> "VerificationLinePolicy":
        """이 경로를 따라가는 **검증용 전개 정책**."""
        return VerificationLinePolicy(line=self, then=then)

    def describe_ko(self) -> str:
        lines = [f"{self.title_ko} ({len(self.steps)}단계)"]
        lines.extend(
            f"  {i}. {step.describe_ko()}" for i, step in enumerate(self.steps, 1)
        )
        return "\n".join(lines)

    def canonical_state(self) -> tuple:
        return (self.name, tuple(s.canonical_state() for s in self.steps))

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class VerificationLinePolicy:
    """
    **검증용 전개 정책** — ``execute_opening(choose=…)`` 에 그대로 넣는다.

    🔴 **상태를 갖지 않는다.** 어느 단계인지 세지 않고, 매 상태마다 경로를
    **처음부터** 훑어 그 자리의 후보와 맞는 **첫 단계**를 고른다. 그래서
    사본에서 같은 정책 객체를 써도 원본과 서로 간섭하지 않는다.

    왜 그래도 반복되지 않는가: 한 단계를 수행하면 그 행동이 **후보에서
    사라진다** — 일반 소환권을 썼고, 사건이 소비되었고
    (``Duel.consumed_events``), 「1턴에 1번」 을 썼고
    (``EffectDefinition.use_limit``), 링크 몬스터가 엑스트라 덱을 떠났다.
    즉 진행은 **엔진이 만든 사실**이 밀고 나가는 것이고 정책의 메모가 아니다.

    🔴 **그 전제가 깨지면 반복될 수 있다.** 같은 행동이 두 번 허가되는 경로를
    적으면 이 정책은 그것을 두 번 고른다. 그때 멈추는 것은
    ``execute_opening`` 의 걸음 상한이고 (``MAX_EXECUTED_ACTIONS``), 그것이
    **경로를 잘못 적었다는 신호**다 — 정책이 몰래 중복을 걸러 주면 그 신호가
    사라진다.

    ``then`` 은 경로가 끝난 **뒤**에 쓸 선택 방식이다. 주지 않으면 ``None``
    을 돌려주고 호출자가 멈춘다 — 그것이 "이 경로만 본다" 다.
    """

    line: ComboLine
    then: object | None = None

    def __call__(self, duel, legal):
        for step in self.line.steps:
            for action in legal.allowed:
                if step.matches(duel, action):
                    return action
        if self.then is None:
            return None
        return self.then(duel, legal)

    def describe_ko(self) -> str:
        tail = "" if self.then is None else " (경로 뒤에는 다른 방식으로 계속)"
        return f"검증용 전개 정책: {self.line.title_ko}{tail}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


# ======================================================================
# 어디까지 갔는가 — 실행 기록과 경로를 대조한다
# ======================================================================


@dataclass(frozen=True, slots=True)
class LineProgress:
    """
    경로를 **어디까지 실행했는가.** 실행 기록에서 읽은 것이고 추측이 아니다.

    🔴 **"경로를 끝까지 실행했는가" 와 "후보 공간 전체를 지원하는가" 는 다른
    질문이다** (보완8 이 ``fully_supported`` 와 ``stopped_kind`` 를 가른 것과
    같은 자리다). 이 타입은 앞의 것만 답한다.
    """

    line: ComboLine
    done: int
    """경로의 앞에서부터 **연속으로** 수행된 단계 수."""
    blocked_at: "PlannedAction | None" = None
    """막힌 단계. 끝까지 갔으면 ``None``."""
    reason: str = ""
    orders: tuple[int, ...] = field(default_factory=tuple)
    """각 단계가 실행 기록의 몇 번째 걸음이었는가."""

    @property
    def completed(self) -> bool:
        return self.done == len(self.line.steps)

    def describe_ko(self) -> str:
        head = (
            f"✅ 경로를 끝까지 실행했습니다 ({self.done}/{len(self.line.steps)}단계)"
            if self.completed
            else f"🔴 경로가 {self.done}/{len(self.line.steps)}단계에서 멈췄습니다"
        )
        if self.blocked_at is not None:
            head += f" — 막힌 단계: {self.blocked_at.describe_ko()}"
        if self.reason:
            head += f" ({self.reason})"
        return head

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


def line_progress(run, line: ComboLine) -> LineProgress:
    """
    실행 기록(:class:`~deck.opening.OpeningRun`)과 경로를 대조한다.

    🔴 **정책에게 묻지 않는다.** 정책은 상태가 없으므로 "어디까지 갔는가" 를
    알지 못하고, 그 답을 들고 있는 것은 **실행 기록**이다 — 실제로 수락된
    걸음만 적혀 있으므로 거절된 시도가 진행으로 집계되지 않는다.

    대조는 **수락되고 종류 · 카드 · 효과 · 대상 · 소재가 맞는** 걸음을
    경로 순서대로 찾는 것이다. 걸음 사이에 다른 걸음(자동 ``pass`` 등)이
    끼어 있어도 순서만 맞으면 센다 — 그 걸음들은 규칙이 요구한 절차이고
    경로의 단계가 아니다.
    """
    done = 0
    orders: list[int] = []
    cursor = 0
    steps = [s for s in run.steps if s.accepted]
    for step in line.steps:
        found = None
        for index in range(cursor, len(steps)):
            if _step_matches(steps[index], step):
                found = index
                break
        if found is None:
            return LineProgress(
                line=line,
                done=done,
                blocked_at=step,
                reason=(
                    f"실행 기록에서 이 단계를 찾지 못했습니다. 멈춘 이유: "
                    f"{run.stopped_reason}"
                    if run.stopped_reason
                    else "실행 기록에서 이 단계를 찾지 못했습니다."
                ),
                orders=tuple(orders),
            )
        orders.append(steps[found].order)
        cursor = found + 1
        done += 1
    return LineProgress(line=line, done=done, orders=tuple(orders))


def _step_matches(executed, planned: PlannedAction) -> bool:
    """
    기록된 걸음 하나가 그 단계인가.

    :meth:`PlannedAction.matches` 와 **다른 입력**을 본다 — 저쪽은
    ``PlayerAction``(지금의 의도)이고 이쪽은 ``ExecutedStep``(지난 사실)이다.
    기록에는 인스턴스가 아니라 **카드 ID 와 문자열**이 남으므로 판을 다시
    읽지 않는다 (판은 이미 바뀌어 있다).
    """
    if executed.kind != planned.kind:
        return False
    if planned.card_id is not None and executed.card_id != planned.card_id:
        return False
    if planned.effect_ref is not None:
        want = f"{planned.effect_ref[0]}:e[{planned.effect_ref[1]}]"
        if executed.effect_ref != want:
            return False
    return True


# ======================================================================
# 적어 둔 경로 — 오르페골
# ======================================================================

#: 🔴 **이 경로의 검증용 레시피** (Phase 6-AC §6).
#:
#: 메인 40장 · 엑스트라 6장이고 같은 카드 3장을 넘지 않는다. **한 카드를
#: 25장 넣은 메우기가 없다** — 전부 실제 「오르페골」 · 「성유물」 카드다.
#:
#: 🔴 **왜 「성유물－『성장』」 이 3장인가.** 경로가 그 카드를 **두 장** 쓴다 —
#: 하나는 기르수 ① 이 **덱에서** 묘지로 보내고, 다른 하나는 묘지의 그 카드가
#: **패에서** 특수 소환한다. 지정된 패가 한 장을 들고 있으므로 덱에 최소 한
#: 장이 더 있어야 하고, 3장은 그 조건을 만족하는 가장 흔한 투입 수다.
#:
#: 🔴 **이것은 검증 자료이고 추천 덱이 아니다.** 실제 오르페골 덱은 「오르페골
#: 디베르」 · 「오르페골 스켈레촌」 의 묘지 제외 전개와 패 트랩 · 범용 마법 ·
#: 함정을 함께 쓴다. 그 효과들은 이 저장소에 등재되지 않았으므로 (덱에서의
#: 특수 소환 · 제외를 소재로 하는 전개가 범위 밖이다) 여기 넣어도 실행에
#: 쓰이지 않는다.
#:
#: 🔴 **금제를 확인하지 않았다.** 그래서 "최신 대회 합법 덱" 이라고 부르지
#: 않는다 — 확인한 금지 · 제한 목록도, 그 날짜도 이 저장소에 없다.
ORCUST_VERIFICATION_RECIPE = """#main
69811710
69811710
69811710
93920420
93920420
93920420
57835716
57835716
57835716
21441617
21441617
21441617
94046012
94046012
94046012
40441990
40441990
40441990
2930675
2930675
2930675
90351981
90351981
90351981
26845680
26845680
26845680
61654098
61654098
61654098
703897
703897
703897
12989604
12989604
12989604
55051920
55051920
47171541
47171541
#extra
30741503
48835607
76145142
93854893
74820316
3134857
"""

#: 같은 레시피를 **사람이 읽는 모양**으로 (보고서와 안내에 쓴다).
#:
#: 🔴 **``parse_recipe`` 에 넣는 것은 위쪽이다.** YDK 구역의 줄은 패스코드
#: 하나뿐이어야 하고 (실측: 줄 끝 주석을 붙이면 26장만 읽힌다), 그래서
#: 이름은 **다른 상수**에 적는다 — 한 문자열에 둘을 섞으면 어느 쪽이
#: 입력인지 알 수 없다.
ORCUST_VERIFICATION_RECIPE_KO = """메인 덱 40장
  69811710 x3  잭나이츠 오르페골 기르수
  93920420 x3  성유물－『성장』
  57835716 x3  오르페골 디베르
  21441617 x3  오르페골 스켈레촌
  94046012 x3  오르페골 카노네
  40441990 x3  성유물－『성건』
  2930675 x3  성유물에 이르는 열쇠
  90351981 x3  오르페골 바벨
  26845680 x3  오르페골 프라임
  61654098 x3  성유물과의 해후
  703897 x3  오르페골 클리막스
  12989604 x3  성유물로부터의 자각
  55051920 x2  오르페골 코어
  47171541 x2  오르페골 릴리스
엑스트라 덱 6장
  30741503 x1  오르페골 갈라테아 (LINK-2) — 이 경로가 소환한다
  48835607 x1  오르페골 갈라테아i (LINK-1)
  76145142 x1  오르페골 롱기르수 (LINK-3)
  93854893 x1  시오르페골 딩기르수 (LINK-8)
  74820316 x1  잭나이츠 오르페골 엔릴기르수 (LINK-4)
  3134857 x1  오르페골 오케스트리언 (LINK-4)
"""

#: 사용자가 이미 적어 둔 패 그대로다 (Phase 6-AC §6).
#:
#: 🔴 **패에 없는 카드를 보태지 않았다.** 이 다섯 장으로 경로가 돈다 —
#: 경로의 2 단계가 덱에서 『성장』 을 꺼내 오므로, 추가 시작 패가 필요하지
#: 않다.
ORCUST_VERIFICATION_HAND: tuple[int, ...] = (
    69811710,  # 잭나이츠 오르페골 기르수
    703897,  # 오르페골 클리막스
    2930675,  # 성유물에 이르는 열쇠
    12989604,  # 성유물로부터의 자각
    93920420,  # 성유물－『성장』
)


#: 「잭나이츠 오르페골 기르수」 로 시작하는 전개 한 경로 (Phase 6-AC).
#:
#: 네 단계이고 **각 단계가 다음 단계를 가능하게 한다** — 앞 단계의 실제 효과
#: 해결이 뒤 단계의 재료를 만든다.
#:
#: ===  ============================================================
#: 1    「잭나이츠 오르페골 기르수」(69811710) 일반 소환
#: 2    기르수 ① 발동 — 덱의 「성유물－『성장』」(93920420) 을 묘지로
#: 3    묘지로 보내진 『성장』 ① 발동 — **패의 다른 『성장』** 을 특수 소환
#: 4    기르수 + 『성장』 을 소재로 「오르페골 갈라테아」(30741503) 링크 소환
#: ===  ============================================================
#:
#: 🔴 **2 단계의 대상이 『성장』 인 것이 경로의 핵심이다.** 기르수 ① 은 덱의
#: 「오르페골」 · 「성유물」 카드 **아무거나** 보낼 수 있고, 그중 **묘지에서
#: 스스로 유발하는** 카드를 고를 때만 3 단계가 열린다. 그래서 이 단계는
#: ``target_card_ids`` 를 비워 두지 않는다.
#:
#: 🔴 **3 단계는 「패에서」 특수 소환이다.** 『성장』 ① 의 공식 텍스트가
#: 「패에서 "성유물" 몬스터 1장을 특수 소환한다」 이고, 그 자리는 이 엔진이
#: 소생 제한을 묻지 않는 유일한 출발 자리다
#: (``engine.effect.ruling.REVIVAL_LIMIT_FREE_ZONES``). 즉 경로가 **구현된
#: 절차의 범위 안**에 있다.
ORCUST_GIRSU_LINE = ComboLine(
    name="orcust-girsu",
    title_ko="기르수 → 『성장』 묘지행 → 패에서 『성장』 특수 소환 → 갈라테아 링크",
    steps=(
        PlannedAction(
            kind="normal_summon",
            card_id=69811710,
            label="「잭나이츠 오르페골 기르수」 를 일반 소환",
        ),
        PlannedAction(
            kind="activate_effect",
            card_id=69811710,
            effect_ref=(69811710, 0),
            label=(
                "기르수 ① 발동 — 덱에서 「성유물－『성장』」 을 묘지로 보낸다 "
                "(대상은 해결 중에 고른다)"
            ),
        ),
        PlannedAction(
            kind="activate_effect",
            card_id=93920420,
            effect_ref=(93920420, 1),
            target_card_ids=(93920420,),
            label=(
                "묘지로 보내진 『성장』 ① 발동 — 패의 「성유물－『성장』」 을 "
                "특수 소환"
            ),
        ),
        PlannedAction(
            kind="link_summon",
            card_id=30741503,
            material_card_ids=(69811710, 93920420),
            label=(
                "기르수 + 『성장』 을 소재로 「오르페골 갈라테아」 링크 소환"
            ),
        ),
    ),
    basis=(
        "① 기르수(69811710) 공식 텍스트 「이 카드가 일반 소환·특수 소환에 "
        "성공했을 경우에 발동할 수 있다. 덱에서 「오르페골」 또는 「성유물」 "
        "카드 1장을 묘지로 보낸다」 와 c69811710.lua 의 e1 "
        "(EVENT_SUMMON_SUCCESS · s.tgfilter · Duel.SendtoGrave). "
        "② 『성장』(93920420) 공식 텍스트 「이 카드가 묘지로 보내졌을 경우에 "
        "발동할 수 있다. 패에서 「성유물」 몬스터 1장을 특수 소환한다」 와 "
        "c93920420.lua 의 e2 (EVENT_TO_GRAVE · s.spfilter1 · "
        "Duel.SpecialSummon). "
        "③ 갈라테아(30741503) 공식 텍스트 「효과 몬스터 2장 (「오르페골」 "
        "몬스터를 포함)」 와 c30741503.lua 의 Link.AddProcedure(..., "
        "Card.IsType(TYPE_EFFECT), 2, nil, s.matcheck). "
        "소재 적격: 기르수는 효과 몬스터이고 setcode 0x11b(오르페골)를 "
        "가지며, 『성장』 은 효과 몬스터이고 setcode 0xfe(성유물)다 — "
        "data/cards.cdb 로 대조했다."
    ),
    hand=ORCUST_VERIFICATION_HAND,
    recipe_ydk=ORCUST_VERIFICATION_RECIPE,
    note=(
        "🔴 이 경로는 **검증용**이다. 최선 전개라고 주장하지 않는다 — "
        "실제 오르페골 전개는 「오르페골 디베르」 · 「오르페골 스켈레촌」 의 "
        "묘지 제외 효과로 이어지고, 그 효과들은 이 저장소에 등재되지 "
        "않았다 (덱에서의 특수 소환 · 제외 소재가 범위 밖이다)."
    ),
)

#: ``/combo`` 가 이름으로 고를 수 있는 경로들.
#:
#: 🔴 **기본값이 아니다.** 이름을 주지 않으면 ``execute_opening`` 은 여전히
#: :func:`~deck.opening.first_meaningful` 을 쓴다 — 사용자가 고르지 않은
#: 정책이 조용히 다른 요청의 행동 선택을 바꾸지 않게 하는 것이 이 Phase 의
#: 규율이다 (§5).
COMBO_LINES: dict[str, ComboLine] = {ORCUST_GIRSU_LINE.name: ORCUST_GIRSU_LINE}


def line_named(name: "str | None") -> "ComboLine | None":
    """그 이름의 경로. **없으면 ``None``** — 비슷한 것을 골라 주지 않는다."""
    if not name or not name.strip():
        return None
    return COMBO_LINES.get(name.strip().lower())


__all__ = [
    "COMBO_LINES",
    "ORCUST_GIRSU_LINE",
    "ORCUST_VERIFICATION_HAND",
    "ORCUST_VERIFICATION_RECIPE",
    "ORCUST_VERIFICATION_RECIPE_KO",
    "ComboLine",
    "LineProgress",
    "PlannedAction",
    "VerificationLinePolicy",
    "line_named",
    "line_progress",
]
