# Phase 3-E-44 — Dormant 판정기와 Live Gate 판정 일치성 측정

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-E-44 — Dormant 판정기와 Live Gate 판정 일치성 측정 |
| 성격 | **AUDIT-ONLY** (production 수정 0줄) |
| Base Phase | 3-E-43 — Trigger pipeline dormant 구조 감사 |
| Base 결과 commit | `35e156e` |
| Base 보고서 commit | `40a7766` |
| Base 최종 판정 | STRUCTURAL_RISK_IDENTIFIED |

**실제 HEAD 확인 (작업 시작 전)**

```
$ git rev-parse HEAD
40a7766c5752be3d443f8d364d1e10140c7469be
$ git rev-parse --abbrev-ref HEAD
claude/pensive-goodall-te1egy
$ git merge-base --is-ancestor 35e156e HEAD   → ANCESTOR
$ git merge-base --is-ancestor 40a7766 HEAD   → ANCESTOR
$ git status --short                          → (비어 있음)
```

Base 산출물도 그 자리에 있다 — `docs/phase3e43-trigger-pipeline-dormant-audit.md`
(23,536 B) · `tests/test_trigger_pipeline_dormant_audit.py` (28,374 B).
**reset · checkout · 되돌리기를 하지 않았다.** Engine V1 freeze 를 유지한다.

### 이번 Phase 가 답한 질문

3-E-43 이 기록한 **R-2** — "dormant trigger 계층의 판정 질문 다섯 개가 live
production 계층의 판정 질문과 의미적으로 중복되는가" — 를 **이름 비교가 아니라
동일 입력 실측**으로 확정한다. 중복이면 중복이라고, 다르면 **재현 근거와 함께**
다르다고 적는다.

---

## 2. 5개 판정 질문의 live / dormant 위치

| 질문 | dormant 위치 | live 위치 |
| --- | --- | --- |
| `EVENT_RELATION` | `engine/trigger.py:1306` `TriggerEligibilityJudge._event_relation` | **없다** |
| `ACTIVATION_ZONE` | `engine/trigger.py:1322` `._activation_zone` | `engine/action_validation.py:1280` `_activation_out_of_scope` + `:273` `ActionValidator._first_unseen` |
| `TRIGGER_CONDITION` | `engine/trigger.py:1363` `._trigger_condition` | `engine/activation.py:647` `EffectActivator._check_condition` |
| `EXECUTION_AUTHORITY` | `engine/trigger.py:1447` `._execution_authority` | `engine/activation.py:615` `EffectActivator._check_authority` |
| `COST_FEASIBILITY` | `engine/trigger.py:1486` `._cost_feasibility` | **관문 자리에 없다** (`engine/duel.py:473` 의 범위 거름이 유일) |

### 관문 수가 다르다

