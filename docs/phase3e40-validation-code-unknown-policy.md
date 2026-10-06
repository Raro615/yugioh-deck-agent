# Phase 3-E-40 — `ValidationCode` UNKNOWN policy 정식화

> 목표는 `_UNKNOWN_CODES` 를 5개에서 7개로 늘리는 것이 **아니었다.**
> "어느 코드가 모름인가" 를 **사람이 읽는 임시 집합이 아니라 저장소가 명시적으로
> 이해할 수 있는 policy** 로 만드는 것이었다. 7 은 결론이 아니라 **측정 결과**다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-E-40 — ValidationCode UNKNOWN policy formalization |
| 성격 | **최소 production 변경** (§21 이 허용한 범위 안) |
| Base | Phase 3-E-39 (`cc17d32`) |
| 작업 시작 시 실제 HEAD | `4299d67` — "Phase 3-E-39 보고서: commit SHA · push 결과 기록" |
| HEAD 가 3-E-39 를 포함하는가 | ○ `git log` 에 `cc17d32` 가 있다 |
| `docs/phase3e39-...-audit.md` | ○ 존재 (46,231 bytes) |
| `tests/test_simulation_status_unknown_codes_audit.py` | ○ 존재 (33 tests) |
| working tree | clean (reset · checkout 하지 않았다) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 결과 commit | `<<SHA1>>` — `Phase 3-E-40: formalize ValidationCode unknown policy` |
| push | <<PUSH>> |

---

## 2. BLOCKER

**없음.**

새 enum 0 · 새 ValidationCode 멤버 0 · 이름 변경 0 · 삭제 0 ·
`SimulationStatus` 변경 0 · `DuelStep` 변경 0 · `WithheldAction` 변경 0 ·
Search/Evaluation 변경 0. 그리고 **행동이 한 칸도 바뀌지 않았다** (§15).

---

## 3. Phase 3-E-39 요약 (이 Phase 가 받은 것)

| 3-E-39 가 측정한 것 | 이 Phase 가 한 것 |
| --- | --- |
| `_UNKNOWN_CODES` 는 48개 중 **5개를 손으로 고른 사본** | 사본을 지우고 엔진에서 **파생**하게 했다 |
| `ValidationResult.unknown(...)` 으로 생산되는 코드는 **7개** | policy 가 그 7개를 모름으로 선언한다 |
| 빠진 둘: `HIDDEN_CARD` · `PRIORITY_STATE_STALE` | 셋 이상의 근거를 다시 재고 포함시켰다 (§7 · §8) |
| "왜 그 5개인가" 를 적은 문서 · 테스트 · 커밋 **없음** | 근거를 policy 옆에 적고 **테스트가 검사**하게 했다 |
| enum 의 묶음은 **주석**이라 기계가 못 읽는다 | 묶음 라벨과 policy 가 어긋나면 깨지는 테스트를 넣었다 |
| UNKNOWN ↔ REFUSED 구분은 AI 결과를 바꾸지 않는다 | 다시 측정했고 **그대로다** (§14) |
| 분기 자체가 dormant (32판 · 11,609 걸음 중 0건) | 다시 측정했고 **그대로다** (§15) |
| 판정 **C. UNKNOWN_CODES_POLICY_UNJUSTIFIED** | 그 판정이 넘긴 일을 이 Phase 가 했다 |

---

## 4. ValidationCode 전체 목록

### 필수 표 1 — 48개 전수

`현재 UNKNOWN 가능` = production 이 `ValidationResult` 에 `UNKNOWN` 으로 선언하는가.
`기존` = 3-E-40 **전**의 `_UNKNOWN_CODES` 포함 여부.
`최종 policy` = `CODE_VALIDITY` 의 값.

| ValidationCode | 현재 UNKNOWN 가능 | 기존 `_UNKNOWN_CODES` | 최종 policy | 근거 |
| --- | :--: | :--: | :--: | --- |
| `OK` | ✕ | ✕ | `VALID` | `valid()` ×3 |
| `ACTOR_INVALID` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 `(INVALID)` |
| `SOURCE_REQUIRED` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `SOURCE_FORBIDDEN` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `EFFECT_REF_REQUIRED` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `EFFECT_REF_FORBIDDEN` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `EFFECT_REF_CARD_MISMATCH` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `EFFECT_REF_OUT_OF_RANGE` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `PHASE_REQUIRED` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `PHASE_FORBIDDEN` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `TARGET_COUNT_MISMATCH` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `TARGET_KIND_INVALID` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `DUEL_ALREADY_OVER` | ✕ | ✕ | `INVALID` | `invalid()` ×2 + 묶음 |
| `NOT_TURN_PLAYER` | ✕ | ✕ | `INVALID` | 묶음 + `Requirement` |
| `SOURCE_NOT_CONTROLLED` | ✕ | ✕ | `INVALID` | 묶음 + `Requirement` |
| `SOURCE_WRONG_ZONE` | ✕ | ✕ | `INVALID` | 묶음 + `ActionValidity.INVALID` 짝 |
| `SOURCE_WRONG_CARD_TYPE` | ✕ | ✕ | `INVALID` | 묶음 + `Requirement` |
| `ZONE_FULL` | ✕ | ✕ | `INVALID` | 묶음 + `Requirement` |
| `WRONG_PHASE` | ✕ | ✕ | `INVALID` | `invalid()` ×2 + 묶음 |
| `SET_THIS_TURN` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| `TARGET_NOT_OPPONENT` | ✕ | ✕ | `INVALID` | 묶음 + `Requirement` |
| `TARGET_SELF_CONTROLLED` | ✕ | ✕ | `INVALID` | 묶음 + `Requirement` |
| `TARGET_WRONG_ZONE` | ✕ | ✕ | `INVALID` | 묶음 + `Requirement` |
| `PHASE_UNCHANGED` | ✕ | ✕ | `INVALID` | `invalid()` + 묶음 |
| **`HIDDEN_CARD`** | **○** | **✕** | **`UNKNOWN`** | `unknown()` ×2 + 묶음 `(UNKNOWN)` + 설명 (§7) |
| `INFORMATION_UNAVAILABLE` | ○ | ○ | `UNKNOWN` | `unknown()` ×3 + 묶음 |
| `CARD_DEFINITION_UNAVAILABLE` | ○ | ○ | `UNKNOWN` | `unknown()` + 묶음 |
| `EFFECT_LIST_UNRELIABLE` | ○ | ○ | `UNKNOWN` | `unknown()` + 묶음 |
| `RULE_NOT_IMPLEMENTED` | ○ | ○ | `UNKNOWN` | `unknown()` ×4 + 묶음 + 설명 |
| `NO_CANDIDATES` | ✕ | ✕ | `INVALID` | `invalid()` |
| `TOO_FEW_SELECTED` | ✕ | ✕ | `INVALID` | `invalid()` |
| `TOO_MANY_SELECTED` | ✕ | ✕ | `INVALID` | `invalid()` |
| `DUPLICATE_SELECTION` | ✕ | ✕ | `INVALID` | `invalid()` |
| `CANDIDATE_NOT_FOUND` | ✕ | ✕ | `INVALID` | 두 생성 자리가 **둘 다** 확정 거부와 짝 (§7) |
| `CANDIDATE_NOT_ELIGIBLE` | ✕ | ✕ | `INVALID` | `invalid()` + 3-E-38 의 M1 |
| `INSUFFICIENT_LIFE` | ✕ | ✕ | `INVALID` | `invalid()` |
| `COST_NOT_IMPLEMENTED` | ○ | ○ | `UNKNOWN` | `unknown()` ×2 + `UNSUPPORTED_COST` 짝 |
| `INSUFFICIENT_DECK` | ✕ | ✕ | `INVALID` | `INSUFFICIENT_CARDS` 짝 + 설명 |
| `INVALID_AMOUNT` | ✕ | ✕ | `INVALID` | `INVALID_CONTEXT`/`INVALID_OPERATION` 짝 |
| `NO_RESPONSE_WINDOW` | ✕ | ✕ | `INVALID` | `invalid()` ×3 |
| `NOT_PRIORITY_HOLDER` | ✕ | ✕ | `INVALID` | `ValidationResult(INVALID, …)` |
| `EXECUTION_FORBIDDEN` | ✕ | ✕ | `INVALID` | `ActionValidity.INVALID` 짝 + 설명 + 3-E-38 의 M2 |
| `CHAIN_EMPTY` | ✕ | ✕ | `INVALID` | `invalid()` |
| **`CHAIN_DEFINITION_UNAVAILABLE`** | ✕ | ✕ | **`None`** | **두 생성 자리가 서로 다른 말을 한다 (§7)** |
| `CANNOT_NORMAL_SUMMON` | ✕ | ✕ | `INVALID` | `Requirement` 전용 (§7) |
| `NORMAL_SUMMON_ALREADY_USED` | ✕ | ✕ | `INVALID` | `Requirement` 전용 (§7) |
| `SPELL_SPEED_TOO_LOW` | ✕ | ✕ | `INVALID` | `invalid()` |
| **`PRIORITY_STATE_STALE`** | **○** | **✕** | **`UNKNOWN`** | `ValidationResult(UNKNOWN, …)` + 설명이 직접 적는다 (§8) |

