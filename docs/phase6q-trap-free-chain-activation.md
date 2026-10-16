# Phase 6-Q — 함정 카드 발동 조건 및 EVENT_FREE_CHAIN 실행 경로 연결

작성: 2026-10-16 · 브랜치 `claude/pensive-goodall-te1egy` · 기준 `8ba9932` (Phase 6-P)

---

## 0. 한 줄 요약

🔴 **수준 3 달성.** 세트한 일반 함정이 `legal_actions` → `ActionValidator` →
체인 → `EffectExecutor` → `GameState` → `EventJournal` 를 **끝까지** 지난다.
상대 턴의 응답 창에서 **체인 2** 로 발동해 **역순으로** 해결되는 것까지
실측했다.

막고 있던 것은 한 문장이 **스스로 적어 둔 빈 칸** 하나였다.

> `TRAP_TRIGGER_MISSING` — *"함정의 유발 조건을 효과마다 구분할 수 없다 —
> 공식 스크립트의 `SetCode(EVENT_*)` 가 `EffectDefinition` 에 없다"*

**그 진단은 맞았다.** 그래서 6-Q 는 관문을 없애지 않고 그 칸을 만들었다
(`EffectDefinition.activation_waits_for_event`). 카드 종류로 종류 전체를
통과시키는 것이 아니라 **적어 둔 사실에만** 답한다.

🔴 **그리고 `EVENT_FREE_CHAIN` 을 엔진에 싣지 않았다.** 그 이름은 Lua 내부
태그이고 공식 규칙의 개념이 아니다 (§3). 옮긴 것은 그 태그가 답하는 **질문
하나**다.

---

## 1. 기존 함정 발동 정보와 실제 코드 구조 (§4-A · §17-1)

| 질문 (§4-A) | 답 | 어디에 |
|---|---|---|
| 1. 함정 발동 정보는 어디에 저장되는가 | `core` 의 `Card.script` — `EffectSpec.effect_types` + `EffectSpec.code` | `core/card_model.py` |
| 2. `EffectDefinition` 에 사건 코드가 있는가 | 🔴 **없었다** → 6-Q 가 `activation_waits_for_event` 를 만들었다 | `engine/effect/definition.py` |
| 3. `EVENT_FREE_CHAIN` 이 어떤 경로로 전달되는가 | ⚪ **엔진으로 전달되지 않는다.** `engine/trigger_compiler.py` 가 `EffectSpec.code` 를 읽지만 `TRIGGER_O`/`TRIGGER_F` 블록만 본다 (`ACTIVATE` 블록은 `None` 을 돌려주고 끝난다) | `trigger_compiler.compile_trigger_spec` |
| 4. 카드 자체의 발동과 카드 효과의 발동을 구분할 수 있는가 | 🟢 **구분된다.** `EFFECT_TYPE_ACTIVATE`(카드 발동) vs `ActivationKind`(몬스터 효과 분류). `ActivationKind` 가 스스로 *"마법 · 함정의 발동도 여기 없다"* 고 적는다 | `engine/vocabulary.py` |
| 5. 함정에 여러 효과가 등록된 경우 | ⚪ **등재된 다섯 장 전부 `ACTIVATE` 블록 하나다** (실측). 둘 이상인 경우를 다루지 않는다 |

### 1-1. 실측 — 등재된 함정 다섯 장

```
  5915629 욕망의 선물      types=['TRAP']  [e1] ACTIVATE  code='EVENT_FREE_CHAIN'  exec=True
 92595643 벌금            types=['TRAP']  [e1] ACTIVATE  code='EVENT_FREE_CHAIN'  exec=True
 94192409 강제 탈출 장치    types=['TRAP']  [e1] ACTIVATE  code='EVENT_FREE_CHAIN'  exec=True
 24623598 로스트          types=['TRAP']  [e1] ACTIVATE  code='EVENT_FREE_CHAIN'  exec=False
 69091732 의적의 입문서     types=['TRAP']  [e1] ACTIVATE  code='EVENT_FREE_CHAIN'  exec=True
```

🔴 **전부 일반 함정**(`['TRAP']`)이다 — 지속 · 카운터가 **0장**. 이 수가
§6 의 범위를 정했다.

---

## 2. `TRAP_TRIGGER_MISSING` 의 정확한 원인 (§17-2)

### 2-1. 발생 위치 — 한 줄

`engine/action_validation.py` 의 `_activation_out_of_scope`:

```python
if not definition.is_spell:
    if "TRAP" in set(definition.type_names):
        return (("함정이다", TRAP_TRIGGER_MISSING),)      # ← 여기
```

그 함수를 두 곳이 부른다.

1. `_normal_spell_activation` — 요구 목록을 만들 때 (범위 밖이면 `always` 만)
2. `_NormalSpellActivation.evaluate` — 조건으로서 `UNKNOWN` 을 돌려줄 때

### 2-2. `legal_actions` 에서 빠지는 경로 (§4-B)

```
Duel.legal_actions(seat)
  → 응답 창이 열려 있고 이 자리가 쥐었는가 / 아니면 턴 플레이어인가
  → Duel._activation_actions(seat, validator)
      → _activation_sources(seat)         🟢 SZONE 포함 — 함정이 **나온다**
      → activatable_effects(card_id)      🟢 등재되어 있다
      → definition.cost.costs             🟢 비용 0 (등재 17개 전부)
      → target_combinations(...)          🟢 대상도 찾는다 (6-P 가 열었다)
      → Duel._activation_gate(...)
          ① ActionValidator.validate      🔴 **여기서 UNKNOWN**
          ② ActivationTimingChecker.check    (닿지 않았다)
          ③ EffectActivator.can_activate     (닿지 않았다)
```

### 2-3. "후보가 없다" 와 "발동 불가" 는 구분된다 (§4-B-4)

🟢 구분된다. 출발지에는 **있고**(`_activation_sources` 에 나온다) 막힌
이유가 `missing_rule` 로 **기록으로 남는다**. 6-Q 전 실측:

| 카드 | 조합 | `legal_actions` | `validate` |
|---|---|---|---|
| 욕망의 선물 | 1 | **0** | `unknown` / `RULE_NOT_IMPLEMENTED` |
| 벌금 | 10 | **0** | `unknown` / `RULE_NOT_IMPLEMENTED` |
| 강제 탈출 장치 | 1 | **0** | `unknown` / `RULE_NOT_IMPLEMENTED` |
| 로스트 | 1 | **0** | `unknown` / `RULE_NOT_IMPLEMENTED` |
| 의적의 입문서 | 1 | **0** | `unknown` / `RULE_NOT_IMPLEMENTED` |

🔴 **다섯 장 전부 같은 한 자리에서 막혔다.** 다른 어떤 관문도 거절하지
않았다 (§2-4 가 그것을 센다).

### 2-4. Phase 6-P 의 실행 경로가 검증을 우회했는가 (§2-6)

🔴 **그렇다 — 6-P 보고서가 그 사실을 적었고, 6-Q 가 다시 측정해 확인했다.**

6-P 의 실행은 `force_resolve`(= `_force_execute` 와 같은 태도)로 **허가를
손으로 넣은** 경로였고, 6-P 는 그래서 수준 3 을 주장하지 않았다
(`docs/phase6p-…md` §11-2 · §20). 6-O 의 실행 사례도 같다.

🟢 **6-Q 는 그 우회를 없앴다.** 아래의 모든 실행은 `legal_actions` 가 만든
`PlayerAction` 을 `Duel.apply` 에 그대로 넣은 것이다.

---

## 3. `EVENT_FREE_CHAIN` 과 `EffectDefinition` 의 관계 (§5 · §17-3)

### 3-1. 🔴 그 태그를 엔진에 싣지 않았다

| 측정 | 결과 |
|---|---|
| 공식 자료(룰북 원문 · 구조화본 · 재정 686파일 · 한국어 공식 DB)에 "Free Chain" | **0회** |
| 필드 마법(공식 스펠 스피드 1, 아무것에도 대응 불가)의 `ACTIVATE` 블록 중 `EVENT_FREE_CHAIN` | 312/312 = **100%** |
| 카운터 함정(공식 스펠 스피드 3, 모든 것에 대응 가능)의 같은 비율 | 3/220 = **1.4%** |

🔴 **공식 속도와 반대 방향으로 70배 차이가 난다.** 그래서 그 태그는 스펠
스피드도, 공식 "체인 가능성" 도 아니다 (Phase 3-F-25 가 처음 측정했고 6-Q 가
재측정했다 — `test_a04`).

