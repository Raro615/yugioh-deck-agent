# Phase 3-E-45 — `_event_relation` 최소 판정 수정

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-E-45 — `_event_relation` 최소 판정 수정 (R-3) |
| 성격 | **최소 production 수정** (`engine/trigger.py` 한 메서드) |
| Base Phase | 3-E-44 — Dormant 판정기와 Live Gate 판정 일치성 측정 |
| Base commit | `3d3906d` (보고서) · `f32922e` (결과) |
| Base 최종 판정 | B. STRUCTURAL_RISK_CONFIRMED |

**실제 HEAD 확인 (작업 시작 전)**

```
$ git rev-parse HEAD
3d3906d554c8edd7dd4ba28af12fb0a5ca0c5483
$ git rev-parse --abbrev-ref HEAD
claude/pensive-goodall-te1egy
$ git merge-base --is-ancestor 3d3906d HEAD   → ANCESTOR
$ git status --short                          → (비어 있음)
```

3-E-44 산출물도 그 자리에 있다 — `docs/phase3e44-dormant-live-gate-equivalence.md`
(35,250 B) · `tests/test_dormant_live_gate_equivalence.py` (48,353 B).

**baseline 테스트**: 4,075 passed / 4 skipped (3-E-44 기록, 이번 작업 전 상태).
Engine V1 freeze 를 유지한다.

---

## 2. 기존 `_event_relation` 동작

```python
def _event_relation(self, spec: TriggerSpec, event: TimingEvent) -> GateVerdict:
    """이 사건에 반응하는가. 선언이 적어 둔 것만 본다."""
    if spec.matches(event):
        return _gate(..., ActionValidity.VALID,   ValidationCode.OK, ...)
    return _gate(..., ActionValidity.INVALID, ValidationCode.RULE_NOT_IMPLEMENTED, ...)
```

### 입력과 출력 (§핵심문제 1)

| | 내용 |
| --- | --- |
| 입력 | `spec: TriggerSpec` (선언) · `event: TimingEvent` (사건) |
| 출력 | `GateVerdict(EVENT_RELATION, ValidationResult)` |
| 묻는 것 | "이 **선언**이 그 **사건**에 반응하는가" |
| 판정 근거 | `TriggerSpec.matches(event)` — **데이터 비교**다. 시점 동일성 + `operations` · `from_zones` · `to_zones` 세 필터 |

`matches` 자신의 docstring 이 적는다: "규칙 판단이 아니라 데이터 비교다."

### 호출 구조 (§검증 3 · 5)

```
judge_all(collection, registry)
   └→ specs = registry.watching(event)      ← 여기서 이미 matches 로 걸러진다
        └→ judge(candidate, spec, event)
             └→ _event_relation(spec, event)   ← 첫 관문
```

`judge_all` 경로에서는 `watching` 이 선행 필터이므로 **`_event_relation` 은 항상
`VALID`** 다. 불일치 분기는 **`judge()` 를 직접 부를 때만** 닿는다.

---

## 3. 문제의 정확한 원인

### 3-1. 코드가 틀렸다 — 판정은 맞았다 (§핵심문제 2 · 3 · 4)

| 질문 | 답 |
| --- | --- |
| `INVALID` 가 "입력 자체의 invalid" 인가 "판정 불가" 인가 | **대부분은 확정된 거부다.** `matches` 는 전칭(total) 비교이고, 양쪽 값이 다 있으면 답이 확정된다 |
| `RULE_NOT_IMPLEMENTED` 가 이 자리에서 맞는 코드인가 | **아니다.** 그 코드의 뜻은 "이 엔진이 아직 못 한다 · 코드가 생겨야 풀린다" 인데, `matches` 는 **제 일을 끝까지 했다** |
| 3-E-40 의 policy 와 맞는가 | **아니다.** `CODE_VALIDITY[RULE_NOT_IMPLEMENTED] is ActionValidity.UNKNOWN` |

**저장소가 답을 이미 적어 두고 있었다.** `RULE_NOT_IMPLEMENTED` 의 enum docstring:

> 구분해 쓸 자리들 (Phase 3-E-24 에서 측정, 3-E-26 에서 정리):
> * 정보가 없어서 모른다 → `INFORMATION_UNAVAILABLE` · `HIDDEN_CARD`
> * 출처가 실행을 금지한다 → `EXECUTION_FORBIDDEN`
> * **후보가 조건을 만족하지 않는다 → `CANDIDATE_NOT_ELIGIBLE`**