**분할**: `VALID` 1 + `INVALID` 39 + `UNKNOWN` 7 + `None` 1 = **48**, 남는 것 없음
(`test_24`).

---

## 5. UNKNOWN source 전체 목록

AST 로 `ValidationResult.unknown(...)` 과 `ValidationResult(ActionValidity.UNKNOWN, …)`
를 production 전 파일에서 다시 측정했다 (3-E-39 의 숫자를 믿지 않고).

| Code | 생성 자리 | 수 |
| --- | --- | --- |
| `RULE_NOT_IMPLEMENTED` | `action_validation.py:300,352` · `turn_progression.py:472,550` | 4 |
| `INFORMATION_UNAVAILABLE` | `action_validation.py:358` · `cost/validation.py:151,227` | 3 |
| `HIDDEN_CARD` | `action_validation.py:277` · `cost/validation.py:233` | 2 |
| `COST_NOT_IMPLEMENTED` | `cost/validation.py:58,67` | 2 |
| `CARD_DEFINITION_UNAVAILABLE` | `action_validation.py:410` | 1 |
| `EFFECT_LIST_UNRELIABLE` | `action_validation.py:416` | 1 |
| `PRIORITY_STATE_STALE` | `priority.py:513` | 1 |

**일곱이고, policy 가 선언하는 일곱과 정확히 같다** (`test_10`).

그리고 **같은 코드가 두 판정으로 생산되는 자리가 하나도 없다** (`test_11`) —
그래서 policy 를 "코드 → 판정" 의 **함수**로 적을 수 있었다. 이것이 §10 이 묻던
"코드의 semantic" 과 "이번 결과의 validity" 의 관계에 대한 측정 답이다: 지금
저장소에서는 **둘이 어긋나지 않는다.**

---

## 6. 기존 `_UNKNOWN_CODES` 분석

```python
# 3-E-40 전 — agent/simulation.py
_UNKNOWN_CODES: frozenset[ValidationCode] = frozenset({
    ValidationCode.RULE_NOT_IMPLEMENTED,
    ValidationCode.COST_NOT_IMPLEMENTED,
    ValidationCode.INFORMATION_UNAVAILABLE,
    ValidationCode.CARD_DEFINITION_UNAVAILABLE,
    ValidationCode.EFFECT_LIST_UNRELIABLE,
})
```

| 질문 (§5) | 답 |
| --- | --- |
| 기존 5개가 모두 여전히 모름인가 | **그렇다.** 다섯 모두 `unknown()` 으로만 생산된다. **하나도 빼지 않았다** (`test_07`) |
| 왜 `HIDDEN_CARD` 가 빠져 있었는가 | **기록이 없다.** 집합의 주석은 "엔진이 **아직 규칙이 없다** 고 말하는 코드들" 이라고 적었다 — 그 **좁은 문구**를 기준으로 읽으면 가려진 카드는 들어가지 않는다. 다만 그러면 같은 집합에 있는 `INFORMATION_UNAVAILABLE`("정보가 없다")이 설명되지 않는다. **문구와 집합이 서로를 설명하지 못한다** → provenance unavailable (§16). 추측하지 않는다 |
| 왜 `PRIORITY_STATE_STALE` 이 빠져 있었는가 | 같다. 기록이 없다 |
| 그 둘이 정말 모름인가 | **그렇다.** §7 · §8 에 근거를 셋씩 적었다 |
| 잘못 들어간 것이 있는가 | **없다.** 다섯 중 `invalid()`/`valid()` 로 생산되는 것은 하나도 없다 (`test_12`) |

---

## 7. `HIDDEN_CARD` 분석

**판정: `ActionValidity.UNKNOWN`.** 근거 셋이 모두 같은 말을 한다 (`test_08`).

1. **production** — `ValidationResult.unknown(...)` 으로만 생산된다 (2곳).
   `invalid()` 로 생산되는 자리가 **없다.**
2. **enum 의 묶음** — `# --- 모른다 (UNKNOWN) ---` 묶음의 **첫 멤버**다.
3. **설명** — "가리킨 카드가 관측에 없다. **없다는 뜻이 아니다** — 가려진 것일
   수 있다."