### 3-2. 그 태그가 **답하는 질문 하나**만 옮겼다

```
EffectDefinition.activation_waits_for_event: bool | None = None
    None   적지 않았다 ("사건을 기다리지 않는다" 가 아니다)
    True   특정 사건이 와야 발동한다 → 범위 밖 (엔진이 그 사건을 못 만든다)
    False  사건을 기다리지 않는다 → 범위 안
```

**새 열거형을 만들지 않았다** — `ActivationTiming.set_this_turn` 과 같은
`bool | None` 모양이고, 그 세 값 규율은 이 저장소에 이미 있다 (§16 의
"기존 카드 발동 정보를 재사용할 수 있다면 새로운 타입을 추가하지 않는다").

### 3-3. 신호가 **완전한가** — 측정

`ACTIVATE` 블록은 `SetCode` 를 **반드시** 부른다.

| `effect_types` | 블록 | `EVENT_FREE_CHAIN` | `code is None` |
|---|---|---|---|
| `ACTIVATE` | 4,297 | 3,639 (85%) | **0** |
| `QUICK_O` | 1,875 | 1,257 (67%) | **0** |
| `IGNITION` | 4,137 | 17 (0%) | 4,119 (99.6%) |

🔴 `ACTIVATE` 블록에서 `code is None` 이 **0건**이므로 이 축에는 "읽지 못한
칸" 이 없다. 그것이 이 질문에 한해 신호가 쓸 만한 이유다.

### 3-4. 🔴 손으로 적었다 (ADR-006)

12,968장을 자동 변환하지 않았다. 등재된 **다섯 장**에만 `False` 를 적고,
각 자리에 근거 Lua 파일명을 주석으로 남겼다. 마법 · 몬스터에는 적지
않았다 (`test_a02` 가 센다) — 축을 전부에 뿌리면 "적지 않았다" 가 어디인지
알 수 없게 된다.

---

## 4. 일반 · 지속 · 카운터 함정의 기존 지원 범위 (§6 · §17-4)

| 종류 | 룰북 | 판정 | 왜 |
|---|---|---|---|
| **일반 함정** | RULE-SPELLTRAP-009 — *"you must Set it on the field first … you cannot activate a Trap in the same turn that you Set it, but you can activate it **at any time after that**"* | 🟢 **이번 범위** | 룰북이 발동 시점을 **문장으로 확정**했다 (6-K 가 기동 효과를 고른 것과 같은 기준) |
| 지속 함정 | RULE-SPELLTRAP-010 — *"remain on the field once they are activated"* | 🔴 범위 밖 | 발동 뒤 필드에 남는 수명 계층이 없다 |
| 카운터 함정 | RULE-SPELLTRAP-011 — *"normally activated **in response to the activation of other cards**"* | 🔴 범위 밖 | 응답 전용 타이밍 계층이 없다 |

🔴 **`_OUT_OF_SCOPE_TYPES` 가 6-Q 전까지 함정에 닿지 않고 있었다.** 3-E-16 이
그 사실을 적어 두었다 (*"그 항목은 닿지 않는 코드였다"*). 6-Q 가 함정 분기를
열면서 **그 표를 함정에도 적용했다** — 즉 여는 동시에 **막는 것을 늘렸다**
(`test_c01` · `test_c02`).

지속 · 카운터가 저장소에 0장이므로, 그 가지는 종류 이름을 손으로 붙인
**지어낸 정의**로 직접 재었다.

---

## 5. 세트 턴 및 발동 위치 판정 결과 (§9 · §17-5)

| §9 질문 | 답 |
|---|---|
| 1. 세트된 함정인가 | 🟢 `_points_at_set_trap` — 정의(`is_trap`) + 자리(`SZONE`) + 표시(뒷면) |
| 2. 어느 턴에 세트됐는가 | 🟢 `GameState.rule_uses` 가 `(턴, 플레이어, instance_id, SET_SPELL_TRAP)` 로 적는다 |
| 3. 현재 턴 | 🟢 `TurnState.turn_number` |
| 4. 카드 효과로 제한이 달라지는가 | ⚪ **표현할 수 없다.** 그런 효과가 등재되어 있지 않고, 없는 것을 미리 만들지 않았다 |
| 5. 필드를 떠났다가 다시 세트되면 | 🟢 기록은 `instance_id` 단위이므로 새 세트가 새로 기록된다 (같은 인스턴스면 그 턴 기록이 갱신된다) |
| 6. 이미 앞면인 지속 함정의 효과 발동 | 🔴 **범위 밖.** 앞면 함정은 `_points_at_set_trap` 이 거짓이므로 `TRAP_NOT_SET` 이다 (`test_d05`) |

### 5-1. 실측

| 상황 | `_set_this_turn` | `legal_actions` | 막는 계층 |
|---|---|---|---|
| 세트한 턴 | `True` | **0건** | `ActivationTimingChecker` → `SET_THIS_TURN` · **INVALID** |
| 다음 턴 | `False` | **있다** | — |
| 모른다 (값을 넘기지 않음) | `None` | — | `ActivationTimingChecker` → `SET_TURN_MISSING` · **UNKNOWN** |
| 패에 있다 | — | **0건** | `ActionValidator` → `TRAP_NOT_SET` · **UNKNOWN** |
| 앞면으로 돌아간 함정 | — | **0건** | `ActionValidator` → `TRAP_NOT_SET` · **UNKNOWN** |

🔴 **세트한 턴을 막는 것은 검증기가 아니다.** 검증기는 통과시키고 타이밍
계층이 `INVALID` 로 막는다 — 두 관문이 서로 다른 사실을 본다는 증거이고,
`test_d01` 이 그 둘을 함께 센다.

### 5-2. 🟡 패의 함정을 `INVALID` 로 적지 않은 이유

룰북은 *"you must Set it on the field first"* 라고 하므로 패에서의 발동은
**규칙이 금지하는 일**이고 `INVALID` 로 적을 수 있다. 그러나 발동 **위치**는
이 관문이 이미 범위 조건으로 다루고 있고 (마법도 그렇다), 한 질문에
`INVALID` 와 `UNKNOWN` 두 길을 두면 둘이 갈라진다. `UNKNOWN` 은 허가가
아니므로 **안전한 쪽으로 틀린다.** 보수적 선택임을 적어 둔다.

---

## 6. 체인 · 타이밍 · 우선권 검증 결과 (§10 · §17-6)

### 6-1. 🔴 열기 전에 **있어야 했던 일곱 가지** — 전부 있었다

`F` 절이 하나씩 센다. 하나라도 없었다면 관문을 열어서는 안 됐다.

| # | 무엇 | 어디에 | 근거 |
|---|---|---|---|
| ① | 스펠 스피드 2 · 3 | `classify_spell_speed` — **카드 종류**에서 나온다 | RULE-CHAIN-005 · 006 |
| ② | 응수 가능 여부 | `RESPONSE_TABLE` — 룰북의 표 그대로이고 **테스트가 대조한다** | RULE-CHAIN-003 · 004 |
| ③ | 세트 기록 | `GameState.rule_uses` | — |
| ④ | 세트한 턴 제약 | `ActivationTimingChecker._set_turn_refusal` — **스펠 스피드로 가른다** | RULE-SPELLTRAP-007 · 009 |
| ⑤ | 응답 창 · 우선권 | `PriorityState` + `Duel.legal_actions` 의 창 검사 | RULE-CHAIN-001 · 009 |
| ⑥ | 카드별 조건 · 비용 · 대상 | `EffectActivator.can_activate` | — |
| ⑦ | 발동 절차 (앞면 → 해결 → 묘지) | `NormalSpellPlacement.reveal` / `retire` | RULE-SPELLTRAP-009 |

### 6-2. 실측된 타이밍 결과

| 상황 | 결과 |
|---|---|
| 체인이 비었고 내 턴 | 🟢 후보가 된다 |
| 체인이 열렸고 내가 응답 자리 | 🟢 후보가 된다 (스펠 스피드 2 → 1) |
| **상대 턴 · 창이 닫혀 있음** | 🔴 **후보가 아니다** — 기존 우선권 모델이 턴 플레이어만 허용한다 |
| 스펠 스피드가 맞지 않음 | 🟢 `SPELL_SPEED_TOO_LOW` · INVALID (마법 1 로 함정 2 에 응수 불가) |
| 발동 조건 미충족 | 🟢 발동 계층이 거른다 (`test_e03` — 상대 패를 비우면 후보가 사라진다) |

