# Phase 3-F-22 — `ACTIVATE_CARD` ↔ `ACTIVATE_EFFECT` 의미 경계 감사

## 0. Base 와 실제 HEAD

| 항목 | 값 | 확인 |
|---|---|---|
| Phase 3-F-21 작업 commit | `080d6f00dfc1b9c801bcb537b7d603124468e556` — *Phase 3-F-21: audit legal action engine boundary* | ✅ `git log --format=%H` |
| Phase 3-F-21 보고서 commit | `124fcfeb36a5108da9a4ac53c7d35e6a5ca341c4` — *Phase 3-F-21: document legal action engine boundary audit* | ✅ |
| 작업 시작 시 실제 HEAD | `124fcfe` | ✅ |
| 작업 트리 | 깨끗함 | — |

---

## 1. 조사 범위

`engine/action.py`(`PlayerActionKind` · `PlayerAction` · 세 표) ·
`engine/action_validation.py`(`_MISSING_RULE` · `_COMPLETE_RULES` ·
`_REQUIREMENT_BUILDERS` · `_activate` · `_activate_effect`) ·
`engine/activation.py`(`EffectActivator.activate` 입구) ·
`engine/duel.py`(`legal_actions` · `_activation_actions` ·
`_withheld_board_actions` · `apply` dispatch) ·
`engine/response.py`(`RESPONDABLE`) · `engine/action_execution.py`
(`UNSUPPORTED_REASON`) · `engine/chain.py`(`ChainLink`) ·
`engine/effect/library.py`(`EFFECT_LIBRARY` 16개) ·
`agent/`(heuristic · policy · search · simulation) ·
그리고 **저장소의 공식 룰북** `data/rules/structured/sd-rulebook-en-v10.json`.

정적 조사는 전부 **문자열 리터럴을 지운 AST**(`code_only`)로 했다 — 설명문에 적힌
낱말을 코드로 세지 않았다.

---

## 2. `activate_card` 전체 호출 경로

```
PlayerAction.activate_card(actor, source, targets=(), effect_ref=None)
    │   effect_ref 는 **선택**
    ↓
ActionValidator.validate
    │   _REQUIREMENT_BUILDERS[ACTIVATE_CARD] = _activate   (요구 1개: 자기 카드인가)
    │   _MISSING_RULE[ACTIVATE_CARD] = "activation-timing (Phase 2-C/2-F)"
    ↓
  UNKNOWN  (code=rule_not_implemented, missing_rule 지목)
    ↓
Duel.legal_actions
    │   _withheld_board_actions 가 **withheld 로만** 적는다 (종류·이유·빠진 규칙)
    ↓
  allowed 에 **들어가지 않는다**
    ↓
Duel.apply → 첫 관문에서 거부 (RULE_NOT_IMPLEMENTED, "허가된 행위가 아닙니다")
    ↓
  ✗ EffectActivator 에 닿지 않는다. 닿아도 **kind 로 거절**된다
  ✗ ChainLink 없음 · ✗ resolution 없음 · ✗ state_hash 불변
```

production 에서 `PlayerAction.activate_card` 를 만드는 자리는 **한 곳**
(`engine/duel.py:649`, 보류 사유를 적기 위한 검증용)이다.

## 3. `activate_effect` 전체 호출 경로

```
PlayerAction.activate_effect(actor, source, effect_ref, targets=())
    │   effect_ref 는 **필수** (팩토리 시그니처가 강제)
    ↓
Duel._activation_actions
    │   _activation_sources(패 · 세트된 마법/함정)
    │   × activatable_effects(card_id)        ← executable 인 것만 (ADR-006)
    │   × target_combinations(...)            ← 대상 하나하나가 다른 후보
    │   → _activation_gate (세 관문)
    ↓
ActionValidator.validate
    │   _REQUIREMENT_BUILDERS[ACTIVATE_EFFECT] = _activate_effect
    │   _COMPLETE_RULES 에 **있다** → VALID 까지 갈 수 있다
    ↓
  VALID  (범위 = 패의 통상 마법)  /  UNKNOWN (그 밖)
    ↓
Duel.legal_actions → allowed 에 **들어간다**
    ↓
Duel.apply → dispatch 가 이름으로 집어 **_apply_activation**
    ↓
EffectActivator.activate  (kind 검사 통과 · effect_ref 검사 통과)
    ↓
ActivationResult(status=ACTIVATED) + **ChainLink(sequence, actor, effect_ref)**
    ↓
ResponseLoop (RESPONDABLE 에 있다) → ChainResolver → EffectResult
```