그리고 `tests/test_validation_code_rejection_semantics_audit.py::test_11` 의
docstring 이 3-E-37 당시 이미 진단해 두었다:

> "이 선언은 그 사건에 반응하지 않는다" 는 **확실하고 올바른 거부**다 — 엔진이
> 못 하는 것이 아니다. 3-E-36 은 이 자리를 "진짜 미구현" 으로 분류했는데
> **틀렸다.**

즉 이 Phase 는 새 판단을 내린 것이 아니라 **이미 측정된 진단을 코드에
반영**했다. 그래서 "48개 중에 INVALID 코드가 있는가" 같은 개수 세기가 아니라
**같은 사실에 저장소가 이미 쓰는 코드**를 썼다.

### 3-2. 실측한 하류 피해 (§핵심문제 5)

`trigger_chain._refusal_code` 는 **첫 `INVALID` 관문의 코드**를 올리고,
`_event_relation` 이 `judge` 의 첫 관문이다. 그래서 그 함수가 **자기 docstring 을
어겼다**:

> 자리가 틀려서 막힌 후보에 `RULE_NOT_IMPLEMENTED` 를 적으면 "엔진이 못 한다" 와
> "규칙이 막았다" 가 다시 섞인다

실측 (수정 전):

```
G2 시점 불일치  → event_relation=(invalid, RULE_NOT_IMPLEMENTED)
                  _refusal_code = RULE_NOT_IMPLEMENTED   ← docstring 위반
```

### 3-3. 그리고 더 중요한 것 — `matches()` 의 `False` 가 **한 가지 사실이 아니었다**

단순 코드 치환으로는 끝나지 않는다는 것이 이 Phase 의 실제 발견이다.
`matches` 가 `False` 를 내는 경로를 전수로 재면 두 종류가 섞여 있다.

| 측정 | 사건 | `event.operation` | `matches` | 실제 뜻 |
| --- | --- | --- | --- | --- |
| F2 | `ZoneMoved(DESTROY)` vs 선언 `{SEND_TO_GRAVE}` | `destroy` | `False` | **다르다** (확정) |
| F3 | `CardDrawn` vs 선언 `CARD_MOVED` | `draw` | `False` | **다르다** (확정) |
| **F7** | **`TimingEvent.unimplemented(...)`** | `None` | `False` | **무슨 일이 있었는지 모른다** |
| **F4** | **`TimingEvent(CARD_MOVED)` (delta 없음)** | `None` | `False` | **필터를 읽을 수 없다** |

`None not in {...}` 는 참이므로, **정보가 없어서** `False` 가 되는 길이 있다.

**F7 은 가상의 입력이 아니다.** `timing_for` 가 옮길 시점 이름이 없는 변화를
`UNIMPLEMENTED` 로 남기고 (STRUCTURAL-74 · Phase 2-AJ), 등재된 실제 카드
**리로드**의 해결에 `ZoneShuffled` 가 들어 있다.
`tests/engine/test_real_card_semantics.py` 가 그 사건이 해결 시퀀스의 **네 번째
자리**에 남는 것을 이미 고정해 두었다:

```python
assert points == [
    TimingPoint.CARD_MOVED, TimingPoint.CARD_MOVED, TimingPoint.CARD_MOVED,
    TimingPoint.UNIMPLEMENTED,  # 셔플
    TimingPoint.CARD_DRAWN, ...
]
```

수정 전에는 이 셔플 사건 하나 때문에 후보가 `INELIGIBLE` 로 접혔다 — **"규칙이
막았다"** 고 말하는 셈이다. 이것은 이 Phase 가 고치려던 바로 그 섞임이고, 저장소
규칙("unknown 을 임의로 true/false 로 처리하는 구조를 만들지 마라") 위반이다.

그래서 **코드만 바꾸면 결함의 절반이 남는다.** 한 분기가 두 종류의 입력을 받고
있었으므로, 그 분기에 맞는 단일 조합이 **존재하지 않는다.**

---

## 4. 적용한 최소 변경

`engine/trigger.py` 의 `_event_relation` **하나**. 실제 코드 줄 변경 **32줄**
(나머지는 까닭을 적은 docstring · 주석).