### 6-3. 🔴 체인 링크 생성 ≠ 효과 해결

`Duel.apply` 가 받아들이면 **체인 링크만** 생기고 응답 창이 열린다.
해결은 양쪽이 패스한 뒤다 (RULE-CHAIN-001). 실측: 발동 직후 상대 패가
**변하지 않고**, `settle_chain` 뒤에 변한다 (`test_g01`). 그 둘을 섞어
"발동했으니 해결됐다" 고 적지 않는다.

---

## 7. 선정한 최소 대표 사례 (§7 · §17-7)

| # | 확인 사항 | 벌금 (92595643) | 대표로 쓴 다른 카드 |
|---|---|---|---|
| 1 | 실제 카드 텍스트 | "자신은 패를 2장 버린다." | 욕망의 선물 · 강제 탈출 장치 |
| 2 | 함정 종류 | **일반 함정** (`['TRAP']`) | 같음 |
| 3 | Lua 등록 정보 | `ACTIVATE` + `EVENT_FREE_CHAIN` | 같음 |
| 4 | `EffectRef` | `92595643:e[0]` | — |
| 5 | `EffectDefinition` | 있다 · `executable=True` | — |
| 6 | 발동 조건 | `ZoneCountAtLeast(CONTROLLER, HAND, 2)` | 의적의 입문서: 상대 패 5장 |
| 7 | 비용 | **없다** | 등재 17개 전부 없다 |
| 8 | 대상 · 선택 절차 | `choosing` · 정확히 2장 (6-P) | — |
| 9 | 해결 연산 | `CardOperation.discard` | — |
| 10 | 누락 지점 | `ActionValidator` (§2) | 같음 |

**세 장을 함께 썼다.** 벌금은 §11-N(다중 선택)을, 욕망의 선물은 대상 없는
가장 단순한 경로를, 강제 탈출 장치는 §11-F(상대 턴 · 체인 2)를 가장 잘
드러낸다. 카드 ID 분기는 **프로덕션에 0건**이다 (`test_e05`).

---

## 8. 선택한 구현 방식과 대안 비교 (§8 · §17-8)

### 8-1. 채택

```
EffectDefinition.activation_waits_for_event   ← 손으로 적은 사실 (ADR-006)
        ↓  _declared_activation_event(validator, action)      ← 등록소에서 읽는다
_activation_out_of_scope(..., waits_for_event)
        ↓  _trap_activation_out_of_scope(...)                 ← 네 갈래
   지속·카운터 → _OUT_OF_SCOPE_TYPES | None → TRAP_TRIGGER_MISSING
   True → TRAP_EVENT_UNSUPPORTED      | 세트 아님 → TRAP_NOT_SET
        ↓  범위 안이면
activation_is_set_trap(...) → 요구는 ``always`` 뿐 (좁은 요구를 걸지 않는다)
        ↓
기존 ActionValidator → ActivationTimingChecker → can_activate → 체인 → 실행기
```

**`_declared_activation_kind` 와 같은 모양**이다 (Phase 6-K) — 새 경로를
만들지 않고 이미 있는 자리를 하나 더 지난다.

### 8-2. 고르지 않은 대안

| 대안 | 왜 쓰지 않았나 |
|---|---|
| 카드 종류만 보고 함정 전체 통과 | 🔴 일반 함정 `ACTIVATE` 블록 1,386개 중 **390개(28.1%)** 가 사건을 적는다 (`EVENT_ATTACK_ANNOUNCE` 96 등). 그 390개가 아무 때나 발동하게 된다 |
| `EVENT_FREE_CHAIN` 문자열을 `EffectDefinition` 에 싣기 | §3-1 — Lua 내부 태그이고 공식 개념이 아니다. 실으면 그 뜻풀이가 엔진의 규칙처럼 굳는다 |
| `EffectSpec.code` 에서 자동 변환 | ADR-006 — `ACTIVATE` 블록 4,297개를 한꺼번에 판정으로 바꾸는 일이다 |
| `ActivationKind` 에 멤버 추가 | 그 열거형이 스스로 *"마법 · 함정의 발동도 여기 없다"* 고 적는다. 같은 질문에 답하는 자리를 둘로 만들면 갈라진다 |
| `activation=UnimplementedRule(...)` 로 표현 | 🔴 Phase 6-F 가 **고친 실수**다 — 조건은 판 위의 사실을 묻는 것이고 "어떤 사건인가" 는 사건의 성질이다 |
| 새 `Enum` 추가 | §16 — `bool \| None` 로 표현된다 (`set_this_turn` 과 같은 모양) |
| 우선권 모델을 고쳐 상대 턴에 창을 열기 | §10 · §15 — 체인 · 우선권 재설계는 범위 밖이다. §19-1 에 BLOCKER 로 적었다 |

### 8-3. 하위 호환성 (§3-1 · §3-2)

- `EffectDefinition` 에 **기본값 있는 필드 하나**를 더했다 → 기존 생성 코드 전부 그대로 동작한다 (Phase 6-K 가 `activation_kind` 로 한 것과 같다).
- `PlayerAction` · `GameState` · `EffectRef` 의 공개 계약은 **한 글자도** 바뀌지 않았다.
- `_activation_out_of_scope` 의 새 인자는 **기본값 `None`** 이므로 기존 호출자가 그대로 쓴다.

---

## 9. 변경 파일과 함수 (§17-9)

| 종류 | 파일 | 증감 |
|---|---|---|
| production | `engine/action_validation.py` | **+179 −6** |
| production | `engine/effect/definition.py` | **+45 −0** |
| production | `engine/effect/library.py` | **+50 −0** (주석 + 다섯 줄) |
| 테스트(신규) | `tests/engine/test_trap_activation_free_chain.py` | 35개 |
| 테스트(수정) | `tests/engine/test_set_trap_timing_audit.py` | +69 −19 |
| 테스트(수정) | `tests/engine/test_set_turn_record.py` | +43 −15 |
| 테스트(수정) | `tests/engine/test_set_card_activation.py` | +40 −13 |
| 테스트(수정) | `tests/engine/test_multi_target_selection.py` | +38 −13 |
| 테스트(수정) | `tests/engine/test_effect_activation_path.py` | +21 −1 |
| 보고서 | `docs/phase6q-trap-free-chain-activation.md` | 신규 |

### 9-1. 함수별

| 이름 | 무엇 |
|---|---|
| `EffectDefinition.activation_waits_for_event` (신규) | 손으로 적은 세 값 축 |
| `TRAP_EVENT_UNSUPPORTED` (신규) | "기다린다고 적혀 있는데 사건을 못 만든다" |
| `TRAP_NOT_SET` (신규) | "세트가 앞서야 한다" (RULE-SPELLTRAP-009) |
| `_declared_activation_event` (신규) | 등록소에서 축을 읽는다 (`None` = 모른다) |
| `_trap_activation_out_of_scope` (신규) | 네 갈래 — 종류 표 · `None` · `True` · 세트 아님 |
| `_points_at_set_trap` (신규) | 정의 + 자리 + 표시 형식을 함께 본다 |
| `activation_is_set_trap` (신규) | 요구 생성기가 함정 분기를 고르는 술어 |
| `_activation_out_of_scope` (수정) | 인자 하나 추가 · 함정 분기 교체 |
| `_NormalSpellActivation` (수정) | 축을 들고 `canonical_state` 에 넣는다 |
| `_normal_spell_activation` (수정) | 축을 읽고 함정 분기를 둔다 |

🔴 **새 엔진 · 새 체인 엔진 · 새 데이터 타입 0개.** 축은 `bool | None` 이고
사유는 `str` 상수다.

---

## 10. `legal_actions` 의 전후 결과 (§13 · §17-10)

같은 판(세트 다음 턴 · 상대 몬스터 1장 · 상대 패 6장):

| 카드 | 조합 | `legal_actions` 전 | `legal_actions` 후 |
|---|---|---|---|
| 욕망의 선물 | 1 | 0 | **1** |
| **벌금** | **10** | 0 | 🔴 **10** |
| 강제 탈출 장치 | 1 | 0 | **1** |
| 로스트 (`executable=False`) | 1 | 0 | **0** ← 발동 계층이 막는다 |
| 의적의 입문서 | 1 | 0 | **1** |

