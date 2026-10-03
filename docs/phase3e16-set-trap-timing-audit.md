# Phase 3-E-16 — 세트한 함정의 발동 타이밍 감사 (`_OUT_OF_SCOPE_TYPES` 의 TRAP)

- 실제 HEAD / Base: `eb89805` (Phase 3-E-15)
- 판정: **B — AUDIT ONLY.** 함정을 열지 않았다.
- Engine 변경: **문장 하나** (판정 결과 변화 0). 아래 §27 조건 검토 참조.

---

## §0 의 질문에 대한 답

> "현재 repository 의 Trap effect definition 이 유발 조건 없는 함정의 발동
> 시점을 표현할 수 있는가?"

**아니다.** 그런데 **데이터는 repository 에 있다.** 둘이 다른 층에 있다.

| 층 | 유발 조건 정보 |
|---|---|
| 공식 Lua (`cXXXXXXXX.lua`) | `SetCode(EVENT_FREE_CHAIN)` — **있다** |
| `sources/lua_loader.py` | `spec.code = "EVENT_…"` 로 파싱 — **있다** |
| `core` 의 `Card.script` | `trigger_events` · 효과별 `code` — **있다** |
| `analysis` 의 `effect_model` | `trigger_event: str \| None` — **있다** |
| **`engine` 의 `EffectDefinition`** | **없다** |

`EffectDefinition` 의 필드는 `effect_ref` · `source_card_id` · `operations` ·
`activation` · `cost` · `targets` · `declarations` · `requirements` · `guards` ·
`provenance` 뿐이다. `trigger` / `event` / `timing` 이라는 이름이 **하나도
없다.** 그리고 `engine/` 의 어떤 실행 코드도 `trigger_events` 를 읽지 않는다
(AST 로 확인 — `test_01`).

즉 ADR-006 의 모습 그대로다: 엔진 정의는 손으로 옮기고, **옮기지 않은 것은
모른다.**

---

## §3 — 등재된 함정 **5장** (4장 실행 가능)

Phase 3-E-15 보고서는 "함정 4장" 이라고 적었다. **5장이 맞다** — 세는 기준이
"등재" 와 "실행 가능" 으로 달랐다. 여기서 바로잡는다.

| Trap | Effect Type | Trigger | Condition | Spell Speed | Free Chain | Set-Turn | 현재 상태 |
|---|---|---|---|---|---|---|---|
| 욕망의 선물 (5915629) | ACTIVATE / draw | **없음** | 상대 DECK ≥ 2 | 2 | `EVENT_FREE_CHAIN` | 읽힌다 | 후보 ✗ · **실행 ✓** |
| 벌금 (92595643) | ACTIVATE / discard | **없음** | 자신 HAND ≥ 2 (자신 제외) | 2 | `EVENT_FREE_CHAIN` | 읽힌다 | 후보 ✗ · 실행 ✗ (다리) |
| 강제 탈출 장치 (94192409) | ACTIVATE / return_to_hand | **없음** | (없음) | 2 | `EVENT_FREE_CHAIN` | 읽힌다 | 후보 ✗ · 실행 ✗ (조작 관문) |
| 로스트 (24623598) | ACTIVATE | **없음** | (없음) | 2 | `EVENT_FREE_CHAIN` | 읽힌다 | `executable=False` |
| 의적의 입문서 (69091732) | ACTIVATE / discard | **없음** | 상대 HAND ≥ 5 | 2 | `EVENT_FREE_CHAIN` | 읽힌다 | 후보 ✗ · **실행 ✓** |

### `EVENT_FREE_CHAIN` 의 뜻 (§3 의 경고대로 확인했다)

`EVENT_FREE_CHAIN` 은 **"언제나 발동 가능"이 아니다.** `EFFECT_TYPE_ACTIVATE`
와 함께 쓰여 **"유발 조건이 없다"** 를 뜻한다. 그래도 세트한 턴
(RULE-SPELLTRAP-009) · 스펠 스피드 (RULE-CHAIN-003~006) · 발동 기회(창)는
각각 따로 걸린다.