---

## 4. 두 action 의 semantic contract

| 축 | `ACTIVATE_CARD` | `ACTIVATE_EFFECT` |
|---|---|---|
| 선언된 뜻 (`engine/action.py`) | "카드 자체를 발동한다 (마법 · 함정의 발동)" | "카드가 가진 **특정 효과**를 발동한다. `effect_ref` 로 어느 효과인지 지목한다" |
| `effect_ref` | 허용(선택) | 🔴 **필수** |
| 요구 생성기 | `_activate` — 요구 **1개** (자신이 쥔 카드인가) | `_activate_effect` — 범위 안이면 **4개** (쥔 카드 · 메인 페이즈 · 턴 플레이어 · 마법&함정 존 빈 칸) |
| `_MISSING_RULE` | **있다** | 없다 |
| `_COMPLETE_RULES` | 없다 | **있다** |
| `EffectActivator` | 🔴 **kind 로 거절** — "activate_card 는 효과 발동이 아닙니다" | 받는다 |
| `RESPONDABLE` | 없다 | **있다** |
| `legal_actions` | `withheld` 전용 | `allowed` 에 나온다 |
| `apply` dispatch | 이름으로 집지 않는다 | **집는다** |
| `ChainLink` | 만들지 않는다 | 만든다 |

### 🟢 분리는 **의도된 수정**이었다

`_activate_effect` 의 docstring 이 직접 적는다.

> 왜 갈라야 했는가: `ACTIVATE_CARD` 와 `ACTIVATE_EFFECT` 는 **뜻이 다른데**
> (`engine/action.py` 의 설명) 요구 하나를 **공유하고 있었다** (STRUCTURAL-119).
> 그리고 발동 계층(`EffectActivator`)은 `ACTIVATE_EFFECT` **만** 받으므로, 허가를
> 낼 수 있는 쪽도 그쪽 하나다.

즉 **합쳐져 있던 것을 갈라낸 것**이고, 그 분리에 식별된 결함 번호가 붙어 있다.

### 🔴 모듈이 스스로 분리를 강제한다

```python
assert not (_COMPLETE_RULES & set(_MISSING_RULE)), (
    "한 종류가 '끝까지 본다' 와 '규칙이 없다' 를 동시에 말할 수 없습니다."
)
```

고의 위반 주입에서 `ACTIVATE_CARD` 를 `_COMPLETE_RULES` 에 넣자 **import 자체가
실패했다.** 계약이 테스트가 아니라 **production 안에서** 지켜지고 있다.

### §2 의 일곱 질문에 대한 답

| # | 질문 | 답 |
|---|---|---|
| ① | `activate_card` 는 정확히 무엇인가 | 선언된 뜻은 "카드 자체의 발동". **현재 계약상 유효하지 않다** — 빠진 규칙이 `activation-timing (Phase 2-C/2-F)` 로 지목되어 있다 |
| ② | `activate_effect` 는 정확히 무엇인가 | "`effect_ref` 로 **지목한 특정 효과**의 발동". 유일하게 끝까지 가는 쪽이다 |
| ③ | 둘은 서로 다른 `PlayerAction` 인가 | 🟢 **그렇다.** 같은 카드·같은 효과를 가리켜도 `canonical_state` 가 다르고 `==` 가 아니다 |
| ④ | 같은 내부 경로로 들어가는가 | 🔴 **아니다.** `EffectActivator` 가 **종류만 보고** 한쪽을 거절한다. 수렴하지 않는다 |
| ⑤ | 차이를 정하는 것은 무엇인가 | 🔴 카드 종류도·효과 종류도·출처도·타이밍도·intent 도 아니다. 현재 **강제되는** 차이는 **`effect_ref` 의 필수성**과 **종류 그 자체**다 |
| ⑥ | 구분하지 않으면 게임 의미가 손상되는 사례가 있는가 | 🟡 **현재 등록 카드 범위에서는 없다** — 몬스터 효과가 0장이라 "카드의 발동 ≠ 효과의 발동" 이 갈리는 카드가 없다. 다만 구분을 없애면 `effect_ref` 필수성과 검증기 분리(STRUCTURAL-119 의 수정)가 사라진다 |
| ⑦ | consumer 가 차이를 쓰지 않으면 미래 계약인가 불필요한 추상인가 | **엔진 내부 consumer 는 차이를 쓴다** (검증기 · 활성기 · 응답 루프 · dispatch). **AI 는 쓰지 않는다**(§7). 그래서 불필요한 추상이 아니라 **엔진 계층의 현재 계약**이다 |

