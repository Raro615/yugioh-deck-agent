# Phase 2-AL — Operation Applicability & Scope Resolution

기준 커밋: `cc16989` (Phase 2-AK) · 2908 passed / 4 skipped
→ 이번 단계: **2919 passed / 4 skipped**

한 줄 결론: **STRUCTURAL-98 은 절반만 맞은 진단이었고, STRUCTURAL-99 는
🟡 가 아니라 실제 버그였다.** 재현해서 고쳤다.

> 명세가 §3-A 중간에서 잘려 들어왔다 (§0 목적 · §1 핵심 질문 Q1~Q6 ·
> §2 기존 구조 우선 · §3-A 까지 받았다). 받은 범위는 전부 답했고,
> 완료 보고서 형식은 앞 단계들의 것을 따랐다.

---

## 1. 핵심 질문에 대한 답 (§1)

### Q1 · Q2 — Ruling 은 무엇까지 판단하는가

**"이 Operation 이 가능한가" 만 판단한다.** 범위는 판단하지 않는다.

근거는 추론이 아니라 **공식 스크립트의 모양**이다.

```lua
Duel.SelectTarget(tp, Card.IsAbleToHand, tp, LOCATION_MZONE, LOCATION_MZONE, 1,1, nil)
--                    └ 가능한가 (카드마다) ┘  └──── 어디를 보는가 (범위) ────┘
```

두 인자가 **따로** 있다. 범위는 호출 인자이고 가능성은 필터다. 엔진의
가름도 그대로다.

| 계층 | 답하는 질문 | 어휘 |
|---|---|---|
| `CandidateSource` | **어디를 보는가** (zones · owner) | 범위 |
| `CandidateSource.require` | **무엇인가** (몬스터인가 · 앞면인가 · 레벨이 얼마인가) | `Condition` |
| `BoardRuling` | **무엇을 해도 되는가** | `RuleQuestion` |

### Q3 — 책임 경계는 어디인가

**겹치지 않는다. 구조가 그것을 보장한다.**

`Condition` 어휘 전체(`PhaseIs` · `CardIsInZone` · `CardIsFaceUp` ·
`IsMonster` · `IsSpellTrap` · `LevelAtLeast` · `AttackAtLeast` ·
`AttributeIs` · `ControllerIs` · `InAnyZone` …)는 **카드가 무엇인가**만
묻는다. "이 카드를 패로 되돌릴 수 있는가" 를 적을 수 있는 `Condition` 이
**하나도 없다.** 그러므로 `require=` 로 관문 질문을 표현할 길이 없고,
두 자리에 같은 질문이 놓일 수 없다.

코퍼스가 그 가름을 다시 확인해 준다 — 스크립트의 필터는 둘을 **and 로
잇는다**: `c:IsMonster() and c:IsAbleToGrave()`. 이어 붙인다는 것은 둘이
다른 술어라는 뜻이다.

### Q4 — GameState 를 어느 계층이 읽는가

| 계층 | 읽는 것 |
|---|---|
| `EffectExecutor` | `GameState` (바꿀 수 있는 판) — **여기 하나뿐** |
| `TargetResolver` · `CandidateResolver` · `BoardRuling` | `GameStateView` (스냅숏) |

`BoardRuling` 은 `GameState` 를 받으면 **`TypeError`** 를 낸다.

문제는 "어느 타입" 이 아니라 **"어느 시점"** 이었다 — 아래 §3.

### Q5 — `scope_limits()` 는 무엇이었나

**잘못된 책임 배치였다.**

판정마다 달라지지 않는 **모듈 상수**(`UNSCANNED_ZONES`)를 판정기 인스턴스의
메서드로 두었다. 그래서 양쪽 패가 비어 아무것도 놓치지 않은 판정과, 상대
패 5장을 못 본 판정이 **같은 문장**을 돌려주었다. 답의 성질이 아니라
**함수의 성질**을 적고 있었던 셈이다.

게다가 그 어휘는 **이미 있었다.**

| `CandidateSet` (2-N) | `BoardRuling` (2-AK) |
|---|---|
| `eligible` — 확실히 후보 | `TRUE` |
| `undecided` — 후보인지 모른다 | `UNKNOWN` |
| `reasons` — 왜 모르는지 | `RulingVerdict.reason` |
| **`unchecked` — 아예 들여다보지 못한 곳들** | **`scope_limits()`** ← 새로 만든 것 |

