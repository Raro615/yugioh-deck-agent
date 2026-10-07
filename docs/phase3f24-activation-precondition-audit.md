# Phase 3-F-24 — 발동 선행 계약 및 `EffectDefinition` 유발 조건 감사

## 0. 실제 HEAD / Base — `git` 으로 검증

| 항목 | 값 | 검증 |
|---|---|---|
| 전달받은 3-F-23 작업 commit | `3cf59c2` | ✅ `3cf59c2edfa46e0c2f5ea293719eaad5f9857771` *Phase 3-F-23: fix/document…* |
| 전달받은 3-F-23 보고서 commit | `f49b186` | ✅ `f49b1866415692b7138fae9d113e070af73d57c7` *Phase 3-F-23: document…* |
| 작업 시작 시 실제 HEAD | **`f49b186`** | ✅ 전달값과 일치 |
| `git diff f49b186 -- <production>` | **빈 출력** | ✅ |
| 작업 트리 | 깨끗함 | ✅ |

---

## 1. 🔴 먼저 — 내 앞 Phase 의 틀을 **정정한다**

Phase 3-F-23 보고서가 다음 Phase 후보를 이렇게 적었다.

> 함정 발동의 선행 계약 — `EffectDefinition` 의 유발 조건(`SetCode(EVENT_*)`)
> **누락** 범위 감사

**"누락" 이 부정확하다.** 측정하면 그 값은 **잃어버린 것이 아니다.**

| 사실 | 측정값 |
|---|---|
| `EffectSpec.code` 가 그 값을 들고 있다 | 블록 **30,771개** / 상수 **298종** |
| 그 중 `EVENT_*` | **16,727 블록** |
| 그 중 `EFFECT_*` | **14,044 블록** |
| `engine.ids.iter_effects` 로 닿을 수 있다 | ✅ 함수가 있다 |
| `EffectDefinition` 에 `code` 칸 | ❌ **없다** |