---

## 5. 실제 카드 / fixture 사례 — 다섯 장

전부 공식 DB 에 등록된 실제 카드다. 가상 카드를 만들지 않았다.

| # | 카드 | 종류 | `activate_effect` 검증 | 활성기 결과 | ChainLink | `activate_card` |
|---|---|---|---|---|---|---|
| 1 | 욕망의 항아리 `55144522` | 마법 | 🟢 **VALID** | `activated` | **1** | UNKNOWN → 활성기 `invalid_action` |
| 2 | 싸이크론 `5318639` | 마법 | 🟢 **VALID** | `invalid_target` (`too_few_selected`) | 0 | 같음 |
| 3 | 강제 탈출 장치 `94192409` | 함정 | 🟡 **UNKNOWN** — `trap-activation-timing (함정의 유발 조건을 효과마다 구분할 수 없다 — 공식 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다)` | `unauthorized` | 0 | 같음 |
| 4 | 로스트 `24623598` | 함정 | 후보 자체가 없다 (`executable` 효과 **0개**, ADR-006) | — | 0 | 같음 |
| 5 | 홍옥의 사령 `11091375` | 통상 몬스터 | 후보 자체가 없다 (효과 없음) | — | 0 | 같음 |

🔴 **3번이 중요하다.** 함정이 막히는 이유는 `activate_card` 가 막히는 이유와
**다른 문자열**이다. 두 이유를 하나로 적으면 "발동이 전부 안 된다" 로 읽히는데,
그것은 거짓이다.

그리고 1번은 **실제 듀얼에서도** 끝까지 간다 —
`"55144522:e[0] 를 체인 1 로 발동했습니다. 상대의 응답을 기다립니다."`

### 🔴 몬스터 효과 발동은 **도달할 수 없다**

`EFFECT_LIBRARY` 16개 전수 조사:

| 종류 | 장수 |
|---|---|
| 마법 | 10 |
| 함정 | 6 |
| **몬스터** | **0** |

그래서 §3 이 구분하라고 한 "Monster Effect activation" · "Ignition/Quick/Trigger
계열" 은 **현재 구현 범위에 없다.** 없는 것을 있다고 적지 않는다.

---

## 6. Engine V1 계약과의 관계

Phase 3-F-21 의 판정을 뒤집지 않았다. 이 Phase 가 답한 것은 **"왜 한쪽만
허용되는가"** 다.

§6 이 요구한 세 갈래로 분류하면:

| 갈래 | 판정 |
|---|---|
| 단순히 "아직 구현하지 않은 기능" | 🔴 **아니다.** 그러면 빠진 규칙의 이름이 없을 것이다 |
| **"현재 `PlayerAction` 모델에서 별도 action 으로 필요하지 않은 기능"** | 🟡 **부분적으로 맞다** — 현재 등록 카드(마법·함정) 범위에서는 `activate_effect` 하나로 전부 처리된다 |
| **"향후 확장을 위한 placeholder"** | 🟢 **이것이 가장 가깝다.** `_MISSING_RULE` 이 `activation-timing (Phase 2-C/2-F)` 를 지목하고, `UNSUPPORTED_REASON` 이 "발동 절차 — 비용 · 대상 · 체인 삽입이 앞선다" 를 적는다. **무엇이 생기면 열리는지**가 적혀 있다 |

즉 `activate_card` 는 **빈 칸이 아니라 남은 일의 목록**이다 — 이 프로젝트가
`withheld` · `_MISSING_RULE` · `UNSUPPORTED_REASON` 으로 일관되게 쓰는 방식이다.

---

## 7. AI / Search 영향

```
GameStateView → legal_actions() → Policy/Search → PlayerAction → Engine
```