그리고 이 저장소의 가장 오래된 규칙과도 맞는다: **가려진 정보를 거부로 접지
않는다.** 3-E-39 는 이 코드가 집합에 없어서 "만약 `DuelStep` 까지 내려오면
`REFUSED`(= 규칙에 따라 거절했다)로 읽힐" 상태였다고 기록했다. 이제 두 축이 같은
말을 한다 (`test_31`).

### 함께 측정한 것 — `CANDIDATE_NOT_FOUND` 는 가려진 정보가 **아니다**

3-E-39 는 이 코드를 context-dependent 로 남겼다. 설명이 "고른 카드가 **관측에**
없다" 라고 적기 때문이다. 이번에 **코드를 읽어 보니 다르다.**

```python
card = state.find_instance(instance)     # ← 관측이 아니라 판 전체다
if card is None:
    return CostPaymentResult(PaymentStatus.INVALID_SELECTION,
                             ValidationCode.CANDIDATE_NOT_FOUND, ...)
```

두 생성 자리(`payment.py:517` · `effect/executor.py:1178`) 모두 `GameState`
전체를 보고, 둘 다 **확정 거부**와 짝짓는다(`PaymentStatus.INVALID_SELECTION` ·
`ResolutionStatus.INVALID_TARGET`). 즉 "가려졌다" 가 아니라 **"이 듀얼에 없다"**
이고, 그것은 확실한 사실이다. → **`INVALID`** 로 분류했다.

**설명과 코드가 어긋난 것은 기록해 둔다** — 설명은 "관측" 이라고 적지만 코드는 판
전체를 본다. 이 Phase 는 설명 문구를 고치지 않았다 (분류의 문제가 아니다).

---

## 8. `PRIORITY_STATE_STALE` 분석

**판정: `ActionValidity.UNKNOWN`.** 설명이 **직접** 그렇게 적는다 (`test_09`).

> 우선권 상태가 지금 판과 맞지 않는다 (턴 플레이어 · 페이즈가 다르다).
>
> ``INVALID`` 가 아니라 ``UNKNOWN`` 에 쓴다 — 어느 쪽이 낡았는지 모르는
> 상태에서 "안 된다" 고 단정하지 않는다.

그리고 production 이 그대로 한다 — `priority.py:513` 의
`ValidationResult(ActionValidity.UNKNOWN, …)` 한 자리뿐이다.

**enum 의 묶음은 `발동 타이밍 · 스펠 스피드 (Phase 2-S)` 이고 validity 라벨이
없다.** 그래서 묶음만 읽는 사람은 이 코드가 모름인지 알 수 없었다 — 설명을 읽어야
했고, 설명은 기계가 읽지 않는다. 이것이 사본이 어긋난 **두 번째 경로**다
(`HIDDEN_CARD` 는 묶음에 있었는데도 빠졌고, 이 코드는 묶음이 말해 주지도 않았다).

---

## 9. UNKNOWN policy 후보 비교 (§3 · §8)

| 후보 | 내용 | 평가 |
| --- | --- | --- |
| **A** | `ValidationCode` 자체가 source of truth | **채택 (절반).** 의미를 **만드는 모듈**이 선언해야 한다. 소비자가 선언하면 소비자가 늘 때마다 사본이 늘고, 그것이 3-E-39 가 찾은 문제였다 |
| **B** | enum docstring 을 machine-readable 하게 | **기각.** 설명을 파싱하는 구조는 설명을 고치면 깨진다. "문구를 다듬는다고 부르는 쪽이 깨지면 안 된다" 는 이 enum 자신의 원칙과 정면으로 어긋난다 |
| **C** | 별도 policy mapping 모듈 | **기각.** 사본을 셋째 자리로 **옮기는** 것이고, §8 이 금지한 "하드코딩 집합을 이름만 바꿔 옮기기" 다 |
| **D** | 문서만 보강 | **기각.** §8 이 명시적으로 허용하지 않는다 — production 이 여전히 다른 수동 집합을 읽는다 |
| **E** | 이미 있는 구조를 재사용 | **채택 (절반).** "모름인가" 는 **새 어휘가 필요 없는 질문**이다. `ActionValidity` 가 이미 세 값으로 그것을 말한다 |

**선택: A + E.**
`ValidationCode` 바로 아래에서(**A**) 기존 `ActionValidity` 어휘로(**E**) 선언한다.

---

## 10. 최종 policy 선택

```python
# engine/validation.py — enum 바로 다음
CODE_VALIDITY: "dict[ValidationCode, ActionValidity | None]" = {
    ValidationCode.OK: ActionValidity.VALID,
    ...                                   # 48개 **전부**
    ValidationCode.CHAIN_DEFINITION_UNAVAILABLE: None,
    ...
}

_UNCLASSIFIED = set(ValidationCode) - set(CODE_VALIDITY)
if _UNCLASSIFIED:
    raise RuntimeError(...)               # ← 빠뜨리면 **import 가 실패한다**


def codes_declaring(validity) -> frozenset[ValidationCode]: ...
def unknown_codes() -> frozenset[ValidationCode]: ...
```

### 왜 이것이 "집합을 이름만 바꿔 옮긴 것" 이 아닌가 (§8 의 금지 조건)

| | 전 (`_UNKNOWN_CODES`) | 후 (`CODE_VALIDITY`) |
| --- | --- | --- |
| 범위 | 48개 중 **5개만** 적는다 | **48개 전부**를 적는다 (총함수) |
| 빠뜨림 | **조용히** 모름이 아닌 것이 된다 | **import 가 실패한다** |
| 값의 어휘 | 암묵적 bool ("집합에 있다/없다") | 기존 `ActionValidity` **세 값** + 명시적 `None` |
| 사는 곳 | 소비자(`agent/`) | 의미를 만드는 곳(`engine/`) |
| "정할 수 없다" | 표현할 수 없다 | `None` 으로 **적는다** |
| production 과의 일치 | 검사하는 것이 없었다 | 테스트가 AST 로 양방향 검사 (`test_10` · `test_12`) |
| 묶음 주석과의 일치 | 검사하는 것이 없었다 | 라벨이 붙은 28개를 검사 (`test_13`) |

### `None` — 정하지 못한 것을 임의로 접지 않는다 (§7)

`CHAIN_DEFINITION_UNAVAILABLE` **하나**가 `None` 이다. 두 생성 자리가 **서로 다른
말을 한다.**

| 자리 | 짝지은 status | 읽히는 뜻 |
| --- | --- | --- |
| `trigger_chain.py:409` | `ChainInsertion.UNKNOWN` | "정의가 없어 무엇이 필요한지 **확인할 수 없습니다**" → 모름 |
| `chain.py:592` | `ChainResolutionStatus.INVALID_CHAIN_LINK` | "정의가 등록되어 있지 않아 해결할 수 없습니다" → 거부 쪽 status |