후보 계층이 쓰던 이름 · 모양 · 뜻이 그대로 맞았는데 새로 만들었다.
이번에 `RulingVerdict.unchecked` 로 **같은 이름 · 같은 모양**으로 옮겼다.

### Q6 — STRUCTURAL-98 은 blocker 인가

**아니다. 그리고 진단 자체가 절반만 맞았다.**

2-AK 는 "결과에 실을 자리가 없다" 고 적었다. `EffectResult.unchecked_rules`
는 **2-M 부터 있었고**, 문서에 이미 두 출처가 적혀 있다.

> 1. 의미를 주장하는 일을 **수행했지만** 그 의미의 규칙을 전부 옮기지는
>    못했을 때
> 2. 규칙을 판정하지 못해 **수행하지 않았을 때**

없던 것은 **칸**이 아니라 **판정 한 번의 사실을 그 칸에 넣는 길**이었다.
칸은 `tuple[str, ...]` 이고, 채우는 경로만 조작 **종류**별 표에 묶여
있었다. 구조 문제가 아니라 배선 문제다 → 🟠 에서 🟡 로 내린다.

---

## 2. 무엇을 바꿨는가 — `scope_limits()` → `RulingVerdict.unchecked`

```python
@dataclass(frozen=True, slots=True)
class RulingVerdict:
    answer: ConditionResult
    reason: str
    unchecked: tuple[str, ...] = ()   # ← 2-AL
```

`TRUE` 일 때만 채워진다. `FALSE` 는 판과 무관하고(막는 것은 혼자서도
막는다), `UNKNOWN` 은 이미 못 본 것을 **이유로** 말한다.

### 셋이 같은 무게가 아니었다

2-AK 의 `UNSCANNED_ZONES` 는 세 줄을 나란히 두었다. 다시 읽으니 하나만
한계다.

| 자리 | 왜 안 훑는가 | 한계인가 |
|---|---|---|
| 덱 | 덱의 카드는 효과를 적용하지 않는다 (룰북) | **아니다** — 볼 것이 없다 |
| 뒷면 카드 | 세트된 카드는 발동·반전 전까지 효과를 적용하지 않는다 (룰북) | **아니다** |
| **패** | **가려져 있다** | **그렇다** |

그래서 `BLIND_ZONE = Zone.HAND` 하나만 판정마다 실린다.

### 장수는 가려진 자리에서도 공개된 사실이다

처음에 `len(hand.cards)` 로 셌더니 **언제나 0** 이었다 — 가려진 자리의
`cards` 는 비어 있다. 그것을 "패가 없다" 로 읽으면 **못 본 것을 못 봤다고
말하게 된다.** `ZoneView.size` 를 쓴다.

```
P1 hand  concealed=True  cards=()  size=2      ← 장수는 공개, 내용은 비공개
```

### 비어 있을 수 있다는 것이 요점이다

양쪽 패가 모두 비면 `unchecked == ()` 이고, 그때의 `TRUE` 는 **전부 보고
낸 답**이다. 언제나 한 줄을 붙이면 그 줄은 곧 무시된다.

---

## 3. 🔴 STRUCTURAL-99 는 배선이 아니라 버그였다 (재현함)

2-AK 는 이것을 🟡 "판정기가 판을 스스로 보지 못해 부르는 쪽이 만들어
넘겨야 한다" 로 적었다. **재현해 보니 결과가 틀린다.**

```
판:   P0 MZONE 페더맨 · P1 MZONE <막을 수 있는 카드>
효과: 0번 상대 몬스터를 패로  ·  1번 내 몬스터를 패로
```

0번이 끝나면 막는 카드는 **필드에 없다.** 그러므로 1번은 통과해야 한다.

**고치기 전** (부르는 쪽이 `BoardRuling` 을 만들어 넘김):

```
0번 대상: true
1번 대상: unknown | MZONE 의 55144522 는 다른 카드의 조작을 막을 수 있습니다.
실행:     UNCHECKED_RULES          ← 효과 전체가 멈춘다
```