> `TRAP` ≠ `TRIGGER` · `EVENT_FREE_CHAIN` ≠ `ALWAYS LEGAL`

---

## §4 — 공식 규칙 근거 (repository 자료)

- **RULE-SPELLTRAP-008** (Trap Cards) — "you can activate Trap Cards during
  your opponent's turn"
- **RULE-SPELLTRAP-009** (Normal Trap Cards) — "Before you can activate a Trap
  Card, you must Set it on the field first. You cannot activate a Trap in the
  same turn that you Set it, but you can activate it **at any time after
  that—starting from the beginning of the next turn.**"
- **RULE-SPELLTRAP-010 / 011** — 지속 함정은 필드에 남고, 카운터 함정은 다른
  발동에 응답한다. 각각 `_OUT_OF_SCOPE_TYPES` 의 자기 항목으로 남아 있다.
- Draw Phase / Standby Phase 절 — "Activate Trap Cards, Quick-Play Spell Cards,
  etc." 가 가능한 행동으로 적혀 있다.

"at any time after that" 은 **기회(창)가 있어야** 쓸 수 있다는 뜻이고, 그
기회를 여는 자리가 지금은 **발동 직후 하나**뿐이다 (STRUCTURAL-34 의 나머지).

---

## §6 · §7 — 감사 결과: 막는 곳이 **정확히 하나**다

| Q | 답 |
|---|---|
| Q1 TRAP 전체가 범위 밖인가 | 종류 단위로 막혀 있다. **이유는 종류가 아니라 정보 부족**이다 |
| Q2 특정 family 만인가 | 아니다 — 지금은 구분할 **수단이 없다** |
| Q3 `EVENT_FREE_CHAIN` 함정을 표현할 수 있는가 | **아니다** — `EffectDefinition` 에 자리가 없다 |
| Q4 candidate 를 만들 수 있는가 | 출발지에는 **이미 들어 있다** (Phase 3-E-14) |
| Q5 Timing checker 가 판단할 수 있는가 | **할 수 있다** — 스펠 스피드 2 · 세트한 턴 모두 |
| Q6 Validator 가 판단할 수 있는가 | **아니다 — 여기가 막는 곳이다** |
| Q7 Execution 이 처리할 수 있는가 | **4장 중 2장은 끝까지 된다** |

### 세 계층 측정 (§7 · §8)

```
Action Space   출발지에 있다                               ✓  통과
Timing         스펠 스피드 2 · set_this_turn 읽음           ✓  통과 (VALID)
Validator      "함정이다" → UNKNOWN                        ✗  막는다
Execution      2/4 는 reveal → resolve → 묘지까지 된다      (아래)
```

---

## 감사가 찾아낸 것 — 코드가 **스스로에 대해 거짓**을 적고 있었다

### ① 이유가 거짓이 되어 있었다

`_OUT_OF_SCOPE_TYPES` 의 `TRAP` 항목:

```
"trap-activation-timing (세트가 앞서고 세트한 턴에는 못 쓴다 — RULE-SPELLTRAP-009)"
```

**둘 다 지금 있다.** 세트는 `SET_SPELL_TRAP` 이 하고 (3-E-2), 세트한 턴은
`rule_uses` 가 적고 `ActivationTimingChecker` 가 본다 (3-E-15).

### ② 그 항목은 **닿지 않는 코드**였다

`_activation_out_of_scope` 는 이름 검사보다 **먼저** `definition.is_spell` 을
본다. 함정은 거기서 돌아가므로 `TRAP` 항목까지 **가지 않는다.** 즉 틀린 문장이
아무 영향도 주지 않는 자리에 있었고, 그래서 틀린 채로 남았다.

실제로 나오던 문장은 하나였다.

```
"non-spell-activation-timing (함정 · 몬스터 효과의 발동 타이밍)"
```

**서로 다른 두 공백을 한 문장에 담고 있었다.** 함정은 *유발 조건*을 구분할 수
없고, 몬스터는 *효과 분류*가 없어 스펠 스피드조차 정하지 못한다. 한 문장이면
어느 쪽을 고쳐야 하는지 알 수 없다.