어느 한쪽으로 접으면 다른 한쪽이 거짓이 된다. 그래서 **비워 두었고**, 비워 둔 것은
모름 집합에 들어가지 않는다 — **3-E-40 전의 동작과 같다** (`test_23`). 이 저장소가
"unknown 을 임의로 true/false 로 처리하는 구조를 만들지 않는다" 고 정한 규칙을
**코드 분류에도** 적용한 것이다.

`CANNOT_NORMAL_SUMMON` · `NORMAL_SUMMON_ALREADY_USED` 는 `None` 이 **아니다** —
`Requirement` 로만 실리고, `_check_requirements` 는 조건이 `FALSE` 일 때만 그
코드를 `invalid()` 로 쓰며 `UNKNOWN` 일 때는 코드를 **모름 쪽으로 갈아 끼운다**.
즉 그 코드가 결과에 실릴 때는 **항상** 확정 거부다.

---

## 11. 기존 `_UNKNOWN_CODES` 처리

§11 의 네 선택지 중 **B — 기존 set 을 policy 에서 파생** 을 골랐다.

```python
# agent/simulation.py — 전: 리터럴 9줄 / 후: 1줄
_UNKNOWN_CODES: frozenset[ValidationCode] = unknown_codes()
```

- **A(승격)를 고르지 않은 까닭**: 그 집합은 **소비자 쪽**에 있다. 승격하면 엔진이
  에이전트를 읽어야 한다.
- **C(완전 제거)를 고르지 않은 까닭**: 이름을 지우면 이 사실을 재는 기존 테스트
  여섯 파일이 **import 단계에서** 깨진다. 그것은 의미 변화 없이 생기는 순수한
  손실이고, 파생 한 줄로 같은 목적(단일 source)을 달성할 수 있다.
- **D(유지)를 고르지 않은 까닭**: 그것이 3-E-39 가 판정 C 를 낸 이유다.

**이중 source 가 아니라는 것을 테스트가 센다**: `agent/simulation.py` 에
`ValidationCode.<멤버>` 리터럴이 **0개**이고 (`test_21`), production 전체에서 모름
코드를 셋 이상 나열하는 자리가 **`engine/validation.py` 의 policy 하나뿐**이다
(`test_22`).

---

## 12. Production call path

```
ActionValidator / CostValidator / TurnProgressor / PriorityState
        │  ValidationResult.unknown(CODE, ...)        ← 생산 (7개 코드)
        ▼
ValidationResult(validity=UNKNOWN, code=CODE, ...)
        │  validity 가 DuelStep 에서 사라진다 (3-E-39 §11)
        ▼
DuelStep(accepted=False, code=CODE, ...)
        │
        ▼
Simulator.simulate
        │  step.code in _UNKNOWN_CODES
        │           └── = unknown_codes()                   ← ★ 이 Phase
        │                   └── = codes_declaring(UNKNOWN)
        │                           └── = CODE_VALIDITY      ← 단일 source
        ▼
SimulationStatus.UNKNOWN | SimulationStatus.REFUSED
        │  code 가 SearchCandidate 에서 사라진다 (3-E-39 §11)
        ▼
SearchCandidate(status, value=None, reason)
        │  ordering_key() 는 status 를 보지 않는다
        ▼
PlayerAction
```

**바뀐 칸은 ★ 하나다.** 위아래의 모든 칸이 그대로다.

---

## 13. Consumer 영향

§12 가 요구한 consumer 전수 확인.

| Consumer | policy 를 읽는가 | 영향 |
| --- | --- | --- |
| `ValidationResult` | 아니다 | 없음 (diff 0 — 클래스 본문은 손대지 않았다) |
| `agent/simulation.py` | **그렇다** (파생) | 집합이 5 → 7. 분기 코드는 **한 글자도** 바뀌지 않았다 |
| `agent/search.py` | 아니다 | 없음 (diff 0) |
| `SearchCandidate` | 아니다 | 없음 — `code` 칸이 애초에 없다 |
| `SimulationResult` | 아니다 | 없음 |
| `Duel.apply` | 아니다 | 없음 (diff 0) |
| `ActionValidator` | 아니다 | 없음 (diff 0) |
| `engine/trigger.py` | 아니다 | 없음 (diff 0, dormant 그대로 — `test_28`) |
| `engine/effect/executor.py` | 아니다 | 없음 (diff 0) |
| `engine/effect/resolution.py` | 아니다 | 없음 (diff 0) |

`gives_a_future` · `ordering_key` · `SimulationStatus` · Search ranking ·
policy selection 전부 **코드 변경 0**이고, 측정값도 동일하다 (§15).

---

## 14. AI / Search 영향

**NO EFFECT.** 3-E-39 가 측정한 사실이 그대로 유지된다.

| 질문 | 답 | 근거 |
| --- | --- | --- |
| 순위가 바뀌는가 | 아니다 | 다섯 상태와 `None` 이 전부 같은 키 — BEFORE/AFTER 동일 (`test_26`) |
| 점수가 바뀌는가 | 아니다 | 둘 다 `value is None` |
| 고르는 수가 바뀌는가 | 아니다 | `end_phase P0` — BEFORE/AFTER 동일 (`test_30`) |
| 후보 수 · 시뮬레이션 수 | 아니다 | 1 · 1 — 동일 |
| 32판의 승자 · 턴 수 · 행동 수 · 최종 해시 | 아니다 | **32개 해시 전부 동일** (§15) |

그리고 **분기 자체가 여전히 깨어나지 않는다**: 32판 · `DuelStep` 11,609 걸음이
**전부** `(accepted=True, OK)` 이고 `Simulator.simulate` 5,316 호출이 **전부**
`SUPPORTED` 다 — BEFORE 와 AFTER 가 같다. 즉 모름 집합이 5 → 7 로 늘어난 것이
**실제로 관측되는 결과를 만들 자리가 오늘은 없다** (`test_32`).

§13 이 요구한 중단 조건("POLICY CHANGE HAS BEHAVIORAL IMPACT")에 **해당하지
않는다.** consumer 를 고쳐서 맞춘 것이 아니라, 애초에 바뀌지 않았다.

---

## 15. Before / After

같은 seed(11) · 같은 덱 · 같은 32판 코퍼스로 전후를 JSON 으로 떠서 `diff` 했다.

### 필수 표 3