판정기가 들고 있는 관측이 **효과 시작 시점**에 멈춰 있어서, 이미 치운
카드가 계속 막고 있다.

**STRUCTURAL-94 와 같은 종류의 버그다** — 2-AH 가 조건 계층에서 고친
그것이고, 계층만 다르다.

### 고친 방법 — 지식과 판정을 나눈다

```python
EffectExecutor(..., rulings=OperationRulingRegistry)   # 지식: 판과 무관
    ↓ 계획 단계마다
BoardRuling(GameStateView.from_state(board, ...), rulings)   # 판정: 판마다
```

`board` 는 2-AH 가 만든 **투영된 판**이다. 앞 조작이 끝난 판을 뒤 조작이
본다.

**고친 뒤:** 같은 정의 · 같은 판 · 같은 지식인데 `RESOLVED` 다.

### 규칙 질문은 관측 질문이 아니다

2-AK 가 미뤄 둔 "누구의 눈으로 보는가" 를 여기서 답한다.

**그 카드 주인의 눈으로, 그 카드가 있는 자리를 열어서 묻는다.**

근거: 어리석은 매장이 **자기 덱 안의 카드**에 `IsAbleToGrave` 를 묻는다.
컨트롤러의 평범한 관측으로는 자기 덱이 보이지 않지만, "이 카드를 묘지로
보낼 수 있는가" 의 답은 **누가 보고 있는지에 따라 달라지지 않는다.**

2-AI 의 `_authoritative_candidates` 가 후보를 셀 때 쓴 것과 **같은
방법**이고, 같은 이유로 그 관측은 밖으로 나가지 않는다. 경계 시험
(`test_j_the_observation_boundary_is_the_actors`)이 예외를 **둘 다**
이름으로 고정한다 — 변수명 `owner` 까지.

**예외를 하나 더 연 것이 아니라, 같은 종류의 예외가 하나 더 생겼고 같은
방법으로 막았다.**

### 기본값으로 넣지 않는다

`build_executor` 는 `OPERATION_RULINGS` 를 몰래 넣지 않는다. 넣으면
**목록에 실렸다는 사실이 판정을 대신하게 된다** — `destruction` 을 몰래
바꾸지 않는 것과 같은 이유다 (ADR-006).

---

## 4. 못 본 것이 결과까지 나온다

```python
unchecked = list(collect_unchecked(record.kind for record in applied))  # 2-M, 종류별 표
for step in plan:
    for note in step.blind:                                             # 2-AL, 판정 한 번
        if note not in unchecked:
            unchecked.append(note)
```

두 출처가 같은 칸에 들어가는 이유는 **읽는 쪽에 같은 뜻**이기 때문이다 —
"이 실행은 규칙을 전부 보지 못했다".

**`OperationOutcome` 은 건드리지 않았다.** 못 본 자리가 있다고 조작의
성패를 `UNKNOWN` 으로 바꾸면 같은 효과 안의 뒤 조작이 앞의 결과를 읽을 때
막힌다. 그것은 "못 본 자리가 있다" 와 **다른 결정**이고, 근거를 모으기
전에 내릴 결정이 아니다 (STRUCTURAL-100 으로 남긴다).

---

## 5. 코드 변경

| 파일 | 변경 | 왜 |
|---|---|---|
| `engine/effect/ruling.py` | `RulingVerdict.unchecked` 추가 · `scope_limits()` 제거 · `BLIND_ZONE` | Q5 — 잘못된 책임 배치 |
| `engine/effect/executor.py` | `rulings=` 인자 · `_movement_ruling()` · `_check_rule_gate` 가 판을 받는다 · `_Step.blind` | 🔴 99 · 98 배선 |
| `engine/effect/library.py` | `build_executor(rulings=…)` | 같은 배선 |

기존 테스트 수정 **2건** (삭제 0건):

- `test_operation_ruling.py::test_d_what_is_not_scanned_is_written_down` —
  `scope_limits()` 가 사라졌다. **잘못된 가정**: "한계는 판정마다 같다".
  이제 같은 시험이 빈 경우와 아닌 경우를 **둘 다** 본다.