| 질문 | 답 |
|---|---|
| 둘이 각각 candidate 로 생성되는가 | `activate_effect` 만. `activate_card` 는 **0회** |
| Search 가 둘을 별개로 평가하는가 | **구분조차 하지 않는다** — `agent/` 에 두 종류의 이름이 **한 번도** 나오지 않는다 |
| `RuleBasedPolicy` 가 별도로 처리하는가 | 아니다. `agent/heuristic.py` 가 이름으로 집는 종류는 `NORMAL_SUMMON` · `END_PHASE` · `PASS` 셋뿐이다 |
| canonical ordering 이 둘을 구분하는가 | 🟢 **구분한다** (`canonical_state` 첫 칸이 종류, `"activate_card" < "activate_effect"`). 그런데 한쪽이 후보에 없으므로 **실제 정렬에는 영향이 없다** |
| 합치면 search digest 가 바뀌는가 | **후보 기여가 0 이므로 action space 는 달라지지 않는다** — digest·tie-break·legal action count 가 그 종류 때문에 변하는 일은 없다 |
| 기존 duel result 가 바뀌는가 | 아니다 |
| `state_hash` · RNG 가 바뀌는가 | 아니다. 후보 생성·검증을 반복해도 해시와 RNG 가 그대로다 |
| hidden information 이 깨지는가 | 아니다. 검증은 `GameStateView` 로만 한다 |

🔴 **그래도 "합쳐도 된다" 는 뜻이 아니다.** 지시가 경계한 그대로 — digest 가
안 바뀐다는 것은 **AI 쪽 영향이 없다**는 말일 뿐이고, 합치면 `effect_ref`
필수성과 검증기 분리(STRUCTURAL-119 의 수정)가 **사라진다.** §9 가 금지한
항목이고, 이 Phase 는 합치지 않았다.

---

## 8. 공식 용어와 프로젝트 용어의 차이

저장소에 이미 있는 **공식 룰북**(`data/rules/structured/sd-rulebook-en-v10.json`)
에서 읽었다. 나무위키 · 비공식 위키 · 커뮤니티 자료를 쓰지 않았다.

| 공식 룰북 | 원문 |
|---|---|
| 메인 페이즈 1 의 행동 | **"Activate a Card or Effect"** — **한 행동**으로 적는다 |
| 체인 | *"You can only create a Chain by responding to the activation of **a card or effect**."* |
| 스펠 스피드 1 | `"Spells (Normal, Equip, Continuous, Field, Ritual)"` 와 `"Effect Monster's effects (Ignition, Trigger, and Flip)"` — **마법은 카드**로, **몬스터 쪽은 효과**로 묶는다 |
| 발동이 **아닌** 것 | `"Summoning a monster"` · `"Tributing"` · `"changing a monster's battle position"` · `"paying costs"` |

### 🔴 차이 — 이름이 공식과 어긋난다

* 공식은 "카드 **또는** 효과의 발동" 을 **하나의 행동**으로 적는다. 프로젝트는
  그것을 **두 `PlayerActionKind`** 로 나눈다 → 공식 규칙의 구분이 아니라
  **엔진 내부의 구분**이다.
* 공식 분류로 **마법·함정은 "카드"** 다. 그런데 현재 등록된 16개는 **전부
  마법·함정**이고, 엔진은 그것을 **`ACTIVATE_EFFECT`** 로 처리한다.
* 즉 **`ACTIVATE_CARD` 라는 이름이 가리키는 공식 개념(마법·함정 카드의 발동)을
  실제로 처리하고 있는 것은 `ACTIVATE_EFFECT` 다.**

프로젝트 내부 기준으로는 모순이 없다 — 엔진은 모든 발동을 "카드 X 의 효과 #N"
으로 모델링하고 `effect_ref` 가 그 지목 수단이다. 공식 용어로 읽는 사람에게만
이름이 거꾸로 보인다. 🟡 **structural risk 로 기록**한다(§11).

---

## 9. production 변경 여부 — **0줄**

§9 가 요구한 다섯 조건을 모두 만족해야 하는데 **첫째와 둘째가 성립하지 않는다.**

| 조건 | 판정 |
|---|---|
| 1. semantic contract 가 **명백히 잘못**되어 있다 | 🔴 **아니다.** 계약이 코드에 적혀 있고(세 표 · 두 docstring · 모듈 assert) 측정과 일치한다 |
| 2. production consumer 가 그 잘못된 의미에 **의존한다** | 🔴 **아니다.** AI 는 둘을 구분조차 하지 않고, 엔진 consumer 들은 분리된 계약을 **올바르게** 쓴다 |
| 3. 최소 수정으로 바로잡을 수 있다 | (1·2 가 아니므로 해당 없음) |
| 4. Engine V1 freeze 를 깨지 않는다 | — |
| 5. AI/Search 계약을 깨지 않음이 검증된다 | — |