| 항목 | Before | After | 변화 |
| --- | --- | --- | --- |
| `ValidationCode` members | 48 | 48 | — |
| UNKNOWN policy members | (policy 없음) | **7** | **★ 생겼다** |
| `_UNKNOWN_CODES` | 5 (손으로 적은 리터럴) | **7 (파생)** | **★ 바뀐 것** |
| `HIDDEN_CARD` 분류 | `NOT_UNKNOWN` | **`UNKNOWN`** | **★** |
| `PRIORITY_STATE_STALE` 분류 | `NOT_UNKNOWN` | **`UNKNOWN`** | **★** |
| 나머지 46개 코드 분류 | — | — | 전부 동일 |
| `SimulationStatus` | 5 | 5 | — |
| `ActionValidity` | 3 | 3 | — |
| `gives_a_future` (5개 상태) | 전부 동일 | 전부 동일 | — |
| `ordering_key` (5개 상태) | `(1,0,0,…)` | `(1,0,0,…)` | — |
| Search 고른 수 | `end_phase P0` | `end_phase P0` | — |
| Search 후보/시뮬 수 | 1 / 1 | 1 / 1 | — |
| Search 후보 상태 | `['supported']` | `['supported']` | — |
| Evaluation (후보 점수) | 동일 | 동일 | — |
| RNG `draws` (탐색 전/후) | 2 / 2 | 2 / 2 | — |
| `state_hash` (탐색 전/후) | `d1d66338…be40` | 같은 해시 | — |
| hidden info (상대 손) | `concealed=True`, `cards=()` | 같음 | — |
| 코퍼스 32판 결과 | `completed` ×32 | `completed` ×32 | — |
| 코퍼스 `DuelStep` 쌍 | `{True|ok: 11609}` | 같음 | — |
| 코퍼스 `Simulation` 쌍 | `{supported|ok: 5316}` | 같음 | — |
| 코퍼스 32개 최종 해시 | — | **전부 동일** | — |

**`diff` 전문이 다섯 덩이이고 전부 policy 자신이다.**

```
20c20   "HIDDEN_CARD": "NOT_UNKNOWN"          → "UNKNOWN"
34c34   "PRIORITY_STATE_STALE": "NOT_UNKNOWN" → "UNKNOWN"
311a312 + "HIDDEN_CARD"            (unknown_codes 목록)
312a314 + "PRIORITY_STATE_STALE"   (unknown_codes 목록)
315c317 "unknown_codes_count": 5  → 7
```

§22 가 요구한 "달라지는 것은 UNKNOWN policy 의 source of truth 뿐" 을 **그대로**
만족한다.

---

## 16. Git provenance

| 대상 | 최초 commit | 날짜 | 비고 |
| --- | --- | --- | --- |
| `ValidationCode` | `d8d20d6` "Add the Cost and Choice system (Phase 2-C)" | 2026-09-17 | enum 과 `ActionValidity` 가 같은 commit |
| `ActionValidity` | `d8d20d6` | 2026-09-17 | 세 값이 처음부터 있었다 |
| `HIDDEN_CARD` | `d8d20d6` | 2026-09-17 | **enum 과 같은 날** |
| `PRIORITY_STATE_STALE` | `bc445d8` "Express whose turn it is to decide (Phase 2-F-1)" | 2026-09-18 | |
| `SimulationStatus` | `40ea6c8` "Phase 3-C" | 2026-10-01 | |
| `_UNKNOWN_CODES` | `40ea6c8` | 2026-10-01 | **태어난 뒤 이 Phase 까지 한 번도 바뀌지 않았다** |

**결정적 사실**: `_UNKNOWN_CODES` 가 태어난 2026-10-01 에 `HIDDEN_CARD`(2주 전) 와
`PRIORITY_STATE_STALE`(2주 전)은 **이미 enum 에 있었다.** 즉 집합이 **낡아서**
어긋난 것이 아니라 **쓰는 순간부터** 달랐다.

**왜 달랐는지 설명하는 기록은 없다** — 커밋 메시지 · 문서 · 테스트 어디에도
"다섯을 고른 기준" 이 없다. → **provenance unavailable.** 추측하지 않는다.
(다만 집합 위 주석의 문구가 "아직 **규칙이 없다**" 로 좁았던 것이 한 가지 단서다 —
§6 에 그대로 적었다.)

---

## 17. 테스트

### 새 파일

`tests/test_validation_code_unknown_policy.py` — **33개** (요구 최소 25개).
§17 의 1~27 항목을 전부 덮는다.

| §17 항목 | 테스트 |
| --- | --- |
| 1 member 수 | `test_01` |
| 2 새 code 없음 | `test_02` |
| 3 policy source 존재 | `test_03` |
| 4 전 member 를 다루는가 | `test_04` |
| (§0 새 enum 없음) | `test_05` |
| 5 UNKNOWN member 추출 | `test_06` |
| 6 기존 5개 확인 | `test_07` |
| 7 `HIDDEN_CARD` | `test_08` |
| 8 `PRIORITY_STATE_STALE` | `test_09` |
| 9 7개와 policy 비교 | **`test_10`** (drift 감지) |
| (§10 코드↔결과) | `test_11` |
| (역방향) | `test_12` |
| (§8 주석 검사) | **`test_13`** |
| 10 policy → `UNKNOWN` 연결 | `test_14` |
| 11 ≠ FALSE | `test_15` |
| 12 ≠ INVALID | `test_16` |
| 13 ≠ LOSS | `test_17` |
| 14 `RULE_NOT_IMPLEMENTED` | `test_18` |
| 15 `CANDIDATE_NOT_ELIGIBLE` | `test_19` |
| 16 `EXECUTION_FORBIDDEN` | `test_20` |
| (§11 파생 확인) | **`test_21`** · **`test_22`** |
| (§7 `None`) | `test_23` |
| (분할) | `test_24` |
| 20 `SimulationStatus` 불변 | `test_25` |
| 18 `ordering_key` | `test_26` |
| 25 · 26 `DuelStep`/`WithheldAction` | `test_27` |
| (§29-17 트리거) | `test_28` |
| 22 · 23 `state_hash`/RNG | `test_29` |
| 19 Search ranking | `test_30` |
| 24 hidden info | `test_31` |
| (도달 가능성) | `test_32` |
| (전체 모양) | `test_33` |
| 27 full regression | §19 |

### 기존 테스트 수정 — 삭제 0 · skip 추가 0 · assertion 약화 0

**5개 파일 · 11개 테스트 + 3곳의 모듈 상수 + 측정 helper 1곳.** 전부 **당시의
사실을 정확히 세고 있던 것들**이고, 그 사실이 이 Phase 로 바뀌었다.