🔴 **로스트가 0건인 것이 중요하다.** 검증기는 통과시키는데 후보가 되지
않는다 — ADR-006 의 "등재 ≠ 실행 허가" 가 지켜진다는 증거다 (`test_e04`).

### 10-1. 🔴 불법 후보 수 = **0건**

| 재어 본 불법 상황 | 후보 |
|---|---|
| 세트한 턴 | **0** |
| 패에 있는 함정 | **0** |
| 앞면으로 돌아간 함정 | **0** |
| 사건을 기다리는 함정 (지어낸 축) | **0** |
| 지속 · 카운터 함정 (지어낸 종류) | **0** |
| 축을 적지 않은 함정 (등록소 없음) | **0** |
| 발동 조건 미충족 (상대 패 < 5) | **0** |
| `executable=False` | **0** |
| 상대 턴 · 응답 창 닫힘 | **0** |
| 상대의 후보 목록에 내 함정 | **0** (정보 누출 없음) |

---

## 11. `ActionValidator` 의 전후 결과 (§17-11)

| 검증기 | 전 | 후 |
|---|---|---|
| 등록소를 **받은** 검증기 (생산 경로) | `unknown` / `TRAP_TRIGGER_MISSING` | 🟢 `valid` / `OK` |
| 등록소를 **받지 못한** 검증기 | `unknown` / `TRAP_TRIGGER_MISSING` | 🔴 **그대로** `unknown` / `TRAP_TRIGGER_MISSING` |

🔴 **막는 것이 카드 종류가 아니라 적어 둔 사실이 되었다.** 같은 판 · 같은
카드 · 같은 관문인데 등록소를 주었는지만 다르고 답이 갈린다
(`test_b01` · `test_b02`, 그리고 `test_set_trap_timing_audit::test_04` 가
네 장으로 같은 것을 센다).

---

## 12. 실제 체인 생성 및 해결 여부 (§17-12)

### 12-1. 내 턴 — 욕망의 선물

```
legal_actions(P0) → ACTIVATE_EFFECT(5915629:e[0])
Duel.apply       → accepted · 체인 링크 1개 · 응답 창 열림
                   🔴 이 시점에 상대 패는 **변하지 않았다**
settle_chain     → 해결
GameState        → 상대 패 0 → 2 · 함정 자신 SZONE → GRAVE
```

### 12-2. 🔴 상대 턴 — 강제 탈출 장치가 **체인 2**

```
1. P0 가 자기 턴에 강제 탈출 장치를 세운다
2. P1 의 턴 — P1 이 욕망의 항아리를 발동 → 체인 1 · 응답 창 열림
3. priority.window is RESPONSE · holds(P0) · turn_player == P1
4. 🔴 legal_actions(P0) 에 함정이 **있다** (스펠 스피드 2 → 1, RULE-CHAIN-005)
5. Duel.apply → 체인 2
6. settle_chain → **역순 해결**
```

EventJournal 의 `EffectEvent` 순서 (실측):

```
#3 EffectEvent 94192409:e[0]   ← 체인 2 (함정) 가 먼저
#4 EffectEvent 55144522:e[0]   ← 체인 1 (마법) 이 나중
```