§9 의 금지 항목도 전부 지켰다 — `activate_card` 제거 ✗ · `activate_effect`
제거 ✗ · enum 병합 ✗ · 새 `ActivationAction` enum ✗ · 활성기 재설계 ✗ ·
`Chain` 변경 ✗ · AI/Search 변경 ✗ · freeze 해제 ✗.

---

## 10. 테스트 결과

새 파일: `tests/test_activation_action_semantic_boundary_audit.py` — **30개**
(요구 최소 20개)

| # | 테스트 | §10 요구 |
|---|---|---|
| 01 | 🟢 `effect_ref` 필수성이 둘을 가른다 (시그니처) | 정의/의미 계약 |
| 02 | 두 action 은 서로 다른 **값**이다 | 계약 |
| 03 | 두 enum 이 그대로 있다 (제거·병합 없음) | §9 |
| 04 | 🔴 검증기의 두 등록부 + 모듈 자기 assert | 계약 |
| 05 | 🟢 요구 생성기가 다르다 (STRUCTURAL-119) | 계약 |
| 06 | `activate_card` 는 빠진 규칙으로 등록되어 있다 | UNKNOWN 구분 |
| 07 | 🔴 활성기가 **kind 로** 거절한다 | activation 경로 |
| 08 | 🟢 `activate_effect` 는 ChainLink 까지 간다 | ChainLink |
| 09 | `RESPONDABLE` 에 한쪽만 있다 | activation 경로 |
| 10 | 🟡 실행기에는 둘 다 없는데 결과가 다르다 | `apply` 허용 |
| 11 | **실제 카드 다섯 장** 전수 분류 | 실제 사례 |
| 12 | 🔴 등록 효과 16개 전부 마법·함정, 몬스터 0 | 실제 사례 |
| 13 | 🔴 갈림의 기준은 `effect_ref`/종류다 | 계약 |
| 14 | 실제 듀얼: 한쪽은 후보, 한쪽은 `withheld`(사유 출처까지) | `legal_actions` |
| 15 | 듀얼에 직접 넣어도 거부, 판 불변 | 잘못된 입력 |
| 16 | 🟡 함정은 **다른 이유**로 막힌다 | UNKNOWN 구분 |
| 17 | 없는 `effect_ref` 는 거절된다 | 잘못된 입력 |
| 18 | 🟢 AI 는 둘을 이름으로 구분하지 않는다 | Policy 소비 |
| 19 | canonical ordering 은 둘을 구분한다 | ordering |
| 20 | 🟢 합쳐도 action space 는 안 변한다 (기여 0) | Search 소비 |
| 21 | 시뮬레이션이 발동을 같은 종류로 받아 간다 | Search 소비 |
| 22 | 숨은 정보 · `state_hash` · RNG 불변 | hidden-info |
| 23 | clone 독립성 | clone |
| 24 | 같은 seed → 같은 발동 | RNG |
| 25 | 🔴 공식 룰북은 **한 행동**으로 적는다 | §7 |
| 26 | production 변경 0 (AUDIT-ONLY) | §9 |
| 27 | 두 종류의 참조 파일 집합 전수 고정 | §1 |
| 28 | 금지된 재구조화 없음 | §9 |
| 29 | 미등록 종류는 실행기가 거부 (ADR-006) | INVALID/FORBIDDEN |
| 30 | 검색 digest 불변 (611결정) | §12 |

기존 테스트를 **삭제·skip·약화하지 않았고, 고친 것도 없다.**

### 전체 회귀

```
4608 passed, 4 skipped in 601.34s (0:10:01)
```

| | 개수 |
|---|---|
| Phase 3-F-21 (base `124fcfe`) | 4578 |
| 이 Phase 가 추가한 테스트 | **+30** |
| **합계 (실측)** | **4608** |
| 실패 | **0** |
| skip | 4 (이 Phase 가 추가한 것 **없음**) |

삭제 0 · skip 추가 0 · assertion 약화 0 · 기존 테스트 수정 0.

### 🔴 고의 위반 주입 9건

`engine/action.py` · `engine/action_validation.py` · `engine/activation.py` ·
`engine/duel.py` · `engine/response.py` · `agent/heuristic.py` 를 md5 로 백업하고
하나씩 심었다 되돌렸다. 마지막 복원을 md5 로 확인했다.