dormant 는 **다섯 관문을 전부 돌린다** (`judge` 는 "하나가 막혀도 나머지를 계속
본다"). live 는 `Duel._activation_gate` 가 **세 관문**을 순서대로 세우고 하나가
막히면 거기서 멈춘다 — `ActionValidator` → `ActivationTimingChecker` →
`EffectActivator.can_activate`.

`ActivationTimingChecker`(스펠 스피드 · 세트한 턴) 는 **dormant 대응이 없다**.
이것은 R-2 의 반대 방향 공백이고 이번 측정의 범위 밖이므로 `F.
NO_DORMANT_COUNTERPART` 로만 적어 둔다 (§12 참조).

---

## 3. 각 판정의 caller → callee 구조

### dormant

```
(production caller 없음)
   ↓
TriggerEligibilityJudge.judge(candidate, spec, event)       engine/trigger.py:1258
   ├→ _event_relation(spec, event)        → spec.matches(event)        :1308
   ├→ _activation_zone(candidate, spec)   → view.find(source)
   ├→ _trigger_condition(...)             → ConditionEvaluator.evaluate
   │                                      → condition.missing_rules
   ├→ _execution_authority(spec, defn)    → execution_availability(defn, lookup)
   └→ _cost_feasibility(candidate, defn)  → CostValidator.validate_group
   ↓
TriggerEligibility.fold(candidate, gates) → GateVerdict × 5
```

`judge_all` 의 caller 는 **부품 모듈 밖에 없다** (3-E-43 측정 재확인).

### live

```
Duel.legal_actions ─┐                       engine/duel.py
Duel.apply ─────────┴→ Duel._activation_gate(action, validator, selections)   :551
   ├→ ActionValidator.validate(action)                 action_validation.py:253
   │     ├→ _first_unseen → HIDDEN_CARD
   │     └→ requirements(_activate_effect) → _NormalSpellActivation
   │                                       → _activation_out_of_scope   :1280
   ├→ ActivationTimingChecker.check(ActivationTiming(...), action)
   └→ EffectActivator.can_activate(state, chain, action, authorization=verdict)
         └→ _check(...)
              ├→ _check_shape        (모양 · 체인 수용)
              ├→ _verdict            (허가)
              ├→ definition 조회      → RULE_NOT_IMPLEMENTED
              ├→ _check_authority    → execution_availability   ← 공유 지점
              ├→ _check_condition    → ConditionEvaluator        ← 같은 평가기
              └→ _check_targets
```

`Duel._activation_actions` 는 관문에 **들어가기 전에** `if definition.cost.costs:
continue` 로 비용 있는 효과를 통째로 뺀다 (`engine/duel.py:473`).

---

## 4. 동일 입력 fixture / scenario

전부 **실제 카드 · 실제 리포지토리**로 만든 판이다. 같은 `GameState` · 같은
`EffectDefinition` · 같은 `InstanceId` 를 두 계층에 그대로 건넨다
(`tests/test_dormant_live_gate_equivalence.py` 의 `board()` · `definition_of()` ·
`dormant_gates()` · `live_verdicts()`).

| 카드 | passcode | 종류 (공식 DB `type_mask`) |
| --- | --- | --- |
| 욕망의 항아리 | 55144522 | 통상 마법 |
| 싸이크론 | 5318639 | 속공 마법 |
| 벌금 | 92595643 | 함정 |

관문별 시나리오 수: ACTIVATION_ZONE **7** · TRIGGER_CONDITION **6** ·
EXECUTION_AUTHORITY **5** · COST_FEASIBILITY **4** · EVENT_RELATION **5**.
요구된 "관문마다 최소 3개" 를 모두 넘긴다.

---

## 5. 결과 비교표

### 5-1. `ACTIVATION_ZONE` — **D. DIFFERENT_RESULT**

| # | 동일 입력 | dormant `(validity, code)` | live `ActionValidator` | 일치 |
| --- | --- | --- | --- | --- |
| Z1 | 패의 통상 마법 · 선언 `{HAND}` | `VALID / OK` | `VALID / OK` | ✅ |
| **Z2** | **세트한 통상 마법 · 선언 `{HAND}`** | **`INVALID / SOURCE_WRONG_ZONE`** | **`VALID / OK`** | ❌ |
| Z3 | 세트한 통상 마법 · 선언 `{SZONE}` | `VALID / OK` | `VALID / OK` | ✅ |
| **Z4** | **패의 통상 마법 · 선언 `None`** | **`UNKNOWN / RULE_NOT_IMPLEMENTED`** | **`VALID / OK`** | ❌ |
| Z5 | 상대 패의 카드 (관측 불가) | `UNKNOWN / HIDDEN_CARD` | `UNKNOWN / HIDDEN_CARD` | ✅ |
| **Z6** | **패의 함정 · 선언 `{HAND}`** | **`VALID / OK`** | **`UNKNOWN / RULE_NOT_IMPLEMENTED`** | ❌ |
| Z7 | 패의 속공 마법 · 선언 `{HAND}` | `VALID / OK` | `VALID / OK` | ✅ |

**세 자리에서 답이 실제로 갈린다. 양쪽 방향 모두다.**

* **Z2 · Z4 — dormant 가 더 많이 막는다.** dormant 는 `spec.activates_from` 라는
  **선언과의 대조**를 묻는다. 선언이 판의 사실과 어긋나면 `SOURCE_WRONG_ZONE`
  (`INVALID`) 이고, 선언이 없으면 `UNKNOWN` 이다.
* **Z6 — dormant 가 더 많이 허가한다 (위험한 방향).** live 는 "지금 이 Phase 가
  판정할 수 있는 발동인가" 를 묻고 함정을 `UNKNOWN` 으로 둔다. dormant 는 그
  질문을 **아예 하지 않으므로** 함정을 `VALID` 로 통과시킨다.

**두 질문은 같은 질문이 아니다.** live 쪽의 근거는 production 자신이 적어 둔다
(`engine/action_validation.py` `_activation_out_of_scope` docstring):

> 필드에서의 발동(몬스터의 기동 효과 · 세트한 마법 · 함정)은 **실제 규칙에서
> 적법하다.** 그것을 `SOURCE_WRONG_ZONE` 같은 `INVALID` 로 적으면 "규칙이
> 금지한다" 는 거짓을 말하게 된다.

그 태도는 코드로도 확인된다 — live 에서 `SOURCE_WRONG_ZONE` 을 내는 함수는
`_summon_like` · `_set_spell_trap` · `_change_position` · `_attack` **넷뿐이고
발동은 하나도 없다**. `_activate_effect` 의 코드 집합은
`{NOT_TURN_PLAYER, RULE_NOT_IMPLEMENTED, SOURCE_NOT_CONTROLLED, WRONG_PHASE, ZONE_FULL}`
이다 (`test_08`).

### 5-2. `TRIGGER_CONDITION` — **B. EQUIVALENT_WITH_DIFFERENT_REPRESENTATION**

| # | 동일 입력 | dormant | live `can_activate` | 일치 |
| --- | --- | --- | --- | --- |
| C1 | 조건 없음 | `VALID / OK` | `VALID / OK` | ✅ |
| C2 | 조건 참 (`Always()`) | `VALID / OK` | `VALID / OK` | ✅ |
| C3 | 조건 거짓 (`IsMonster()`) | `INVALID / CANDIDATE_NOT_ELIGIBLE` | `INVALID / CANDIDATE_NOT_ELIGIBLE` | ✅ |
| C4 | 조건 모름 · 없는 규칙 | `UNKNOWN / RULE_NOT_IMPLEMENTED` | `UNKNOWN / RULE_NOT_IMPLEMENTED` | ✅ |
| C5 | 정의 미등록 | `UNKNOWN / RULE_NOT_IMPLEMENTED` | `UNKNOWN / RULE_NOT_IMPLEMENTED` | ✅ |
| C6 | `spec.condition` 만 있다 | `UNKNOWN / RULE_NOT_IMPLEMENTED` | `VALID / OK` | — (동일 입력 아님) |

**공유 입력 다섯 건 전부 한 칸도 다르지 않다.** 두 계층이 같은
`ConditionEvaluator` 를 쓰고, `UNKNOWN` 안에서 까닭을 가르는 방법
(`missing_rules` 가 비면 `INFORMATION_UNAVAILABLE`, 있으면
`RULE_NOT_IMPLEMENTED`) 까지 같다 — Phase 3-E-26 과 3-E-38 이 그렇게 맞춰
두었다 (`test_12`).

**C6 을 `DIFFERENT_RESULT` 로 적지 않는다 — 같은 입력이 아니다.**
`TriggerSpec.condition` 에는 live 대응 통로가 없고, live `_check_condition` 은
`definition.activation` 하나만 읽는다 (AST 로 확인: `activation` 은 있고
`condition` 은 없다). 이것은 **입력 영역(domain)의 차이**이고 판정의 차이가
아니다.

차이는 **표현**에만 있다 — dormant 는 `GateVerdict`(관문 이름을 보존), live 는
`ActivationResult`(`ActivationStatus.CONDITION_FALSE` / `CONDITION_UNKNOWN`) 를
거쳐 `ValidationResult` 로 정규화한다. C5 에서 두 계층은 **다른 관문**에서
멈추면서 **같은 답**을 낸다.

### 5-3. `EXECUTION_AUTHORITY` — **A. EQUIVALENT**

| # | 동일 입력 | `ExecutionAvailability` | dormant | live | 일치 |
| --- | --- | --- | --- | --- | --- |
| A1 | `official_lua` + 구현 등록 | `EXECUTABLE` | `VALID / OK` | `VALID / OK` | ✅ |
| A2 | 구현 없음 | `NO_IMPLEMENTATION` | `UNKNOWN / RULE_NOT_IMPLEMENTED` | 같음 | ✅ |
| A3 | 정의 미등록 | — | `UNKNOWN / RULE_NOT_IMPLEMENTED` | 같음 | ✅ |
| A4 | 공식 텍스트 유추 | `FORBIDDEN_SOURCE` | `INVALID / EXECUTION_FORBIDDEN` | 같음 | ✅ |
| A5 | 손으로 쓴 미검증 | `UNVERIFIED` | `UNKNOWN / RULE_NOT_IMPLEMENTED` | 같음 | ✅ |

**다섯 관문 중 유일하게 `A. EQUIVALENT` 다 — 판단이 두 벌이 아니라 한 벌이기
때문이다.** dormant `_execution_authority` 와 live `_check_authority` 가 **모두**
`execution_availability(definition, lookup)` 를 부른다 (`test_16`). 맞춰 둔 것이
아니라 공유한다. `ExecutionAvailability` 는 5개 값이고 그 전부에서 같은 답이
나오는 것이 우연일 수 없다.

(A4 의 `EXECUTION_FORBIDDEN` 일치는 Phase 3-E-38 의 M2 가 live 쪽 코드를 그
자리로 옮겨 둔 결과다.)

### 5-4. `COST_FEASIBILITY` — **D. DIFFERENT_RESULT**

| # | 동일 입력 (라이프 8000) | dormant | live 열거 | live `can_activate` | 일치 |
| --- | --- | --- | --- | --- | --- |
| K1 | 비용 없음 | `VALID / OK` | 뺴지 않는다 | `VALID / OK` | ✅ |
| **K2** | **라이프 비용 1000 (치를 수 있다)** | **`VALID / OK`** | **행동을 통째로 뺀다** | `VALID / OK` | ❌ |
| **K3** | **라이프 비용 9000 (치를 수 없다)** | **`INVALID / INSUFFICIENT_LIFE`** | **행동을 통째로 뺀다** | **`VALID / OK`** | ❌ |
| K4 | 라이프 비용 8000 (정확히 전부) | `VALID / OK` | 행동을 통째로 뺀다 | `VALID / OK` | ❌ |

**K3 이 가장 선명하다.** 같은 판에서 dormant 는 "라이프가 8000 뿐이라 9000 을
지불할 수 없다" 는 **확실한 거부**를 내고, live 관문은 `VALID` 를 낸다.
live 쪽이 거짓말을 하는 것이 아니다 — `can_activate` 의 docstring 이 직접 적는다:

> 비용은 **치르지 않는다.** 치를 수 있는지까지는 여기서 답하지 못한다 —
> `CostPayer` 의 preflight 가 비공개이고, 그것을 밖에서 흉내 내면 두 벌이 갈린다.

그래서 live 의 "안 된다" 는 **비용 판정이 아니라 범위 제한**이다
(`engine/duel.py:473`, ADR-008 이 일반 rollback 을 미뤄 둔 자리). 두 계층의 답이
형태만 다른 것이 아니라 **뜻이 다르다.**

구조적 증거 둘:

* `CostValidator.validate_group` 을 부르는 자리는 repo 전체에서 **하나**이고
  그것이 dormant 관문이다 (`engine/trigger.py:1514`). live 지불 경로
  (`CostPayer._preflight`) 는 `validate` 를 비용마다 부른다 — **다른 단계의
  다른 질문**이다 (`test_20`).
* 등재 효과 **16개 전부 비용이 없다** (실측). 그래서 live 의 거름은 지금
  아무것도 빼지 않고, 이 차이는 **현재 production 결과를 바꾸지 않는다**
  (`test_21`).

### 5-5. `EVENT_RELATION` — **E. NO_LIVE_COUNTERPART**

| # | 동일 입력 | dormant | live |
| --- | --- | --- | --- |
| E1 | 선언 `CARD_DRAWN` ← 사건 `CARD_DRAWN` | `VALID / OK` | 대응 없음 |
| E2 | 선언 `CARD_DRAWN` ← 사건 `LIFE_CHANGED` | `INVALID / RULE_NOT_IMPLEMENTED` | 대응 없음 |
| E3 | `to_zones={GRAVE}` ← 사건 `to_zone=MZONE` | `INVALID / RULE_NOT_IMPLEMENTED` | 대응 없음 |
| E4 | `to_zones={GRAVE}` ← 사건 `to_zone=GRAVE` | `VALID / OK` | 대응 없음 |
| E5 | `operations={DESTROY}` ← 사건 `SEND_TO_GRAVE` | `INVALID / RULE_NOT_IMPLEMENTED` | 대응 없음 |

`TriggerSpec.matches` 를 부르는 자리는 `engine/trigger.py` **두 곳**뿐이다
(`TriggerRegistry.watching:568` · `_event_relation:1308`). `engine/` 과 `agent/`
어디에도 다른 caller 가 없다 (`test_24`). live 발동 열거는 **사건을 하나도 읽지
않는다** (Phase 3-E-30 이 이미 측정했다).

### 5-6. 요약

| 관문 | 판정 | 근거 |
| --- | --- | --- |
| `EVENT_RELATION` | **E. NO_LIVE_COUNTERPART** | `spec.matches` caller 2곳 모두 dormant |
| `ACTIVATION_ZONE` | **D. DIFFERENT_RESULT** | Z2 · Z4 · Z6 에서 실제로 답이 갈린다 (양방향) |
| `TRIGGER_CONDITION` | **B. 표현만 다르다** | 공유 입력 5건 전부 `(validity, code)` 동일 |
| `EXECUTION_AUTHORITY` | **A. EQUIVALENT** | 판단 함수가 한 벌 (`execution_availability`) |
| `COST_FEASIBILITY` | **D. DIFFERENT_RESULT** | K3 에서 `INVALID` ↔ `VALID`. live 는 묻지 않는다 |

**3-E-43 의 R-2 는 절반만 맞았다.** "넷이 live 와 같은 질문" 이라는 기록은
이름 수준의 관찰이었고, 동일 입력으로 재면 **같은 답을 내는 것은 둘**
(`EXECUTION_AUTHORITY` · `TRIGGER_CONDITION`) 이고 **둘은 답이 갈린다**
(`ACTIVATION_ZONE` · `COST_FEASIBILITY`). 이 정정이 이번 Phase 의 핵심 결과다.

---

## 6. UNKNOWN / INVALID / FORBIDDEN 차이

세 구분이 **존재하고 양쪽에서 살아 있다.**

| 구분 | dormant 에서 | live 에서 | 일치 |
| --- | --- | --- | --- |
| `UNKNOWN` (모른다) | `HIDDEN_CARD` · `RULE_NOT_IMPLEMENTED` · `INFORMATION_UNAVAILABLE` | 같은 세 코드 | ✅ |
| `INVALID` (확실한 거부) | `CANDIDATE_NOT_ELIGIBLE` · `SOURCE_WRONG_ZONE` · `INSUFFICIENT_LIFE` | `CANDIDATE_NOT_ELIGIBLE` 등 | 부분 |
| `FORBIDDEN` (이 근거로는 실행하지 않는다) | `EXECUTION_FORBIDDEN` (`GateVerdict.forbids`) | `EXECUTION_FORBIDDEN` (`_AVAILABILITY_REFUSAL`) | ✅ |

**모름이 통과로 새지 않는다** — `GateVerdict.passed` 는 `VALID` 일 때만 참이고
(`test_32`), live 는 `ActionValidity.VALID` 가 아니면 관문에서 멈춘다.

### 다섯 관문이 낼 수 있는 코드 집합 (AST 실측)

```
_event_relation       OK · RULE_NOT_IMPLEMENTED
_activation_zone      OK · RULE_NOT_IMPLEMENTED · HIDDEN_CARD · SOURCE_WRONG_ZONE
_trigger_condition    OK · RULE_NOT_IMPLEMENTED · INFORMATION_UNAVAILABLE
                      · CANDIDATE_NOT_ELIGIBLE
_execution_authority  OK · RULE_NOT_IMPLEMENTED · EXECUTION_FORBIDDEN
_cost_feasibility     OK · RULE_NOT_IMPLEMENTED
                      (+ CostValidator 결과를 그대로 싣는다 → 9개가 더 흘러든다:
                       INSUFFICIENT_LIFE · NO_CANDIDATES · COST_NOT_IMPLEMENTED
                       · HIDDEN_CARD · INFORMATION_UNAVAILABLE
                       · CANDIDATE_NOT_ELIGIBLE · DUPLICATE_SELECTION
                       · TOO_FEW_SELECTED · TOO_MANY_SELECTED)
```

합집합 **7개 코드**. `SOURCE_WRONG_ZONE` 은 **dormant 발동 판정에만** 있고 live
발동 판정에는 없다 (§5-1).

---

## 7. state_hash / RNG / hidden information 영향

| 질문 | 측정 결과 |
| --- | --- |
| **state_hash 에 영향을 주는가** | **아니다.** dormant 판정 100회(무료 · 유료 정의 교대) 전후로 `state_hash` 가 동일 — `6a8f9596a8bb7f09…` (`test_26`) |
| **RNG 를 소비하는가** | **아니다.** `state.rng.getstate()` 가 전후 동일 (`test_26`) |
| **hidden information 에 따라 결과가 달라지는가** | **그렇다. 그리고 그것이 올바른 동작이다** |

### hidden information — 대칭이고 누설이 없다

| 관측 시점 | 출처 카드 | `ACTIVATION_ZONE` | `may_activate` |
| --- | --- | --- | --- |
| `MINE` | 내 패 | `VALID / OK` | `True` |
| `MINE` | 상대 패 | `UNKNOWN / HIDDEN_CARD` | `False` |
| `THEIRS` | 내 패 | `UNKNOWN / HIDDEN_CARD` | `False` |
| `THEIRS` | 상대 패 | `VALID / OK` | `True` |

완전히 대칭이다 — 각 시점은 자기 카드만 판정할 수 있다. **live 와 같은 코드
(`HIDDEN_CARD`) 로 같은 답을 낸다** (Z5). 구조적 보호도 있다:
`TriggerEligibilityJudge(GameState)` 는 `TypeError` 로 거부하고, 그 검사는
`__init__` 자기 자리에 있다 (`test_27`).

> **측정 방법에 대한 정정.** 처음 쓴 `test_27` 은 런타임 `TypeError` 만 보았고,
> 고의 위반 10 (보호 제거) 을 **잡지 못했다** — 아래 계층 `CostValidator` 가 같은
> 문장으로 던지기 때문에 테스트가 **엉뚱한 이유로 통과**했다. AST 로 "그 검사가
> 이 클래스의 `__init__` 안에 있는가" 를 더해 고쳤고, 그러자 위반을 잡았다.

---

## 8. AI / Search 영향

| 질문 | 측정 결과 |
| --- | --- |
| **AI/Search 가 어느 판정 계층을 소비하는가** | **live 뿐이다** |
| **production duel path 가 dormant 판정기를 간접적으로라도 호출하는가** | **아니다 — 0회** |
| **dormant 판정기의 출력이 현재 production 결과에 영향을 주는가** | **아니다** |

### `agent/` 의 실제 import (AST)

| 모듈 | import 하는 engine 모듈 |
| --- | --- |
| `agent/arena.py` | `action` · `duel` · `state.game_state` · `vocabulary` |
| `agent/evaluation.py` | `game_state_view` |
| `agent/heuristic.py` | `action` · `duel` · `game_state_view` |
| `agent/policy.py` | `action` · `duel` · `game_state_view` |
| `agent/runner.py` | `action` · `duel` · `state.game_state` · `vocabulary` |
| `agent/search.py` | `action` · `duel` · `game_state_view` · `vocabulary` |
| `agent/simulation.py` | `action` · `duel` · `game_state_view` · `validation` |

**다섯 trigger 모듈을 import 하는 `agent/` 모듈이 하나도 없다** (`test_28`).
AI 는 `Duel.legal_actions` / `Duel.apply` 를 통해 **live 세 관문만** 소비한다.

### 실제 듀얼 중 호출 횟수 (16판 · 1,359행동 · 전부 `completed`)

| 계층 | 호출 |
| --- | --- |
| `DORMANT TriggerEligibilityJudge.judge` | **0** |
| `DORMANT` 관문 `EVENT_RELATION` / `ACTIVATION_ZONE` / `TRIGGER_CONDITION` / `EXECUTION_AUTHORITY` / `COST_FEASIBILITY` | **각 0** |
| `DORMANT TriggerCollector._judge` · `TriggerSpec.matches` · `CostValidator.validate_group` | **각 0** |
| `LIVE ActionValidator.validate` | 121,125 |
| `LIVE _activation_out_of_scope` | 54,686 |
| `LIVE Duel._activation_gate` | 25,483 |
| `LIVE EffectActivator._check_authority` | 12,992 |
| `LIVE EffectActivator._check_condition` | 12,992 |
| `LIVE execution_availability` | 12,992 |
| `LIVE EffectActivator.can_activate` | 12,105 |
| `LIVE CostValidator.validate` · `CostPayer._preflight` | **각 0** |

dormant 합계 **0** · live 합계 **252,375**.

> **측정 방법에 대한 정정 둘.** ① `engine/effect/definition.py` 쪽
> `execution_availability` 만 감싸면 **0** 으로 보인다 — `engine/activation.py`
> 가 이름으로 import 했기 때문이다. 그 이름을 감싸서 12,992 를 얻었다. 처음의
> 0 은 사실이 아니라 **측정의 결함**이었다. ② `CostValidator.validate` 0 과
> `CostPayer._preflight` 0 은 **실제 사실**이다 — 등재 효과 전부가 무비용이므로
> 비용을 치르는 경로가 한 번도 열리지 않는다. 즉 비용 가능성은 **live 에서도
> dormant 에서도 런타임에 한 번도 묻지 않는다.**

`engine/duel.py` 는 trigger 타입 이름을 **하나도** 읽지 않는다 (AST). import
닫힘도 재측정했다 — `engine.duel` 의 engine-only closure **57** 모듈 (전체 65).
닫힘 밖: `engine.trigger_chain` · `engine.trigger_order` · `engine.timing` ·
`engine.event_pipeline`. 닫힘 안의 `engine.trigger` 는 **타입 주석 하나**로만
들어온다 — `activation_timing.py` 가 가져가는 이름이 `TimingPoint` 하나이고
`ActivationTiming.point` 의 타입으로 **한 자리**(line 256) 에서만 쓰인다.
3-E-43 의 숫자가 이 HEAD 에서 그대로 재현됐다.

---

## 9. `CHAIN_DEFINITION_UNAVAILABLE` — R-1 분석

**R-1 은 이번 측정에서 의미 차이를 만들지 않는다.**

| 확인 | 결과 |
| --- | --- |
| 다섯 관문의 코드 합집합에 `CHAIN_DEFINITION_UNAVAILABLE` 이 있는가 | **없다** |
| `CODE_VALIDITY[CHAIN_DEFINITION_UNAVAILABLE]` | `None` (3-E-40 그대로) |
| live carrier | `engine/chain.py:592` → `ChainResolutionStatus.INVALID_CHAIN_LINK` |
| dormant carrier | `engine/trigger_chain.py:406` → `ChainInsertion.UNKNOWN` |

추측이 아니라 **코드 집합을 세어** 확인했다 (`test_29`). 그 코드는 체인 **삽입**
단계에 살고, 다섯 관문은 삽입을 하지 않는다 — `TriggerEligibilityJudge` 의
docstring 이 "체인에 넣지도 않는다. `Chain.push` 를 부르지 않고 `engine.chain`
을 import 하지도 않는다" 고 적고, 그것이 사실이다.

그러므로 R-1 은 **3-E-40 의 policy 한 칸을 묶어 두는 문제로 그대로 남아 있고**,
관문 일치성과는 독립이다. 이번 Phase 에서 고치지 않는다.

---

## 10. 실제 확인된 위험

### R-2′ (정정) — 다섯 관문 중 **둘**이 live 와 다른 답을 낸다

3-E-43 은 "넷이 중복" 이라고 적었다. 동일 입력 실측 결과는 다르다.

| | 같은 답 | 다른 답 | live 없음 |
| --- | --- | --- | --- |
| 관문 | `EXECUTION_AUTHORITY` · `TRIGGER_CONDITION` | `ACTIVATION_ZONE` · `COST_FEASIBILITY` | `EVENT_RELATION` |

**왜 위험인가.** "중복이니 하나를 지우면 된다" 는 결론이 틀렸다는 뜻이다.
`ACTIVATION_ZONE` 과 `COST_FEASIBILITY` 는 **다른 질문을 하는 다른 판정기**이고,
어느 쪽을 지워도 그쪽 질문이 사라진다. 특히 Z6 방향(dormant 가 더 허가한다) 은
dormant 를 연결하는 순간 **live 가 일부러 `UNKNOWN` 으로 둔 함정을 `VALID` 로
바꾼다.**

### R-3 (새로 발견) — `_event_relation` 이 3-E-40 의 UNKNOWN policy 와 어긋난다

`engine/trigger.py` 의 `_gate(...)` 생산은 **17자리**다. 코드가 리터럴인 16자리를
`CODE_VALIDITY` 와 맞춰 보면 **정확히 한 자리**가 어긋난다.

| 자리 | 관문 | 선언한 validity | 코드 | 3-E-40 policy |
| --- | --- | --- | --- | --- |
| `engine/trigger.py:1315` | `EVENT_RELATION` | `INVALID` | `RULE_NOT_IMPLEMENTED` | **`UNKNOWN`** |

나머지 16자리(IfExp 한 자리 포함)는 전부 policy 와 일치한다.

**왜 중요한가 세 겹.**

1. `RULE_NOT_IMPLEMENTED` 는 `# --- 모른다 (UNKNOWN) ---` 묶음의 코드다. 그것을
   `INVALID` 와 짝지으면 **"엔진이 못 하는 것" 을 "규칙이 금지하는 것" 으로
   적는다** — 3-E-38 의 M1 이 live 쪽에서 바로 이것을 고쳤던 모양이다.
2. 어긋난 한 자리가 **live 대응이 없는 유일한 관문**에 있다. 즉 이 어긋남을
   잡아 줄 live 판정기가 없고, 3-E-43 이 센 "live↔dormant 상태 불일치 1건" 의
   실체가 이것이다.
3. live 쪽에는 이 짝을 **구문상 직접 적는 자리가 하나도 없다** (`test_31`).
   단 그것이 "live 가 그 짝을 절대 내지 않는다" 는 증명은 아니다 —
   `_fail` 처럼 `ActivationStatus` 로 `UNKNOWN` 여부를 가르는 경로는 코드만
   바꿔도 그 짝을 낼 수 있고, 고의 위반 3 이 실제로 그렇게 만들었다. 그 경로를
   막는 것은 **코드 선택**이고 3-E-38 의 M1 이 그 선택을 고쳐 두었다.

**지금은 터지지 않는다** — 그 관문은 런타임 호출이 0회다. 고치지 않는다:
`INVALID` → `UNKNOWN` 도 production 변경이고, 이번 Phase 는 측정이다.

### R-4 — `COST_FEASIBILITY` 를 연결하면 ADR-008 과 충돌한다

dormant 는 K2(치를 수 있는 비용) 를 `VALID` 로 통과시킨다. live 열거는 같은
행동을 **빼 둔다** — "비용을 치른 뒤 발동이 깨지면 되돌릴 방법이 없다
(ADR-008 이 일반 rollback 을 미뤄 두었다)" 가 그 까닭이다. dormant 판정을 믿어
후보로 올리면 **rollback 없는 지불 경로가 열린다.**

지금은 등재 효과 16개 전부가 무비용이라 **현재 production 결과를 바꾸지
않는다.** 그 숫자가 변하는 날이 신호다 (`test_21` 이 16과 0을 못박아 둔다).

---

## 11. 확인되지 않은 위험

정직하게 **측정하지 않은 것**을 적는다.

1. **`ActivationTimingChecker` 의 dormant 대응 없음** (`F.
   NO_DORMANT_COUNTERPART`). live 관문 2(스펠 스피드 · 세트한 턴, RULE-CHAIN-003
   · 004) 에 대응하는 dormant 관문이 없다. 이번 Phase 의 다섯 질문 밖이라 재지
   않았다. dormant 를 연결하면 **그 관문이 빠진 판정**이 된다.
2. **`SEGOC` · 동시 트리거 순서 · 타이밍 윈도우 · WHEN/IF · 발동 횟수 제한 ·
   체인 상한.** `UNCHECKED_RULES` 6개 항목이 dormant 자신의 선언으로 남아 있고,
   두 계층 **어디에도** 없다. 그래서 비교할 대상이 없었다.
3. **`CostValidator` 의 카드 비용 경로.** K1–K4 는 `LifeCost` 로 쟀다.
   `CardCost`(후보 수 판정 · `HIDDEN_CARD` · `NO_CANDIDATES`) 는 재지 않았다 —
   `_cost_feasibility` 가 결과를 그대로 싣는 구조이므로 코드 9개가 흘러들 수
   있다는 사실까지만 적었다.
4. **`TriggerCollector._judge`(또 하나의 dormant 판정기) 와 live 의 비교.**
   런타임 0회를 확인했고 코드 일치(3-E-26) 는 기존 테스트가 지키지만, **동일
   입력 비교는 하지 않았다.** 이번 Phase 는 `TriggerEligibilityJudge` 의 다섯
   관문만 쟀다.
5. **등재 16개 효과를 넘어선 범위.** 모든 측정이 등재 효과와 synthetic 정의
   기준이다. 14,000장 전체에 대한 주장이 아니다.
6. **`TimingPoint` 7개 전부에 대한 `EVENT_RELATION` 측정.** 5개 시나리오로
   `CARD_DRAWN` · `LIFE_CHANGED` · `CARD_MOVED` 를 쟀다. `MONSTER_SUMMONED` ·
   `PHASE_CHANGED` · `EFFECT_RESOLVED` · `COST_PAID` 는 재지 않았다.

---

## 12. 최종 판정

### **B. STRUCTURAL_RISK_CONFIRMED**

근거:

* **다섯 관문 중 둘이 동일 입력에서 실제로 다른 답을 낸다** — 추측이 아니라
  재현되는 측정이다 (`ACTIVATION_ZONE` Z2 · Z4 · Z6 / `COST_FEASIBILITY` K2 ·
  K3 · K4). 3-E-43 의 R-2 ("넷이 중복") 를 **정정**해야 한다.
* `ACTIVATION_ZONE` 의 Z6 은 **dormant 가 더 많이 허가하는** 방향이다. 연결하면
  live 가 일부러 `UNKNOWN` 으로 둔 함정이 `VALID` 가 된다.
* **R-3** — `_event_relation` 한 자리가 3-E-40 의 `CODE_VALIDITY` 와 어긋난다
  (`INVALID` + `RULE_NOT_IMPLEMENTED`). 17자리 중 하나이고, 하필 **live 대응이
  없는 관문**에 있다.
* **R-4** — `COST_FEASIBILITY` 를 연결하면 ADR-008(rollback 없음) 과 충돌한다.

`C. PRODUCTION_BLOCKER` 가 **아닌** 까닭도 측정했다:

* dormant 다섯 관문의 런타임 호출이 16판 1,359행동에서 **전부 0**이다. 간접
  호출조차 없다.
* `state_hash` 와 RNG 가 한 비트도 바뀌지 않는다.
* `agent/` 가 trigger 모듈을 **하나도** import 하지 않는다 — AI/Search 는 live
  만 소비한다.
* 등재 효과 16개 전부 무비용이라 R-4 가 **현재** 결과를 바꾸지 않는다.
* hidden information 경계가 양쪽에서 같은 코드로 지켜진다.

`A. AUDIT_ONLY_SUFFICIENT` 가 아닌 까닭: "문제가 없으면 없다고 판정한다" 가
원칙이지만, **동일 입력에서 답이 갈리는 것을 실제로 재현했다.** 지금 production
에 영향이 없다는 것과 구조적 위험이 없다는 것은 다른 말이다.

---

## 13. 이번 Phase 에서 하지 않은 것

* **`TriggerRegistry` 를 `duel.py` 에 연결하지 않았다.**
* **dormant trigger pipeline 을 활성화하지 않았다.** 다섯 관문의 런타임 호출은
  측정 후에도 0이다.
* **dormant 판정기를 삭제하지 않았다.** `engine/trigger.py` 1,565줄 그대로다.
* **live 판정기를 dormant 구조에 이식하지 않았다.**
* **새 `EventBus` 를 만들지 않았다.** 새 graph · event architecture 도 없다.
* **Chain 구조를 변경하지 않았다.**
* **`ValidationCode` enum 을 추가하거나 변경하지 않았다.** 48개 그대로다.
* **`CODE_VALIDITY` 를 고치지 않았다.** R-3 의 어긋난 한 자리도 **그대로 두었다**
  — `INVALID` → `UNKNOWN` 도 production 변경이다.
* **Search / AI 를 변경하지 않았다.** ranking · `ordering_key` · 평가 함수 모두
  그대로다.
* **Engine V1 freeze 를 해제하지 않았다.**
* **"중복처럼 보인다" 는 이유로 refactor 하지 않았다.** 오히려 중복이라는 기존
  기록이 절반 틀렸다는 것이 이번 결과다.
* **기존 테스트를 하나도 삭제 · 수정 · skip 하지 않았다.** assertion 을 약화한
  자리도 없다. 새 파일 하나만 더했다.
* **`scripts/fetch_ocg_rulings.py --all` 을 돌리지 않았다.** 공식 DB 외의 출처를
  참조하지 않았다.
* **카드 데이터(Lua · cards.cdb · data/ko)** 를 건드리지 않았다.
* **`state_hash` · RNG · hidden-information 경계 · AI ranking** 을 바꾸지 않았다
  (측정으로도 확인했다 — §7 · §8).

### 산출물

| 파일 | 내용 |
| --- | --- |
| `tests/test_dormant_live_gate_equivalence.py` | 감사 시험 **41개** (전부 통과) |
| `docs/phase3e44-dormant-live-gate-equivalence.md` | 이 보고서 |

production diff = **0 줄**.

### 테스트 결과

```
$ python3 -m pytest tests/test_dormant_live_gate_equivalence.py -p no:randomly -q
41 passed in 19.50s

$ python3 -m pytest -p no:randomly -q
4075 passed, 4 skipped in 511.97s (0:08:31)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-E-43 직후 (base) | 4,034 | 4 |
| Phase 3-E-44 (이번) | **4,075** | 4 |
| 차이 | **+41** | 0 |

**+41 이 이번에 더한 감사 시험 수와 정확히 같다.** 기존 테스트의 통과 수가 한
건도 줄지 않았고, skip 도 늘지 않았다 — 삭제 · 수정 · skip 추가 · assertion
약화가 없다는 뜻이다.

### 고의 위반 검증

감사 시험이 실제로 무언가를 재는지 확인하기 위해 production 에 **13건**의 고의
위반을 넣고 각각 복원했다 (복원은 md5 로 확인).

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `_event_relation` 의 `INVALID` → `UNKNOWN` | `test_22` · `test_23`×2 · `test_30` |
| 2 | `_activation_zone` 의 `SOURCE_WRONG_ZONE` → `CANDIDATE_NOT_ELIGIBLE` | `test_02` · `test_29` |
| 3 | live 조건 거짓 코드를 `RULE_NOT_IMPLEMENTED` 로 되돌림 (3-E-38 M1 역행) | `test_09[C3]` · `test_12` |
| 4 | `duel.py` 의 비용 거름 제거 | `test_21` · `test_33` |
| 5 | `agent/policy.py` 가 `engine.trigger` 를 import | `test_28` |
| 6 | `_cost_feasibility` 가 `validate_group` 대신 `validate` | `test_20` |
| 7 | `GateVerdict.passed` 가 `UNKNOWN` 도 통과로 센다 | `test_32` |
| 8 | live 가 함정을 범위 안으로 받는다 (Z6 수렴) | `test_06` |
| 9 | `activates_from=None` 을 "어디서든" 으로 읽는다 | `test_04` · `test_30` |
| 10 | `TriggerEligibilityJudge` 의 관측 경계 보호 제거 | `test_27` (**처음엔 못 잡았다** → 고쳤다) |
| 11 | production duel path 가 dormant 관문을 호출 | `test_25` |
| 12 | `COST_FEASIBILITY` 의 "비용 없음" 을 `UNKNOWN` 으로 | `test_17` · `test_27` |
| 13 | dormant 권위 판단을 `execution_availability` 에서 떼어 두 벌로 | `test_13[A2]` · `test_14` · `test_16` |

13건 전부 잡았다. **10번은 처음 놓쳤고**, 그 까닭(아래 계층의 같은 문장이 대신
던진다) 과 고친 방법을 §7 에 적었다 — 숨기지 않는다.

---

## 다음 Phase 후보 (1개)

**Phase 3-E-45 — `_event_relation` 의 validity/code 짝 최소 수정 (R-3)**

이번 Phase 가 찾은 어긋남은 **한 자리이고 범위가 닫혀 있다**:
`engine/trigger.py:1315` 의 `ActionValidity.INVALID` 가
`ValidationCode.RULE_NOT_IMPLEMENTED` 와 짝을 이룬다. 3-E-40 이 세운
`CODE_VALIDITY` 는 그 코드를 `UNKNOWN` 으로 분류하고, `_gate(...)` 17자리 중
그 한 자리만 policy 를 거스른다.

고를 길이 둘이고 **어느 쪽인지는 측정이 결정해야 한다**:

* **(a)** `INVALID` → `UNKNOWN` — policy 를 따른다. 단 "선언이 이 사건에
  반응하지 않는다" 는 **확실한 데이터 비교 결과**이므로 `UNKNOWN` 이 거짓이
  될 수 있다.
* **(b)** 코드를 바꾼다 — 이 사실에 맞는 `INVALID` 계열 코드가 **이미 있는지**
  48개 안에서 찾는다. 없으면 **새로 만들지 않는다** (새 `ValidationCode` 금지).

(b) 를 먼저 재는 것이 순서다. 선택지가 없다고 판명되면 그 자체가 결론이다.
`_event_relation` 은 런타임 0회이므로 behavior·`state_hash`·RNG·AI ranking 에
영향이 없고, 변경 범위가 한 줄로 닫힌다 — 3-E-38 · 3-E-40 과 같은 모양의
최소 수정 Phase 다.

**R-2′ · R-4 는 후보로 올리지 않는다.** 둘 다 "dormant 를 연결하는가" 라는
훨씬 큰 결정에 달려 있고, 그 결정을 지금 내릴 근거가 없다.

---

## Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 결과 commit | `f32922e` — `Phase 3-E-44: measure dormant-live gate equivalence` |
| 보고서 commit | 이 섹션을 담은 커밋 (아래) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| Push | `40a7766..f32922e` → `origin/claude/pensive-goodall-te1egy` (성공) |
| production diff | **0 줄** |
| 변경 파일 | `tests/test_dormant_live_gate_equivalence.py` (신규) · `docs/phase3e44-dormant-live-gate-equivalence.md` (신규) |

**다음 Phase 는 임의로 진행하지 않는다.**