🔴 **역순 해결이 기록으로 증명된다** (RULE-CHAIN-001 의 "resolve the outcome
in reverse order"). 이 경로는 마법으로는 만들 수 없다 — 함정이라서 된다.

---

## 13. GameState 와 EventJournal 변경 (§17-13)

### 13-1. 상대 턴 · 체인 2 (`test_g02`)

| 항목 | 전 | 후 |
|---|---|---|
| 대상 몬스터 | `MZONE` (P1) | **`HAND`** (주인에게) |
| 상대 패 | 0 | **3** (되돌린 1 + 드로우 2) |
| 함정 자신 | `SZONE` 뒷면 | **`GRAVE`** |
| 체인 길이 | 0 → 1 → **2** → 0 |

### 13-2. 다중 선택 (`test_g03`, Phase 6-P 회귀)

| 항목 | 전 | 후 |
|---|---|---|
| `legal_actions` 후보 | — | **10개** (조합 전부) |
| 패 | 5 | **3** |
| 묘지 | 0 | **3** (버린 2 + 벌금) |
| `EffectEvent` | — | 1개 / `applied` 1개 / `instances` **2장** |

🔴 **실행되지 않은 후보를 성공으로 적지 않는다** (§11-K): 발동 직후에는
`EffectEvent` 가 없고 `ActionEvent`(앞면으로 돌림)만 있다. `EffectEvent` 는
해결된 뒤에만 생긴다.

---

## 14. Phase 6-P 다중 선택 회귀 (§17-14)

🔴 **6-P 의 남은 BLOCKER 가 바로 이것이었다.**

6-P 보고서 §17-1 이 적었다 — *"등재된 함정 5장 중 실행 가능한 4장이
`legal_actions` 에 전혀 오르지 못한다 — 벌금(다중 대상)과 강제 탈출 장치
(6-O)를 포함한다."* 6-Q 가 그것을 닫았다.

| 6-P 의 수준 3 항목 | 6-P | 🔴 6-Q 이후 |
|---|---|---|
| 실제 Duel 에서 **합법적인** 효과를 발동한다 | 🔴 아니다 (허가 주입) | 🟢 **`legal_actions` → `apply`** |
| 복수 대상을 기존 계약으로 선택한다 | 🟢 | 🟢 조합 10개 전부가 적법한 행동 |
| 기존 `EffectExecutor` 가 해결한다 | 🟢 | 🟢 |
| 실제 GameState 변경 | 🟢 | 🟢 패 5→3 · 묘지 0→3 |
| EventJournal 일치 | 🟢 | 🟢 |
| 어니스트 · 6-O 유지 | 🟢 | 🟢 |

그래서 6-P 의 타깃 테스트 `test_g01` 의 **이름이 거짓**이 되었고
(`..._is_still_not_a_legal_action`), 과거형이 아니라 현재형으로 바꿨다
(§17-2).

---

## 15. 기존 어니스트와 ACTIVATE 효과 회귀 (§17-15)

| 회귀 | 결과 |
|---|---|
| **통상 마법** (욕망의 항아리) | 🟢 상대 턴 · 배틀 페이즈에서 `INVALID` / `NOT_TURN_PLAYER` — 함정에 요구를 걸지 않은 것이 마법에서 풀린 것이 **아니다** |
| **세트한 속공 마법** (리로드) | 🟢 세트한 턴 0건 · 다음 턴 1건 (Phase 3-E-15 그대로) |
| **어니스트** (6-L `SELF_TARGET`) | 🟢 `references_self=True`, 축은 `None` (함정이 아니므로 읽히지 않는다) |
| **6-O 카드 이동** | 🟢 `MZONE → HAND` · 상대 패 +1 (이제 `legal_actions` 경유로) |
| **6-P 다중 선택** | 🟢 §14 |
| **꽉 찬 마법 & 함정 존** | 🟢 패의 마법은 `ZONE_FULL`, 세트된 함정은 후보 (자기 칸에 있다) |
| **읽기 멱등성** | 🟢 `legal_actions` 를 3회 불러도 `state_hash` · 난수 소비가 그대로 |
| **비공개 정보** | 🟢 상대의 후보 목록에 내 함정이 없고, 상대 관측에 정체가 없다 |

---

## 16. 불법 발동 거절 및 UNKNOWN 유지 결과 (§12 · §17-16)

§12 의 열한 가지 오류를 **하나씩** 재었다.

| §12 오류 | 방지 | 재는 시험 |
|---|---|---|
| `EVENT_FREE_CHAIN` 만 보고 발동 허용 | 🟢 그 태그를 엔진이 읽지 않는다 | `test_a04` |
| 세트한 턴 제한 무시 | 🟢 `SET_THIS_TURN` · INVALID | `test_d01` |
| 지속 · 일반 함정 혼동 | 🟢 `_OUT_OF_SCOPE_TYPES` 가 함정에 닿는다 | `test_c01` · `test_c02` |
| 카드 발동과 앞면 카드 효과 발동 혼동 | 🟢 앞면 함정은 `TRAP_NOT_SET` | `test_d05` |
| 효과 조건 · 비용 누락 | 🟢 `can_activate` 가 거른다 | `test_e03` |
| 대상 선택 미지원인데 임의 선택 | 🟢 `target_combinations` 가 조합을 만들고 (6-P), 모르는 모양은 빈 목록 | 6-P 의 `test_d0*` |
| 우선권 없이 체인 링크 생성 | 🟢 창이 닫히면 후보가 아니다 | `test_f04` |
| 스펠 스피드 위반 | 🟢 `RESPONSE_TABLE` — 룰북 표와 대조 | `test_f02` |
| 실제 `EffectDefinition` 없이 성공 표시 | 🟢 등록소가 없으면 `UNKNOWN` | `test_b01` |
| 상태 변경 없이 해결 성공 기록 | 🟢 `EffectEvent` 는 해결 뒤에만 | `test_g01` |
| `legal_actions` 밖의 실행을 성공으로 보고 | 🟢 **모든 실행이 `legal_actions` 경유다** | `test_g01`~`g03` |
| 기존 `UNKNOWN` 을 무조건 `VALID` 로 | 🟢 "적지 않았다" 는 여전히 `UNKNOWN` | `test_b01` · 움직인 핀 넷 |

---

## 17. 타깃 · 통합 · 최종 회귀 테스트 결과 (§14 · §17-17)

### 17-1. 신규 — `tests/engine/test_trap_activation_free_chain.py` (35개)

| 절 | 무엇 | 개수 |
|---|---|---|
| A | 감사 — 다섯 장 전부 일반 함정 · 축을 적은 곳 · 룰북 문장 대조 · "Free Chain" 0회 | 4 |
| B | 축이 판정을 가른다 — 등록소 유무 · `True` 거부 · `canonical_state` | 4 |
| C | 지속 · 카운터는 범위 밖 — 표가 함정에 닿는다 | 3 |
| D | 세트 턴 · 위치 — 세트한 턴 · 다음 턴 · 모른다 · 패 · 앞면 | 5 |
| E | 좁은 요구를 걸지 않았다 — 턴 플레이어 · 빈 칸 · 카드 조건 · `executable` · 카드 ID 0 | 5 |
| F | 🔴 열기 전에 있어야 했던 일곱 가지 | 5 |
| G | 🔴 실제 수직 실행 — 내 턴 · 상대 턴 체인 2 · 다중 선택 · Duel 격리 | 4 |
| H | 회귀 — 마법 · 속공 마법 · 어니스트 · 멱등성 · 비공개 정보 | 5 |

### 17-2. 움직인 기존 테스트 — **다섯 파일 / 여덟 개**

🔴 지운 테스트 · 추가한 skip · 약화한 단언 · 완화한 threshold 는 **없다.**
여덟 개 전부 *"함정 관문이 닫혀 있다"* 를 단언하던 핀이고, 그것이 6-Q 가
룰북 근거로 바꾼 사실이다.

| 테스트 | 틀린 전제 | 어떻게 고쳤나 |
|---|---|---|
| `test_set_trap_timing_audit::test_01` | `EffectDefinition` 에 사건/타이밍 **필드가 없다** | 🔴 재는 방향을 뒤집었다 — 필드가 **정확히 하나**(`activation_waits_for_event`)이고 다섯 장 전부 적혀 있고 마법·몬스터에는 없음을 **더** 센다. `core` 의 Lua 사실과 AST 검사(엔진이 `trigger_events` 를 읽지 않는다)는 **그대로** |
| `test_set_trap_timing_audit::test_04` | 검증기가 **카드 종류로** 막는다 | 두 축으로 센다 — 등록소 없음 → `UNKNOWN`/`TRAP_TRIGGER_MISSING`, 등록소 있음 → `VALID`. 막는 것이 종류가 아니라 **적어 둔 사실**임을 센다 |
| `test_set_trap_timing_audit::test_06` | 응답 창에서도 **후보가 아니다** | 🔴 후보가 **된다**고 센다 (`[a.source] == [instance]`). 원래 주제("응답 자리가 이미 올바르다")가 **실제로 쓰인다**는 것이 더해졌다 |
| `test_set_trap_timing_audit::test_10` | 함정은 후보가 아니다 (멱등성 시험의 전제 한 줄) | 전제 한 줄을 현재 사실로. 재는 것(해시 · 난수 · 점수가 **읽기만으로** 안 바뀜)은 그대로 |
| `test_set_turn_record::test_07` | 기록이 생겨도 함정은 **더 넓은 이유**로 범위 밖 | 그 "더 넓은 이유" 가 닫혔다. 세트한 턴 0건(타이밍 계층 `INVALID`) + 등록소 없음 `UNKNOWN` + 등록소 있음 후보 — **셋을 센다** |
| `test_set_card_activation::test_10` | 함정은 다음 턴에도 `UNKNOWN` | 세 축으로 센다 — 세트한 턴 거절 · 등록소 없음 `UNKNOWN` · 등록소 있음 후보. 주제("`UNKNOWN` 을 허가로 바꾸지 않았다")가 더 분명해졌다 |
| `test_effect_activation_path::test_09` | 꽉 찬 존에서 **발동 후보가 0건** | 🔴 세는 범위를 **정확히 가리켰다** — 주제는 "**패의** 욕망의 항아리가 `ZONE_FULL`" 이고 그대로다. 칸을 채운 세트된 함정 5장이 후보가 되는 것은 **다른 사실**이므로 함께 센다 |
| `test_multi_target_selection::test_g01` | 🔴 **"다중 대상 효과는 아직 적법한 행동이 아니다"** (6-P 가 적은 남은 BLOCKER) | 이름을 현재형으로 바꾸고, 조합 10개가 **적법한 행동 10개**가 됨을 센다. 등록소 없는 축은 여전히 `UNKNOWN` 임도 함께 |

### 17-2-2. 🔴 루트 회귀에서 움직인 핀 — **스무 파일 / 서른넷**

1차 루트 회귀(65파일)에서 **34건**이 깨졌다. 네 갈래이고, 전부 "함정 관문이
닫혀 있다" 또는 "그 때문에 AI 가 함정을 고르지 않는다" 를 단언하던 핀이다.

#### ① 검색 랭킹 digest — 17개 (8파일이 값을 공유)

🔴 **AI 가 실제로 함정을 쓰기 시작했으므로 그 기록이 바뀌었다.**

| 측정 | 전 | 후 |
|---|---|---|
| 6판 결정 수 | 611 | **689** |
| 공유 digest | `30fa3597…` | **`78d35fb4…`** |
| 행위 종류 | — | `end_phase` 357 · `set_spell_trap` 81 · `pass` **73** · `normal_summon` 62 · `activate_effect` **60** · `attack` 56 |

그 핀은 *"digest 값을 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장
많은 파일이 못 박은 값을 기준으로 쓴다"* 로 설계되어 있다. 그래서 **8파일의
값을 함께** 갱신하고, 결정 수를 못 박는 **21파일**의 `611` 을 `689` 로
고쳤다. 각 자리에 왜 바뀌었는지(함정이 후보가 되었고 체인 응답이 생겼다)를
주석으로 적었다. **사용자 승인을 받고 갱신했다.**

#### ② `EffectDefinition` 의 칸 수 · 이름 — 12개

11칸 → **12칸**. 일곱 파일이 같은 주석 블록을 공유하므로 거기에 6-Q 단락을
붙였고, 칸 이름 목록 세 곳에 새 이름을 끼웠다.

🔴 **재는 사실은 그대로다** — 그 핀들이 지키는 것은 *"사건을 담는 칸이
없다"* 이고, 새 칸은 `bool | None` 이므로 **사건을 담을 수 없다.** 그래서
`{"code", "trigger_event", "timing", "point", "event"}` 교집합이 여전히 비어
있다. 이름에 "event" 가 들어가는 두 핀
(`test_trigger_connectivity_audit::test_09` ·
`test_trigger_semantics_audit::test_08`)은 **이름 부분 문자열에서 담는
것으로** 단언을 옮겼다 — ① 사건 이름을 담는 칸이 하나도 없다 ② 그 한 칸의
타입이 `bool | None` 이다. 느슨해진 것이 아니라 **더 센 사실**을 잰다.

#### ③ 🔴 생산 코드가 Lua 태그 이름을 쓰지 않는다 — 코드를 고쳤다

`test_event_free_chain_semantic_audit::test_05` 와
`test_trigger_condition_separation_audit::test_01` 이 각각
*"`FREE_CHAIN` 이 나오는 production 파일의 집합"* 과
*"`engine/effect/definition.py` 에 `EVENT` 라는 글자가 없다"* 를 못 박고
있었다. 내 주석이 그 경계를 **깨고 있었다.**

🔴 **테스트를 고치지 않고 코드를 고쳤다.** `engine/effect/definition.py` 와
`engine/effect/library.py` 에서 Lua 태그 이름을 전부 지우고, 같은 사실을
이름 없이 적었다 ("그 블록이 어떤 사건도 적지 않는다"). 실측: 두 파일의
`EVENT` 글자 수 **0**. 측정과 경고는 원래 자리
(`core.card_model.EffectSpec.code`)에 그대로 있다.

#### ④ 함정의 행동을 단언하던 핀 — 4개

| 테스트 | 틀린 전제 | 어떻게 고쳤나 |
|---|---|---|
| `test_activation_event_input_audit::test_07` | 함정은 **패에 있든 세트되어 있든** 후보가 아니다 | 두 축 — 등록소 없음은 그대로 `UNKNOWN`, 등록소 있음은 **자리가 답을 가른다** (패는 `TRAP_NOT_SET`, 세트는 `VALID`). 주제("사건 의존 효과가 일반 발동으로 섞이지 않는다")는 더 분명해졌다 |
| `test_dormant_live_gate_equivalence::test_06` | 이유 문장이 `"함정이다"` | 6-Q 가 네 갈래로 갈랐으므로 이 판의 문장은 `"함정인데 발동 사건을 적지 않았다"` 다. 두 경로의 답이 **다르다**는 사실은 그대로이고, 문장이 여전히 함정을 가리킴을 함께 센다 |
| `test_duel_advance_rule_step_contract::test_12` | 실제 듀얼이 닿는 행위가 **넷**이고 `activate_effect` 는 0회 | 🔴 여섯이 되었다 (`activate_effect` · `pass` 추가). 수까지 못 박고, **여전히 0회인 둘**(`special_summon` · `activate_card`)은 그대로 0 으로 못 박았다 |
| `test_legal_action_engine_boundary_audit::test_03` | 🔴 **"후보로 나온 것은 거부 0건"** | §19-4 — 실제 결함을 찾았다. 아래 참조 |

### 17-3. Mutation 테스트 — 12개

**내가 바꾼 코드만** 대상으로 했다. `git checkout` 을 쓰지 않았고 원본을
메모리에 들고 있다가 되돌리고 `assert` 로 확인했다
(`scratchpad/mutate8.py`). 판정은 **pytest 의 실제 종료 코드**다.

| # | 고의 결함 | 결과 |
|---|---|---|
| N1 | 축을 보지 않고 함정 전체를 통과시킨다 | killed |
| N2 | 사건을 기다리는 함정도 통과시킨다 | killed |
| N3 | 지속 · 카운터 함정도 통과시킨다 | killed |
| N4 | 세트되지 않은 함정도 통과시킨다 | killed |
| N5 | 앞면 함정도 "세트된 함정" 으로 읽는다 | killed |
| N6 | 자리를 보지 않는다 (패의 함정도 세트로 읽는다) | killed |
| N7 | 함정에도 `IsTurnPlayer` 를 건다 | killed |
| N8 | `canonical_state` 에서 축을 뺀다 | killed |
| N9 | 조건이 축을 넘기지 않는다 | killed |
| N10 | 요구 생성기가 축을 읽지 않는다 | killed |
| N11 | 등록소가 없어도 사건을 안다고 한다 | killed |
| N12 | 라이브러리가 "사건을 기다린다" 로 적는다 | killed (앵커 5회 — 전부 바꿔 재측정) |

**12/12 killed, 생존 0.**

### 17-4. 실행 기록

(§21 에 명령 · 시간 · 종료 코드와 함께 적었다.)

---

## 18. 신규 실제 실행 가능한 함정 효과 수 (§13 · §17-18)

| # | 지표 | 전 | 후 |
|---|---|---|---|
| 1 | 함정 발동 관련 `EffectDefinition` | 5 | 5 (변화 없음) |
| 2 | `EVENT_FREE_CHAIN` 관련 등록 | 5 (core 에만) | 5 (**엔진이 그 태그를 읽지 않는다**) |
| 3 | 발동 조건을 확인할 수 있는 등재 | **0** | **5** |
| 4 | 세트 턴을 검증할 수 있는 사례 | 5 (계층은 있었다) | 5 (**실제로 쓰인다**) |
| 5 | `legal_actions` 의 적법한 함정 후보 | **0** | 🔴 **4장 / 13건** (벌금 10 + 3) |
| 6 | 잘못 생성되는 불법 후보 | 0 | 🔴 **0** (§10-1 의 열 가지) |
| 7 | `ActionValidator` 통과 | **0** | **5장** (로스트 포함 — 발동 계층이 따로 막는다) |
| 8 | 실제 체인 생성 성공 | **0** | 🔴 **3건** (체인 1 둘 · 체인 **2** 하나) |
| 9 | 실제 효과 해결 성공 | **0** | 🔴 **3건** (욕망의 선물 · 강제 탈출 장치 · 벌금) |
| 10 | GameState 변경 검증 | **0** | 🔴 **3건** |
| 11 | EventJournal 일관성 | — | 🟢 해결된 것만 `EffectEvent`, 역순까지 일치 |
| 12 | 어니스트 · 다중 선택 회귀 | 🟢 | 🟢 (다중 선택은 **수준 3 으로 올라갔다**) |
| 13 | 남은 구조적 차단 | — | §19 |

🔴 **정적 후보 · 발동 허가 · 체인 등록 · 효과 해결을 각각 구분했다.**
5번은 후보, 7번은 허가, 8번은 체인 등록, 9~10번이 실제 해결이다.

**신규 실제 실행 가능한 함정 효과 = 3장** (욕망의 선물 · 강제 탈출 장치 ·
벌금). 의적의 입문서는 후보가 되고 검증기를 통과하지만 **해결까지 돌려
보지 않았으므로 세지 않는다.** 로스트는 `executable=False` 이므로 세지
않는다.

---

## 19. 남아 있는 구조적 BLOCKER (§17-19)

### 19-1. 🔴 상대 턴에 **창이 닫혀 있으면** 함정을 발동할 수 없다 (가장 큼)

```python
if self.priority.is_open and self.priority.holds(seat):
    allowed.extend(self._activation_actions(seat, validator))
elif seat == self.turn_player and not self.priority.is_open:
    ...   # 턴 플레이어만
```

기존 우선권 모델은 **응답 창**만 비(非)턴 플레이어에게 열어 준다. 실제
규칙에서는 상대 턴의 열린 게임 상태에서도 함정을 발동할 수 있다.

**영향**: 공격 선언 · 페이즈 전환 같은 "사건 없는 열린 시점" 에 함정을 쓸
수 없다. **6-Q 가 만든 제약이 아니다** — 기존 모델이고, §10 · §15 가
우선권 재설계를 금지하므로 열지 않았다. `test_f04` 가 그 사실을 못 박았다.

### 19-2. 🟠 사건이 필요한 함정 (390블록 / 28.1%)

`EVENT_ATTACK_ANNOUNCE` 96 · `EVENT_SPSUMMON_SUCCESS` 50 ·
`EVENT_CHAINING` 46 · `EVENT_BATTLE_DESTROYED` 29 … 엔진이 그 사건들을
만들어 내지 못한다. 축에 `True` 를 적으면 `TRAP_EVENT_UNSUPPORTED` 로
막힌다 — 즉 **표현은 되고 판정은 안 된다.**

### 19-3. 🟠 지속 함정 · 카운터 함정

지속은 발동 뒤 필드에 남는 수명 계층이, 카운터는 응답 전용 타이밍이 없다
(RULE-SPELLTRAP-010 · 011). 등재 0장이므로 지금은 드러나지 않는다.

### 19-4. 🔴 반쯤 풀린 체인이 남는다 — **6-Q 가 처음 도달 가능하게 만든 결함**

🔴 **6-Q 가 만든 결함이 아니라, 6-Q 가 드러낸 결함이다.** 함정이 체인에
들어갈 수 있게 되면서 **링크 셋인 체인**이 실제 듀얼에서 처음 만들어졌고,
거기서 다음이 재현된다.

```
체인1 P0 55144522:e[0] 를 해결하지 못했습니다:
    발동 조건이 거짓입니다: 자신 DECK 에 2장 이상
```

먼저 해결된 링크(욕망의 선물 · 체인 3)가 덱을 비우면, 나중에 해결되는
체인 1 의 발동 조건이 **해결 시점에** 거짓이 된다. 실제 규칙에서도 그 카드는
불발된다 — 거기까지는 맞다. 문제는 그 뒤다.

```python
# engine/duel.py — _resolve_chain
if self.chain.is_complete:
    self.chain = Chain()          # ← 완전히 풀렸을 때만 비운다
...
if not resolution.fully_resolved:
    return DuelStep(action, False, last.code, last.reason)   # ← PASS 가 "거부"
```

**두 가지가 어긋난다.**

| # | 어긋난 것 | 실측 |
|---|---|---|
| ①-보고 | `PASS` 라는 **적법한 행위**가 `accepted=False` 로 보고된다. `accepted` 하나가 "행위가 위법이었다" 와 "링크가 불발되었다" 를 같은 값에 담는다 | 6판 산책 중 **2건** |
| ②-상태 | 🔴 **반쯤 풀린 체인이 남는다.** `is_complete` 가 거짓이므로 비워지지 않고, **턴을 넘겨도 사라지지 않는다** | 링크 3 · `resolved_count` 2 · 턴 5 → 7 까지 그대로 |

②가 더 깊다 — 다음 발동이 체인 1 이 아니라 **체인 4** 가 될 수 있다 (이번
산책에서는 그 뒤에 발동이 없어 그 장면까지는 관측하지 못했다. 관측하지 못한
것을 관측했다고 적지 않는다).

**왜 6-Q 가 고치지 않았나.** `DuelStep.accepted` 의 의미와 체인 수명은
공유 계약이고 §15 가 체인 재설계를 금지한다. 게다가 단순히 뒤집을 수도
없다 — `ChainResolution.__bool__` 이 *"해결되지 않은 것이 조용히 성공으로
읽히는 것을 막기 위해"* 참·거짓 평가를 거부하고 있으므로, `accepted=True`
로 바꾸면 그 규율을 반대 방향으로 깨뜨린다.

**대안 두 가지** (다음 Phase 에서 승인 후):

1. `DuelStep` 에 "행위 수락" 과 "해결 결과" 를 **두 칸으로** 가른다 —
   `ChainResolution` 이 이미 그 둘을 가르고 있으므로 그 값을 그대로 싣는다.
2. 불발된 링크가 있어도 체인이 **끝났으면** 비운다 — "완전히 해결됨" 과
   "더 풀 것이 없음" 은 다른 사실이고, 지금 코드가 그 둘을 `is_complete`
   하나로 읽는다.

`tests/test_legal_action_engine_boundary_audit.py::test_03` 이 이 결함을
**숨기지 않고 못 박았다** — 고쳐지면 그 단언이 깨지고 이 절을 다시 읽게 된다.

### 19-5. 🟡 `_set_this_turn` 이 "기록 없음" 과 "지난 턴" 을 같은 값으로 본다

```python
return self.state.rule_uses.used_card(turn, controller, source, SET_SPELL_TRAP)
```

`bool` 이므로 **"이 턴에 세운 기록이 없다"** 와 **"지난 턴에 세웠다"** 가 둘
다 `False` 다. 생산 경로에서는 세트가 전부 `SET_SPELL_TRAP` 행위를 거치므로
문제가 없지만, 세 값 규율이 이 경계에서만 둘로 접힌다. 카드를 직접
배치하는 시험 코드에서는 "세트한 턴" 이 아닌 것으로 읽힌다 —
`test_effect_activation_path::test_09` 가 그 자리다. 공유 계약
(`rule_uses`)을 바꾸는 일이므로 이번 범위가 아니다.

### 19-6. 🟡 함정에 여러 효과가 등록된 경우

등재된 다섯 장 전부 `ACTIVATE` 블록 하나다. 둘 이상이면 "어느 효과의
발동인가" 를 `EffectRef.ordinal` 이 가리키지만, 축은 **효과 단위**이므로
모델은 이미 그것을 표현한다 — 다만 그런 카드를 등재해 본 적이 없다.

### 19-7. 🟡 "타이밍을 놓쳤다" 와 1턴 1회

`UNRESOLVED_TIMING_RULES` 가 스스로 적고 있다 — 페이즈별 발동 제약 ·
1턴에 1번 · 타이밍 놓침(when/if) · 데미지 스텝 타이밍 · 카드별 발동 예외.
함정이 열렸으므로 그 목록의 무게가 커졌다.

---

## 20. 다음 단계의 최소 구현 우선순위 (§19 · §17-20)

### 20-0. 🔴 그런데 §19-4 를 먼저 보아야 한다

6-Q 가 **실제 결함 하나를 드러냈다** (반쯤 풀린 체인이 남는다). 그것은
"실행을 막는" 문제가 아니라 **상태가 조용히 틀어지는** 문제이고, 그 위에
무엇을 더 쌓든 그 틀어짐을 함께 상속한다.

| 기준 | 판정 |
|---|---|
| 실행을 막는가 | 🟡 막지 않는다 — 듀얼은 계속된다 |
| 조용히 틀리는가 | 🔴 **그렇다** — 다음 발동이 체인 4 가 될 수 있다 |
| 범위 | 🟡 작다 — `_resolve_chain` 과 `DuelStep` 한 칸 |
| 승인 | 🔴 **필요** (공유 계약) |

🔴 **그래서 B 보다 §19-4 를 먼저 권한다.** 범위가 작고, 고치지 않으면
`/combo` 가 그 틀어진 상태를 사용자에게 보여 주게 된다.

### 20-1. 그다음 — **B (Discord `/combo` 의 실제 엔진 연결)**

§19 는 *"Phase 6-Q에서 기존 실행 경로가 충분히 확보됐다면 B의 최소 수직
경로를 우선 검토한다"* 고 했다. **확보되었다**:

| B 가 필요한 것 | 지금 |
|---|---|
| 실제 GameState 생성 | 🟢 `Duel.start` · `GameState.create` |
| 합법적 행동 확인 | 🟢 `legal_actions` — 마법 · 기동 효과 · **함정** |
| 기존 Duel 에서 행동 실행 | 🟢 `Duel.apply` + `settle_chain` |
| 실행 후 상태 검증 | 🟢 `GameState` · `EventJournal` |
| 다음 행동 탐색 | 🟢 `agent/search.py` |

**범위가 작고 새 규칙이 필요 없다** — 이미 있는 것들을 잇는 일이다. 그리고
실제로 돌아가는 수직 경로가 생기면 다음 BLOCKER 를 **실측으로** 고를 수
있다.

### 20-2. A 를 먼저 한다면 — §19-1 (우선권)

실행을 막는 가장 작은 구조적 문제는 §19-1 이다. 다만:

| 기준 | 판정 |
|---|---|
| 영향 | 🟢 크다 — 함정의 절반 이상이 "사건 없는 열린 시점" 을 쓴다 |
| 범위 | 🔴 **크다** — `PriorityState` 는 체인 · 응답의 공유 계약이다 |
| 근거 | 🟡 룰북의 우선권 조항(RULE-CHAIN-009 계열)을 다시 읽어야 한다 |
| 승인 | 🔴 **필요** (§10 · §15 가 재설계를 금지한다) |

🔴 **이 Phase 는 위 셋 중 아무것도 진행하지 않았다.**

---

## 21. 테스트 실행 기록 및 Git 커밋 · 푸시 결과

### 21-1. 명령어 · 시간 · 결과 · 🔴 **실제 종료 코드**

모두 `YGO_CARDS_CDB=data/cards.cdb` 를 설정하고 `-p no:randomly` 로 돌렸다
(§14). 종료 코드는 `| tail` 이 가리지 않도록 **pytest 자신의 종료 코드**를
따로 읽었다.

| # | 단계 | 명령어 | 시간 | 통과 | 실패 | skip | 종료 코드 |
|---|---|---|---|---|---|---|---|
| 1 | 1·2단계 — 타깃 | `pytest tests/engine/test_trap_activation_free_chain.py -q -p no:randomly --no-header --tb=short` | 3.95s | **35** | 0 | 0 | 🟢 **0** |
| 2 | 3단계 — 엔진 (1차, 신규 파일 전) | `pytest tests/engine -q -p no:randomly --no-header --tb=line` | 381.09s (6:21) | 3,370 | 🔴 **8** | 0 | 🔴 **1** |
| 3 | 움직인 핀 파일 넷 (각각 단독) | `pytest <각 파일> -q -p no:randomly --no-header --tb=short` | 3.45 / 16.34 / 3.66 / 3.85s | 17 / 38 / 19 / 58 | 0 | 0 | 🟢 **0** |
| 4 | 3단계 — 엔진 (최종) | `pytest tests/engine -q -p no:randomly --no-header --tb=line` | 374.39s (6:14) | **3,413** | 0 | 0 | 🟢 **0** |
| 5 | 4단계 — 루트 65파일 (1차) | `pytest <65 files> -q -p no:randomly --no-header --tb=short` | 3057.46s (50:57) | 1,752 | 🔴 **34** | 0 | 🔴 **1** |
| 6 | 움직인 핀 파일별 재확인 | 파일 단독 실행 | 각 3.4~122s | 전부 | 0 | 0 | 🟢 **0** |
| 7 | 4단계 — 루트 69파일 (**처음부터 재실행**) | `pytest <69 files> -q -p no:randomly --no-header --tb=short` | 3188.22s (53:08) | **1,870** | 0 | 0 | 🟢 **0** |
| 8 | Mutation 12건 | `scratchpad/mutate8.py` (판정은 pytest 종료 코드) | — | killed **12/12** | 생존 **0** | — | — |

🔴 **#2 의 8건을 숨기지 않는다.** 여덟 개 전부 "함정 관문이 닫혀 있다" 를
단언하던 핀이고, §17-2 에 "왜 그 전제가 거짓이 되었는지" 를 하나씩 적었다.

기준선: 6-P 의 엔진 최종이 **3,378** 이었고 `3,378 + 35(신규) = 3,413` 으로
맞는다. 움직인 여덟 개는 **수를 늘리지 않았다** (본문만 고쳤다).

🔴 **돌리지 않은 것**: `scripts/fetch_ocg_rulings.py --all`(14,000장 크롤링)
은 금지되어 있어 실행하지 않았다. 공식 사이트에 접속한 적이 없고, 저장소
전체 회귀도 돌리지 않았다 (§14 — 릴리즈 수준 검증이 필요한 변경이 아니다).

### 21-2. 루트 회귀 결과

```
=== root (65 files) start 10:29:48 ===   1차
ROOT_EXIT=1
34 failed, 1752 passed, 1 warning in 3057.46s (0:50:57)

=== root2 (69 files) start 13:00:03 ===  수정 뒤 처음부터 재실행
ROOT2_EXIT=0
1870 passed, 1 warning in 3188.22s (0:53:08)
```

🔴 **1차의 34건을 숨기지 않는다.** 네 갈래 전부 §17-2-2 에 "왜 그 전제가
거짓이 되었는지" 를 적었고, 그중 하나는 **실제 결함**이어서 §19-4 에
근본 원인과 대안을 적었다. 고친 뒤에는 중간에서 이어 돌리지 않고 **처음부터
다시** 돌렸고, 파일 집합도 69개로 넓혔다 (갱신한 digest · `FREE_CHAIN` 핀을
쓰는 파일을 모두 포함하도록).

경고 1건은 `discord.py` 의 `audioop` DeprecationWarning 이고 이 Phase 와
무관하다.

### 21-3. 커밋

작업 브랜치: `claude/pensive-goodall-te1egy`. base 는 Phase 6-P 의 마지막
commit `8ba9932` 다. 기존 commit 을 rewrite · amend 하지 않았고 force push
하지 않았다. 새 브랜치와 PR 을 만들지 않았다.

| 순서 | commit | 내용 | 파일 |
|---|---|---|---|
| 1 | `7d3291c` | production — 함정이 스스로 적어 둔 빈 칸을 채운다 | 3파일 (+274 −6) |
| 2 | `e75e0a8` | 테스트 — 신규 35개와 전제가 거짓이 된 핀 마흔둘 | 신규 1 + 수정 34 |
| 3 | `ebedc51` | 보고서 — 수준 3 | `docs/phase6q-…md` |
| 4 | (이 commit) | 보고서 §21-3 · §21-4 에 실제 SHA 와 푸시 출력 | 같음 |

### 21-4. 푸시 결과

```
$ git push -u origin claude/pensive-goodall-te1egy
To https://github.com/Raro615/yugioh-deck-agent
   8ba9932..ebedc51  claude/pensive-goodall-te1egy -> claude/pensive-goodall-te1egy
branch 'claude/pensive-goodall-te1egy' set up to track 'origin/claude/pensive-goodall-te1egy'.
```

🟢 **fast-forward (`8ba9932..ebedc51`)** — force push 가 아니고 기존 commit 을
하나도 다시 쓰지 않았다. 지정된 브랜치 외에 푸시한 곳이 없고, PR 을 만들지
않았다.

---

## 22. 완료 수준 판정 (§18)

### 🟢 수준 1 — 함정 발동 경로 감사 **달성**

- 실제 함정 발동 등록 정보의 전달 경로를 확인했다 (§1).
- `TRAP_TRIGGER_MISSING` 의 근본 원인을 확인했다 — 한 줄, 그리고 그 문장이
  **스스로 적어 둔 빈 칸** (§2).
- `EVENT_FREE_CHAIN` 의 의미를 검증했다 — Lua 내부 태그이고 공식 개념이
  아니며, 공식 속도와 **반대 방향으로** 70배 차이가 난다 (§3).
- 기존 체인 · 우선권 구조를 조사했다 (§6).
- 미지원 조건을 정확히 기록했다 (§19).

### 🟢 수준 2 — 합법적 발동 후보 생성 **달성**

- 지원되는 함정 효과의 발동 조건을 확인한다 (§4 — 일반 함정 하나).
- `legal_actions` 에서 적법한 `PlayerAction` 을 생성한다 (§10 — 4장 13건).
- 세트 턴 · 위치 · 타이밍 · 우선권 조건을 무시하지 않는다 (§5 · §6).
- 불법 발동 후보 **0건** (§10-1 의 열 가지).
- 기존 `ActionValidator` 와 상태를 일치시킨다 (§11).
- Engine V1 계약을 보존했다 (§8-3 — 기본값 있는 필드 하나).

### 🟢 수준 3 — 실제 함정 발동 · 해결 **달성**

| 항목 | 증거 |
|---|---|
| 실제 Duel 에서 합법적인 함정 발동 요청이 생성된다 | `legal_actions(P0)` → `ACTIVATE_EFFECT(94192409:e[0])`, 대상 포함 |
| 기존 `ActionValidator` 를 통과한다 | `valid` / `OK` (등록소를 받은 생산 경로) |
| 정상적인 체인 절차를 거친다 | 🔴 상대 턴 응답 창에서 **체인 2** · 역순 해결 |
| 기존 `EffectExecutor` 로 효과를 해결한다 | `EffectEvent` 2개가 역순으로 기록 |
| 실제 GameState 가 변경된다 | 대상 `MZONE → HAND` · 상대 패 0 → 3 · 함정 `SZONE → GRAVE` |
| EventJournal 에 실제 적용 결과가 기록된다 | `#3` 함정 → `#4` 마법 (역순) |
| 어니스트 및 다중 대상 효과가 정상 작동한다 | §14 · §15 |

**카드명 · `EffectRef` · 게임 상태 · 체인 처리 · GameState 변경 ·
EventJournal 증거를 §12 · §13 에 제시했다.**

🔴 **과장하지 않는다.** 실행을 확인한 함정은 **3장**이고, 상대 턴의 발동은
**응답 창이 열린 경우**뿐이다 (§19-1). 창이 닫힌 상대 턴에는 여전히 후보가
아니며, 그것은 기존 우선권 모델이다.

---

## 23. 다음 Phase

🔴 **다음 Phase 는 자동으로 시작하지 않는다** (§17).

§20 은 순서를 이렇게 권한다.

1. 🔴 **§19-4** — 반쯤 풀린 체인이 남는 결함. 범위가 작고, 고치지 않으면
   그 위에 쌓는 모든 것이 틀어진 상태를 상속한다. **승인 필요** (공유 계약).
2. **B (Discord `/combo` 의 실제 엔진 연결)** — 수직 경로가 확보되었고 새
   규칙이 필요 없다.
3. **§19-1 (우선권)** — 영향이 가장 크지만 재설계이므로 범위와 근거를 먼저
   합의해야 한다.

어느 것도 자동으로 시작하지 않는다.