| 파일 | 대상 | 왜 바뀌었나 |
| --- | --- | --- |
| `test_simulation_status_unknown_codes_audit.py` | 상수 `UNKNOWN_CODE_NAMES` 5→7 · `UNKNOWN_GAP` 2개→빈 집합 | **3-E-39 가 재던 틈이 닫혔다.** 그 Phase 는 AUDIT-ONLY 라 고치지 않고 숫자만 고정했고, 이 Phase 가 그것을 닫았다 |
| 〃 | `test_06`(개명) · `test_07`(개명) | "다섯" → "일곱". 틀린 가정이 아니었다 — **고치면 깨지도록** 일부러 고정한 설계가 의도대로 작동했다 |
| 〃 | `test_10`(개명) | "틈이 있다" → **"틈이 없다"**. 역할이 기록에서 **감시**로 바뀌었다 |
| 〃 | `test_11`(개명) | "묶음과 집합이 다르다" → "묶음이 집합의 **부분집합**이다" |
| 〃 | `test_31`(개명) | "두 축이 어긋난다" → "두 축이 같은 말을 한다" |
| 〃 | `test_32`(개명) | "에이전트에 코드 5줄이 있다(= diff 0)" → "에이전트가 policy 를 **적지 않는다**" |
| `test_validation_code_rejection_semantics_audit.py` | `rejection_productions()` helper | **dict 키도 멤버십으로 센다.** 집합의 원소를 "거부 생성" 으로 세지 않던 것과 같은 이유다 — 키는 **선언**이다. 이 Phase 가 처음으로 dict 모양을 만들었고 세는 쪽을 그때 맞췄다 (54 유지) |
| 〃 | `test_04` | 간접으로 읽히는 집합이 5→7 이므로 상한 8→10 · 하한 40→38. **직접 비교되는 것은 여전히 셋뿐**이고 요지는 그대로다 |
| 〃 | `test_10` | `SOURCE_FORBIDDEN` 의 "사용처 한 곳" 에서 `engine/validation.py` 를 뺀다 — enum 의 집이고, policy 표가 48개 멤버를 **선언으로** 한 번씩 등장시킨다. 선언을 사용처로 세면 그 사실을 말할 수 없다 |
| 〃 | `test_23`(개명) | 집합 5→7. "거부 코드는 하나도 없다" 는 요지는 **그대로 성립** |
| 〃 | `test_24` | `agent/` 의 `RULE_NOT_IMPLEMENTED` 등장 1→**0**. 읽는 자리가 사라진 것이 아니라 **엔진이 정하게** 되었다 |
| `test_rule_not_implemented_code_audit.py` | `test_21` | 같은 1→0. 그 테스트의 요지("에이전트가 거의 읽지 않는다")가 **더 강하게** 성립한다 |
| `test_validation_code_minimal_fix.py` | `test_14`(개명) | 집합 5→7. 그 테스트의 요지("M1·M2 를 고치면서 집합을 건드리지 않았다")는 **그대로 맞다** — 두 거부 코드는 여전히 집합 밖이다 |

### 고의 위반 (deliberate violation)

policy 의 **drift 감지 장치가 정말 작동하는지** 확인하려고, 분류를 틀리게 ·
빠뜨리게 · 사본을 되살리게 하는 **10가지**를 하나씩 주입하고 매번 관련 테스트 6개
파일을 돌린 뒤 원복했다.

**10/10 전부 잡혔다.** 조용히 지나간 주입은 **없다.**

| # | 주입한 잘못 | 파일 | 깨진 테스트 수 | 맨 처음 깨진 것 |
| --- | --- | --- | --- | --- |
| V01 | policy 에서 HIDDEN_CARD 분류를 빼기 (총함수가 깨진다 — import 실패를 기대) | `engine/validation.py` | ERROR 6 | `**import 실패** (6건 수집 오류)` |
| V02 | HIDDEN_CARD 를 확정 거부로 잘못 분류 (production 과 어긋난다) | `engine/validation.py` | **13** | `test_06_the_unknown_policy_has_exactly_seven_members` |
| V03 | PRIORITY_STATE_STALE 를 확정 거부로 잘못 분류 | `engine/validation.py` | **11** | `test_06_the_unknown_policy_has_exactly_seven_members` |
| V04 | 확정 거부(CANDIDATE_NOT_ELIGIBLE)를 모름으로 (M1 을 되돌린다) | `engine/validation.py` | **20** | `test_06_the_unknown_policy_has_exactly_seven_members` |
| V05 | 출처 금지(EXECUTION_FORBIDDEN)를 모름으로 (M2 를 되돌린다) | `engine/validation.py` | **15** | `test_06_the_unknown_policy_has_exactly_seven_members` |
| V06 | 정하지 못한 코드를 임의로 모름에 밀어 넣기 | `engine/validation.py` | **12** | `test_05_the_policy_speaks_only_in_the_existing_three_value_vocabulary` |
| V07 | import 때의 총함수 검사를 지우기 | `engine/validation.py` | **1** | `test_04_the_policy_is_total_and_breaks_at_import_if_a_member_is_missed` |
| V08 | agent 에 사본을 되살리기 (이중 source 복귀) | `agent/simulation.py` | **17** | `test_03_the_policy_lives_next_to_the_enum_not_in_the_agent_layer` |
| V09 | 모름 집합을 비우기 (모든 미구현이 '거절' 로 읽힌다) | `engine/validation.py` | **19** | `test_06_the_unknown_policy_has_exactly_seven_members` |
| V10 | OK 를 모름으로 (성공이 모름이 된다) | `engine/validation.py` | **12** | `test_05_the_policy_speaks_only_in_the_existing_three_value_vocabulary` |

읽을 점:

- **V01 이 가장 중요하다.** 분류 한 줄을 지우자 테스트가 "실패" 한 것이 아니라
  **import 자체가 실패해 6개 파일이 수집조차 되지 않았다.** 분류를 빠뜨린 채로
  코드를 돌릴 길이 **없다** — §16-8 이 요구한 "향후 추가 시 누락 발견" 이
  경고가 아니라 **차단**으로 구현되었다는 뜻이다.
- **V02 · V03** (추가한 둘을 거부로 되돌리기) 은 13개 · 11개를 깨뜨린다. 두 코드의
  분류가 한 자리의 값이 아니라 **여러 테스트가 함께 지키는 사실**이 되었다.
- **V04 · V05** (3-E-38 의 M1 · M2 를 policy 쪽에서 되돌리기) 는 20개 · 15개로
  가장 많이 깨뜨린다. 앞선 Phase 가 세운 구분이 이 Phase 의 policy 를 통해 **다시
  한 번** 보호된다.
- **V06 · V10** 은 `test_05` 에서 먼저 깨진다 — "세 값과 `None` 이 **모두** 실제로
  쓰인다" 를 고정해 둔 자리가, `None` 을 없애거나 `VALID` 를 없애는 변경을 잡는다.
- **V08** (agent 에 사본 되살리기) 이 잡히는 것이 §11 의 요구를 지킨다 — "둘 다
  두는" 방향이 테스트로 막혀 있다.
- **V09** (모름 집합 비우기) 는 가장 조용히 지나갈 법한 변경인데 19개가 깨졌다.

주입 전후로 두 production 파일의 `md5` 를 비교해 **원복을 확인**했다.

---

## 18. Safety invariants

