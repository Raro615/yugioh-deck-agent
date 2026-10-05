# Phase 3-E-39 — `SimulationStatus` / `_UNKNOWN_CODES` semantic audit

> **AUDIT-ONLY.** production 을 한 줄도 고치지 않았다 (§19 에서 `git diff` 로 확인).
> 이 Phase 의 목적은 `UNKNOWN` 과 `REFUSED` 를 억지로 분리하는 것이 아니라
> **정확히 알아내는 것**이다. 현재 구조가 안전하다면 "안전하다" 고 적는 것도 성공이다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-E-39 — SimulationStatus / _UNKNOWN_CODES semantic audit |
| 성격 | **AUDIT-ONLY** (production diff = 0) |
| Base | Phase 3-E-38 (`913b05a`) |
| 작업 시작 시 실제 HEAD | `29a7f5f` — "Phase 3-E-38 보고서: commit SHA · push 결과 기록" |
| HEAD 가 3-E-38 을 포함하는가 | ○ `git log` 에 `913b05a` 가 있다 |
| `docs/phase3e38-validation-code-minimal-fix.md` | ○ 존재 (39,003 bytes) |
| `tests/test_validation_code_minimal_fix.py` | ○ 존재 (24 tests) |
| working tree | clean (reset · checkout 하지 않았다) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 결과 commit | `<<SHA1>>` — `Phase 3-E-39: audit simulation status and unknown codes` |
| push | <<PUSH>> |

**3-E-38 의 회귀 수치를 같은 HEAD 에서 다시 확인했다**: `3874 passed / 4 skipped`
(376.59s). 보고서의 숫자가 맞다.

---

## 2. BLOCKER

**없음.** 다만 이 Phase 는 **프롬프트의 전제 하나와 3-E-38 보고서의 서술 하나를
바로잡는다.** 결론을 바꾸지는 않지만, 틀린 이름 위에 다음 Phase 를 세우면 안 된다.

### 바로잡는 것 — `is_usable()` 은 **존재하지 않는다**

§10 은 "`search.py:311` 의 `is_usable()`" 을 읽으라고 했고, 3-E-38 보고서도
`agent/simulation.py:85` 를 `is_usable` 이라고 적었다. **그 이름은 repository
어디에도 없다** (`engine/` · `agent/` · `core/` · `analysis/` · `sources/` 전 파일
문자열 검색 0건). 실제로 있는 것은 둘이다.

| 실제 이름 | 자리 | production 사용처 |
| --- | --- | --- |
| `SimulationStatus.gives_a_future` | `agent/simulation.py:83` (property) | **2곳** — `SimulationResult.__post_init__` 의 불변식 검사 |
| `result.status is not SimulationStatus.SUPPORTED` | `agent/search.py:311` | 1곳 — 후보를 점수 없는 쪽으로 보내는 분기 |