### 고친 것 (판정 결과 변화 0)

- 닿지 않는 `TRAP` 항목을 **지웠다** (표는 5개로 — CONTINUOUS · EQUIP · FIELD ·
  RITUAL · COUNTER).
- 실제로 걸리는 분기에서 함정과 몬스터를 **나눴다**.
  - `TRAP_TRIGGER_MISSING` (`trap-activation-timing`) — "함정의 유발 조건을 효과마다 구분할 수 없다 —
    공식 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다"
  - `MONSTER_ACTIVATION_MISSING` — "기동 · 유발 · 플립 · 유발즉시 분류가 없다"
- 둘 다 **여전히 `UNKNOWN`** 이다. 바뀐 것은 **왜**뿐이다.

§27 조건 검토: (1) 최소 연결 — 이것은 연결이 아니라 **거짓 문장 교정**이다.
(2) 기존 계층만 — 그렇다. (3) 새 subsystem — 없다. (4) `GameStateView` — 변경
0. (5) Evaluation/Search — 변경 0. 판정 결과가 바뀌지 않으므로 **행동 변화
0**이고, 그래서 `ENGINE CHANGE REQUIRED = NO` 로 두되 **틀린 문장은 고쳤다** —
숨기면 다음 사람이 그 문장을 읽고 엉뚱한 곳을 고친다.

---

## §9~§13 — 네 시나리오와 응답 자리

| 시나리오 | 출발지 | set_this_turn | Timing | Validator | 후보 |
|---|---|---|---|---|---|
| ⑨ 자기 턴 · 세트한 턴 | ✓ | `True` | **INVALID** (RULE-SPELLTRAP-009) | UNKNOWN | 0 |
| ⑪ 자기 턴 · 세트한 턴 (같은 자리) | ✓ | `True` | INVALID | UNKNOWN | 0 |
| ⑫ 자기 턴 · 다음 턴 | ✓ | `False` | **VALID** | UNKNOWN | 0 |
| ⑩ 상대 턴 · 응답 창 | ✓ | `False` | **VALID** (2 → 1 응수) | UNKNOWN | 0 |

**세트한 턴에는 이유가 둘이다** — 검증기(UNKNOWN)와 타이밍(INVALID). 하나로
뭉치지 않는다. 그리고 §11 이 요구한 대로 **모든 함정에 무조건 같은 답을 주지
않았다**: 같은 턴은 `INVALID`(규칙이 금지), 다음 턴은 `UNKNOWN`(우리가 모름).

### §7 응답 자리 — 이미 맞다

```
turn_player      = P1   (상대 턴)
priority holder  = P0   (응답 자리)
to_act           = P0
```

셋이 서로 다르고, 우선권이 `turn_player` 를 바꾸지 않는다. 즉 **"turn_player
가 아니라서 invalid" 는 거짓**이다 — 자리는 맞고 막는 것은 검증기다.
`test_15` 가 이 구별을 고정한다 (§24-C).

### 실제 Trace (§25)

```
[SET]       P0 turn=5  욕망의 선물 → SZONE 뒷면   rule_uses{(5,0,#40,set_spell_trap):1}
[TURN]      turn=6  turn_player=P1
[RESPONSE]  P1 욕망의 항아리 → 체인 1 · 창=response · 쥔 자리=P0
[CANDIDATE] P0 후보 = [PASS] 뿐          ← 여기서 멈춘다
[VALIDATE]  UNKNOWN · trap-trigger-timing (유발 조건을 구분할 수 없다)
[APPLY]     도달하지 않음
```

실행이 안 되어서 멈춘 것이 **아니다.** 검증기가 모르기 때문에 멈췄다.

---

## §19 — Execution 경계: **2/4 는 이미 끝까지 간다**

검증기만 열려 있다면(감사용 허가를 넣어 실행 계층만 측정):