§29 의 17개를 전부 확인했다.

| # | 불변식 | 결과 | 테스트 |
| --- | --- | --- | --- |
| 1 | UNKNOWN ≠ FALSE | ○ | `test_15` |
| 2 | UNKNOWN ≠ INVALID | ○ 두 집합의 교집합이 공집합 | `test_16` |
| 3 | UNKNOWN ≠ LOSS | ○ | `test_17` |
| 4 | REFUSED ≠ LOSS | ○ | `test_17` |
| 5 | `RULE_NOT_IMPLEMENTED` ≠ 자동 LOSS | ○ `value is None`, 0 이 아니다 | `test_17` `test_18` |
| 6 | `CANDIDATE_NOT_ELIGIBLE` semantics 보존 | ○ M1 그대로 · policy 는 `INVALID` | `test_19` |
| 7 | `EXECUTION_FORBIDDEN` semantics 보존 | ○ M2 그대로 · policy 는 `INVALID` | `test_20` |
| 8 | `ValidationCode` 기존 member 보존 | ○ 48개 · 이름 · 값 전부 | `test_01` `test_02` |
| 9 | `SimulationStatus` 기존 member 보존 | ○ 5개 | `test_25` |
| 10 | Search behavior 보존 | ○ 고른 수 · 후보 · 키 동일 | `test_26` `test_30` |
| 11 | Evaluation 보존 | ○ 후보 점수 동일 | `test_30` · §15 |
| 12 | RNG 불변 | ○ `draws` 2 → 2 | `test_29` |
| 13 | `state_hash` 불변 | ○ `d1d66338…be40` | `test_29` |
| 14 | hidden information 불변 | ○ 상대 손 `concealed` · `cards=()` | `test_31` |
| 15 | `DuelStep` 불변 | ○ 필드 5개 | `test_27` |
| 16 | `WithheldAction` 불변 | ○ 필드 3개 | `test_27` |
| 17 | Trigger pipeline 불변 | ○ production 생성 0곳 · `duel.py` 에 "trigger" 없음 | `test_28` |

---

## 19. Production diff

```
engine/validation.py | 151 +++++++++++++++++++++++++++++++++++++++++++++++++++
agent/simulation.py  |  24 ++++----
2 files changed, 164 insertions(+), 11 deletions(-)
```

§21 의 허용 범위와 정확히 일치한다.

| 파일 | 변경 | 허용? |
| --- | --- | --- |
| `engine/validation.py` | `CODE_VALIDITY` + import 검사 + `codes_declaring` · `unknown_codes` helper | ○ "ValidationCode semantic metadata/policy" |
| `agent/simulation.py` | 리터럴 9줄 → 파생 1줄 (+ 까닭 주석) | ○ "기존 `_UNKNOWN_CODES` 제거/대체" |

**그 밖은 전부 diff 0**: `engine/validation.py` 의 `ValidationCode` ·
`ActionValidity` · `ValidationResult` **클래스 본문**, `engine/duel.py`,
`engine/trigger.py`, `engine/trigger_chain.py`, `engine/chain.py`,
`engine/activation.py`, `engine/effect/*`, `agent/search.py`, `agent/evaluation.py`,
`agent/policy.py`, `agent/arena.py`, `core/`, `analysis/`, `sources/`, `app/`.

### Full regression

```
$ python -m pytest -q -p no:randomly
3940 passed, 4 skipped in 429.39s (0:07:09)
```

| 항목 | Phase 3-E-39 종료 시 | 이번 Phase 종료 시 |
| --- | --- | --- |
| passed | 3907 | **3940** (+33, 새 파일) |
| failed | 0 | **0** |
| skipped | 4 | **4** (증가 없음) |
| 기존 테스트 삭제 | — | **0** |
| 기존 assertion 약화 | — | **0** |
| enum member 변경 | — | **0** |

---

## 20. 82 최종 질문

### 필수 표 2 — 코드별 최종 판단 (대표 7 + 경계 3)

| Code | UNKNOWN semantic | Production path | Context dependent | 최종 판단 |
| --- | --- | --- | --- | --- |
| `RULE_NOT_IMPLEMENTED` | ○ | `unknown()` ×4 | ✕ | `UNKNOWN` |
| `INFORMATION_UNAVAILABLE` | ○ | `unknown()` ×3 | ✕ | `UNKNOWN` |
| `HIDDEN_CARD` | ○ | `unknown()` ×2 | ✕ | `UNKNOWN` **(추가)** |
| `CARD_DEFINITION_UNAVAILABLE` | ○ | `unknown()` ×1 | ✕ | `UNKNOWN` |
| `EFFECT_LIST_UNRELIABLE` | ○ | `unknown()` ×1 | ✕ | `UNKNOWN` |
| `COST_NOT_IMPLEMENTED` | ○ | `unknown()` ×2 | ✕ | `UNKNOWN` |
| `PRIORITY_STATE_STALE` | ○ | `ValidationResult(UNKNOWN,…)` ×1 | ✕ | `UNKNOWN` **(추가)** |
| `CANDIDATE_NOT_FOUND` | ✕ | `_fail`/`CostPaymentResult` ×2 | **✕ (해소)** | `INVALID` — 판 전체를 보고 둘 다 확정 거부와 짝 |
| `CHAIN_DEFINITION_UNAVAILABLE` | ? | `ChainResolution`/`TriggerChainEntry` ×2 | **○** | **`None`** — 두 자리가 다른 말을 한다 |
| `EXECUTION_FORBIDDEN` | ✕ | `_fail`/`_gate` ×5 | ✕ | `INVALID` (ADR-004) |

**Q1.** `ValidationCode` UNKNOWN semantic 을 명시적으로 정의할 수 있는가 →
**그렇다.** 48개 중 **47개**를 기존 `ActionValidity` 어휘로 정했고, 1개는 "정할 수
없다" 를 `None` 으로 **명시**했다.

**Q2.** 기존 5개 중 잘못된 것이 있는가 → **없다.** 다섯 모두 `unknown()` 으로만
생산된다. 하나도 빼지 않았다.

**Q3.** `HIDDEN_CARD` 는 UNKNOWN 인가 → **그렇다.** 근거 셋이 일치한다 (§7).

**Q4.** `PRIORITY_STATE_STALE` 은 UNKNOWN 인가 → **그렇다.** 설명이 직접 적는다 (§8).

**Q5.** UNKNOWN source 7개와 policy 가 일치하는가 → **정확히 일치한다**
(`test_10`). 그리고 그 일치를 **테스트가 계속 감시한다.**

**Q6.** 5개가 아니라 7개가 되어야 하는가 → **그렇다 — 측정 결과로서.** 자동으로
5→7 을 한 것이 아니라 코드마다 근거를 셋씩 보고 정했고, 그 과정에서
`CANDIDATE_NOT_FOUND` 는 **모름이 아님**으로, `CHAIN_DEFINITION_UNAVAILABLE` 은
**정할 수 없음**으로 갈라졌다.

