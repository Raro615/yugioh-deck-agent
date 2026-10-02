# Phase 3-E-3 — Effect Action Space Audit

- **Base commit**: `abb91da` (Phase 3-E-2 — SET Action Space)
- **Branch**: `claude/pensive-goodall-te1egy`
- **성격**: **Audit only** — `engine/` 변경 0건
- **결과**: 3245 → **3266 passed, 4 skipped** (Audit 테스트 21개 추가, 회귀 0건)
- **판정**: **ENGINE CHANGE REQUIRED** — 승인 대기

---

## 1. 한 줄 결론

> 발동 · 비용 · 체인 · 해결 · 효과 실행은 **전부 동작한다.**
> 동작하지 않는 것은 `PlayerAction` 에서 거기로 **들어가는 길**이다.

손으로 부르면 욕망의 항아리가 덱 20 → 18, 패 1 → 3 을 만든다. 같은 카드를
`Duel.apply` 에 넣으면 거절되고 판은 한 글자도 바뀌지 않는다.

---

## 2. 조사한 구조 — 전부 실제로 있다

| 구조 | 위치 | 상태 |
|---|---|---|
| `ACTIVATE_CARD` | `engine/action.py:68` | 존재 · 생성자 `PlayerAction.activate_card` |
| `ACTIVATE_EFFECT` | `engine/action.py:70` | 존재 · 생성자 `PlayerAction.activate_effect` |
| 모양 검사 | `action_validation.py:191~212` | **생성자가 아니라 검증기에 있다** |
| Activation validation | `action_validation.py:807` `_activate` | 요구 **1개**(컨트롤러)뿐 · 영원히 `UNKNOWN` |
| Activation timing | `engine/activation_timing.py` (447줄) | 스펠 스피드만 · 미판정 6항목을 스스로 적어 둔다 |
| Activation core | `engine/activation.py` (868줄) | `EffectActivator.can_activate` / `activate` **동작** |
| Cost | `engine/payment.py` (608줄) `CostPayer` | 동작 · 호출 순서 보장 · **라이브러리에 비용 효과 0건** |
| ChainLink · Chain | `engine/chain.py` (657줄) | 동작 · LIFO |
| Chain resolution | `chain.py` `ChainResolver` | 동작 |
| Priority | `engine/priority.py` (538줄) | 동작 — 단 발동과 **연결되어 있지 않다** |
| Response loop | `engine/response.py` | 동작 — 단 **여는 규칙이 없다** (STRUCTURAL-34) |
| Effect execution | `engine/effect/executor.py` | 동작 · 실제 state mutation 확인 |
| Effect library | `engine/effect/library.py` | 16개 정의 · **13개 executable** |
| `legal_actions` | `engine/duel.py:258` | **ACTIVATE 후보를 만드는 코드가 없다** |
| `GameStateView` | `engine/game_state_view.py` | 동작 · 발동 경로에서 경계 유지 |
| `Simulator` | `agent/simulation.py` | 동작 · 발동은 `NOT_A_CANDIDATE` |
| `StateEvaluator` | `agent/evaluation.py` | 동작 · 발동 미도달 |

---

## 3. 끊어진 자리는 **정확히 둘**이다

```
PlayerAction(ACTIVATE_*)
      ↓
  legal_actions()          ✗ 후보를 만드는 코드가 없다        ← 구멍 B
      ↓
  ActionValidator          △ 영원히 UNKNOWN (요구 1개)
      ↓
  Duel.apply()             ✗ 수행기가 등록되어 있지 않다      ← 구멍 C
  ────────────────────────────────────────────────────────────
  EffectActivator          ✓ 동작
  CostPayer                ✓ 동작 (지나간 카드 0장)
  Chain.push               ✓ 동작
  ChainResolver            ✓ 동작
  EffectExecutor           ✓ 동작 — 판이 실제로 바뀐다
```

### 두 구멍이 **독립**이라는 증거

고의 위반으로 확인했다. `ACTIVATE_CARD` 를 `_COMPLETE_RULES` 에 올려 검증기가
`VALID` 를 내게 만든 뒤:

```
검증기 판정(ACTIVATE_CARD): valid
legal_actions 의 ACTIVATE_CARD 후보 수: 0
Duel.apply: False rule_not_implemented | activate_card 는 지금 허가된 행위가 아닙니다.
```

`Duel.legal_actions` 의 패 순회가 **세 가지만** 만들어 보기 때문이다
(`normal_summon` · `set_monster` · `set_spell_trap`). 그래서 **"검증기를
고치면 후보가 나온다" 는 틀렸다.** `test_07b` 가 이 사실을 고정한다.