| Trap | 결과 |
|---|---|
| 욕망의 선물 | **끝까지 ✓** — reveal → 해결(상대 2장 드로우) → 묘지 |
| 의적의 입문서 | **끝까지 ✓** — reveal → 해결(상대 패 1장) → 묘지 |
| 강제 탈출 장치 | 해결 실패 — `Card.IsAbleToHand` 를 옮기지 못했다 (`RULE_NOT_IMPLEMENTED`) |
| 벌금 | 대상 열거 0개 — `target_combinations` 가 **단일 대상만** 센다 |

**둘의 실패는 함정 때문이 아니다.**

- 강제 탈출 장치 → **조작 관문의 공백.** 마법이 같은 조작을 써도 같다.
- 벌금 → **다리의 한계.** `target_combinations` 가
  `choice.minimum != 1 or choice.maximum != 1` 이면 빈 목록을 돌려준다
  (Phase 3-E-4 범위). 등재된 효과 중 `minimum>1` 인 것은 **벌금 한 장뿐**이므로,
  이 공백은 함정에서 드러났을 뿐 함정의 것이 아니다.

그래서 **`SET_ACTIVATION_EXECUTION` 은 함정에 대해 이미 있다** — Phase 3-E-14
의 `reveal` + `retire` 가 통상 함정의 모양(해결 뒤 묘지)과 같다. 남은 것은
`SET_CARD_EFFECT_EXECUTION`(카드별 조작 · 관문)이고 **그것도 함정 전용이
아니다.**

---

## §15 · §16 · §17 · §18 — 경계와 불변

| | 결과 |
|---|---|
| 상대 세트 함정의 정체 | **비공개** (`card_id`·`name`·`definition` 전부 `None`) |
| 상대의 세트한 턴 | **비공개** — 관측에 그런 필드가 없다 |
| "함정이다" 라는 사실 | **비공개** — 정체를 모르면 종류도 모른다 |
| `GameStateView` 변경 | **0** |
| Evaluation 변경 | **0** (점수 · 항 동일, `agent/` 가 이 Phase 의 대상을 읽지 않음) |
| Search ranking 변경 | **0** |
| RNG | **0** |
| 후보 수 변화 | **0** — 함정은 여전히 0개, 통상 마법은 그대로 |
| STRUCTURAL-34 | **건드리지 않았다** (우선권 · ResponseLoop 변경 0) |

---

## §26 — 성능

판정 결과가 같고 분기 하나가 늘었을 뿐이다. 전체 테스트 시간 **349s → 365s**
로, 유의미한 regression 이 아니다 (후보 수가 한 건도 변하지 않았다 — 늘어난
것은 신규 테스트 18개다).

---

## §23 · §24 — 테스트

### 전체

```
3514 passed, 4 skipped in 365.33s
```

기준선 3496 + 신규 18 = 3514. 실패 0 · skip 증가 0 · 삭제 0.

신규 `tests/engine/test_set_trap_timing_audit.py` — **18개**

1. 다섯 장 전부 `EVENT_FREE_CHAIN` (core 에는 있고 engine 에는 없다, AST 로 확인)
2. 막는 이유가 참이고 **닿는 자리에** 있다
3. 세트한 턴 기록을 **읽기만** 한다 (함정도 같은 표)
4. **막는 곳이 검증기 하나**다 (4장 전부)
5. 같은 턴에는 이유가 **둘**이다 (UNKNOWN + INVALID)
6. 상대 턴 응답 자리는 **이미 맞다** (turn_player ≠ response seat)
7. 두 장은 **실행이 끝까지 된다**
8. 남은 둘의 실패는 **함정과 무관**하다 (조작 관문 · 다리)
9. 상대는 함정이라는 사실조차 모른다
10. 이 Phase 는 행동을 바꾸지 않았다 (후보 · 점수 · 해시 · 난수)
11. clone 독립
12. 새 subsystem 없음
13. **§24-A** 함정을 스펠 스피드 1 로 읽으면 두 규칙이 동시에 무너진다
14. **§24-B** 세트한 턴을 무시하면 같은 턴/다음 턴이 구별되지 않는다
15. **§24-C** 응답 자리를 턴 플레이어와 같다고 보면 상대 턴 응답이 사라진다