3-E-38 보고서는 "`is_usable` 은 production 호출 0곳" 이라고 적었다. 없는 이름의
호출이 0 인 것은 당연하고, **진짜 이름 `gives_a_future` 는 production 사용처가
2곳이다** (불변식 검사). 결론("두 자리 모두 `SUPPORTED` 만 보므로 `UNKNOWN` ↔
`REFUSED` 를 가르지 않는다")은 그대로다. `test_26` 이 이 사실 자체를 고정한다.

### 바로잡는 것 — `SimulationResult` 에 없는 칸들

§13 은 `score` · `value` · `ordering_key` · `notes` · `state_hash` 를 확인하라고
했다. **`SimulationResult` 에는 그 다섯이 모두 없다.** 실제 필드는 여섯이다.

```
action · status · viewer · reason · code · future
```

`value` 와 `ordering_key` 는 `SearchCandidate` 의 것이고, `state_hash` 는
`SearchDecision` 의 것이다. 계층이 섞여 있지 않다 (`test_16`).

---

## 3. SimulationStatus 전체 목록

**다섯이고, 미래를 주는 것은 하나뿐이다.**

| Status | 생성 위치 | 입력 Code | 의미 | gives_a_future | ordering | AI 영향 |
| --- | --- | --- | --- | --- | --- | --- |
| `SUPPORTED` | `simulation.py:274` | `step.code` (=`OK`) | 엔진이 적용했다. 미래를 볼 수 있다 | **True** | 점수 있음 → 키 `(0, …)` | 유일하게 평가된다 |
| `NOT_A_CANDIDATE` | `simulation.py:254` | **없음** (`code=None`) | 지금 허가된 후보가 아니다 | False | 키 `(1,0,0,canonical)` | 없음 |
| `UNKNOWN` | `simulation.py:283` | `step.code ∈ _UNKNOWN_CODES` | 규칙이 아직 없다 — **모른다는 것이지 나쁘다는 것이 아니다** | False | 키 `(1,0,0,canonical)` | 없음 |
| `REFUSED` | `simulation.py:285` | `step.code ∉ _UNKNOWN_CODES` | 엔진이 규칙에 따라 거절했다 | False | 키 `(1,0,0,canonical)` | 없음 |
| `ERROR` | `simulation.py:265` | **없음** (`code=None`) | 실행 중 예외가 났다. 숨기지 않는다 | False | 키 `(1,0,0,canonical)` | 없음 |

`terminal` · `win/loss` 칸은 **없다.** 승패는 `DuelResult` 의 일이고
`SimulationStatus` 는 그것을 만들지 않는다 (`test_29`).

---

## 4. UNKNOWN 생성 경로

**production 전체에서 `SimulationStatus.UNKNOWN` 을 쓰는 자리는 한 곳이다.**
AST 로 전 파일을 훑어 확인했다 (`test_04`).

```python
# agent/simulation.py:282-286 — 거절된 걸음에서만 갈린다
status = (
    SimulationStatus.UNKNOWN
    if step.code in _UNKNOWN_CODES
    else SimulationStatus.REFUSED
)
```

입력은 **`DuelStep.code` 이고, `step.accepted` 가 거짓일 때뿐이다.** 그 앞의 세
관문이 다른 경우를 먼저 걷어낸다 (`test_05` 가 순서를 고정한다).

```
simulate(action)
  ├ action ∉ legal.allowed        → NOT_A_CANDIDATE   (code 없음)
  ├ apply 가 예외                 → ERROR             (code 없음)
  ├ step.accepted                 → SUPPORTED         (code = OK)
  └ 그 밖                         → ★ 분류기 ★       UNKNOWN | REFUSED
```

`DuelStep` 을 거절로 만드는 production 자리는 **열 곳**이다 (`engine/duel.py`).

| 자리 | code 의 출처 | 종류 |
| --- | --- | --- |
| `apply:677` | `DUEL_ALREADY_OVER` (리터럴) | 확정 거부 |
| `apply:683` | `RULE_NOT_IMPLEMENTED` (리터럴) | **"지금 허가된 행위가 아니다"** — 이름과 뜻이 어긋난 자리 |
| `_resolve_chain:751` | `last.code` (체인 해결 걸음) | 동적 |
| `_apply_end_phase:785` | `progressed.verdict.code` | 동적 (`ValidationResult`) |
| `_apply_board:809` | `executed.code` (`ActionExecutor`) | 동적 |
| `_apply_activation:871` | `RULE_NOT_IMPLEMENTED` (리터럴) | 정의 미등록 — 진짜 미구현 |
| `_apply_activation:882` | `TARGET_COUNT_MISMATCH` (리터럴) | 확정 거부 |
| `_apply_activation:897` | `gate.code` (세 관문) | 동적 |
| `_apply_activation:912` | `activated.code` (`EffectActivator`) | 동적 |
| `_apply_activation:928` | `RULE_NOT_IMPLEMENTED` (리터럴) | 배치 실패 |

`apply:683` 은 주목할 자리다 — "후보가 아니다" 에 "모른다" 코드를 붙인다.
`Simulator.simulate` 는 **그것을 알고** 후보 여부를 자기가 먼저 보며, 소스 주석이
그 까닭을 그대로 적어 두었다("거기서는 '허가된 후보가 아니다' 가 '규칙이 없다' 와
같은 코드로 나와서 둘을 가를 수 없다"). 즉 **에이전트 계층이 엔진의 코드 오용을
우회하고 있다**는 사실이 코드에 기록되어 있다.

---

## 5. REFUSED 생성 경로

**같은 삼항의 `else` 가지 하나뿐이다** (`test_04`: 두 자리의 줄 번호 차가 3 이내).
`REFUSED` 는 독립적인 생성 경로를 갖지 않는다 — **`_UNKNOWN_CODES` 의 여집합**으로
정의된다. 그래서 `REFUSED` 의 뜻은 `_UNKNOWN_CODES` 가 무엇을 담고 있느냐에
**전적으로** 달려 있다. 이것이 이 Phase 가 집합을 파고든 이유다.

---

## 6. `_UNKNOWN_CODES` 전체 목록

```python
# agent/simulation.py:89-97
_UNKNOWN_CODES: frozenset[ValidationCode] = frozenset({
    ValidationCode.RULE_NOT_IMPLEMENTED,
    ValidationCode.COST_NOT_IMPLEMENTED,
    ValidationCode.INFORMATION_UNAVAILABLE,
    ValidationCode.CARD_DEFINITION_UNAVAILABLE,
    ValidationCode.EFFECT_LIST_UNRELIABLE,
})
```

### 필수 표 1 — UNKNOWN_CODES

| Code | `_UNKNOWN_CODES` | 생성 경로 (production) | 실제 의미 | 근거 | Production reachable |
| --- | --- | --- | --- | --- | --- |
| `RULE_NOT_IMPLEMENTED` | ○ | `ValidationResult.unknown` ×4 외 49곳 | 이 엔진이 아직 못 한다 | enum 의 `모른다 (UNKNOWN)` 묶음 + docstring | `DuelStep` 리터럴 3곳 (§4) |
| `COST_NOT_IMPLEMENTED` | ○ | `cost/validation.py:58,67` (`unknown`) | 비용 판정 규칙이 없다 | `UNKNOWN` validity 로만 생산 | 비용 있는 효과 0개 → **오늘 0** |
| `INFORMATION_UNAVAILABLE` | ○ | `action_validation.py:358` 외 (`unknown`) | 판정할 정보가 없다 | enum 의 `모른다` 묶음 | 동적 `gate.code` |
| `CARD_DEFINITION_UNAVAILABLE` | ○ | `action_validation.py:410` (`unknown`) | 카드 정의를 읽을 수 없다 | enum 의 `모른다` 묶음 | 동적 `gate.code` |
| `EFFECT_LIST_UNRELIABLE` | ○ | `action_validation.py:416` (`unknown`) | `effect_count` 가 0 이다 | enum 의 `모른다` 묶음 | 동적 `gate.code` |
| **`HIDDEN_CARD`** | **✕** | `action_validation.py:277` · `cost/validation.py:233` (`unknown`) | 가리킨 카드가 관측에 없다 — **없다는 뜻이 아니다** | enum 의 `모른다` 묶음 **첫 멤버** | `withheld` 로 감 → **오늘 0** |
| **`PRIORITY_STATE_STALE`** | **✕** | `priority.py:513` (`ValidationResult(UNKNOWN, …)`) | 우선권 상태가 판과 맞지 않다 | docstring: "``INVALID`` 가 아니라 ``UNKNOWN`` 에 쓴다" | `withheld` 로 감 → **오늘 0** |

**측정 방법**: `ValidationResult.unknown(...)` · `ValidationResult.invalid(...)` ·
`ValidationResult(<validity>, …)` 를 production 전 파일에서 AST 로 훑어, 각 코드가
**어떤 `ActionValidity` 와 함께** 생산되는지 셌다. 결과:

- `ActionValidity.UNKNOWN` 과 함께 생산되는 코드 = **7개**
- `_UNKNOWN_CODES` = **5개**
- **빠진 것 = `HIDDEN_CARD` · `PRIORITY_STATE_STALE`**
- **잘못 들어간 것 = 없음** (5개 모두 `UNKNOWN` validity 로만 생산된다)

`Requirement` 가 들고 다니는 코드들(`ZONE_FULL` · `NOT_TURN_PLAYER` 등)은 추가
후보가 **아니다**. `_check_requirements` 는 조건이 `FALSE` 일 때만 그 코드를
`invalid()` 로 쓰고, `UNKNOWN` 일 때는 코드를 **`RULE_NOT_IMPLEMENTED` 또는
`INFORMATION_UNAVAILABLE` 로 갈아 끼운다** — 둘 다 집합에 있다. 그래서 그 방향으로
새는 구멍은 없다.

### enum 자신의 묶음과도 다르다

| | 멤버 |
| --- | --- |
| enum 의 `# --- 모른다 (UNKNOWN) ---` 묶음 (5) | `HIDDEN_CARD` · `INFORMATION_UNAVAILABLE` · `CARD_DEFINITION_UNAVAILABLE` · `EFFECT_LIST_UNRELIABLE` · `RULE_NOT_IMPLEMENTED` |
| `_UNKNOWN_CODES` (5) | `RULE_NOT_IMPLEMENTED` · **`COST_NOT_IMPLEMENTED`** · `INFORMATION_UNAVAILABLE` · `CARD_DEFINITION_UNAVAILABLE` · `EFFECT_LIST_UNRELIABLE` |

**크기는 같고 내용은 다르다** — 묶음에는 `HIDDEN_CARD` 가 있고 집합에는
`COST_NOT_IMPLEMENTED` 가 있다 (`test_11`). 둘 중 어느 쪽도 다른 쪽을 가리키지
않는다: enum 의 묶음은 **주석**이라 기계가 읽을 수 없고, 집합은 **손으로 쓴 리터럴**
이라 enum 이 바뀌어도 따라오지 않는다.

---

## 7. ValidationCode → SimulationStatus mapping

경로는 **네 칸**이고, 칸을 넘을 때마다 무엇이 떨어지는지가 핵심이다.

```
ValidationResult(validity, code, reason, missing_rule, notes)
        │  validity 가 여기서 **사라진다**
        ▼
DuelStep(action, accepted: bool, code, reason, result)
        │  accepted 로 압축됨 — "왜 안 되는가" 는 code 에만 남는다
        ▼
SimulationResult(action, status, viewer, reason, code, future)
        │  code 가 여기서 **사라진다**
        ▼
SearchCandidate(action, status, value, reason)   ← 오래 사는 흔적
```

### 필수 표 3 — ValidationCode 전체 분류 (48개)

`생성` = production 에서 그 멤버가 등장하는 자리 수 (carrier 무관, AST 측정).
`validity` = `ValidationResult` 와 함께 생산될 때의 판정.
`분류` = §17 의 범주.

| ValidationCode | 생성 | validity | `_UNKNOWN_CODES` | 분류 | 문제 |
| --- | --- | --- | --- | --- | --- |
| `OK` | 33 | VALID×3 | ✕ | VALID | — |
| `ACTOR_INVALID` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `SOURCE_REQUIRED` | 2 | INVALID | ✕ | TRUE INVALID | — |
| `SOURCE_FORBIDDEN` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `EFFECT_REF_REQUIRED` | 2 | INVALID | ✕ | TRUE INVALID | — |
| `EFFECT_REF_FORBIDDEN` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `EFFECT_REF_CARD_MISMATCH` | 4 | INVALID | ✕ | TRUE INVALID | — |
| `EFFECT_REF_OUT_OF_RANGE` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `PHASE_REQUIRED` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `PHASE_FORBIDDEN` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `TARGET_COUNT_MISMATCH` | 5 | INVALID | ✕ | TRUE INVALID | — |
| `TARGET_KIND_INVALID` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `DUEL_ALREADY_OVER` | 3 | INVALID×2 | ✕ | TRUE INVALID | — |
| `NOT_TURN_PLAYER` | 6 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `SOURCE_NOT_CONTROLLED` | 7 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `SOURCE_WRONG_ZONE` | 7 | — | ✕ | TRUE INVALID | — |
| `SOURCE_WRONG_CARD_TYPE` | 4 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `ZONE_FULL` | 4 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `WRONG_PHASE` | 8 | INVALID×2 | ✕ | TRUE INVALID | — |
| `SET_THIS_TURN` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `TARGET_NOT_OPPONENT` | 2 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `TARGET_SELF_CONTROLLED` | 1 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `TARGET_WRONG_ZONE` | 1 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `PHASE_UNCHANGED` | 2 | INVALID | ✕ | TRUE INVALID | — |
| **`HIDDEN_CARD`** | 4 | **UNKNOWN×2** | **✕** | **TRUE UNKNOWN** | **집합에서 빠졌다** |
| `INFORMATION_UNAVAILABLE` | 7 | UNKNOWN×3 | ○ | TRUE UNKNOWN | — |
| `CARD_DEFINITION_UNAVAILABLE` | 1 | UNKNOWN | ○ | TRUE UNKNOWN | — |
| `EFFECT_LIST_UNRELIABLE` | 1 | UNKNOWN | ○ | TRUE UNKNOWN | — |
| `RULE_NOT_IMPLEMENTED` | 49 | UNKNOWN×4 | ○ | TRUE UNKNOWN | 13곳은 3-E-36 이 계약 위반으로 기록 |
| `NO_CANDIDATES` | 3 | INVALID | ✕ | TRUE INVALID | — |
| `TOO_FEW_SELECTED` | 10 | INVALID | ✕ | TRUE INVALID | — |
| `TOO_MANY_SELECTED` | 2 | INVALID | ✕ | TRUE INVALID | — |
| `DUPLICATE_SELECTION` | 2 | INVALID | ✕ | TRUE INVALID | — |
| `CANDIDATE_NOT_FOUND` | 2 | — | ✕ | CONTEXT_DEPENDENT (관측에 없음 = 가려짐일 수도) | 판단 보류 — §17 |
| `CANDIDATE_NOT_ELIGIBLE` | 9 | INVALID | ✕ | TRUE CANDIDATE_NOT_ELIGIBLE | 3-E-38 이 여기로 옮겼다 |
| `INSUFFICIENT_LIFE` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `COST_NOT_IMPLEMENTED` | 5 | UNKNOWN×2 | ○ | TRUE UNKNOWN | 비용 있는 효과 0개 → dormant |
| `INSUFFICIENT_DECK` | 1 | — (`_fail`) | ✕ | TRUE INVALID | — |
| `INVALID_AMOUNT` | 6 | — (`_fail`) | ✕ | TRUE INVALID | — |
| `NO_RESPONSE_WINDOW` | 3 | INVALID×3 | ✕ | TRUE INVALID | — |
| `NOT_PRIORITY_HOLDER` | 1 | INVALID | ✕ | TRUE INVALID | — |
| `EXECUTION_FORBIDDEN` | 5 | — (`_fail`/`_gate`) | ✕ | EXECUTION_FORBIDDEN | 3-E-38 이 여기로 옮겼다 |
| `CHAIN_EMPTY` | 2 | INVALID | ✕ | TRUE INVALID | — |
| `CHAIN_DEFINITION_UNAVAILABLE` | 2 | — | ✕ | CONTEXT_DEPENDENT | 판단 보류 — §17 |
| `CANNOT_NORMAL_SUMMON` | 2 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `NORMAL_SUMMON_ALREADY_USED` | 3 | — (`Requirement`) | ✕ | TRUE INVALID | — |
| `SPELL_SPEED_TOO_LOW` | 1 | INVALID | ✕ | TRUE INVALID | — |
| **`PRIORITY_STATE_STALE`** | 1 | **UNKNOWN** | **✕** | **TRUE UNKNOWN** | **집합에서 빠졌다** |

**48개 전부 production 생성처가 1곳 이상 있다** — "enum 에만 있고 아무도 안
만드는" 코드는 **없다** (`생성처 0 인 code: []`). `EXECUTION_FORBIDDEN` 의 5곳은
3-E-38 의 수정이 들어간 자리를 포함한다.

---

## 8. UNKNOWN vs REFUSED semantic 비교

### 필수 표 4

| 항목 | UNKNOWN | REFUSED | 동일 처리 안전? |
| --- | --- | --- | --- |
| 의미 | "규칙이 아직 없다 — 모른다는 것이지 나쁘다는 것이 아니다" | "엔진이 규칙에 따라 거절했다" | **뜻은 다르다** |
| 정의 방식 | `step.code ∈ _UNKNOWN_CODES` | **그 여집합** (독립 정의 없음) | REFUSED 의 뜻이 집합에 종속 |
| ValidationCode | 측정상 5개 (실제 UNKNOWN validity 는 7개) | 나머지 43개 | **✕ — 2개가 잘못된 쪽에 선다** |
| `gives_a_future` | False | False | ○ 같다 |
| `ordering` | `(1, 0, 0, canonical)` | `(1, 0, 0, canonical)` | ○ **완전히 같다** |
| score | `value is None` (0 이 **아니다**) | `value is None` | ○ 같다 |
| candidate | 후보에서 **빠지지 않는다** | 빠지지 않는다 | ○ 같다 |
| `SimulationResult.code` | 보존됨 | 보존됨 | ○ 보존된다 |
| `reason` | 보존됨 (`step.reason` 그대로) | 보존됨 | ○ 보존된다 |
| `SearchCandidate` | `code` 칸 없음 → 사라짐 | 같음 | ○ 똑같이 사라진다 |
| AI/Search | 영향 없음 (`is not SUPPORTED` 한 갈래) | 같음 | ○ 안전 |
| Full Duel | 32판에서 **0건** | 32판에서 **0건** | ○ 둘 다 dormant |

**Q (§9): 저장소가 쓰는 실제 의미가 프롬프트의 정의와 같은가.** 거의 같다.
`UNKNOWN` 은 프롬프트의 "엔진이 이 판단을 확정할 수 없다" 보다 **좁다** — 소스는
"규칙이 아직 없다" 고 적는데, 집합에는 "정보가 없다" 쪽(`INFORMATION_UNAVAILABLE` ·
`CARD_DEFINITION_UNAVAILABLE`)도 들어 있다. 즉 **설명 문구가 집합보다 좁다.**
이것이 `HIDDEN_CARD` 가 빠진 까닭일 수 있다 — "규칙이 없다" 라는 좁은 문구를 기준으로
읽으면 가려진 카드는 거기 들어가지 않는다. 다만 그러면 `INFORMATION_UNAVAILABLE` 이
들어간 것이 설명되지 않는다. **문구와 집합이 서로를 설명하지 못한다.**

---

## 9. `is_usable()` / `gives_a_future` 영향

§10 이 요구한 CASE 판정이다.

| 자리 | `UNKNOWN` | `REFUSED` | `INVALID` 계열 | `SUPPORTED` | 예외 |
| --- | --- | --- | --- | --- | --- |
| `search.py:311` `is not SUPPORTED` | 점수 없는 후보 | **같음** | (`SimulationStatus` 에 없다) | 평가 → 점수 | `ERROR` 도 같음 |
| `simulation.py:118,122` `gives_a_future` | 미래 금지 | **같음** | — | 미래 필수 | `ERROR` 도 같음 |

**판정: CASE A 와 CASE B 가 섞여 있다. 이 Phase 는 CASE A 로 읽는다.**

- **CASE A 인 근거**: 탐색의 결정에 필요한 정보는 "점수를 낼 수 있는가" 하나다.
  `UNKNOWN` 과 `REFUSED` 는 **둘 다 점수를 낼 수 없다.** 그러므로 탐색이 둘을 가르지
  않는 것은 **정보를 버리는 것이 아니라 쓸 일이 없는 것**이다. 그리고 두 상태가
  `SearchCandidate.status` 에 **그대로 남으므로** 흔적을 읽는 사람은 구분할 수 있다.
- **CASE B 로 읽을 수 있는 여지**: 미래의 정책이라면 "모르는 수는 다시 시도할 가치가
  있고 거절된 수는 없다" 처럼 둘을 다르게 다룰 수 있다. 그런 정책은 **지금 없다.**
  없는 소비자를 위해 "정보가 소실되고 있다" 고 적으면 측정보다 센 말이 된다.

---

## 10. `ordering_key()` 영향

**다섯 상태와 `None` 까지 전부 같은 키다** (`test_13`, 실측).

```
SUPPORTED        (1, 0, 0, ('pass', 0, None, (), None, None))
NOT_A_CANDIDATE  (1, 0, 0, ('pass', 0, None, (), None, None))
UNKNOWN          (1, 0, 0, ('pass', 0, None, (), None, None))
REFUSED          (1, 0, 0, ('pass', 0, None, (), None, None))
ERROR            (1, 0, 0, ('pass', 0, None, (), None, None))
None             (1, 0, 0, ('pass', 0, None, (), None, None))
```

키를 가르는 것은 **`value` 의 유무 하나**다 — `value` 가 있으면 첫 칸이 `0`,
없으면 `1`. `status` 는 키에 **한 번도 등장하지 않는다.**

```python
def ordering_key(self):
    if self.value is None:
        return (1, 0, 0, self.action.canonical_state())
    terminal, heuristic = self.value.ordering_key()
    return (0, -terminal, -heuristic, self.action.canonical_state())
```

**§11 의 경고를 지킨다**: 키가 같다고 두 상태의 **뜻**이 같다고 결론 내리지 않는다.
여기서 재는 것은 "순위에 영향이 없다" 하나다. 그리고 그 반대도 적지 않는다 — 키가
같다는 것이 "구분이 불필요하다" 는 증명은 아니다.

---

## 11. SimulationResult 정보 보존

| 칸 | 있는가 | `UNKNOWN`/`REFUSED` 에서 보존되는가 | 읽는 consumer |
| --- | --- | --- | --- |
| `action` | ○ | 보존 | `SearchCandidate` |
| `status` | ○ | 보존 | `search.py:311,315,324` |
| `viewer` | ○ | 보존 | — |
| `reason` | ○ | **보존** (`step.reason` 그대로) | `SearchCandidate.reason` |
| `code` | ○ | **보존** (`step.code` 그대로) | **없다 — 0곳** |
| `future` | ○ | `None` (실패에는 미래가 없다) | 평가자 |
| `score`·`value`·`notes`·`ordering_key`·`state_hash` | **✕ 없다** | — | 다른 계층의 칸 |

### 정보가 사라지는 두 경계 (§14)

| 경계 | 사라지는 것 | 성격 |
| --- | --- | --- |
| `ValidationResult` → `DuelStep` | **`validity`** (3값) → `accepted` (2값) · `missing_rule` · `notes` | **status-level semantic compression.** 그리고 이것이 `_UNKNOWN_CODES` 가 **존재하는 이유**다 — 잃어버린 `validity` 를 에이전트 계층이 코드 집합으로 **되짚는다.** |
| `SimulationResult` → `SearchCandidate` | **`code`** | **information loss**, 단 **아무도 읽지 않는 정보**다. `ValidationCode` 는 `agent/` 안에서 `simulation.py` 밖으로 나가지 않고, 그 안에서도 **읽는** 자리는 분류기 하나뿐이다 (`test_18`). |

**가장 중요한 구조적 발견은 첫 줄이다.** `DuelStep` 이 `validity` 를 들고 있었다면
분류기가 필요하지 않았다 — `step.validity is ActionValidity.UNKNOWN` 한 줄이면
된다. 지금은 **같은 사실이 두 곳에 서로 다른 모양으로 적혀 있고**(enum 의 묶음 주석 ·
`_UNKNOWN_CODES` 리터럴), 셋째 곳(생산 시점의 `validity`)이 진짜인데 전달되지 않는다.
그래서 두 사본이 서로 어긋났고, 어긋난 것이 이 Phase 가 찾은 2개다.

---

## 12. AI / Search 영향

**판정: NO EFFECT.** 여섯 질문에 측정으로 답한다.

| # | 질문 | 답 | 근거 |
| --- | --- | --- | --- |
| 1 | 두 상태가 AI 의 행동을 다르게 만드는가 | **아니다** | `status` 를 비교하는 production 자리 2곳 모두 `SUPPORTED` 만 본다 (`test_12`) |
| 2 | ordering 이 다른가 | **아니다** | 키가 완전히 같다 (`test_13`) |
| 3 | score 가 다른가 | **아니다** | 둘 다 `value is None`, 0 이 아니다 (`test_29`) |
| 4 | 하나가 후보에서 제거되는가 | **아니다** | 둘 다 후보 목록에 남는다 (`search.py:311-319`) |
| 5 | 하나가 usable 로 판단되는가 | **아니다** | `gives_a_future` 가 둘 다 False |
| 6 | 둘이 같은 행동을 유도하는가 | **그렇다** | 1~5 의 결과 |

검사한 consumer 전체: `GameStateView` · `legal_actions` · 후보 생성 ·
`SearchPolicy` · `RuleBasedPolicy` · `RandomPolicy` · `FirstLegalPolicy` ·
`Evaluation` · `Simulation` · `SimulationResult` · ranking · tie-break.
이 중 `SimulationStatus` 를 보는 것은 `SearchPolicy` 하나이고, 나머지 정책들은
`SimulationStatus` 를 아예 import 하지 않는다.

---

## 13. Full Duel 영향

**실제 코퍼스를 돌렸다.** `agent.arena.run_match` 로 8 seed × 4 대전 = **32판**,
`Duel.apply` 와 `Simulator.simulate` 를 측정용으로 감싸 **지나간 값 전부**를 셌다
(production 수정 없음 — 이 프로세스에서만 감쌌다).

| 측정 | 값 |
| --- | --- |
| 완주한 판 | **32 / 32** (`completed`) |
| 정책 거부 | 0 |
| `DuelStep` 총 걸음 | **11,609** |
| 그중 `(accepted=True, code=OK)` | **11,609 — 전부** |
| 그중 거절된 걸음 | **0** |
| `Simulator.simulate` 총 호출 | **5,316** |
| 그중 `SUPPORTED` | **5,316 — 전부** |
| `UNKNOWN` | **0** |
| `REFUSED` | **0** |
| `NOT_A_CANDIDATE` · `ERROR` | **0** |

**즉 `_UNKNOWN_CODES` 분기는 실제 플레이에서 한 번도 실행되지 않는다.**

### 왜 그런가 — 구조적 까닭

1. `legal_actions` 는 **`VALID` 만** 후보에 넣는다 ("`UNKNOWN` 은 후보가 아니다").
2. 발동 후보는 `_activation_gate` 가 정하고, **`apply` 도 같은 함수로 같은 판을
   다시 본다** (STRUCTURAL-134 가 고친 바로 그 자리). 그래서 "후보로 내놓고 나서
   거절" 이 일어나지 않는다.
3. `Simulator.simulate` 는 **후보 목록에 있는 수만** 적용한다. 없는 수는 분류기
   앞에서 `NOT_A_CANDIDATE` 로 끝난다.

### 분기를 깨우려는 시도 — 전부 실패했다

가정이 아니라 **실제로 해 본 것**만 적는다.

| 시도 | 결과 |
| --- | --- |
| 얇은 덱(7장 · 6장)으로 덱 모자람 유도 | 덱 데스로 **정상 종료** (`accepted=True`) |
| 구현이 등록되지 않은 정의 3장(블랙홀 · 죽은 자의 소생 · 로스트)을 덱에 넣기 | `activatable_effects` 가 `executable` 만 돌려주므로 **후보에 아예 오르지 않았다** |
| MAIN1 에서 덱을 1장으로 줄이고 욕망의 항아리 발동 시도 | 발동 후보 **0** — 조건이 거짓이라 `withheld` 로 갔다 (= 3-E-38 의 M1 경로) |
| 32판 코퍼스 전수 | 거절 걸음 0 |

세 번째가 특히 중요하다. **3-E-38 이 고친 M1/M2 코드는 `SimulationStatus` 가 아니라
`legal_actions().withheld` 로 나온다.** 그런데 `WithheldAction` 에는 `code` 칸이
**없다** (`kind` · `reason` · `missing` 셋뿐). 그래서 그 코드는 이 길로도 기계가
읽을 형태로 나오지 않는다 (`test_28`).

### 가정과 실제의 분리 (§16)

- **실제 측정**: `UNKNOWN` · `REFUSED` 생산 0건. 두 상태의 AI 영향 없음.
- **가정 (실제 관측이 아니다)**: *만약* `HIDDEN_CARD` 가 `DuelStep` 까지 내려온다면
  분류기의 정의에 따라 `REFUSED` 가 된다 — "가려진 카드" 를 "규칙에 따라 거절했다"
  로 읽는 것이다. **그런 경로는 지금 없다.** 이것은 분류기의 정의를 그대로 적용한
  결과이고 관측된 사건이 아니다 (`test_31` 이 그 구분을 명시한다).

---

## 14. Git history / provenance

`git log -L 89,97:agent/simulation.py` 로 추적했다 (history 를 바꾸지 않았다).

| 질문 (§6) | 답 |
| --- | --- |
| 1. 언제 추가되었는가 | **`40ea6c8`, 2026-10-01** |
| 2. 왜 추가되었는가 | 커밋 제목: "Phase 3-C: 미래를 보고 고르는 AI — 그리고 아직 아무것도 더 알려주지 않는다". 집합 위 주석: "엔진이 '아직 규칙이 없다' 고 말하는 코드들. 이것을 거절과 섞지 않습니다." |
| 3. 최초 commit | `40ea6c8` — `agent/simulation.py` 가 **태어난** 커밋이다 (`/dev/null` → 신규) |
| 4. 당시 contract | `SimulationStatus` 도 같은 커밋에서 태어났다. `UNKNOWN` 의 설명이 지금과 같다 |
| 5. 실제 production 사례 | **찾지 못했다.** 당시에도 거절된 걸음을 만든 기록이 없다 (§13 과 같은 구조였다) |
| 6. 테스트가 보장하는가 | **부분적으로.** `UNKNOWN`/`REFUSED` 를 쓰는 기존 테스트 전부가 `SimulationResult`/`SearchCandidate` 를 **손으로 만든다** — `Simulator.simulate` 를 통해 온 것은 하나도 없다 |
| 7. 문서가 정의하는가 | **아니다.** 다섯 멤버를 고른 **기준**을 적은 문서가 없다 |
| 8. 이후 code 가 추가되며 갱신 누락? | **아니다 — 이것이 가장 중요한 답이다.** `HIDDEN_CARD` 는 `d8d20d6`(Phase 2-C), `PRIORITY_STATE_STALE` 는 `bc445d8`(Phase 2-F-1) 에 추가되었고, **둘 다 `40ea6c8` 보다 앞선다.** `40ea6c8` 시점의 `engine/validation.py` 에 `HIDDEN_CARD` 가 `모른다 (UNKNOWN)` 묶음의 **첫 멤버**로, `PRIORITY_STATE_STALE` 이 파일 끝에 이미 있었다 |
| 변경 이력 | 태어난 뒤 **한 번도 바뀌지 않았다** (`git log -L` 결과가 한 커밋) |

**결론**: 집합이 낡아서 어긋난 것이 **아니다.** 쓰는 순간부터 enum 의 `모른다`
묶음과 달랐다. 왜 `HIDDEN_CARD` 를 뺐는지 **설명하는 기록이 없다** →
**provenance unavailable** (추측하지 않는다).

---

## 15. 48 ValidationCode 분류

§7 의 필수 표 3 에 전부 적었다. 범주별 수는 다음과 같다.

| 범주 | 수 | 비고 |
| --- | --- | --- |
| VALID | 1 | `OK` |
| TRUE INVALID | 36 | 구조 · 판 위의 사실 · 비용/선택 · 실행 |
| TRUE UNKNOWN | 7 | 그중 **2개가 `_UNKNOWN_CODES` 에 없다** |
| TRUE CANDIDATE_NOT_ELIGIBLE | 1 | 3-E-38 이 여기로 옮겼다 |
| EXECUTION_FORBIDDEN | 1 | 3-E-38 이 여기로 옮겼다 |
| CONTEXT_DEPENDENT | 2 | `CANDIDATE_NOT_FOUND` · `CHAIN_DEFINITION_UNAVAILABLE` |
| DORMANT | 0 | — |
| MISCLASSIFIED | 0 추가 | 3-E-36 이 센 13곳이 그대로 남아 있다 (범위 밖) |
| UNUSED / NO PRODUCTION PATH | **0** | 48개 전부 생성처가 있다 |

**CONTEXT_DEPENDENT 둘을 임의로 A/B 로 밀어 넣지 않았다** (§8 의 지시).

- `CANDIDATE_NOT_FOUND` — "고른 카드가 관측에 없다". **`HIDDEN_CARD` 와 같은
  사실**일 수 있다(가려져서 안 보임) 하지만 "아예 없는 카드를 골랐다"(= 확정 거부)
  일 수도 있다. 생산처 2곳이 `CostPaymentResult` · `_fail` 이고 `ValidationResult`
  의 validity 와 짝지어지지 않으므로 **지금 자료로는 가를 수 없다.**
- `CHAIN_DEFINITION_UNAVAILABLE` — "정의를 찾을 수 없다. 해결할 수 없다". 뜻은
  미구현에 가깝지만 `ChainResolution` · `TriggerChainEntry` 가 들고 다니고
  `ValidationResult` 로 생산되지 않아 validity 축에 나타나지 않는다.

합이 48 이다: 1 + 36 + 7 + 1 + 1 + 2. (처음에 `TRUE INVALID` 를 37 로 적었다가
합이 49 가 되어 다시 셌다 — `test_33` 이 이 분할을 코드로 고정한다.)

둘 다 **판단 불가능(E)** 이 아니라 **context-dependent(C)** 로 적는다 — 가를 수
있는 정보가 repository 안에 있을 수 있고, 그것을 찾는 것이 이 Phase 의 범위가 아니다.

---

## 16. M1 / M2 semantic 확인

3-E-38 의 두 수정이 `SimulationStatus` 에서 어떻게 읽히는지 §18 이 물었다.
**"UNKNOWN 이 아니게 되었으므로 반드시 REFUSED 여야 한다" 는 추론을 하지 않았다** —
consumer 를 읽었다.

| | code | `_UNKNOWN_CODES` | 분류기를 지난다면 | 실제로 지나는가 |
| --- | --- | --- | --- | --- |
| **M1** 조건 거짓 | `CANDIDATE_NOT_ELIGIBLE` | ✕ | `REFUSED` | **아니다** — `legal_actions().withheld` 로 간다 |
| **M2** `TEXT_DERIVED` | `EXECUTION_FORBIDDEN` | ✕ | `REFUSED` | **아니다** — 후보가 아예 오르지 않는다 (`activatable_effects` 가 `executable` 만 돌려준다) |

**그래서 3-E-38 이 §10 에 적은 "네 자리의 분류가 `UNKNOWN` → `REFUSED` 로
바뀐다" 는 서술을 여기서 정밀하게 고친다.** 분류 **규칙**으로는 그렇다. 그러나
**그 네 자리가 분류기에 도달하는 production 경로가 없다** — 실측으로 32판 ·
11,609 걸음 · 5,316 시뮬레이션에서 0건이다. 3-E-38 은 그 변화를 "AI 영향 없음" 으로
적었고 그 결론은 맞았지만, 까닭을 "consumer 가 구분하지 않기 때문" 으로만 적었다.
**더 강한 까닭이 있다: 그 분기 자체가 실행되지 않는다.**

그리고 M1/M2 가 **실제로 소비되는 길**은 `withheld` 다. 그 길에는 `code` 칸이
없다 — 즉 3-E-38 이 정확하게 만든 코드는 지금 **기계가 읽을 수 있는 형태로 AI 에
전달되지 않는다.** 이것은 3-E-38 의 결함이 아니다 (그 Phase 는 엔진의 어휘를 고쳤다).
다음 Phase 가 다룰 사실로 기록한다.

---

## 17. 테스트

### 새 파일

`tests/test_simulation_status_unknown_codes_audit.py` — **33개** (요구 최소 20개).
§22 가 요구한 1~22 항목을 전부 덮는다.

| §22 항목 | 테스트 |
| --- | --- |
| 1 SimulationStatus 전체 | `test_01` |
| 2 UNKNOWN 존재·뜻 | `test_02` |
| 3 REFUSED 존재·뜻 | `test_03` |
| 4·5 생성 경로 | `test_04` (자리 1곳 AST) · `test_05` (관문 순서) |
| 6 집합 전체 | `test_06` |
| 7 count | `test_07` |
| 8 전부 ValidationCode | `test_08` |
| 9 production 경로 | `test_09` |
| 10 집합 밖의 UNKNOWN code | `test_10` · `test_11` (enum 묶음과도 다르다) |
| 11 is_usable 동일 여부 | `test_12` |
| 12 ordering_key 동일 여부 | `test_13` |
| 13 code 보존 | `test_14` |
| 14 reason 보존 | `test_15` |
| 15 notes 보존 | `test_16` (없는 칸을 밝힌다) · `test_17` (손실 지점) · `test_18` (읽는 자리 0) |
| 16 state_hash | `test_19` |
| 17 RNG | `test_20` |
| 18 hidden information | `test_21` |
| 19 M1 경로 | `test_22` |
| 20 M2 경로 | `test_23` |
| 21 genuine RULE_NOT_IMPLEMENTED | `test_24` |
| 22 새 code 없음 | `test_25` |
| (§2 정정) | `test_26` |
| (도달 가능성) | `test_27` · `test_28` |
| (§32 불변식) | `test_29` · `test_30` · `test_31` |
| (§33 diff 0) | `test_32` |
| (분류 합) | `test_33` |

### §23 을 지켰다 — "반드시 달라야 한다" 를 적지 않았다

테스트 이름이 대부분 **현재 사실의 서술형**이다.
`test_12_the_search_consumer_puts_both_statuses_in_the_same_branch` ·
`test_13_every_status_including_none_gets_the_same_ordering_key` ·
`test_10_two_codes_are_produced_as_unknown_but_are_not_in_the_set`.
"둘은 달라야 한다" 를 주장하는 테스트는 **하나도 없다.**

### 기존 테스트 수정

**0건.** 삭제 0 · skip 추가 0 · assertion 약화 0. 기존 파일을 한 줄도 건드리지
않았다.

### 이 파일을 쓰며 고친 내 오류 네 개

측정으로 찾았고 전부 **내 테스트 쪽**이 틀렸다.

1. `SimulationStatus.UNKNOWN.__doc__` 이 멤버 아래 문구라고 착각했다. `Enum` 멤버의
   `__doc__` 은 **클래스 docstring** 이다 — 멤버 밑의 `"""..."""` 는 런타임에 남지
   않는다(Sphinx 가 소스에서 읽는다). `member_note()` 헬퍼로 소스에서 읽게 고쳤다.
2. `ValidationCode.HIDDEN_CARD.__doc__` 도 같은 착각이었다.
3. `agent/simulation.py` 의 `"ValidationCode."` 등장을 6 으로 예상했는데 **5** 였다
   — 타입 주석이 `frozenset[ValidationCode]` 라서 점이 없다.
4. `engine/validation.py` 의 문자열 할당을 `48 + 3 = 51` 로 예상했는데 **53** 이었다
   — enum 밖의 상수까지 걸린다. 문자열 세기를 버리고 **AST 로 클래스별 멤버 수**를
   세게 고쳤다 (`ValidationCode == 48` · `ActionValidity == 3`).

---

## 18. Safety invariants

§32 의 14개를 전부 확인했다.

| # | 불변식 | 결과 | 테스트 |
| --- | --- | --- | --- |
| 1 | UNKNOWN ≠ FALSE | ○ `permits_execution` False **이고** `is_structural_failure` False | `test_29` |
| 2 | UNKNOWN ≠ LOSS | ○ 승패 칸이 없다 | `test_29` |
| 3 | REFUSED ≠ LOSS | ○ 같다 | `test_29` |
| 4 | `RULE_NOT_IMPLEMENTED` ≠ LOSS | ○ `value is None`, 0 이 아니다 | `test_29` |
| 5 | `CANDIDATE_NOT_ELIGIBLE` ≠ `RULE_NOT_IMPLEMENTED` | ○ | `test_22` `test_30` |
| 6 | `EXECUTION_FORBIDDEN` ≠ `RULE_NOT_IMPLEMENTED` | ○ | `test_23` `test_30` |
| 7 | hidden information ≠ REFUSED | **△ 두 축이 어긋난다** — validity 축에서는 ○ (`HIDDEN_CARD` 는 `UNKNOWN`), `_UNKNOWN_CODES` 축에서는 ✕ (집합에 없으므로 `REFUSED` 쪽). **오늘 그 경로는 없다** | `test_31` |
| 8 | hidden information ≠ LOSS | ○ | `test_29` `test_31` |
| 9 | `state_hash` 불변 | ○ 탐색 전후 동일 | `test_19` |
| 10 | RNG 불변 | ○ `draws` 전후 동일 | `test_20` |
| 11 | Simulation 이 실제 `GameState` 를 바꾸지 않음 | ○ `clone()` 기반, 9·10 이 증거 | `test_19` `test_20` |
| 12 | `ValidationCode` enum 변경 없음 | ○ 48 그대로 | `test_25` `test_32` |
| 13 | `SimulationStatus` enum 변경 없음 | ○ 5 그대로 | `test_25` |
| 14 | AI/Search production 변경 없음 | ○ `git diff` 0 | `test_32` · §19 |

**7번이 이 Phase 가 찾은 유일한 어긋남이다.** 그리고 그것이 §21 의 판정을 정한다.

---

## 19. Production diff

```
$ git diff --stat -- engine/ agent/ core/ analysis/ sources/ app/
(출력 없음)
```

**production diff = 0.** 추가한 것은 둘뿐이다.

```
tests/test_simulation_status_unknown_codes_audit.py   (신규, 33 tests)
docs/phase3e39-simulation-status-unknown-codes-audit.md (신규, 이 문서)
```

`test_32` 가 손댈 수 있었던 네 자리(`_UNKNOWN_CODES` 다섯 줄 · 분류기 한 자리 ·
탐색 분기 한 자리 · enum 크기)를 소스에서 다시 확인한다.

### Full regression

```
$ python -m pytest -q -p no:randomly
3907 passed, 4 skipped in 358.35s (0:05:58)
```

| 항목 | Phase 3-E-38 종료 시 | 이번 Phase 종료 시 |
| --- | --- | --- |
| passed | 3874 | **3907** (+33, 새 파일) |
| failed | 0 | **0** |
| skipped | 4 | **4** (증가 없음) |
| 기존 테스트 삭제 | — | **0** |
| 기존 assertion 약화 | — | **0** |
| production diff | — | **0** |

---

## 20. 82 최종 질문

**Q1. `UNKNOWN` 과 `REFUSED` 는 실제 semantic 이 다른가?**
**다르다.** 소스가 둘을 다르게 적는다 — "규칙이 아직 없다 (모른다는 것이지 나쁘다는
것이 아니다)" 와 "엔진이 규칙에 따라 거절했다". 그러나 **`REFUSED` 는 독립적인
정의가 없다** — `_UNKNOWN_CODES` 의 여집합이다. 그래서 두 상태의 경계는
`SimulationStatus` 가 아니라 **그 집합**이 정한다.

**Q2. 현재 production consumer 가 둘을 동일하게 취급하는 것이 안전한가?**
**안전하다.** consumer 가 필요한 것은 "점수를 낼 수 있는가" 하나이고 둘 다 낼 수
없다. 그리고 두 상태가 `SearchCandidate.status` 에 그대로 남으므로 흔적을 읽는
사람은 구분할 수 있다.

**Q3. 그 동일 처리가 AI/Search ranking 을 실제로 바꾸는가?**
**바꾸지 않는다.** 순위 키가 완전히 같고(측정), `status` 는 키에 등장하지 않는다.
그리고 **더 강한 사실**: 32판 · 5,316 시뮬레이션에서 두 상태가 **0건** 생산되었다.

**Q4. `_UNKNOWN_CODES` 5개는 근거 있는 policy 인가?**
**아니다 — 부분적으로만.** 들어간 5개는 모두 정당하다(전부 `UNKNOWN` validity 로만
생산된다, 오탐 0). 그러나 **빠진 것이 2개**다(`HIDDEN_CARD` ·
`PRIORITY_STATE_STALE`). 그리고 집합이 enum 자신의 `모른다 (UNKNOWN)` 묶음과
**다르다.** 선택 기준을 적은 문서도, 테스트도 없고, git history 도 설명하지 않는다
(**provenance unavailable**). 태어난 뒤 한 번도 갱신되지 않았고, **낡은 것이 아니라
처음부터 달랐다** (빠진 두 코드가 집합보다 먼저 존재했다).

**Q5. 48개 중 UNKNOWN 으로 분류되어야 하는 범위가 현재 집합과 일치하는가?**
**일치하지 않는다.** 측정값 **7 vs 5**. 반대 방향(들어가면 안 되는 것이 들어간 경우)
은 **0**. `CANDIDATE_NOT_FOUND` · `CHAIN_DEFINITION_UNAVAILABLE` 둘은
context-dependent 로 남겨 두었다 — 임의로 A/B 를 정하지 않았다.

**Q6. 현재 구조에서 정보 손실이 발생하는가?**
**두 경계에서 발생하고, 성격이 다르다.**
① `ValidationResult → DuelStep` 에서 **`validity` 가 사라진다** — 이것이
`_UNKNOWN_CODES` 가 존재하는 이유이고, 같은 사실의 사본이 셋(생산 시점의 validity ·
enum 의 묶음 주석 · 집합 리터럴)이 되어 서로 어긋난 원인이다. **이것이 진짜 문제다.**
② `SimulationResult → SearchCandidate` 에서 **`code` 가 사라진다** — 다만 그 code 를
읽는 consumer 가 **0곳**이므로 지금 잃는 것은 쓰이지 않는 정보다.

**Q7. 새 enum 이 필요한가?**
**필요하지 않다.** 빠진 두 코드는 이미 enum 에 있다. `SimulationStatus` 도 다섯으로
충분하다 — 모자란 것은 멤버가 아니라 **"어느 코드가 모름인가" 의 단일 출처**다.

**Q8. production 변경이 필요한가?**
**필요하다, 단 급하지 않다.** 집합이 불완전한 것은 사실이고 고쳐야 한다. 그러나 두
코드가 분류기에 도달하는 경로가 **오늘 없으므로** 잘못된 결과를 내고 있지는 않다.
**이번 Phase 에서는 고치지 않는다** (AUDIT-ONLY).

**Q9. 필요하다면 어떤 최소 변경이 필요한가?**
두 길이 있고 크기가 다르다.

| 안 | 변경 | 크기 | 평가 |
| --- | --- | --- | --- |
| 임시 | `_UNKNOWN_CODES` 에 두 줄 추가 | 2줄 | 증상은 멈추지만 **사본이 여전히 둘**이다 — 다음에 또 어긋난다 |
| 근본 | `ValidationCode` 에 "모름인가" 를 **기계가 읽을 수 있게** 붙이고 집합을 그것으로 유도 | enum + 집합 | 단일 출처가 된다. 묶음 주석이 코드가 된다 |

**§19 의 architecture decision: B — `ValidationCode` 자체에 semantic metadata 가
필요하다.** 까닭: enum 은 이미 그 사실을 알고 **주석으로** 적어 두었다
(`# --- 모른다 (UNKNOWN) ---`). 기계가 읽을 수 없는 자리에 적혀 있다는 것이 문제의
전부다. A(현재 형태가 적절한 명시적 policy)는 측정과 맞지 않고(2개 누락),
C(별도 resolver)는 사본을 셋째로 늘린다, D(현재 구조로 충분)는 Q4 와 모순이다.

**Q10. 지금 수정하면 Engine V1 / AI 단계의 범위를 깨는가?**
**임시안은 깨지 않는다** (`agent/` 2줄, enum 무변경, 도달 경로가 없으므로 동작 변화
0). **근본안도 깨지 않는다** — `ValidationCode` 에 분류를 붙이는 것은 멤버를 추가하는
것이 아니다. 다만 `DuelStep` 에 `validity` 를 실어 보내는 **셋째 방안**은 엔진의
걸음 계약을 바꾸므로 **별도 architecture Phase** 가 맞다.

---

## 21. Final Decision

**C. UNKNOWN_CODES_POLICY_UNJUSTIFIED**

`_UNKNOWN_CODES` 의 5개 선택에 충분한 근거가 없다. → **현재 production 은 건드리지
않고** 다음 phase 로 넘긴다.

근거 셋:

1. **측정상 불완전하다.** `ActionValidity.UNKNOWN` 과 함께 생산되는 코드는 7개이고
   집합은 5개다. `HIDDEN_CARD`(enum 의 `모른다` 묶음 **첫 멤버**)와
   `PRIORITY_STATE_STALE`(docstring 이 "`INVALID` 가 아니라 `UNKNOWN` 에 쓴다" 고
   명시)이 빠져 있다.
2. **근거가 기록되어 있지 않다.** 선택 기준을 적은 문서 0 · 테스트 0 · 커밋 설명 0.
   그리고 **낡아서 어긋난 것이 아니다** — 빠진 두 코드는 집합보다 **먼저** 존재했다
   (`d8d20d6` · `bc445d8` < `40ea6c8`). 즉 처음부터 enum 의 묶음과 달랐고, 왜
   달랐는지 설명하는 기록이 없다 (**provenance unavailable**).
3. **집합이 `REFUSED` 의 뜻을 혼자 정한다.** `REFUSED` 는 독립 정의가 없는 여집합
   이므로, 집합이 틀리면 `REFUSED` 의 뜻이 틀린다. 지금 그 결과로
   "가려진 카드" 가 "규칙에 따라 거절했다" 쪽에 선다 — 도달 경로가 없어 해가 없지만
   **분류 자체는 틀렸다.**

### 다른 판정을 고르지 않은 까닭

- **A (SEMANTICALLY_SAFE)** — "정보도 충분히 보존된다 → production 변경 없음".
  consumer 쪽은 정말 안전하고 그것을 §9 · §12 에 적었다. 그러나 A 를 고르면
  **집합이 불완전하다는 측정값이 헤드라인에서 사라진다.** "오늘 해가 없다" 와
  "분류가 맞다" 는 다른 말이다.
- **F (DORMANT_ONLY)** — 분기가 dormant 라는 것은 **측정된 사실**이고 §13 에 적었다.
  그러나 F 의 결론은 "수정하지 않는다" 이고, 그러면 2개 누락이 영구히 묻힌다.
  dormant 는 **급하지 않은 까닭**이지 **고칠 필요가 없다는 근거**가 아니다.
- **B (SEMANTIC_DISTINCTION_REQUIRED)** — "consumer 가 구분하지 않아 실제 semantic
  loss 가 발생한다" 는 판정이다. 측정은 반대다 — 구분을 **쓰는 consumer 가 없고**,
  쓸 consumer 가 생기기 전에는 손실이라 부를 것이 없다.
- **D (INFORMATION_LOSS)** — `code` 가 `SearchCandidate` 에서 사라지는 것은 사실
  (§11). 그러나 그 code 를 읽는 자리가 **0곳**이므로 "실제로 소실된다" 를 헤드라인
  으로 적으면 센 말이 된다. §11 에 사실로 기록하는 것이 정확하다.
- **E (AI_SEMANTIC_CHANGE)** — 구분이 Search/Evaluation/Policy 결과를 바꾼다는
  판정이다. 측정상 **바꾸지 않는다** (순위 키 동일 · 생산 0건).
- **G (BLOCKER)** — 막힌 것이 없다. 48개 전수, 생성처, validity, git history,
  32판 코퍼스까지 전부 repository 안에서 측정했다.

---

## 22. Next Phase Candidate

**하나만 제안한다.**

> **Phase 3-E-40 — `_UNKNOWN_CODES` policy 정식화** (§36 의 후보 2번)

다룰 것 (이번 Phase 가 **구현하지 않은** 것):

1. `ValidationCode` 의 `모른다 (UNKNOWN)` 묶음을 **기계가 읽을 수 있는 형태**로
   만든다 — 지금은 주석이다. 새 멤버는 추가하지 않는다.
2. `_UNKNOWN_CODES` 를 그 단일 출처에서 유도하거나, 최소한 두 코드
   (`HIDDEN_CARD` · `PRIORITY_STATE_STALE`)를 더해 **7개로 맞춘다.**
3. `CANDIDATE_NOT_FOUND` · `CHAIN_DEFINITION_UNAVAILABLE` 두 context-dependent
   코드를 가른다 — 이번 Phase 는 가를 자료가 부족해 보류했다.
4. 그 변경이 도달 불가 경로만 건드린다는 것을 **before/after 로 측정**한다
   (`state_hash` · RNG · 순위 · 32판 코퍼스).

**다루지 말 것으로 함께 제안한다**: `DuelStep` 에 `validity` 를 싣는 일.
엔진의 걸음 계약을 바꾸는 일이고, `WithheldAction` 에 `code` 를 싣는 문제(§16)와
함께 **별도 architecture Phase** 가 맞다.

**이번 Phase 에서 그것을 구현하지 않았다.** 다음 Phase 의 범위와 금지 사항은
사용자가 정한다.