### 구멍 C 는 **의도된 것**이다 (STRUCTURAL-55)

`engine/activation.py` 의 모듈 설명이 직접 적어 두었다.

> `ActionHandler` 는 `apply(state, action)` 이 **`StateDelta` 만** 돌려주는
> 모양이다. 그런데 발동의 결과물은 판의 모양이 아니라 **흐름의 위치**
> (`Chain` · `PriorityState`)이고, 그것은 `GameState` 밖에 산다. 그래서
> 발동을 `ActionHandler` 로 끼워 넣으면 체인을 어딘가 숨겨 두고 주고받아야
> 한다. 숨긴 통로는 통로가 아니다.

그리고 `Duel` 은 그 흐름의 위치를 담을 자리로 만들어졌는데 — 모듈 설명이
"체인이 어디까지 쌓였는지 ... 그 자리가 여태 없었다. 이 클래스가 그 자리다"
라고 쓴다 — 실제로 받은 칸은 `priority` 하나다. `chain` 칸이 **없다**
(`test_10`).

---

## 4. `ACTIVATE_CARD` ≠ `ACTIVATE_EFFECT`

추측하지 않고 코드에서 읽었다.

| | `ACTIVATE_CARD` | `ACTIVATE_EFFECT` |
|---|---|---|
| 뜻 | 카드 자체의 발동 (마법 · 함정) | 카드가 가진 **특정 효과** |
| `effect_ref` | 가질 수 **있다** (필수 아님) | **필수** — 없으면 `EFFECT_REF_REQUIRED` |
| 검증 요구 | `_activate` (공유) | `_activate` (**같은 것**) |
| `legal_actions` | `withheld` 에 이유가 남는다 | **어디에도 없다** |
| `EffectActivator` | **거절** — "효과 발동이 아닙니다" | 받는다 |

두 번째 줄이 중요하다: **검증기는 아직 둘을 구분하지 않는다.** 결함이
아니라, 구분할 근거(발동 타이밍 계층)가 없어서 지어내지 않은 결과다
(`test_02`).

네 번째 줄도 중요하다: `ACTIVATE_EFFECT` 는 `withheld` 에도 없다. 빈 목록은
"할 것이 없다" 로 읽히고 적어 둔 것은 "아직" 으로 읽히는데, 지금
`ACTIVATE_EFFECT` 는 **앞쪽으로 읽힌다** (`test_07`).

---

## 5. 실제 카드 Audit

### 선정 — 욕망의 항아리 (55144522)

§6 의 기준으로 **가장 단순한** 효과다.

| 기준 | 값 |
|---|---|
| `EffectRef` | `EffectRef(55144522, 0)` |
| 비용 | `CostGroup(costs=())` — **없다** |
| 대상 | `()` — **없다** |
| 조작 | `DrawOperation(count=2, who=CONTROLLER)` 하나 |
| 발동 조건 | `ZoneCountAtLeast(CONTROLLER, DECK, 2)` |
| 근거 | `c55144522.lua` 의 `s.activate` · `lua_excerpt` 가 원문을 들고 있다 |
| 공식 ruling | **`not_checked`** — 수집된 11장에 들어 있지 않다 |

마지막 줄이 §6 의 기준 하나와 **어긋난다.** 공식 ruling 이 있는 라이브러리
카드는 싸이크론(5318639, 316건)과 **리로드**(22589918, 4건) 둘뿐이고, 둘 다
대상 또는 다단 조작이 있어 "가장 단순" 과 충돌한다. 그래서 둘을 **따로**
적는다 — 기준 카드는 욕망의 항아리, 공식 ruling 이 있는 가장 단순한 카드는
싸이크론. 어느 쪽도 상대를 대신하지 않는다.
(ruling 수집은 `scripts/fetch_ocg_rulings.py` 의 일이고 이번 Audit 의 범위가 아니다.)

### 경로별 판정

| 단계 | 욕망의 항아리 | 싸이크론 (앞면 대상) |
|---|---|---|
| Activation | **PASS** | **PASS** |
| Cost | **NOT_REACHED** (비용이 없다) | **NOT_REACHED** (비용이 없다) |
| Target | **NOT_REACHED** (대상이 없다) | **PASS** |
| Chain | **PASS** — 체인 1 | **PASS** — 체인 1 |
| Resolution | **PASS** | **PARTIAL** — `effect_not_applied` |
| State Change | **PASS** — 덱 20→18 · 패 1→3 | **NOT_REACHED** — 아무것도 안 바뀐다 |