→ **누락이 아니라 "건너지 않은 경계"** 다. 그리고 그 선택은 ADR-006("등록하지
않은 것은 실행되지 않는다")과 같은 태도다. 이 Phase 는 그 구분을 바로잡는다.

---

## 2. 조사 범위

`core/card_model.py`(`EffectSpec`) · `analysis/effect_model.py` ·
`analysis/effect_analyzer.py` · `sources/lua_loader.py` ·
`engine/effect/definition.py`(`EffectDefinition`) · `engine/ids.py`(`EffectRef` ·
`iter_effects`) · `engine/trigger.py`(`TriggerSpec` · `TimingPoint`) ·
`engine/activation_timing.py`(`SpellSpeed` · `ActivationTimingChecker`) ·
`engine/activation.py`(`EffectActivator`) · `engine/action.py` ·
`engine/action_validation.py`(`TRAP_TRIGGER_MISSING` · `MONSTER_ACTIVATION_MISSING` ·
`_NormalSpellActivation`) · `engine/duel.py`(`legal_actions` · `_activation_gate` ·
`apply`) · `engine/chain.py`(`ChainLink`) · `agent/` 전체 · 그리고 카드 corpus
**14,520장**.

정적 조사는 전부 **문자열 리터럴을 지운 AST**(`code_only`)로 했다.

### 🔴 앞선 감사가 이미 답한 것 — 다시 쓰지 않고 **이어서** 센다

| Phase | 파일 | 이미 확정한 것 |
|---|---|---|
| **3-E-31** | `tests/test_effectdefinition_trigger_boundary_audit.py` | `code` 칸이 `EffectSpec` 에만 있다 · `TriggerSpec.point` 는 `EVENT_*` 의 사본이 아니다 · 등재 함정 전부 `EVENT_FREE_CHAIN` |
| **3-F-4** | `tests/test_trigger_condition_separation_audit.py` | EVENT / TRIGGER CONDITION / ELIGIBILITY / ACTIVATION 네 단계의 LIVE·DORMANT 표 |

이 Phase 가 **새로 재는 것은 셋**이다 — §4 의 두 어휘 혼재, `iter_effects` 의
production 호출자 0, corpus 186종 vs 등재 5장의 비대칭.

---

## 3. `EffectDefinition` 계약 — §2 의 분류

### 세 계층의 칸 (측정)

| 계층 | 칸 |
|---|---|
| `EffectSpec` (파서) | `index` · `effect_types` · **`code`** · `ranges` · `target_ranges` · `categories` · `properties` · `count_limit` · `cloned_from` |
| `EffectDefinition` (엔진) | `effect_ref` · `source_card_id` · `operations` · **`activation`** · `cost` · `targets` · `declarations` · `requirements` · `guards` · `provenance` |
| `TriggerSpec` (등록) | `effect_ref` · **`point`** · `requirement` · `wording` · `operations` · `from_zones` · `to_zones` · `activates_from` · **`condition`** |

🔴 **`EffectDefinition` 에 사건 칸이 하나도 없다** — `code` · `event` · `trigger` ·
`timing` · `card_type` · `spell_speed` 전부 없다.

### §2 항목별 분류

| 항목 | 어디에 | 판정 |
|---|---|---|
| 효과의 종류 | `EffectSpec.effect_types` (파서·분석) | **B/C** |
| **발동 조건** | `EffectDefinition.activation: Condition \| None` — **8/16** 에 있다 | **D** (엔진이 쓴다) |
| **유발 조건** | `EffectDefinition` 에 **칸 없음**. DORMANT 등록 계층의 `TriggerSpec.point`/`condition` | **E** (정의 계층) |
| activation timing | `engine/activation_timing.py` — `SpellSpeed` 는 **카드 종류**에서 파생 | **D** |
| 카드가 Spell/Trap/Monster | `CardDefinition.type_names` | **D** |
| `effect_ref` / `ordinal` | `EffectRef` — 등재 전부 `ordinal=0` | **D** |
| **`SetCode(EVENT_*)`** | `EffectSpec.code` | 🔴 **B** — 파서가 뽑지만 **engine 이 안 쓴다** |
| 발동 비용 | `EffectDefinition.cost` — 칸은 있고 값은 **전부 비어 있다** | **D** (구조) / **E** (값) |
| 발동 가능 여부 | 세 관문의 합성 결과 | **D** |

🔴 **"필드가 있다" ≠ "엔진이 쓴다"**: `code` 는 A(데이터로 명시됨)이면서 동시에
**B**(execution 이 안 쓴다)다. 두 축을 섞으면 "구현되어 있다" 로 오독된다.

### `activation` 은 timing 이 아니다

이름 때문에 타이밍으로 읽기 쉽다. 타입은 **`Condition | None`** 이고, 타이밍은
**다른 모듈**에 있다. 그리고 `engine/activation_timing.py` 는 `EffectSpec` ·
`iter_effects` · `EVENT_` 를 **하나도 읽지 않는다**(각 0회).

---

## 4. `SetCode(EVENT_*)` 조사 결과

### 🔴 한 칸에 **두 어휘가 섞여 있다**

| 접두사 | 블록 수 |
|---|---|
| `EVENT_*` | **16,727** |
| `EFFECT_*` | **14,044** |

즉 `EffectSpec.code` 는 "유발 사건" 이 아니라 **"블록의 첫 `SetCode` 류 상수"**
다. `EFFECT_UPDATE_ATTACK` · `EFFECT_DISABLE` · `EFFECT_SPSUMMON_PROC` 같은
**효과 속성** 상수가 45%를 차지한다.

→ §3 이 경고한 그대로다 — **이름만 보고 "유발 조건" 이라고 단정할 수 없다.**
데이터가 그것을 보여 준다.

### corpus 분포

| 범위 | 카드 | 상수 종류 | 블록 |
|---|---|---|---|
| 전체 | 14,520 | **298종** | 30,771 |
| 함정 | 2,079 | **186종** | 4,755 |
| 몬스터 | 9,547 | 259종 | 19,961 |

함정 상위: `EVENT_FREE_CHAIN` 1,846 · `EVENT_CHAINING` 258 · `EVENT_PHASE` 170 ·
`EVENT_ATTACK_ANNOUNCE` 142 · `EVENT_LEAVE_FIELD` 115 · `EVENT_TO_GRAVE` 106 …

→ **corpus 차원에서는 "효과마다 구분" 이 실제 문제다.** `EVENT_FREE_CHAIN` 이
최다이지만 **과반이 아니다**(39%).

### 누가 읽는가 (§8 A)

| 받는 쪽 | 읽는 파일 |
|---|---|
| **`spec.code`** | `sources/lua_loader.py` · `analysis/effect_analyzer.py` — **둘뿐** |
| `blocked.code` | `engine/activation.py` — 🔴 **전혀 다른 것** |

.. note::
   🔴 측정 중 한 번 걸렸다. 받는 쪽을 `("spec","block","entry")` **부분 문자열**로
   골랐더니 `engine/activation.py` 의 `blocked.code` 가 잡혔다 — `"block"` 이
   `"blocked"` 의 부분 문자열이기 때문이다. 그런데 그 `blocked` 는
   `EffectActivator._check` 가 돌려준 **`ActivationResult`** 이고 `.code` 는
   `ValidationCode` 다. 받는 쪽 이름을 **정확히** 세도록 고쳤다.

→ **engine production 에서 `EffectSpec.code` 를 읽는 자리는 0곳이다.**

### 🔴 `iter_effects` — 닿을 수 있지만 **닿지 않는다**

Phase 3-E-31 이 "engine 안에 production 함수가 이미 있다" 고 적었다. 맞다 —
`engine/ids.py:130` 에 있다. 그런데 측정하면:

| 측정 | 값 |
|---|---|
| production 호출자 | **0곳** |
| 전체 호출자 | 감사 테스트 **5개 파일**뿐 |

→ **"닿을 수 있다" 와 "닿고 있다" 는 다른 말이다.** 3-E-31 의 서술을 이 Phase 가
이 정도로 좁혔다.

---

## 5. activation-timing 조사 결과

### 생성과 소비 (§4 의 provenance 추적)

```
CardDefinition.type_names ──→ classify_spell_speed ──→ SpellSpeed
Chain · PriorityState · set_this_turn ─┐
                                       ├→ ActivationTiming
                                       ↓
EffectDefinition.activation (Condition) ─┐
                                          ├→ Duel._activation_gate  (관문 3개)
ActivationTimingChecker ──────────────────┤     ① ActionValidator
EffectActivator.can_activate ─────────────┘     ② ActivationTimingChecker
                                                ③ can_activate
                                       ↓
                 legal_actions  ─┬─→ apply ─→ EffectActivator ─→ ChainLink
                                 └─ (같은 함수를 **양쪽이** 부른다)
```

🟢 **이 경로는 끊기지 않는다.** `_activation_gate` 가 세 관문을 한 함수에 모아
두고, 후보 생성과 실행이 **같은 함수·같은 판**을 본다 (STRUCTURAL-134 의 수정).

### 🔴 끊기는 곳은 **다른 경로**다

```
Lua script
   ↓  sources/lua_loader.py
EffectSpec.code   (EVENT_* 16,727 · EFFECT_* 14,044 · 298종)
   ↓  analysis/effect_analyzer.py        ✅ 읽는다
   ✗  EffectDefinition                   🔴 code 칸이 **없다** ← 여기서 끊긴다
   ✗  activation_timing                  (EVENT_ 0회)
   ✗  legal_actions / apply / ChainLink  (닿지 않는다)
```

provenance 를 정확히 적으면: **`SetCode(EVENT_*)` 정보는 파서/분석 계층에는
존재하지만 `EffectDefinition` 으로 옮겨지지 않으므로 `legal_actions` 까지
전달되지 않는다.** `iter_effects` 라는 **우회로가 있으나 production 이 쓰지
않는다.**

---

## 6. 실제 카드 corpus — 등재된 16개 전수

| passcode | 종류 | exec | `activation` | cost | targets | `EffectSpec.code` | 판정 |
|---|---|---|---|---|---|---|---|
| `5318639` 싸이크론 | 마법 | ✅ | 없음 | 없음 | 1 | `EVENT_FREE_CHAIN` | 발동 가능 |
| `5915629` | **함정** | ✅ | 있음 | 없음 | 0 | `EVENT_FREE_CHAIN` | 🟡 보류 |
| `15103313` | 마법 | ✅ | 없음 | 없음 | 1 | `EVENT_FREE_CHAIN` | 발동 가능 |
| `22589918` 리로드 | 마법 | ✅ | 있음 | 없음 | 1 | `EVENT_FREE_CHAIN` | 발동 가능 |
| `24623598` 로스트 | **함정** | ✗ | 없음 | 없음 | 0 | `EVENT_FREE_CHAIN` | 후보 없음 |
| `53129443` 블랙홀 | 마법 | ✗ | 없음 | 없음 | 0 | `EVENT_FREE_CHAIN` | 후보 없음 |
| `55144522` 욕망의 항아리 | 마법 | ✅ | 있음 | 없음 | 0 | `EVENT_FREE_CHAIN` | 🟢 체인 1 |
| `66719324` | 마법 | ✅ | 없음 | 없음 | 0 | `EVENT_FREE_CHAIN` | 발동 가능 |
| `69091732` | **함정** | ✅ | 있음 | 없음 | 1 | `EVENT_FREE_CHAIN` | 🟡 보류 |
| `70368879` | 마법 | ✅ | 있음 | 없음 | 0 | `EVENT_FREE_CHAIN` | 발동 가능 |
| `73148972` | 마법 | ✅ | 있음 | 없음 | 2 | `EVENT_FREE_CHAIN` | 발동 가능 |
| `81439173` | 마법 | ✅ | 있음 | 없음 | 1 | `EVENT_FREE_CHAIN` | 발동 가능 |
| `83764718` | 마법 | ✗ | 없음 | 없음 | 0 | `EVENT_FREE_CHAIN` | 후보 없음 |
| `84257639` 다이안 켓 | 마법 | ✅ | 없음 | 없음 | 0 | `EVENT_FREE_CHAIN` | 🟢 체인 1 |
| `92595643` 벌금 | **함정** | ✅ | 있음 | 없음 | 1 | `EVENT_FREE_CHAIN` | 🟡 보류 |
| `94192409` 강제 탈출 장치 | **함정** | ✅ | 없음 | 없음 | 1 | `EVENT_FREE_CHAIN` | 🟡 보류 |

집계: 마법 **11** · 함정 **5** · 몬스터 **0** / `activation` 있음 **8/16** /
cost 있음 **0/16** / `ordinal` 전부 **0** / executable **13**.

### 🔴 이 Phase 의 핵심 비대칭

| | corpus | 등재 |
|---|---|---|
| 함정 카드 | 2,079장 | **5장** |
| 함정의 `code` 상수 | **186종** | **1종** (`EVENT_FREE_CHAIN`) |

→ `TRAP_TRIGGER_MISSING`("함정의 유발 조건을 효과마다 구분할 수 없다")은
**corpus 차원에서 성립하지만 등재된 다섯 장에는 물리지 않는다** — 이 다섯 장에는
구분할 유발 조건이 애초에 없다.

🔴 **그것이 그 문장이 틀렸다는 뜻은 아니다.** 그 문장은 `EffectDefinition` 에
`code` 칸이 없다는 **사실**을 적고 있고(§3), corpus 차원의 필요도 실재한다(§4).
그래서 **production 을 고치지 않았다**(§9).

§5 가 요청한 아홉 범주 중 **실제 표본이 있는 것만** 적는다 — 일반 마법 ·
일반/지속 함정은 있고, **기동 · 유발 · 유발즉시 · 속공 마법 · 카운터 함정 ·
몬스터 효과는 등재 표본이 0** 이다. 억지로 채우지 않았다.

---

## 7. 유발 조건 vs 발동 가능 조건 vs timing (§6)

세 개념이 **서로 다른 계층**에 있고, **하나의 필드로 뭉쳐 있지 않다.**

| 개념 | 사는 곳 | 측정 |
|---|---|---|
| **유발 조건** — "어떤 사건이 났을 때" | `TriggerSpec.point` · `condition` · `requirement` · `activates_from` (DORMANT 등록 계층) | 그 넷이 `EffectDefinition` 에 **하나도 없다** |
| **발동 가능 조건** — "지금 발동할 수 있는가" | `EffectDefinition.activation: Condition \| None` | **8/16**. `evaluate` 를 가진 상태 조건이다 |
| **activation timing** — "어느 타이밍인가" | `engine/activation_timing.py` (`SpellSpeed` · `ActivationTiming` · `ActivationTimingChecker`) | `SpellSpeed` 가 **카드 종류**에서 나온다. `EVENT_*` 를 0회 읽는다 |

Phase 3-F-4 가 이미 네 단계(EVENT / TRIGGER CONDITION / ELIGIBILITY /
ACTIVATION)로 LIVE·DORMANT 표를 만들어 두었다. 이 Phase 는 그 표가 지금도
성립함을 확인하고, **timing 이 카드 종류에서 파생된다**는 점을 더했다.

---

## 8. 함정 발동 선행 계약 — 있는 것과 없는 것

§7 이 요청한 항목을 **이미 있는 것 / 아직 없는 것**으로 가른다. "필요할 것 같다"
만으로 새 필드를 만들지 않았다.

| 선행 정보 | 지금 있는가 | 근거 |
|---|---|---|
| `CardDefinition` 의 카드 종류 | 🟢 **있다** | `type_names` — `_activation_out_of_scope` 가 읽는다 |
| face-up / face-down 상태 | 🟢 **있다** | `CardInstance.is_faceup` · `FACE_DOWN` 분류 |
| **세트 여부 · 세트한 턴** | 🟢 **있다** | Phase 3-E-2 · 3-E-15. `Duel._set_this_turn` → `ActivationTiming.set_this_turn` |
| 현재 turn / phase | 🟢 **있다** | `TurnState` |
| 현재 chain | 🟢 **있다** | `Duel.chain` → `ActivationTiming` |
| 우선권 | 🟢 **있다** | `PriorityState` |
| 발동 가능 zone | 🟢 **있다** | `_activation_sources`(패 + 세트된 마함) |
| 카드의 controller | 🟢 **있다** | `ControllerIs` 요구 |
| `effect_ref` | 🟢 **있다** | 필수 입력 |
| `ChainLink` 생성 정보 | 🟢 **있다** | `(sequence, actor, effect_ref, …)` |
| 비용 | 🟡 **칸은 있고 값이 없다** | 등재 16개 전부 `CostGroup(costs=())` |
| 스펠 스피드 | 🟡 **카드 종류에서 파생** | `classify_spell_speed` |
| **유발 조건** (`EVENT_*`) | 🔴 **엔진에 없다** | `EffectDefinition` 에 칸 없음. 파서 계층에만 |
| 몬스터 효과 분류(기동/유발/플립/유발즉시) | 🔴 **없다** | `MONSTER_CLASSIFICATION_MISSING` |

🔴 **"세트와 세트한 턴" 은 빠진 것이 아니다.** 코드가 직접 그렇게 적는다 —
*"세트와 세트한 턴은 **이유가 아니다.** 둘 다 있다 (Phase 3-E-2 · 3-E-15)"*.
함정이 막히는 **유일한** 이유로 코드가 지목하는 것은 유발 조건이다.

---

## 9. 실제 production call path (§8 A~G)

| # | 질문 | 답 | 경로 |
|---|---|---|---|
| **A** | `SetCode(EVENT_*)` 가 production engine 에서 읽히는가 | 🔴 **아니다** | 읽는 곳은 `sources/lua_loader.py` · `analysis/effect_analyzer.py` 뿐. engine **0곳**. `iter_effects` 는 production 호출자 0 |
| **B** | activation-timing 이 `legal_actions()` 에서 쓰이는가 | 🟢 **예** | `Duel.legal_actions` → `_activation_actions` → **`_activation_gate` 관문 ②** `ActivationTimingChecker` |
| **C** | `apply()` 에서 쓰이는가 | 🟢 **예** | `Duel.apply` → `_apply_activation` → **같은 `_activation_gate`**. 독립 검증이다 |
| **D** | `EffectDefinition` 의 유발 조건이 trigger candidate 생성에 쓰이는가 | 🔴 **아니다** | 쓸 칸이 없다. 후보는 `activatable_effects` + `target_combinations` + 세 관문이 만든다. `duel.py` 에 `TriggerSpec`·`TimingPoint`·`EffectSpec`·`iter_effects` **0회** |
| **E** | 함정 카드 종류가 `ACTIVATE_EFFECT`/`ACTIVATE_CARD` **선택**에 영향을 주는가 | 🔴 **아니다** | 생성기는 언제나 `PlayerAction.activate_effect` 를 만든다. 카드 종류는 **허가 여부**(`UNKNOWN` + 보류 사유)만 바꾼다 |
| **F** | `legal_actions()` 가 함정의 발동 가능성을 **표현**할 수 있는가 | 🟡 **표현은 한다 · 허가는 못 한다** | `withheld` 에 종류·이유·빠진 규칙으로 남는다. `allowed` 에는 들어가지 않는다 |
| **G** | "함정 카드를 발동한다" 를 **끝까지 실행**할 수 있는가 | 🔴 **아니다** | 검증기 `UNKNOWN` → 후보 제외 → (직접 넣어도) `EffectActivator` 가 `unauthorized`. ChainLink **0** |

---

## 10. `legal_actions` / `apply` 영향

| 항목 | 결과 |
|---|---|
| 후보 생성이 선행 정보를 더 읽게 되었는가 | **아니다** — production 0줄 |
| `_activation_gate` 의 관문 수 | **3개 그대로** |
| 함정 보류 사유 | `TRAP_TRIGGER_MISSING` 그대로 (실제 카드 3장으로 확인) |
| 몬스터 보류 사유 | `MONSTER_ACTIVATION_MISSING` — **함정과 다른 문자열** |
| `ChainLink` | 선행 정보를 **싣지 않는다** (`code`·`event`·`timing`·`spell_speed`·`card_type`·`condition` 칸 전부 없음) |

---

## 11. AI / Search 영향

| 질문 | 답 |
|---|---|
| AI 가 `legal_actions` 가 안 주는 함정 발동을 **임의로 만들 수 있는가** | 🔴 **아니다** — `agent/` 에 `PlayerAction.activate*` 생성 자리가 **0곳** |
| Search 가 activation-timing 을 **스스로 추론**하는가 | 🔴 **아니다** — `ActivationTimingChecker` 를 읽지 않는다 |
| Search 가 `SetCode(EVENT_*)` 를 읽는가 | 🔴 **아니다** — `EffectSpec`·`iter_effects`·`EVENT_FREE_CHAIN` 전부 0회 |
| AI 가 숨은 정보로 발동 조건을 추론하는 문제 | 🔴 **없다** — `EffectDefinition`·`TriggerSpec` 도 읽지 않는다 |
| "`legal_actions` 만 탐색한다" 는 계약과 충돌하는가 | 🔴 **아니다** |

→ AI/Search 에 **변경이 필요하지 않다.** "향후 필요하다" 는 이유로 고치지 않았다.

---

## 12. production 변경 여부 — **0줄**

§10 의 네 조건을 하나씩 확인했고 **하나도 성립하지 않는다.**

| 조건 | 판정 |
|---|---|
| docstring 이 실제 코드와 명백히 모순 | 🔴 **아니다.** `activation` 의 타입·`TRAP_TRIGGER_MISSING` 의 문장·`_NormalSpellActivation` 의 표 전부 측정과 일치 |
| production 계약이 실제 데이터와 명백히 충돌 | 🔴 **아니다.** `TRAP_TRIGGER_MISSING` 은 `EffectDefinition` 에 `code` 칸이 없다는 **사실**을 적고, corpus 186종이 그 필요를 뒷받침한다. 등재 5장에 물리지 않는다는 것은 **범위 차이**이고 모순이 아니다 |
| 특정 필드가 잘못된 의미로 소비되어 동작을 오염 | 🔴 **아니다.** `EffectSpec.code` 는 engine 에서 **소비되지 않는다** — 오염될 경로가 없다 |
| 감사를 위해 반드시 필요한 계약 문서화 변경 | 🔴 **불필요했다.** 측정과 분류는 테스트와 이 보고서로 고정된다 |

§10 의 금지 항목도 전부 지켰다 — `ACTIVATE_CARD` 구현 ✗ · 함정 발동 구현 ✗ ·
새 trigger engine ✗ · 새 event bus ✗ · timing engine ✗ · 새 Condition DSL ✗ ·
새 `PlayerActionKind` ✗ · `legal_actions` 확장 ✗ · AI/Search 확장 ✗ ·
freeze 해제 ✗.

---

## 13. 테스트 결과

새 파일: `tests/test_activation_precondition_audit.py` — **26개** (요구 최소 20개)

| # | 테스트 | §11 요구 |
|---|---|---|
| 01 | 세 계층의 칸이 다르다 (`code` 는 `EffectSpec` 에만) | 1 |
| 02 | 🔴 `activation` 은 Condition 이고 timing 이 아니다 | 5 |
| 03 | 항목별 A~F 분류 (실측) | 1 |
| 04 | 🔴 `code` 한 칸에 **두 어휘** (`EVENT_*`/`EFFECT_*`) | 3 |
| 05 | 🔴 engine 이 `spec.code` 를 읽지 않는다 | 4 |
| 06 | 🔴 `iter_effects` production 호출자 **0** | 4 |
| 07 | `TimingPoint` 8종 ≠ Lua 수백종 | 3 |
| 08 | 🔴 corpus 함정 **186종** — 구분이 실제 문제다 | 3 |
| 09 | 🔴 그런데 등재 함정 **5장 전부 FREE_CHAIN** | 8 |
| 10 | 유발 조건은 `TriggerSpec` 쪽 | 7 |
| 11 | 발동 가능 조건은 `EffectDefinition.activation` (8/16) | 7 |
| 12 | timing 은 제3 계층이고 **카드 종류**에서 나온다 | 6 |
| 13 | 등재 16개 전수 표 | 2 |
| 14 | 실제 **함정 3장** 보류 사유 | 8 |
| 15 | 실제 **마법 2장** 체인까지 | 9 |
| 16 | 몬스터는 **다른 이유** (등재 0장) | 10 |
| 17 | 🟢 타이밍 관문은 `legal_actions`·`apply` 둘 다 쓴다 | 11, 12 |
| 18 | 🔴 정의의 유발 조건이 후보 생성에 안 쓰인다 | 11 |
| 19 | 🔴 카드 종류는 **종류 선택**이 아니라 허가를 바꾼다 | 16 |
| 20 | 함정은 `withheld` 로만 표현 · 끝까지 못 간다 | 15 |
| 21 | `ChainLink` 는 선행 정보를 싣지 않는다 | 14 |
| 22 | 🟢 AI 는 발동을 발명하지 않는다 | 17 |
| 23 | 숨은 정보 · `state_hash` · RNG 불변 | 18 |
| 24 | Engine V1 을 넓히지 않았다 | 20 |
| 25 | production 변경 0 (AUDIT-ONLY) | — |
| 26 | 검색 digest 불변 (611결정) | 19 |

실제 카드 **8장** 사용 — 욕망의 항아리 · 다이안 켓 · 싸이크론 · 강제 탈출 장치 ·
`5915629` · 벌금 · 로스트 · 홍옥의 사령.

기존 테스트를 **삭제·skip·약화하지 않았고, 고친 것도 없다.**

### 전체 회귀

```
$ python -m pytest -p no:randomly -q
4659 passed, 4 skipped in 700.59s (0:11:40)
```

| 항목 | 값 |
|---|---|
| Phase 3-F-23 종료 시점 baseline | 4,633 passed |
| 이번 Phase 신규 테스트 | +26 |
| 합계 (측정값) | **4,659 passed** |
| 실패 | **0** |
| skip | 4 (이전 Phase 와 동일 — 이번 Phase 에서 추가한 skip 은 0건) |

26 = 4,659 − 4,633 이 정확히 맞으므로, **기존 테스트 중 사라지거나 실패로 바뀐 것은
한 건도 없다.** `-p no:randomly` 로 순서 고정 실행했고, 신규 테스트 파일은 실행 시점에
디스크에 존재했으므로 이 4,659 에 포함되어 있다.

### 🔴 고의 위반 주입 9건

7개 파일을 md5 로 백업하고 하나씩 심었다 되돌렸다. 마지막 복원을 md5 로 확인했다.

| # | 심은 위반 | 걸린 테스트 | 결과 |
|---|---|---|---|
| 1 | `EffectDefinition` 에 `code` 칸을 더한다 | `test_01` `test_24` | ✅ |
| 2 | 함정 보류 사유를 몬스터 사유와 같게 | `test_14` | ✅ (기대값이 틀렸다) |
| 3 | 후보 생성이 `EffectSpec` 을 읽게 | `test_18` | ✅ |
| 4 | timing 모듈이 `EVENT_` 를 읽는 척 | `test_02` `test_05` | ✅ |
| 5 | `TimingPoint` 를 하나 더 | `test_07` `test_24` | ✅ |
| 6 | AI 가 `EffectDefinition` 을 읽게 | `test_22` | ✅ |
| 7 | `ChainLink` 에 선행 정보 칸 | `test_21` | ✅ |
| 8 | **세 관문 중 타이밍 관문을 끈다** | `test_17` | ⚠️ **놓쳤다 → 고쳐 잡았다** |
| 9 | 라이브러리에서 발동 가능 조건 하나 제거 | `test_03` `test_11` | ✅ |

#### 주입 8 — 🔴 또 **부분 문자열**이었다

`test_17` 이 `"ActivationTimingChecker" in body` 로 쟀다. 주입은
`timed = None if True else ActivationTimingChecker(...)` 로 관문을 **꺼 버렸는데**,
이름이 꺼진 가지 안에 그대로 남아 통과했다. **3-F-21 · 3-F-22 에서 겪은 것과
같은 함정이 세 번째로 나왔다.**

고친 방향: AST 로 `timed` 에 대입되는 것이 **그 호출 자체**(`ast.Call`)여야 하고
조건식(`IfExp`)이나 상수가 아니어야 한다고 단정한다. 나머지 두 관문도 호출
집합으로 센다.

(부수 확인: 그 주입은 `test_26` 의 digest 도 깼다 — 타이밍 관문을 끄면 **AI 의
수가 바뀐다.** 관문이 후보 집합에 실제로 관여한다는 증거다.)

---

## 14. 불변 조건 검증 (§12)

| 항목 | 결과 |
|---|---|
| `state_hash` | **불변** |
| RNG | **불변** |
| hidden-information | **불변** (상대 손·덱 `concealed=True`, `cards=()`) |
| `GameStateView` | **불변** |
| Search | **불변** |
| AI | **불변** |
| Engine V1 freeze | **유지** (enum 11종 · `EffectDefinition` 칸 10개 · `TimingPoint` 8개) |
| 검색 digest | **불변** — 6판 **611결정** |
| 4,633 baseline 대비 회귀 | **없음** (아래 수치) |

---

## 15. 최종 판정

> ## **B. ACTIVATION_PRECONDITION_DOCUMENTATION_ONLY**

발동 선행 정보의 **소재와 끊기는 지점이 확정되었고, production 을 고칠 이유가
없다.**

### 근거 (실제 코드 경로와 함께)

1. **선행 정보는 대부분 이미 있다**(§8) — 카드 종류 · 앞뒤면 · 세트한 턴 ·
   턴/페이즈 · 체인 · 우선권 · zone · controller · `effect_ref` · ChainLink 정보.
   코드가 직접 *"세트와 세트한 턴은 이유가 아니다. 둘 다 있다"* 라고 적는다.
2. **없는 것은 둘이고, 둘 다 이름으로 지목되어 있다** — 유발 조건
   (`TRAP_TRIGGER_MISSING`) 과 몬스터 효과 분류(`MONSTER_CLASSIFICATION_MISSING`).
3. **유발 조건은 "누락" 이 아니라 "건너지 않은 경계" 다**(§1 · §4) —
   `EffectSpec.code` 에 298종이 있고 `iter_effects` 로 닿을 수 있으나 production
   이 쓰지 않는다. ADR-006 의 태도와 같다.
4. **timing 경로는 끊기지 않는다**(§5) — `_activation_gate` 가 `legal_actions` 와
   `apply` 양쪽에서 같은 세 관문을 돌린다.
5. **production 을 고칠 네 조건 중 하나도 성립하지 않는다**(§12).

### 왜 A 가 아닌가

A(`..._CONTRACT_FIXED`)는 계약을 **고쳤을 때**의 판정이다. 이 Phase 는
production 을 **한 줄도** 바꾸지 않았다 — 고칠 모순이 없었다. (3-F-23 은 실제
모순이 있어 A 였다. 그 구분을 흐리지 않는다.)

### 왜 C 가 아닌가

C(`..._GAP`)는 선행 계약에 **빈 구멍**이 있다는 판정이다. 측정 결과 빈 구멍이
아니다 — 없는 둘은 **이름으로 지목된 경계**이고, 있는 것은 전부 production 에서
실제로 소비된다. §10 이 경고한 대로 "구현되어 있지 않다" 를 gap 으로 바꾸지
않았다.

### 왜 D 가 아닌가

D(`PRODUCTION_BEHAVIOR_CONFLICT`)는 동작 충돌이다. `EffectSpec.code` 는 engine
에서 **소비되지 않으므로** 잘못된 의미로 동작을 오염시킬 **경로 자체가 없다**.

---

## 16. 향후 `ACTIVATE_CARD` / 함정 발동 구현에 필요한 선행 조건

측정에서 **그대로 따라오는 것만** 적는다. 새 설계를 하지 않는다.

| # | 선행 조건 | 왜 |
|---|---|---|
| 1 | **`EffectSpec.code` → 엔진 계층으로 넘길 경계 결정** | 지금은 건너지 않는다. `EffectDefinition` 에 칸을 더할지, `iter_effects` 를 production 에서 쓸지, 등록 시점에 `TriggerSpec` 으로 옮길지 — **셋 다 가능하고 하나를 골라야 한다** |
| 2 | **`EVENT_*` 와 `EFFECT_*` 의 분리** | 한 칸에 두 어휘가 섞여 있다(§4). 유발 사건만 쓰려면 먼저 갈라야 한다 |
| 3 | **298종 → 엔진 어휘로의 사상 범위 결정** | `TimingPoint` 는 8종뿐이고 1:1 사상이 없다. 어디까지 옮길지 정해야 한다 |
| 4 | **함정 corpus 186종 중 지원 범위** | 등재 5장은 전부 `EVENT_FREE_CHAIN` 이라 **현재 표본으로는 검증할 수 없다.** 다른 코드의 함정을 먼저 등재해야 측정이 가능하다 |
| 5 | **스펠 스피드 2 의 응답 타이밍** | `ActivationTimingChecker` 는 있으나 함정이 거기까지 가지 못한다 |
| 6 | **비용 경로** | 칸은 있고 값이 전부 비어 있다. 비용이 생기면 `_activation_actions` 의 "비용 없는 효과만" 관문이 처음으로 작동한다 |
| 7 | **`ACTIVATE_CARD` vs `ACTIVATE_EFFECT` 역할 재배분** | 3-F-23 §12 에 적은 그대로. 지금은 후자가 마법·함정 발동을 맡는다 |
| 8 | **AI/Search 회귀 재측정** | 후보가 늘면 611결정 digest 가 깨진다 (주입 8이 실증) |

---

## 17. 이번 Phase 에서 **의도적으로 하지 않은 것**

* `ACTIVATE_CARD` 를 구현하지 않았다.
* 함정 발동을 구현하지 않았다.
* `SetCode(EVENT_*)` 의 의미를 **추측해서 규칙화하지 않았다** — 298종을 분류하지도,
  `TimingPoint` 로 사상하지도 않았다.
* 새 trigger engine · event bus · timing engine · Condition DSL 을 만들지 않았다.
* `legal_actions` 를 넓히지 않았고 AI/Search 를 고치지 않았다.
* 🔴 **`EffectDefinition` 에 `code` 칸을 더하지 않았다** — "있으면 편하다" 는 이유로
  필드를 만들지 않는다는 §7 의 지시 그대로다.
* 공식 규칙과 Lua/CDB 표현을 **동일시하지 않았다** — `EVENT_FREE_CHAIN` 이 공식
  "자유 체인" 과 같은 것인지 **확인하지 않았고, 확인하지 않았다고 적는다.**
* 앞선 감사(3-E-31 · 3-F-4)의 결론을 **다시 쓰지 않았다.** 인용하고 좁혔다.
* 함정 5장에 `TRAP_TRIGGER_MISSING` 이 물리지 않는다는 발견으로 **그 문장을 고치지
  않았다** — 범위 차이이고 모순이 아니다.

---

## 18. 남은 structural risk

| 항목 | 내용 | 등급 |
|---|---|---|
| 한 칸에 두 어휘 | `EffectSpec.code` 가 `EVENT_*` 와 `EFFECT_*` 를 섞어 담는다. 읽는 쪽이 늘면 먼저 갈라야 한다 | 🟡 |
| `iter_effects` 가 production 에서 안 쓰인다 | 우회로가 **있다는 사실**이 "이미 연결되어 있다" 로 오독될 수 있다 (3-E-31 서술이 그 방향이었다) | 🟡 |
| 등재 함정 표본이 1종뿐 | `EVENT_FREE_CHAIN` 하나라서 유발 조건 구분을 **지금 데이터로는 검증할 수 없다** | 🟡 |
| 보류 사유의 범위 차이 | `TRAP_TRIGGER_MISSING` 이 등재 5장에는 물리지 않는다 — 읽는 사람이 "이 카드도 그 이유로 막혔다" 로 읽을 수 있다 | 🟡 |
| 몬스터 효과 표본 0 | 분류가 없어 속도조차 정할 수 없다는 사실을 **표본으로 확인할 수 없다** | 🟡 |

전부 **FUTURE WORK 로 기록**한다. 고치지 않았다.

---

## 19. 다음 Phase 후보 (최대 1개)

**`EVENT_FREE_CHAIN` 의 의미 확정 — 공식 "자유 체인" 과 Lua 상수의 대응 감사
(조사 전용).**

이유: 이 Phase 가 등재된 16개 전부와 함정 corpus 최다 코드가
`EVENT_FREE_CHAIN` 임을 확인했지만, **그 상수가 공식 규칙의 무엇에 해당하는지는
확인하지 않았다**(§17). 지시 §3 이 "이름만 보고 단정하지 말라" 고 했고 나는 그
지시를 지켜 **확인하지 않은 채로 남겼다.** 그런데 §16 의 1~4번 선행 조건은 전부
"이 상수가 무엇을 뜻하는가" 에 걸려 있다 — 가장 많이 등장하는 단 하나의 코드의
의미를 모르면 경계를 넘길 수도, 지원 범위를 정할 수도 없다. 저장소에 공식 룰북과
ruling 계층이 이미 있으므로 **새 규칙 설계 없이 대응만** 확정할 수 있다.

다만 **다음 Phase 는 임의로 진행하지 않는다.**