| # | 심은 위반 | 걸린 곳 | 결과 |
|---|---|---|---|
| 1 | `effect_ref` 를 양쪽 선택으로 | `test_01` | ✅ |
| 2 | `activate_card` 를 `_COMPLETE_RULES` 에 | 🟢 **production 의 import 시 assert** | ✅ (아래) |
| 3 | 요구 생성기를 다시 공유 (STRUCTURAL-119 재발) | `test_05` `test_11` `test_16` `test_30` | ✅ |
| 4 | 활성기가 `activate_card` 도 받게 | `test_07` `test_27` | ✅ |
| 5 | 응답 루프가 `activate_card` 도 다루게 | `test_09` `test_27` | ✅ |
| 6 | `withheld` 사유를 반대쪽으로 | `test_14` | ⚠️ **놓쳤다 → 고쳐 잡았다** |
| 7 | 발동 후보를 `activate_card` 로 | `test_14` `test_20` `test_21` | ✅ (내 **기대값**이 틀렸다) |
| 8 | AI 가 `activate_effect` 를 이름으로 집게 | `test_18` | ✅ |
| 9 | 빠진 규칙 설명을 지우기 | 13개 테스트 | ✅ |

#### 주입 2 — 🟢 **테스트가 아니라 production 이 막았다**

`ACTIVATE_CARD` 를 `_COMPLETE_RULES` 에 넣자 모듈 import 가 실패했다.

```
AssertionError: 한 종류가 '끝까지 본다' 와 '규칙이 없다' 를 동시에 말할 수 없습니다.
```

개별 테스트가 `FAILED` 로 집히지 않아 내 집계 스크립트가 "놓쳤다" 로 적었지만,
실제로는 **가장 강한 형태로 잡힌 것**이다 — 엔진이 아예 뜨지 않는다. `test_04` 가
그 assert 의 존재를 못 박는다.

#### 주입 6 — 🔴 **이름표만 재고 사유의 출처를 보지 않았다**

`test_14` 가 `withheld` 의 **종류 이름표**만 셌다. 주입은 보류 사유를
`activate_card` 대신 `activate_effect` 를 검증해서 만들게 바꿨는데, 이름표는
코드에 박힌 리터럴(`WithheldAction(PlayerActionKind.ACTIVATE_CARD, ...)`)이라
그대로 남아 통과했다. **사유와 빠진 규칙이 `activate_card` 를 검증한 결과와
같은지**까지 단정하도록 고쳐 잡았다.

#### 주입 7 — 기대값이 틀렸다

`test_27` 도 깨질 것으로 적었는데, 그 테스트는 `PlayerActionKind.*` **참조 파일
집합**을 재므로 팩토리 호출을 바꾼 것과 무관하다. `test_14` 가 올바르게 잡았다.
**"기대와 다르게 걸렸다" 와 "못 잡았다" 는 다른 것**이다.

---

## 11. 남은 structural risk

| 항목 | 내용 | 등급 |
|---|---|---|
| **이름이 공식 용어와 거꾸로 보인다** | 현재 지원되는 마법·함정 발동은 공식 용어로 "**카드**의 발동" 인데 엔진은 `ACTIVATE_EFFECT` 로 처리한다. `ACTIVATE_CARD` 라는 이름을 가진 쪽이 미지원이다(§8) | 🟡 |
| 몬스터 효과가 0장 | "카드의 발동 ≠ 효과의 발동" 이 실제로 갈리는 카드가 **아직 없다.** 그래서 구분의 필요성이 현재 카드로는 **증명되지 않는다** — 미래 계약으로만 성립한다 | 🟡 |
| `UNSUPPORTED_REASON` 이 둘에게 같은 문구 | 실행기 관점에서는 둘 다 미등록이라 맞지만, 한쪽은 `Duel` 이 직접 실행한다. 그 표만 읽으면 `activate_effect` 도 미지원으로 보인다 | 🟡 |
| 함정의 빠진 규칙이 더 깊다 | `trap-activation-timing` 은 `EffectDefinition` 에 `SetCode(EVENT_*)` 가 없다는 **데이터 모델** 문제를 지목한다 — `activation-timing` 보다 아래 계층이다 | 🟡 |

전부 **FUTURE WORK 로 기록**한다. 고치지 않았다.

---