싸이크론이 해결에서 멈추는 이유는 결함이 아니다. 기본 실행기의 파괴
판정기가 `UnknownDestructionRuling` 이고, "파괴 내성 · 대체 효과를 판정할 수
없다" 를 **허가로 바꾸지 않는다** (ADR-006 · STRUCTURAL-47). 라이브러리에
실렸다는 사실이 파괴 판정을 대신하지 않는다 (`test_14`).

### 기본 실행기로 **해결까지 가는** 효과 6개

대상 선택을 주지 않고 측정했다.

```
55144522 욕망의 항아리      resolved
66719324 은혜의 단비        resolved
84257639 치료의 신 다이안 켓 resolved
 5915629 욕망의 선물        resolved
70368879 갑부 고블린        resolved
22589918 리로드             resolved
```

나머지 7개는 `invalid_target`(대상을 줘야 한다) 또는 `condition_false`(판을
갖춰야 한다) 다 — **못 하는 것이 아니라 이 측정이 주지 않은 것**이다
(`test_12`). 실행하지 않는 3개(블랙홀 · 죽은 자의 소생 · 로스트)는
`executable=False` 로 **일부러** 실려 있고, 라이브러리가 이유를 적어 둔다.

---

## 6. 비용 — 경로는 있고 지나간 카드가 없다

`CostPayer` · `CostGroup` · `PaymentContext` 가 모두 있고 `EffectActivator.
activate` 가 순서를 보장한다: **읽기만 하는 검사를 전부 끝낸 뒤**에 치르고,
체인이 링크를 받을 수 있는지도 지불 **전에** 본다.

그런데 등록된 16개 효과 **전부** `CostGroup(costs=())` 이다. 그래서
"비용을 치른 뒤 발동이 실패하면 어떤 semantics 인가" 는 **실제 카드로
확인할 수 없고**, 코드가 선언한 것만 적을 수 있다.

- 지불 실패 → 링크를 만들지 않는다 (`_COST_STATUS` 로 상태만 돌려준다)
- `can_activate` 가 `VALID` 라도 지불에서 멈출 수 있다 — `CostPayer` 의
  preflight 가 비공개이고 그것을 밖에서 흉내 내지 않았기 때문이다
  (**STRUCTURAL-56**, 코드에 그대로 적혀 있다)
- 지불 후 되돌리기는 **없다** (ADR-008 이 rollback 을 미뤄 두었다)

판정: **PARTIAL** — 구조는 있고 실제 카드로 지나간 적이 없다 (`test_15`).

---

## 7. Search · Simulation — NOT_REACHED

| 단계 | 판정 |
|---|---|
| `legal_actions` | **NOT_REACHED** — 후보 0건 |
| simulation | **NOT_REACHED** — `NOT_A_CANDIDATE` |
| future state | **NOT_REACHED** — `future is None` |
| evaluation | **NOT_REACHED** — 평가할 후보가 없다 |

`Simulator` 가 `UNKNOWN` 이 아니라 `NOT_A_CANDIDATE` 를 돌려주는 것이
정확하다 — `UNKNOWN` 은 "해 봤는데 엔진이 모른다" 이고 `NOT_A_CANDIDATE` 는
"애초에 고를 수 없다" 다 (`test_16`·`test_17`).

**Search 전용 발동 우회로를 만들지 않았다.**

---

## 8. 숨은 정보 — PASS

발동 경로가 관측 경계를 **지킨다.**

- `EffectActivator._verdict` 는 `GameStateView.from_state(state, viewer=action.actor)`
  로 관측을 만든다 — 상대 패를 들여다보고 판정하지 않는다
- `TargetResolver` 도 관측만 받는다
- `BoardRuling` 은 `GameState` 를 받으면 **TypeError** 를 던진다

가장 좋은 증거: 싸이크론이 **뒷면** 마법 · 함정을 대상으로 하면 후보 조건
("마법 · 함정인가")을 판정할 수 없으므로

```
can_activate → UNKNOWN(information_unavailable)
activate     → UNCHECKED_TARGET, 체인 길이 0
```

같은 카드가 **앞면**이면 `VALID` → `ACTIVATED` 다. 그래서 거절의 이유가
"싸이크론이 안 된다" 가 아니라 **"보이지 않는다"** 임이 확인된다. 그리고
`UNKNOWN` 이 체인을 늘리지 않는다 (`test_13`).