### 고의 위반 5건 — 전부 잡힘

| 위반 | 잡은 시험 |
|---|---|
| A 함정을 범위 안으로 들여보낸다 | 7개 |
| A2 함정의 스펠 스피드를 1 로 읽는다 | 5개 (`test_13` 포함) |
| B 세트한 턴을 무시한다 | 8개 |
| C 응답 자리 = 턴 플레이어 | 7개 |
| D 함정과 몬스터를 한 문장으로 되돌린다 | 4개 |

### 수정한 기존 테스트 1건 (삭제 0 · skip 0)

| 테스트 | 틀렸던 가정 |
|---|---|
| `test_effect_action_space_audit::test_05b` | 함정의 `missing_rule` 이 `non-spell-activation-timing` 이라고 기대했다. 함정과 몬스터가 **서로 다른 공백**이므로 문장을 나눴고, 기대값을 `trap-activation-timing` 으로 고쳤다. **판정 결과(`UNKNOWN`)는 그대로**이고 바뀐 것은 이유뿐이다 |

---

## §13 — STRUCTURAL 상태

| | 상태 |
|---|---|
| STRUCTURAL-34 | 유지 (건드리지 않았다) |
| STRUCTURAL-124 · 128 · 131 · 133 | 유지 |
| STRUCTURAL-134 | RESOLVED 유지 |
| `SET_ACTIVATION_MISSING` | RESOLVED 유지 |
| `SET_ACTIVATION_TIMING` | **열려 있음** — 기회(창)를 여는 자리가 발동 직후 하나뿐이다 (STRUCTURAL-34 의 나머지) |
| `SET_ACTIVATION_EXECUTION` | **함정에 대해서는 이미 있다** — `reveal` + `retire` 가 통상 함정의 모양과 같다 (2/4 가 끝까지 돌아간다) |
| `SET_CARD_EFFECT_EXECUTION` | 열려 있음 — 카드별 조작 관문(`IsAbleToHand`)과 다리의 다중 선택. **둘 다 함정 전용이 아니다** |

---

## §14 — 새로 발견된 문제

**신규 STRUCTURAL ID 를 만들지 않았다.** 다만 아래 둘을 기록한다.

1. **`_OUT_OF_SCOPE_TYPES` 의 `TRAP` 항목이 닿지 않는 코드였다** — 틀린 이유가
   영향 없는 자리에 있어 오래 남았다. 이번에 지우고 실제 자리로 옮겼다.
   (해결했으므로 TODO 아님.)
2. **`target_combinations` 가 다중 선택을 열거하지 못한다** — 등재된 효과 중
   벌금 한 장만 해당한다. Phase 3-E-4 의 범위이고 함정과 무관하므로 이번
   Phase 에서 고치지 않았다.

---

## §15 — 다음 Phase 후보 (하나)

**`EffectDefinition` 에 "유발 조건이 없다" 를 옮기는 일.**

이번 감사가 그 설계를 좁혀 두었다.

- 데이터는 **이미 repository 에 있다** — `Card.script` 의 효과별 `SetCode`.
  새 파서도 새 데이터 수집도 필요하지 않다.
- 엔진은 그 필드를 **읽지 않는다** (AST 로 확인). 그래서 추가는 "읽기 시작"
  하나다.
- 그것이 생기면 `TRAP_TRIGGER_MISSING` 의 이유가 사라지고, 검증기는 종류가
  아니라 **효과마다** 판정할 수 있다 — 유발 조건 없는 함정만 범위에 들어온다.
- 실행은 2/4 가 이미 되므로, 그 Phase 의 결과는 "후보가 생기고 그중 둘은 끝까지
  돌아간다" 가 된다.

첫 질문: **"유발 조건 없음" 을 `EffectDefinition` 에 어떤 모양으로 적는가** —
`activation` 조건과 섞지 않고, `None`("적지 않았다")과 "없다고 확인했다" 를
구분할 수 있는 모양이어야 한다. 그 구분을 못 하면 옮기지 않은 카드가 "유발
조건 없음" 으로 읽힌다.