- `test_operation_integration.py::test_j_the_observation_boundary_is_the_actors` —
  관측 예외가 하나에서 둘이 되었다. **단언이 약해지지 않았다** — 새 자리도
  같은 두 검사(이름이 `owner` 일 것 · 관측이 밖으로 나가지 않을 것)를
  받는다. 고치는 김에 `self` 검사가 안쪽 루프 밖에 있던 것도 바로잡았다.

---

## 6. 테스트

- New tests: **11** (`test_operation_ruling.py` §G)
- Passed **2919** / Failed 0 / Skipped 4 / Regression **0**

| 무엇을 | 시험 |
|---|---|
| 한계가 판정마다 다르다 | `test_g_the_blind_spot_is_per_call_not_a_constant` |
| 가려진 자리도 장수는 센다 | `test_g_a_concealed_hand_still_reports_its_size` |
| 덱·뒷면은 한계가 아니다 | `test_g_only_the_hand_counts_as_a_blind_spot` |
| FALSE·UNKNOWN 에는 안 싣는다 | `test_g_a_false_and_an_unknown_carry_no_blind_spot` |
| 결과까지 나온다 / 없으면 안 적는다 | `test_g_the_blind_spot_reaches_the_effect_result` · `…_claims_nothing_extra` |
| **버그 재현** | `test_g_a_prebuilt_ruling_sees_the_board_frozen_at_the_start` |
| **고쳐진 것** | `test_g_the_executor_builds_the_ruling_from_the_projected_board` |
| 지식은 판과 무관 | `test_g_knowledge_is_board_independent_and_judgement_is_not` |
| 규칙 질문 ≠ 관측 질문 | `test_g_the_rule_question_is_not_an_observation_question` |
| 기본값으로 넣지 않는다 | `test_g_the_registry_is_not_a_default` |

---

## 7. TODO

- **STRUCTURAL-98 — 해결.** 진단이 절반 틀렸다는 것까지가 답이다. 칸은
  2-M 부터 있었고 배선만 없었다.
- **STRUCTURAL-99 — 해결.** 🟡 로 적었던 것이 실제로는 결과를 틀리게 하는
  버그였다. 재현하고 고쳤다.
- **STRUCTURAL-100 (신규 · 🟡)** — **못 본 자리가 조작의 성패를 바꿔야
  하는가.** 지금은 `EffectResult.unchecked_rules` 에만 싣고
  `OperationOutcome` 은 그대로 둔다. 바꾸면 뒤 조작이 앞 결과를 못 읽게
  되므로, 실제로 그래야 하는 카드를 찾은 뒤에 정한다.
- **STRUCTURAL-76 (지속 효과 계층) — 그대로.** 막을 수 있는 카드가 있으면
  여전히 `UNKNOWN` 이다.
- **ADR-006 — 그대로 부분 해결.** 파괴(347+533장)와 특수 소환(4,297장)은
  여전히 답하지 않는다.
- **97 · 95 · 93 · 90 · 87 · 86 · 83 — 그대로 둔다.**
- 71 · 74 · 75 · 77 · 78 — **하나도 건드리지 않았다.**

---

## 8. 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** (찾은 1건은 이번에 고쳤다 — 99) | |
| 🟠 STRUCTURAL | 0 신규 (98 · 99 해결) | |
| 🟡 DETAIL | 1 신규 | 100 (못 본 자리와 성패) |
| 🟢 COSMETIC | 0 신규 | |

---

## 9. 이번에 하지 않은 것 (§2)

새 시스템을 하나도 만들지 않았다. `RulingVerdict.unchecked` 는 후보 계층이
쓰던 `CandidateSet.unchecked` 를 **그대로 가져온 것**이고, `rulings=` 는
`destruction` · `movement` 와 **같은 자리**에 붙은 인자다.

Duel Engine 재설계 · EffectExecutor 재작성 · 새 Graph Engine · 새 EventBus ·
새 Expression Language · 새 Rule Engine · 새 Scope 계층 · AI 의사결정 ·
카드 이름별 hardcoded rule · 테스트 삭제 · 규칙 추측 — 하나도 하지 않았다.

**새 카드를 한 장도 등재하지 않았다.** 이번 단계는 경계를 맞추는 단계였다.

**다음 Phase 는 시작하지 않았다.**