---

## 9. RNG — PASS

세 난수가 섞이지 않는다.

| 난수 | 자리 | 목적 |
|---|---|---|
| Game RNG | `GameState.randomness` | `DECK_SHUFFLE` · `RANDOM_SELECTION` |
| Policy RNG | `agent/` (`RandomPolicy(seed=)`) | 정책의 선택 |
| Search fork | `state.clone()` | 뽑기 수까지 복제 |

`RandomPurpose` 가 스스로 적어 둔다: *"`AI_*` 를 여기 두지 않는다. 탐색·정책의
무작위는 규칙의 무작위와 다른 계층이고, 한 열거형에 섞으면 같은 난수원을 쓰게
된다."* 효과 실행기는 `state.randomness.shuffle(..., RandomPurpose.DECK_SHUFFLE)`
와 `choose_many(...)` 만 쓰고, 씨앗이 없으면 **거절한다**
(`missing="seeded randomness"`).

이번 Audit 에서 random effect 를 구현하지 않았다.

---

## 10. BLOCKER 판정 (§16)

| 조건 | 해당 | 근거 |
|---|---|---|
| A. ACTIVATE action 이 없다 | **아니다** | 둘 다 있다 |
| B. **legal_actions 에서 생성할 수 없다** | **그렇다** | 후보 0건 · 만드는 코드가 없다 (`test_06`·`test_07b`) |
| C. **`Duel.apply()` 에서 실행할 수 없다** | **그렇다** | 수행기 미등록 (`test_08`·`test_09`) |
| D. ChainLink 를 만들 수 없다 | 아니다 | 만들어진다 (`test_11`) |
| E. resolution 이 없다 | 아니다 | 있다 (`test_11`) |
| F. effect state mutation 이 없다 | 아니다 | 있다 — 덱 20→18 (`test_11`) |
| G. activation legality 를 안전하게 판단할 수 없다 | **그렇다** | 요구 1개 · 미판정 6항목 (`test_05`·`test_19`) |

**B · C · G 로 BLOCKER.** → **ENGINE CHANGE REQUIRED**

---

## 11. 필요한 최소 변경 (제안 — 승인 전)

기존 구조를 **재사용**한다. 새 Chain Engine · 새 EventBus · 새 Expression
Language 를 만들지 않는다.

| # | 파일 | 변경 | 왜 최소인가 |
|---|---|---|---|
| 1 | `engine/duel.py` | `Duel` 에 `chain: Chain` 칸 하나 추가 | 모듈 설명이 이미 이 자리라고 적었다. 새 클래스를 만들지 않는다 |
| 2 | `engine/action_validation.py` | `_activate_effect` 를 `_activate` 에서 분리하고, 이미 있는 `ActivationTimingChecker` · `EffectActivator.can_activate` 가 답할 수 있는 것만 요구로 올린다 | 규칙을 새로 쓰지 않는다. **`_COMPLETE_RULES` 에는 올리지 않는다** — 미판정 6항목이 남아 있으므로 |
| 3 | `engine/duel.py` | 패 순회에 `activate_effect` 후보 생성 추가. 후보는 **`EFFECT_LIBRARY` 에 `executable` 로 등록된 효과에 한한다** | ADR-006 그대로 — 등록되지 않은 카드는 후보가 되지 않는다 |
| 4 | `engine/duel.py` | `_apply_board` 와 **나란히** `_apply_activation` 을 두고 `EffectActivator` → (즉시) `ChainResolver` 를 부른다 | `ActionHandler` 에 억지로 끼우지 않는다 (STRUCTURAL-55 를 깨지 않는다) |

### 2번의 어려운 점을 숨기지 않는다

`_COMPLETE_RULES` 에 올리지 않으면 `legal_actions` 가 후보로 받지 않는다
(지금 그 함수는 `VALID` 만 담는다). 그래서 **셋 중 하나를 골라야 하고,
그 선택은 승인이 필요하다.**

1. 미판정 6항목을 "지금 판정할 수 있는 범위" 로 좁혀 선언하고 올린다 —
   Phase 3-E-2 가 SET 에 쓴 방법과 같다. 단 SET 의 미판정 항목은 0개였고
   여기는 6개다
2. `legal_actions` 에 "발동만은 `UNKNOWN` 도 담는다" 는 예외를 만든다 —
   **권하지 않는다.** 이 저장소 전체의 불변식("UNKNOWN 은 허가가 아니다")에
   예외를 내는 일이다