```python
# ① 사건 자체를 모르면 반응 여부도 모른다
if event.point is TimingPoint.UNIMPLEMENTED:
    return _gate(..., ActionValidity.UNKNOWN, ValidationCode.RULE_NOT_IMPLEMENTED,
                 ..., notes=(event.note,), missing_rule=event.note)

# ② 선언이 건 필터를 사건이 들고 있지 않다 (시점이 같을 때만 묻는다)
unreadable = tuple(
    name for name, declared, value in (
        ("operations", spec.operations, event.operation),
        ("from_zones", spec.from_zones, event.from_zone),
        ("to_zones",   spec.to_zones,   event.to_zone),
    )
    if declared is not None and value is None
)
if event.point is spec.point and unreadable:
    return _gate(..., ActionValidity.UNKNOWN, ValidationCode.INFORMATION_UNAVAILABLE,
                 ..., notes=unreadable)

# ③ 맞는다
if spec.matches(event):
    return _gate(..., ActionValidity.VALID, ValidationCode.OK, ...)

# ④ 값이 다 있고 다르다 — 확정된 거부
return _gate(..., ActionValidity.INVALID, ValidationCode.CANDIDATE_NOT_ELIGIBLE, ...)
```

### 왜 이 조합인가

| 입력 | 판정 | 코드 | 근거 |
| --- | --- | --- | --- |
| 맞는다 | `VALID` | `OK` | 바뀌지 않았다 |
| 값이 다 있고 다르다 | **`INVALID`** | **`CANDIDATE_NOT_ELIGIBLE`** | 판정은 원래 맞았다. 코드는 `RULE_NOT_IMPLEMENTED` 의 enum docstring 이 가리키는 것이고, `_trigger_condition` · `TriggerCollector._judge` · `EffectActivator._check_condition` · `_refusal_code` 기본값이 **같은 사실에 이미 쓰는** 코드다 |
| 사건이 `UNIMPLEMENTED` | **`UNKNOWN`** | `RULE_NOT_IMPLEMENTED` | 코드는 그대로 맞다 — "코드가 생겨야 풀린다" 가 정확히 그 뜻이다. **판정만** 모름으로 바꿨다 |
| 필터를 읽을 수 없다 | **`UNKNOWN`** | **`INFORMATION_UNAVAILABLE`** | "정보가 없어서 모른다" — enum docstring 이 그 자리로 지정한 코드다 |

**`INVALID → UNKNOWN` 을 무조건 적용하지 않았다.** 세 갈래 중 확정 거부는
`INVALID` 로 **남겼고**, 거기서 바꾼 것은 코드뿐이다. 반대로 모름 두 갈래는
코드가 아니라 **판정**을 바꿨다.