## 12. 최종 판정

> ## **D. ONE_SIDED_CONTRACT**

둘 중 **`ACTIVATE_EFFECT` 하나만** 현재 Engine 계약상 유효하고,
**`ACTIVATE_CARD` 는 미래/미지원 경계**다.

### 코드 근거

1. `_COMPLETE_RULES` 에 `ACTIVATE_EFFECT` 만 있고, `_MISSING_RULE` 에
   `ACTIVATE_CARD` 만 있다. **모듈이 두 집합의 분리를 스스로 assert 한다.**
2. `EffectActivator` 가 `ACTIVATE_CARD` 를 **종류만 보고** 거절한다 —
   "activate_card 는 효과 발동이 아닙니다".
3. `RESPONDABLE` · `apply` dispatch · ChainLink 생성이 전부 `ACTIVATE_EFFECT`
   쪽에만 있다.
4. 실제 카드 다섯 장으로 끝까지 확인했다 — 한쪽은 체인 1 까지, 한쪽은 어느
   카드로도 `invalid_action`.
5. 그리고 **왜 없는지가 지목되어 있다** — `activation-timing (Phase 2-C/2-F)`.

### 왜 A 가 아닌가

A(`DISTINCT_SEMANTICS`)의 첫 절은 **참이다** — 둘은 코드가 강제하는 서로 다른
것이다(§4). 그런데 A 는 "둘 다 현재 의미를 갖고 **유지해야 한다**" 로 읽히는데,
측정 결과 **한쪽은 현재 어떤 입력으로도 계약을 통과하지 못한다.** 그 비대칭이
이 Phase 의 핵심 사실이고, D 가 그것을 담는다. (D 를 고르는 것이 "둘이 같다" 는
뜻은 **아니다** — 같지 않다는 것이 C 를 배제하는 근거다.)

### 왜 B · C · E · F 가 아닌가

| 선택지 | 고르지 않은 이유 |
|---|---|
| B. `SAME_SEMANTICS_DIFFERENT_INPUT` | 🔴 **같은 실행 의미로 수렴하지 않는다.** 활성기가 종류로 거절하므로 한쪽은 실행 의미에 **도달조차 못 한다** |
| C. `REDUNDANT_ACTION` | 🔴 증거가 **반대 방향**이다. 둘이 요구 하나를 공유하던 것이 STRUCTURAL-119 로 식별되어 **갈라낸** 것이고, `effect_ref` 필수성·요구 생성기·활성기 입구·응답 루프가 모두 둘을 다르게 다룬다. 지시가 요구한 높은 증거 기준은 **유지해야 한다는 쪽**으로 충족된다 |
| E. `DOCUMENTATION_GAP` | 🟡 가까웠지만 **아니다.** semantic contract 는 문서화되어 있다 — `engine/action.py` 의 두 docstring, `_activate_effect` 의 "왜 갈라야 했는가", `_MISSING_RULE` 의 지목, 모듈 assert. 문서화되지 **않은** 것은 §8 의 **공식 용어 대응**이고, 그것은 contract 자체가 아니라 **이름의 대응표**다 → §11 의 🟡 로 기록했고 다음 Phase 후보로 올렸다 |
| F. `UNKNOWN` | 전 경로를 실측했다. 모르는 것이 없다 |

---

## 13. 다음 Phase 후보 (최대 1개)

**공식 발동 용어 ↔ 엔진 `PlayerActionKind` 대응표 고정 (문서 전용).**

이유: 이 Phase 가 계약은 일관되다는 것을 확인했지만, **이름이 공식 용어와 거꾸로
보인다**는 사실(§8)은 어디에도 적혀 있지 않다. 공식 룰북은 "Activate a Card or
Effect" 를 한 행동으로 적고 마법·함정을 "카드" 로 분류하는데, 엔진은 그 마법·함정
발동을 `ACTIVATE_EFFECT` 로 처리하고 `ACTIVATE_CARD` 를 미지원으로 둔다. 몬스터
효과가 등록되는 날 이 대응을 모르면 **어느 종류를 넓혀야 하는지 틀리게 판단**한다.
저장소에 이미 공식 룰북과 ruling 계층이 있으므로, 새 규칙을 설계하지 않고 **대응표
한 장**을 공식 원문 인용과 함께 고정하는 것으로 충분하다.

다만 **다음 Phase 는 임의로 진행하지 않는다.**