3. 범위를 더 좁힌다: **메인 페이즈 · 자기 턴 · 체인이 비었을 때 ·
   `EFFECT_LIBRARY` 의 일반 마법만**. 그러면 미판정 6항목 중 함정 세트 제약 ·
   데미지 스텝 · 퀵 이펙트가 애초에 닿지 않고, 남는 것은 "턴 1회" 와
   "타이밍 놓침" 이며 둘 다 일반 마법에는 해당 카드가 없다

**3번을 권한다.** 가장 좁고, 좁힌 근거를 조항으로 적을 수 있고,
`_COMPLETE_RULES` 의 뜻("이 종류의 적법성을 끝까지 볼 수 있다")을 거짓으로
만들지 않는다.

### 하지 않는 것

우선권 · 응답 루프를 발동에 **연결하지 않는다.** `ResponseLoop` 는 있지만
여는 규칙이 없고 (STRUCTURAL-34), 없는 규칙을 지어내면 틀린 채로 굳는다.
그래서 위 4번은 발동 직후 바로 해결한다 — 체인 1 단계만. 상대의 응답은
그 규칙이 정해질 때 연결한다.

---

## 12. 기존 TODO — 전부 유지

| ID | 상태 | Audit 중 관찰 |
|---|---|---|
| STRUCTURAL-102 | 유지 | — |
| STRUCTURAL-107 | 유지 | — |
| STRUCTURAL-109 | 유지 | — |
| STRUCTURAL-110 | 유지 | — |
| STRUCTURAL-115 | 유지 | 발동 후보가 없으므로 평가에 닿지 않는다 |
| STRUCTURAL-116 | 유지 | — |

발동 계층이 들고 있던 기존 ID 도 그대로다: **STRUCTURAL-34**(우선권을 누가
여는가) · **STRUCTURAL-51** · **STRUCTURAL-55**(발동은 `ActionExecutor` 밖) ·
**STRUCTURAL-56**(`can_activate` VALID 가 비용 통과를 뜻하지 않는다) ·
**STRUCTURAL-16** · **STRUCTURAL-47**(파괴 판정) · **STRUCTURAL-7**(analysis →
EffectDefinition 컴파일러 없음).

---

## 13. 새로 확인된 TODO (실제 코드에서만)

| ID | 내용 | 근거 |
|---|---|---|
| **STRUCTURAL-117** (신규) | `Duel.legal_actions` 의 패 순회가 세 가지만 만들어 보므로, **검증기를 고쳐도 발동 후보가 생기지 않는다.** 후보 생성과 적법성 판정이 서로 다른 구멍이다 | 고의 위반으로 확인 · `test_07b` |
| **STRUCTURAL-118** (신규) | `ACTIVATE_EFFECT` 는 `withheld` 에도 남지 않는다 — `_withheld_board_actions` 가 `activate_card` 만 만든다. "왜 못 하는가" 가 절반만 적혀 있다 | `test_07` |
| **STRUCTURAL-119** (신규) | 검증기가 `ACTIVATE_CARD` 와 `ACTIVATE_EFFECT` 를 **같은 요구 하나**로 다룬다 (`_activate` 공유). 뜻이 다른 둘이 적법성에서는 구분되지 않는다 | `test_02` |
| **STRUCTURAL-120** (신규) | `EFFECT_LIBRARY` 16개 **전부** 비용이 없다. `CostPayer` 경로를 지나간 실제 카드가 아직 없다 | `test_15` |

추측한 것은 없다. 넷 다 실행되는 주장으로 고정했다.

---

## 14. 테스트

| | |
|---|---|
| Baseline | 3245 passed / 4 skipped |
| New | `tests/engine/test_effect_action_space_audit.py` — **21개** |
| 총계 | **3266 passed / 4 skipped** |
| Regression | **0건** |
| 기존 테스트 수정 | **0건** |
| `engine/` 변경 | **0건** |

고의 위반으로 Audit 주장이 실제로 잡는지 확인했다: `ACTIVATE_CARD` 를
`_COMPLETE_RULES` 에 올리면 `test_04`·`test_05`·`test_07` 이 깨진다. 되돌린 뒤
`git diff engine/` 가 비어 있음을 확인했다.

---

## 15. 다음 단계

**Phase 3-E-3 Implementation 을 시작하지 않고 승인 대기.**

승인이 필요한 결정은 §11 의 네 가지 변경과, 그중 **2번의 세 선택지 중
무엇을 택할 것인가**다.