**`UNKNOWN` 안에서 까닭을 가르는 방법은 새로 만들지 않았다** —
`_trigger_condition` 이 이미 쓰는 그대로다 ("규칙이 없어서 모른다" vs "정보가
없어서 모른다").

### ②에 시점 검사가 붙은 이유

`event.point is spec.point` 를 빼면 **확정된 거부가 모름으로 약해진다.**
시점이 다른 `LIFE_CHANGED` 사건(`operation` 이 `None`) 을 필터 걸린 선언에
넣으면, 시점만으로 답이 확정되는데도 "필터를 못 읽었다" 가 이긴다. 고의 위반
4 가 실제로 그것을 만들어 확인했다.

---

## 5. 변경하지 않은 범위

절대 금지 목록을 하나씩 확인한다.

| 금지 | 확인 |
| --- | --- |
| `TriggerRegistry` 를 `duel.py` 에 연결 | **안 했다.** `engine/duel.py` 에 `trigger` · `Trigger` 문자열이 **0회** (`test_17`) |
| dormant pipeline 을 production 에 연결 | **안 했다.** 16판 1,359행동에서 dormant 관문 호출 **전부 0** |
| `TriggerSpec` / `TriggerRegistry` 구조 재설계 | **안 했다.** 필드 · `__post_init__` · `watching` 그대로. `matches` 도 그대로 (`test_15`) |
| `activation_zone` 수정 | **안 했다.** 코드 집합 `{RULE_NOT_IMPLEMENTED, HIDDEN_CARD, OK, SOURCE_WRONG_ZONE}` 그대로 (`test_16`) |
| `cost_feasibility` 수정 | **안 했다.** 코드 집합 `{RULE_NOT_IMPLEMENTED, OK}` 그대로, `validate_group` 호출 그대로 (`test_16` · `test_18`) |
| live / dormant gate 통합 | **안 했다.** live 관문 셋 · dormant 관문 다섯 그대로 |
| `CHAIN_DEFINITION_UNAVAILABLE` policy 변경 | **안 했다.** `CODE_VALIDITY[...] is None` 그대로 (`test_14`) |
| `ValidationCode` enum 추가 | **안 했다.** 48개 그대로 (`test_14`) |
| `ValidationCode` 기존 의미 변경 | **안 했다.** `engine/validation.py` diff **0줄** |
| 새 `EventBus` / graph / event architecture | **안 했다.** 새 클래스 · 새 모듈 0개 |
| Chain 구조 변경 | **안 했다.** `engine/chain.py` diff 0줄 |
| AI / Search 변경 | **안 했다.** `agent/` diff 0줄 |
| Engine V1 freeze 해제 | **안 했다.** |
| unrelated refactor | **안 했다.** production diff 가 `engine/trigger.py` 한 파일, 한 메서드다 |

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
 engine/trigger.py | 83 ++++++++++++++++++++++++++++++++++++-
 1 file changed, 81 insertions(+), 2 deletions(-)
```

**3-E-44 의 두 `DIFFERENT_RESULT` 는 기록만 유지한다** (`test_18` 이 그 상태를
고정한다):

* `activation_zone` — live / dormant **DIFFERENT_RESULT**
* `cost_feasibility` — live / dormant **DIFFERENT_RESULT**

둘 다 "dormant 를 연결하는가" 라는 더 큰 결정에 달려 있고, 이 Phase 는
`event_relation` 하나만 다뤘다.

---

## 6. ValidationCode / validity 의미

이 관문이 낼 수 있는 짝이 **넷**이고, 넷 **전부** 3-E-40 의 `CODE_VALIDITY` 와
맞는다 (`test_13`).

| 판정 | 코드 | `CODE_VALIDITY` | 일치 |
| --- | --- | --- | --- |
| `VALID` | `OK` | `VALID` | ✅ |
| `INVALID` | `CANDIDATE_NOT_ELIGIBLE` | `INVALID` | ✅ |
| `UNKNOWN` | `RULE_NOT_IMPLEMENTED` | `UNKNOWN` | ✅ |
| `UNKNOWN` | `INFORMATION_UNAVAILABLE` | `UNKNOWN` | ✅ |

`engine/trigger.py` 전체의 `_gate(...)` 생산을 policy 와 맞춰 본 결과:

| | 3-E-44 (수정 전) | 3-E-45 (수정 후) |
| --- | --- | --- |
| `_gate` 생산 자리 | 17 (리터럴 16 + 조건부 1) | **19** (리터럴 18 + 조건부 1) |
| policy 와 어긋나는 자리 | **1** (`_event_relation`) | **0** |

**세 구분이 살아 있다.**

* `UNKNOWN` — 모름. `passed` 가 거짓이고 (`VALID` 일 때만 참) `fold` 가
  `TriggerStatus.UNKNOWN` 으로 접는다. **거부로도 통과로도 접히지 않는다.**
* `INVALID` — 확정된 거부. `fold` 가 `INELIGIBLE` 로 접는다.
* `FORBIDDEN` — `GateVerdict.forbids` 는 `EXECUTION_FORBIDDEN` 일 때만 참이므로
  이 관문은 **금지를 내지 않는다** (`test_03` 이 확인).

dormant 층이 쓰는 `ValidationCode` 는 7개 → **8개**가 되었다
(`INFORMATION_UNAVAILABLE` 추가). **새 코드를 만든 것이 아니라 이미 있던 코드를
모름 쪽에 쓴 것**이고, 나머지 40개는 여전히 dormant 층과 무관하다.

---

## 7. caller 영향

| caller | 변화 |
| --- | --- |
| `judge_all` → `registry.watching` | **없다.** `watching` 이 `matches` 로 먼저 걸러서 이 경로의 `_event_relation` 은 언제나 `VALID` 다 |
| `judge` (직접 호출) | 불일치 입력의 판정이 바뀐다 (§8) |
| `TriggerEligibility.fold` | 세 갈래가 각자 맞는 상태로 접힌다 — 코드 변경 **0줄** |
| `trigger_chain._refusal_code` | **자기 docstring 과 맞게 되었다.** `RULE_NOT_IMPLEMENTED` → `CANDIDATE_NOT_ELIGIBLE` |
| `trigger_chain._undecided_code` | **이제 이 관문을 볼 수 있다.** 전에는 `INVALID` 라서 `UNKNOWN` 필터에 걸리지 않았다 |
| production duel path | **없다.** 호출 0회 |

### 실측 — 수정 전 / 후

| 시나리오 | `event_relation` (전 → 후) | `status` (전 → 후) | `_refusal_code` | `_undecided_code` |
| --- | --- | --- | --- | --- |
| G1 맞는 선언 | `valid/OK` → 같음 | `eligible` → 같음 | — | — |
| G2 시점 불일치 | `invalid/RULE_NOT_IMPLEMENTED` → **`invalid/CANDIDATE_NOT_ELIGIBLE`** | `ineligible` → 같음 | `RULE_NOT_IMPLEMENTED` → **`CANDIDATE_NOT_ELIGIBLE`** | — |
| G3 의미 필터 불일치 | 같은 변화 | `ineligible` → 같음 | 같은 변화 | — |
| G4 `UNIMPLEMENTED` 사건 | `invalid/RULE_NOT_IMPLEMENTED` → **`unknown/RULE_NOT_IMPLEMENTED`** | **`ineligible` → `unknown`** | — | → **`RULE_NOT_IMPLEMENTED`** |
| G5 `UNIMPLEMENTED` + 필터 선언 | 같은 변화 | **`ineligible` → `unknown`** | — | → **`RULE_NOT_IMPLEMENTED`** |
| G6 필터를 읽을 수 없다 | `invalid/RULE_NOT_IMPLEMENTED` → **`unknown/INFORMATION_UNAVAILABLE`** | **`ineligible` → `unknown`** | — | → `INFORMATION_UNAVAILABLE` |

---

## 8. production 영향

### 관찰 가능한 행동 변화: **없다** (§핵심문제 6 · 7)

| 확인 | 결과 |
| --- | --- |
| production duel path 가 `_event_relation` 을 호출하는가 | **0회** — 16판 1,359행동 측정 |
| dormant 관문 다섯의 호출 합계 | **0** (live 합계 252,375) |
| `agent/` 가 trigger 모듈을 import 하는가 | **0개 모듈** |
| `engine/duel.py` 가 trigger 를 언급하는가 | **0회** |

**그래도 의미 변경은 의도된 것이다.** 바뀐 것은 `TriggerEligibilityJudge.judge`
를 **직접** 부르는 쪽이 받는 답이고, 지금 그 caller 는 테스트뿐이다. 그 변경이
의도된 validation semantics 변경인 근거:

1. 확정된 거부에 모름 코드가 붙어 있었다 → policy 위반 (3-E-44 R-3).
2. 모름이 거부로 접히고 있었다 → 저장소 규칙 위반, 그리고 `timing_for` 가 실제로
   만드는 `UNIMPLEMENTED` 사건에서 터지는 모양이었다.
3. `_refusal_code` 가 자기 docstring 을 어기고 있었다.

### 달라진 scenario (정확히)

`judge()` 를 직접 불렀을 때만이고, 위 표의 G2–G6 여섯 가지다. **G1(맞는 짝) 은
한 칸도 바뀌지 않았다** — 즉 정상 경로는 그대로다.

### 16판 시나리오 재실행 (§검증 6)

수정 전 기록(3-E-44) 과 **전 항목 동일**:

| 항목 | 수정 전 | 수정 후 | 동일 |
| --- | --- | --- | --- |
| matches | 16 | 16 | ✅ |
| total_actions | 1,359 | 1,359 | ✅ |
| outcomes | `{completed: 16}` | 같음 | ✅ |
| `state_hash` 16개 | — | 16개 전부 동일 | ✅ |
| 호출 횟수 표 (dormant 10항목 · live 10항목) | — | 전부 동일 | ✅ |
| dormant 합계 / live 합계 | 0 / 252,375 | 0 / 252,375 | ✅ |

첫 해시 `1a9e9a0a5e5ab78b…` · 마지막 해시 `cbe64a0314502bc9…`.

---

## 9. state_hash / RNG 영향

| 질문 | 결과 |
| --- | --- |
| `state_hash` 가 바뀌는가 | **아니다.** 16판 전부 동일 (§8). 판정 100회 반복 뒤에도 동일 (`test_19`) |
| RNG 를 소비하는가 | **아니다.** `state.rng.getstate()` 가 전후 동일 (`test_19`) |
| hidden information 경계가 바뀌는가 | **아니다.** `GameStateView` 타입 보호 그대로, `HIDDEN_CARD` 를 내는 자리는 `_activation_zone` 이고 손대지 않았다 |

`_event_relation` 은 판을 읽지도 않는다 — `spec` 과 `event` 만 본다. `view` ·
`GameState` 를 건드리는 경로가 애초에 없다.

---

## 10. AI / Search 영향

**없다.** 세 겹으로 확인했다.

1. `agent/` 의 어느 모듈도 다섯 trigger 모듈을 import 하지 않는다 (`test_17`).
   AI 는 `Duel.legal_actions` / `Duel.apply` → **live 세 관문**만 소비한다.
2. 16판의 `state_hash` 16개가 전부 동일하다 — AI 가 **같은 수를 같은 순서로**
   골랐다는 뜻이다. 한 수라도 달랐으면 해시가 갈린다.
3. `agent/` diff **0줄**. `ordering_key` · 평가 함수 · 탐색 예산 모두 그대로다.

---

## 11. 테스트 결과

### 새로 더한 것

`tests/test_event_relation_minimal_fix.py` — **24개** (전부 통과).

| 묶음 | 내용 |
| --- | --- |
| A (`test_01`–`02`) | 맞는 짝은 바뀌지 않았다 |
| B (`test_03`–`04`) | 값이 다 있고 다르다 → 확정 거부, `INELIGIBLE` 로 접힌다 (네 모양) |
| C (`test_05`–`09`) | 맞춰 볼 수 없었다 → 모름 (두 까닭 · 번지지 않음 · 시점이 먼저 확정) |
| D (`test_10`–`11`) | `_refusal_code` · `_undecided_code` 하류 전파 |
| E (`test_12`) | `UNIMPLEMENTED` 사건이 **실제로** 만들어진다 |
| F (`test_13`–`15`) | policy 와 맞는다 · 새 코드 0개 · `matches` 그대로 |
| G (`test_16`–`19`) | 네 관문 그대로 · 연결 0 · 두 `DIFFERENT_RESULT` 그대로 · `state_hash`/RNG 불변 |

### 고친 기존 테스트 — 10함수 + 5스냅숫자 (7파일)

**전부 "잘못된 계약을 강제하던" 테스트이고, 왜 그 가정이 틀렸는지 각
docstring 에 적었다.** 삭제 · skip 추가 · assertion 약화는 없다.

| 파일 / 테스트 | 원래 가정 | 왜 틀렸나 |
| --- | --- | --- |
| `test_validation_code_consistency.py::test_11` | engine/ 에 `INVALID`+`RULE_NOT_IMPLEMENTED` 가 **1곳** 남아 있다 | "의도적으로 남겼다" 는 **3-E-38 의 범위 기록**이었다. 3-E-44 가 측정하고 3-E-45 가 고쳐 **0곳**이 되었다 |
| `test_validation_code_minimal_fix.py::test_10` | `_event_relation` 은 **여전히** 그 짝을 쓴다 | 같은 docstring 이 "맞는지 자체가 구조 질문" 이라고 적어 두었다 — 지켜야 할 계약이 아니라 그 시점의 사실이었다 |
| `test_validation_code_rejection_semantics_audit.py::test_11` | `validity is INVALID` **그리고** `code is RULE_NOT_IMPLEMENTED` | **결함을 계약으로 고정**하고 있었다. 이 감사의 진단("확실한 거부인데 모름 쪽 코드다") 은 맞고, 단정만 뒤집었다 |
| `test_validation_code_rejection_semantics_audit.py::test_12` | `_refusal_code` 가 `RULE_NOT_IMPLEMENTED` 를 올린다 | 같은 이유. 문구 검사만 하던 부분도 **반환값**을 보도록 했다 |
| `test_trigger_pipeline_dormant_audit.py::test_14` | M3 가 그 자리에 그대로 있다 | 같은 이유 |
| `test_trigger_pipeline_dormant_audit.py::test_18` | dormant carrier 코드가 **7개** | `INFORMATION_UNAVAILABLE` 이 더해져 **8개** · 무관한 코드 41 → 40. 새 코드가 아니라 **있던 코드를 모름 쪽에 쓴** 결과 |
| `test_trigger_pipeline_dormant_audit.py::test_01` · `test_25` | `engine/trigger.py` **1,565줄** | **1,644줄.** 분기 둘과 까닭 docstring 을 더했다. 다른 다섯 모듈의 숫자가 **그대로인 것**이 범위를 넓히지 않았다는 증거다 |
| `test_dormant_live_gate_equivalence.py::test_22[E2]` · `test_23[E3,E5]` | `INVALID`+`RULE_NOT_IMPLEMENTED` | 양쪽 시점이 **알려진** 값이므로 다르다는 답이 확정된다. 판정은 그대로, 코드만 바뀐다 |
| `test_dormant_live_gate_equivalence.py::test_30` | 어긋나는 자리가 **정확히 1개** (= R-3) | 3-E-45 가 고쳐 **0개**. 생산 자리 17 → 19 |

| `test_rule_not_implemented_code_audit.py::test_02` | 문자열 등장 **76** · 산문 **9** | **79** · **12**. 늘어난 셋은 전부 `_event_relation` 의 docstring 이다. **코드 자리 수 67 은 바뀌지 않았다** — 불일치 분기에서 하나를 빼고 모름 분기에서 하나를 더했으므로 차감이 정확히 맞는다 |
| `test_unimplemented_rule_semantics_audit.py::test_03` | `engine/`+`agent/` 등장 **76** | **79**. 이 테스트가 지키는 사실("그 코드와 `UnimplementedRule` 은 같은 개념이 아니다") 은 그대로다 |

`test_dormant_live_gate_equivalence.py` 의 머리말 R-3 문단도 "고치지 않는다" →
"3-E-45 가 고쳤다" 로 갱신하고, **두 `DIFFERENT_RESULT` 는 그대로 남아 있다**는
문장을 더했다.

**숫자 스냅숏이 함수 이름에 박혀 있던 자리**도 맞췄다 —
`test_02_the_string_count_is_75_but_the_code_count_is_69` 는 상수가 세 번
움직이는 동안 이름이 거짓이 되어 있었다 (75/69 → 76/67 → 79/67).

### 측정 방법에 대한 정정 (숨기지 않는다)

작업 중 **내 테스트**에서 두 가지 결함을 찾았고 고쳤다.

1. **문자열 창(`source[i:i+700]`) 으로 코드를 찾던 두 테스트**가 분기가 늘자
   엉뚱한 자리를 보았다. `ast` 로 `_event_relation` **함수 본문**을 읽도록
   바꿨다.
2. **`ast.walk` 는 소스 순서를 보장하지 않는다.** `matches` 의 `return` 순서를
   재던 테스트가 그래서 틀렸다 — `lineno` 로 정렬했다.

### 고의 위반 검증 — 9건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | 수정 되돌리기 (`CANDIDATE_NOT_ELIGIBLE` → `RULE_NOT_IMPLEMENTED`) | `test_03`×4 · `test_09` · `test_10` · `test_13` |
| 2 | `UNIMPLEMENTED` 모름 가드 제거 | `test_05` · `test_06` · `test_11` · `test_13` |
| 3 | 읽을 수 없는 필터 가드 제거 | `test_07`×3 · `test_13` |
| 4 | 시점 검사 없이 모름 가드 (확정 거부가 약해진다) | `test_09` (**처음엔 못 잡았다** → 고쳤다) |
| 5 | 확정 거부를 `UNKNOWN` 으로 (단순 정책 맞추기) | `test_03`×4 · `test_04` · `test_09` · `test_13` |
| 6 | 두 모름 까닭을 한 코드로 뭉갠다 | `test_07`×2 · `test_11` · `test_13` |
| 7 | 못 읽은 필터 이름(`notes`) 을 버린다 | `test_07`×3 |
| 8 | `passed` 가 `UNKNOWN` 도 통과로 센다 | `test_05` · `test_11` |
| 9 | `matches` 에 판정 어휘를 끌어들인다 | `test_15` |

**4번은 처음 놓쳤다.** `test_09` 가 `CARD_DRAWN` 사건을 쓰고 있었는데
`CardDrawn` 은 `CardMovement` 라서 `operation` 이 `draw` 로 **읽힌다** — 즉
`unreadable` 이 애초에 비어 있어 가드를 지워도 결과가 같았다. `LIFE_CHANGED`
사건(`LifeChanged` 는 `CardMovement` 가 아니다 → `operation is None`) 으로
바꾸자 잡혔다. 그 까닭을 테스트 docstring 에도 적어 두었다.

복원은 매번 md5 로 확인했다.

### 전체 회귀

```
$ python3 -m pytest tests/test_event_relation_minimal_fix.py -p no:randomly -q
24 passed in 1.85s

$ python3 -m pytest -p no:randomly -q
4099 passed, 4 skipped in 548.44s (0:09:08)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-E-44 직후 (baseline) | 4,075 | 4 |
| Phase 3-E-45 (이번) | **4,099** | 4 |
| 차이 | **+24** | 0 |

**+24 가 이번에 더한 감사 시험 수와 정확히 같다.** 기존 테스트의 통과 수가 한
건도 줄지 않았고 skip 도 늘지 않았다 — 고친 10함수 + 5스냅숫자는 전부 **잘못된
계약을 강제하던 자리**이고, 삭제 · skip 추가 · assertion 약화는 없다.

---

## 12. 최종 판정

### **FIXED_MINIMAL**

근거:

* 3-E-44 가 R-3 으로 측정한 **한 자리**를 고쳤고, `engine/trigger.py` 의
  `_gate(...)` 생산이 3-E-40 policy 와 **어긋나는 자리 0개**가 되었다.
* production diff 가 **한 파일 · 한 메서드**이고 실제 코드 줄 변경 **32줄**이다.
  새 enum · 새 어휘 · 새 계층 · 새 구조 0개.
* `state_hash` 16개 · 1,359행동 · 호출 횟수 표가 **전 항목 동일**하다. RNG ·
  hidden information 경계 · AI/Search ranking 모두 불변.
* `INVALID → UNKNOWN` 을 무조건 적용하지 **않았다.** 확정 거부는 `INVALID` 로
  남기고 코드만 바꿨고, 모름 두 갈래는 판정을 바꿨다 — 실제 입력을 전수로 재서
  갈랐다.
* 하류(`_refusal_code`) 가 **자기 docstring 과 맞게** 되었다.

`NO_CHANGE_JUSTIFIED` 가 아닌 까닭: 어긋남이 실재했고(policy · 자기 docstring
둘 다), `UNIMPLEMENTED` 사건은 `timing_for` 가 실제로 만든다.

`STRUCTURAL_RISK_REMAINS` 가 아닌 까닭: `event_relation` 에 관한 한 남은 어긋남이
없다. **단, 이 판정은 `event_relation` 에 대한 것이다** — 3-E-44 의
`activation_zone` · `cost_feasibility` `DIFFERENT_RESULT` 두 건은 **그대로 남아
있고**, 이 Phase 는 그것을 다루지 않았다 (§5 · `test_18`).

### 남아 있는 것 (기록 유지)

| | 내용 | 출처 |
| --- | --- | --- |
| R-1 | `CHAIN_DEFINITION_UNAVAILABLE` 의 live/dormant carrier 분기 → `CODE_VALIDITY` 한 칸이 `None` | 3-E-43 · 3-E-44 |
| R-2′ | `activation_zone` **DIFFERENT_RESULT** (Z2 · Z4 · Z6) | 3-E-44 |
| R-4 | `cost_feasibility` **DIFFERENT_RESULT** (K2 · K3 · K4), ADR-008 충돌 | 3-E-44 |
| 신규 | `TimingEvent(CARD_MOVED)` 를 `delta` 없이 만들 수 있다 — **형식이 깨진** 사건이다. `_event_relation` 은 이제 그것을 모름으로 받지만, `TimingEvent.__post_init__` 가 막는 것이 더 맞는 자리일 수 있다. 이번 Phase 의 범위 밖이라 **고치지 않고 기록한다** |

**다음 Phase 는 임의로 진행하지 않는다.**