**Q7.** context-dependent code 가 있는가 → **하나 있다.**
`CHAIN_DEFINITION_UNAVAILABLE`. 3-E-39 가 둘로 봤던 것 중 하나는 이번에 해소됐다.

**Q8.** 기존 `_UNKNOWN_CODES` 를 제거해도 되는가 → **이름은 남기고 내용을
파생으로 바꿨다** (§11-B). 이름을 지우면 기존 테스트 여섯 파일이 import 단계에서
깨지고, 그 손실에 비해 얻는 것이 없다. **이중 source 는 사라졌다.**

**Q9.** 새 enum 이 필요한가 → **아니다.** `ActionValidity` 세 값과 `None` 으로
충분했다.

**Q10.** 기존 consumer behavior 가 변하는가 → **아니다** (§13). 소비자 코드의
diff 는 리터럴 → 파생 한 줄뿐이고 분기는 글자 그대로다.

**Q11.** AI/Search 결과가 변하는가 → **아니다** (§14 · §15). 32판 전부의 승자 ·
턴 수 · 행동 수 · 최종 해시가 동일하다.

**Q12.** `DuelStep`/`WithheldAction` 변경이 필요한가 → **아니다.** policy 정식화에
필요하지 않았다 (§15 가 기대한 NO 가 맞았다). 다만 **그 둘이 validity/code 를
들고 있지 않아 생기는 문제는 여전히 남아 있다** — §22 의 후보로 남긴다.

**Q13.** 최소 production diff 로 끝낼 수 있는가 → **그렇다.** 두 파일,
`+164/−11`. 그중 **의미 있는 것은 48줄의 분류표와 파생 한 줄**이고 나머지는 까닭을
적은 한국어 주석이다.

**Q14.** 향후 `ValidationCode` 추가 시 policy 누락을 탐지할 수 있는가 →
**그렇다, 두 겹으로.** ① 분류를 빠뜨리면 **import 가 실패한다** ②
`unknown()` 으로 생산하기 시작하고 policy 에 적지 않으면 `test_10` 이 깨진다.
3-E-39 가 **손으로** 찾아낸 어긋남을 앞으로는 테스트가 찾는다.

**Q15.** 이 변경이 Engine V1 freeze 원칙을 깨는가 → **아니다.** enum 멤버 0 ·
자료형 0 · 실행 경로 0 · 관측 경계 0 · 난수 0 · 해시 0. 더한 것은 **이미 있던
사실을 기계가 읽을 수 있게 적은 선언**뿐이다.

---

## 21. Final Decision

**A. UNKNOWN_POLICY_FORMALIZED**

- **policy source 확정** — `engine/validation.py` 의 `CODE_VALIDITY`, 48개 전수,
  기존 `ActionValidity` 어휘, import-time 총함수 검사.
- **이중 source 제거** — `agent` 의 리터럴 사본이 사라지고 파생 한 줄이 남았다.
  production 에서 모름 코드를 나열하는 자리가 **하나뿐**이다 (`test_22`).
- **새 enum 없음** — 멤버 0 추가 · 0 변경 · 0 삭제.
- **behavior 변화 없음** — BEFORE/AFTER diff 가 policy 자신뿐이고 32판 코퍼스가
  byte 단위로 같다.
- **최소 production diff** — 두 파일, 의미 있는 변경은 분류표와 한 줄.

### 다른 판정을 고르지 않은 까닭

- **B (ALREADY_SUFFICIENT)** — 3-E-39 가 측정으로 반박했다. 집합이 둘 빠져 있었고
  근거가 기록되어 있지 않았다. "보강만으로 충분" 하지 않았다.
- **C (POLICY_NEEDS_CONTEXT)** — context-dependent 가 **하나 있다**
  (`CHAIN_DEFINITION_UNAVAILABLE`). 그러나 그것 때문에 **별도 architecture Phase 가
  필요하지는 않았다** — 현재 구조가 `None` 으로 그 사실을 **표현할 수 있고**, 그
  코드의 동작은 전과 같다. C 를 고르면 "정식화를 못 했다" 는 뜻이 되는데, 47개는
  정했고 1개는 정하지 못했음을 **명시적으로 적었다.** 그 1개를 §22 의 후보로 넘긴다.
- **D (CONSUMER_BEHAVIOR_CHANGE)** — 측정상 consumer 행동이 바뀌지 않았다. 그리고
  consumer 를 고쳐서 맞춘 것이 아니다 — `agent/search.py` diff 는 0 이다.
- **E (ARCHITECTURE_GAP)** — 구조를 열지 않고 끝났다. `DuelStep` ·
  `WithheldAction` · `SimulationStatus` 전부 그대로다.
- **F (BLOCKER)** — 근거가 부족한 자리가 **하나**였고 그것을 `None` 으로 적었다.
  나머지는 전부 production 에서 측정했다.

---

## 22. Next Phase Candidate

**하나만 제안한다.**

> **Phase 3-E-41 — `DuelStep` / `WithheldAction` validation information
> architecture** (§31 의 후보 1번)

까닭 — 이 Phase 가 끝내고 보니 **남은 문제가 하나로 수렴한다.**

1. **`DuelStep` 이 `validity` 를 버린다.** 그래서 `agent` 가 "모름인가" 를
   **코드 집합으로 되짚어야** 한다. 이 Phase 는 그 되짚기를 정확하고 단일하게
   만들었지만, **되짚기 자체를 없앤 것은 아니다.** `DuelStep` 이 validity 를
   들고 있었다면 `step.validity is ActionValidity.UNKNOWN` 한 줄이면 됐다.
2. **`WithheldAction` 이 `code` 를 들고 있지 않다.** 그래서 3-E-38 이 정확하게
   만든 M1·M2 코드가, 실제로 그 코드들이 나오는 **유일한 길**(`withheld`)에서
   기계가 읽을 수 없는 형태로 버려진다 (3-E-39 §13 · §16).
3. **`CHAIN_DEFINITION_UNAVAILABLE` 의 `None` 도 같은 뿌리다.** 두 carrier 가 같은
   코드에 다른 status 를 붙이는 것이 가를 수 없는 까닭이고, carrier 가 validity 를
   함께 나르면 그 자리에서 정해진다.

세 가지가 모두 **"판정을 만든 계층의 정보가 다음 계층으로 가지 않는다"** 는 한
문제다. 그것을 여는 것이 다음 Phase 의 범위다.

**이번 Phase 에서 그것을 구현하지 않았다** (§15 · §31 의 금지). 다음 Phase 의
범위와 금지 사항은 사용자가 정한다.
