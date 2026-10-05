# Phase 3-E-38 — M1 · M2 · M3 ValidationCode 최소 수정 + UNKNOWN_CODES 영향 측정

> 이 Phase 의 목표는 "많이 고치는 것" 이 아니다.
> **거부 이유를 더 정확하게 적으면서, 판과 AI 의 의미는 한 칸도 움직이지 않는 것** 이다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-E-38 — minimal validation code fix |
| 성격 | **production 수정 허용** (3-E-33 ~ 3-E-37 은 전부 AUDIT-ONLY 였다) |
| 수정 허용 범위 | M1 · M2 · M3 **그 자리와 그 직접적인 테스트뿐** |
| Base | Phase 3-E-37 (`4b93f48` + 보고서 `bf35d6c`) |
| 작업 시작 시 실제 HEAD | `bf35d6c` — "Phase 3-E-37 보고서: 고의 위반 16건 + test_18 의 실제 구멍 수정 (AUDIT-ONLY)" |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 결과 commit | `913b05a` — `Phase 3-E-38: minimal validation code fix` |
| push | 완료 — `origin/claude/pensive-goodall-te1egy` (`bf35d6c..913b05a`) |

§2 의 지시대로 3-E-37 보고서를 **믿지 않고** production source 를 직접 다시 읽었다.
그 과정에서 보고서의 수 하나가 실제와 달랐다 — §19 에 적는다.

---

## 2. BLOCKER

**없음.**

M1 · M2 는 기존 `ValidationCode` 멤버로 정확히 표현되고, 새 멤버 · 새 status ·
새 계층이 필요 없었다. M3 는 **고치지 않기로** 판단했고 그 까닭을 §6 에 적는다.
공식 재정(`https://www.db.yugioh-card.com/yugiohdb/`)을 새로 조회할 일도 없었다 —
이번 수정은 카드 재정이 아니라 **엔진이 거부 이유를 적는 어휘**의 문제다.

---

## 3. Engine 변경

production 변경은 **두 파일 · 네 줄**이다. 나머지 줄은 전부 "왜 이 코드인가" 를
적은 한국어 주석이다.

```
engine/activation.py        | 31 ++++++++++++++++++++-----------
engine/effect/executor.py   | 11 ++++++++---
```

실제로 **의미가 바뀐 네 줄**:

| # | 파일:자리 | Before | After |
| --- | --- | --- | --- |
| M1-a | `engine/activation.py` · `EffectActivator._check_condition` | `ValidationCode.RULE_NOT_IMPLEMENTED` | `ValidationCode.CANDIDATE_NOT_ELIGIBLE` |
| M1-b | `engine/effect/executor.py` · `EffectExecutor._check_condition` | `ValidationCode.RULE_NOT_IMPLEMENTED` | `ValidationCode.CANDIDATE_NOT_ELIGIBLE` |
| M2-a | `engine/activation.py` · `_AVAILABILITY_REFUSAL[FORBIDDEN_SOURCE]` | `ValidationCode.RULE_NOT_IMPLEMENTED` | `ValidationCode.EXECUTION_FORBIDDEN` |
| M2-b | `engine/effect/executor.py` · `EffectExecutor._check_authority` | `ValidationCode.RULE_NOT_IMPLEMENTED` | `ValidationCode.EXECUTION_FORBIDDEN` |

구조 변경 한 가지가 함께 있다 — **`_AVAILABILITY_REFUSAL` 이 3-튜플에서 4-튜플이
되었다.** 전에는 이 표가 `(status, reason, missing)` 만 들고 있었고 코드는 호출부가
세 갈래에 **하나로** 붙였다. 그래서 "출처 금지" 와 "미검증" 과 "미등록" 이 **코드 한
줄을 공유**했고, M2 를 고치려면 셋을 다시 갈라야 했다. 표에 코드 칸을 넣는 것이
갈래마다 `if` 를 더하는 것보다 적게 바꾼다.

```python
_AVAILABILITY_REFUSAL: dict[
    ExecutionAvailability, tuple[ActivationStatus, ValidationCode, str, str]
] = {
    ExecutionAvailability.FORBIDDEN_SOURCE: (
        ActivationStatus.FORBIDDEN,
        ValidationCode.EXECUTION_FORBIDDEN,        # ← 바뀐 것
        "공식 텍스트에서 유추한 효과는 발동하지 않습니다 (ADR-004).",
        "executable implementation from official script",
    ),
    ExecutionAvailability.UNVERIFIED: (
        ActivationStatus.UNVERIFIED,
        ValidationCode.RULE_NOT_IMPLEMENTED,       # ← 그대로 (모른다)
        ...
    ),
    ExecutionAvailability.NO_IMPLEMENTATION: (
        ActivationStatus.NOT_IMPLEMENTED,
        ValidationCode.RULE_NOT_IMPLEMENTED,       # ← 그대로 (모른다)
        ...
    ),
}
```

**고치지 않은 것** (§18 의 제한을 지켰다):

- `engine/validation.py` — **diff = 0.** `ValidationCode` enum 은 48 멤버 그대로다.
- `agent/simulation.py` — diff = 0. `_UNKNOWN_CODES` 5 멤버 그대로다.
- `engine/trigger.py` · `engine/trigger_chain.py` — diff = 0 (M3, §6).
- `engine/effect/resolution.py` — diff = 0 (dormant `UnimplementedResolver`, 범위 밖).
- `core/` · `analysis/` · `sources/` · `app/` — diff = 0.

---

## 4. M1

### M1

**Before:**
`RULE_NOT_IMPLEMENTED`

**After:**
`CANDIDATE_NOT_ELIGIBLE`

**자리**: `EffectActivator._check_condition` · `EffectExecutor._check_condition`
— 두 계층이 **같은 사실**을 말하는 두 자리다.

**왜 틀렸었나.** 조건 평가기가 조건을 **끝까지 보고** `ConditionResult.FALSE` 를
돌려준 자리다. 끝까지 봤다는 것은 **규칙이 있었다**는 뜻이다. 그런데 거기 붙던
`RULE_NOT_IMPLEMENTED` 의 docstring 은 이렇게 적혀 있다.

> **이 엔진이 아직 못 한다.** … ``UNKNOWN`` 쪽의 코드다 — 확실한 거부(``INVALID``)에
> 붙이지 않는다.

enum 자신이 `# --- 모른다 (UNKNOWN) ---` 묶음에 넣어 둔 코드를 **확실한 거부**에
붙이고 있었다. 판정(`status`)은 `CONDITION_FALSE` 로 맞았고 이유(`code`)만 어긋나
있었다 — 그래서 겉으로 드러나는 오동작이 없었고 3-E-36 까지 살아남았다.

**왜 `CANDIDATE_NOT_ELIGIBLE` 인가.** 추측이 아니다. **같은 사실에 이미 이 코드를
쓰는 자리가 repository 안에 있었다.**

- `engine/trigger.py` `TriggerCollector._judge` — 조건이 거짓인 후보에 이 코드를 쓴다 (3-E-26).
- `engine/trigger_chain.py` `_refusal_code` — 기본값이 `CANDIDATE_NOT_ELIGIBLE` 이다.
- `engine/effect/executor.py` — **이미 세 자리**에서 이 코드를 쓰고 있었다:
  고른 카드를 규칙이 전부 막음 · 특수 소환 실패 · 대상 조건 거짓.

즉 "규칙을 보고 이 후보를 받지 않는다" 를 말하는 코드가 **이미 있었고 쓰이고
있었다.** 3-E-26 이 "그것을 말하는 코드가 enum 에 없다" 고 적은 것이 사실이
아니었다 (§17 에서 그 테스트를 고친 까닭).

**두 계층을 함께 고친 까닭.** 한쪽만 고치면 **같은 정의가 발동 때와 해결 때 다른
이유를 낸다.** 3-E-26 이 맞춰 둔 "두 계층이 같은 말을 한다" 를 깨뜨리게 된다.
`test_03` 이 두 계층의 코드가 같은 객체인지 직접 비교한다.

---

## 5. M2

### M2

**Before:**
`RULE_NOT_IMPLEMENTED`

**After:**
`EXECUTION_FORBIDDEN`

**자리**: `_AVAILABILITY_REFUSAL[FORBIDDEN_SOURCE]` (발동) ·
`EffectExecutor._check_authority` 의 `FORBIDDEN_SOURCE` 갈래 (해결).

**왜 틀렸었나.** `ExecutionAvailability.FORBIDDEN_SOURCE` 는 "구현이 없다" 가
아니다. **구현이 등록되어 있어도** 출처가 `TEXT_DERIVED` 이면 ADR-004 가 실행을
금지한다. 즉 "못 한다" 가 아니라 **"이 근거로는 절대 실행하지 않는다"** 다.

그리고 enum 은 그 말을 하려고 **멤버를 따로 만들어 두었다.**

> `EXECUTION_FORBIDDEN` — 출처가 실행을 금지한다 (``TEXT_DERIVED``, ADR-004).
> ``INVALID`` 중에서도 **따로 구분한다** — '조건이 거짓' 과 '이 근거로는 절대
> 실행하지 않는다' 는 전혀 다른 말…

**정확히 이 경우를 위해 만든 멤버를, 정작 그 경우가 쓰지 않고 있었다.**

**세 갈래를 뭉개지 않았다.** `ExecutionAvailability` 는 세 값이고, 그중
`FORBIDDEN_SOURCE` **하나만** 바꿨다.

| `ExecutionAvailability` | 뜻 | code |
| --- | --- | --- |
| `FORBIDDEN_SOURCE` | 근거가 금지한다 (ADR-004) | **`EXECUTION_FORBIDDEN`** ← 바뀜 |
| `UNVERIFIED` | 의미가 공식 근거로 확인되지 않았다 | `RULE_NOT_IMPLEMENTED` (그대로) |
| `NO_IMPLEMENTATION` | 실행 구현이 등록되어 있지 않다 | `RULE_NOT_IMPLEMENTED` (그대로) |

`test_07` 이 세 갈래를 각각 고정하고, `test_20` 의 negative test 가 "미검증 →
금지" 변환이 생기면 깨진다.

---

## 6. M3

### M3

**Reachability:**
**dormant — production 도달 0.**

**Decision:**
**고치지 않는다.**

**자리**: `engine/trigger.py` `_event_relation` (약 1315행).

```python
return _gate(
    EligibilityGate.EVENT_RELATION,
    ActionValidity.INVALID,                  # ← 확실한 거부
    ValidationCode.RULE_NOT_IMPLEMENTED,     # ← "모른다" 코드
    f"이 선언은 {event.point.value} 사건에 반응하지 않습니다.",
)
```

의미상 M1 과 같은 어긋남이다 (확실한 거부 + 모른다 코드). 그런데 **고치지 않았다.**
까닭은 셋이다.

1. **파이프라인 전체가 dormant 다.** `TriggerSpec` · `TriggerRegistry` 의
   production 생성이 **0곳** 이다 (`test_09` 가 AST 로 전 파일을 훑어 고정한다).
   그 둘 없이는 수집기도 판정기도 돌지 않는다. `engine/duel.py` 는 "trigger" 라는
   말을 **한 번도** 쓰지 않는다.
2. **`judge_all` 은 이 분기에 닿지 않는다.** 사건이 **이미 맞은** 후보만 넘기므로,
   이 `INVALID` 갈래는 공개 `judge()` 를 직접 부를 때만 닿는다 — production 호출 0곳.
3. **고치려면 더 큰 질문에 먼저 답해야 한다.** "이 선언은 그 사건에 반응하지
   않는다" 가 애초에 `INVALID`(확실한 거부) 인지가 구조 질문이다. 반응하지 않는
   선언은 **거부당한 후보가 아니라 후보가 아닌 것**에 가깝다. 그 판단은 Gate ·
   Trigger 구조를 건드리는 일이고, §0 이 이번 Phase 에서 금지한 범위다.

**숨기지 않는다.** `test_10` 이 "M3 가 여전히 옛 코드를 들고 있다" 를 **명시적으로
고정**한다. 누군가 나중에 이 자리를 고치면 그 테스트가 깨지고, 그때 이 문서를 읽게
된다.

한 가지 더 적어 둔다 — **M3 는 자기 방어 장치를 스스로 무력화한다.**
`engine/trigger_chain.py` `_refusal_code` 는 첫 `INVALID` gate 의 코드를 그대로
돌려주고 **기본값이 `CANDIDATE_NOT_ELIGIBLE`** 이다. 즉 이 gate 가 코드를 적지
않았다면 저절로 맞는 답이 나왔을 자리다. 적어서 틀렸다. dormant 가 아니었다면
이것은 production 결함이다.

---

## 7. Before / After

같은 seed(`11`) · 같은 덱 · 같은 시나리오로 수정 전후를 JSON 으로 떠서 `diff` 했다.
**전체 diff 가 네 줄이고, 네 줄 모두 `code` 값이다.**

```
11c11
<   "code": "rule_not_implemented",        # activate.M1_false
>   "code": "candidate_not_eligible",
18c18
<   "code": "rule_not_implemented",        # activate.M2_forbidden
>   "code": "execution_forbidden",
62c62
<   "code": "rule_not_implemented",        # resolve.M1_false
>   "code": "candidate_not_eligible",
66c66
<   "code": "rule_not_implemented",        # resolve.M2_forbidden
>   "code": "execution_forbidden",
```

바뀌지 **않은** 것 (같은 파일 안에서 함께 측정했다):

| 측정 | Before | After |
| --- | --- | --- |
| `activate.M1_false.status` | `condition_false` | `condition_false` |
| `activate.M1_false.missing` | `None` | `None` |
| `activate.M1_false.chain_len` / `deltas` | `0` / `0` | `0` / `0` |
| `activate.M2_forbidden.status` | `forbidden` | `forbidden` |
| `activate.M2_forbidden.missing` | `executable implementation from official script` | 같음 |
| `activate.unknown_rule` | `condition_unknown` · `rule_not_implemented` | **그대로** |
| `activate.unknown_info` | `condition_unknown` · `information_unavailable` | **그대로** |
| `activate.true` | `activated` · `ok` · chain 1 | **그대로** |
| `duel.state_hash` | `5adaf2a4…27af9e` | **같은 해시** |
| `duel.state_hash_after_search` | `5adaf2a4…27af9e` | **같은 해시** |
| `duel.rng_state` / `…_after_search` | `(3, (1864931981, …))` | **같은 상태** |
| `duel.allowed` | `['end_phase']` | 같음 |
| `duel.withheld` | `['activate_card']` | 같음 |
| `duel.withheld_missing` | `['activation-timing (Phase 2-C/2-F)']` | 같음 |
| `duel.special_summon` | 거절 · `rule_not_implemented` | **그대로** (진짜 미구현) |
| `search.candidates` / `scored` / `simulations` | `1` / `1` / `1` | 같음 |
| `search.statuses` | `['supported']` | 같음 |
| `search.ordering_keys` | `[('0','-1','-1000')]` | 같음 |
| `search.chosen` | `end_phase P0` | 같음 |

---

## 8. ValidationResult

**구조 변경 없음.** 필드는 그대로 다섯이다: `validity` · `code` · `reason` ·
`missing_rule` · `notes`.

그리고 **구조적 안전장치가 그대로 일한다.** `missing_rule` 을 받는 생성자는
`ValidationResult.unknown()` **하나뿐**이고 `invalid()` · `valid()` 는 받지 않는다.
M1 이 "확실한 거부" 로 옮겨 갔으므로 그 자리에 규칙 이름이 붙을 길이 애초에 없다 —
`test_01` 이 `missing is None` 을 확인하고, 고의 위반 `V14` 가 거기에 규칙 이름을
억지로 적었을 때 테스트가 잡았다.

바뀐 것은 **`code` 필드에 들어가는 값** 네 자리뿐이다. `validity` 는 네 자리 모두
전과 같다.

---

## 9. GateVerdict

**변경 없음.** M3 를 고치지 않았으므로 gate 가 내는 `(validity, code)` 쌍은 전부
그대로다.

`test_16` 이 트리거 계층을 따로 고정한다 — 트리거 계층에서 `EXECUTION_FORBIDDEN`
을 읽는 자리는 전과 같고, M1·M2 의 수정이 gate 어휘로 **새어 나가지 않았다.**
`engine/trigger.py` · `engine/trigger_chain.py` 의 `git diff` 는 0 줄이다.

---

## 10. SimulationStatus

**enum 은 그대로 5 멤버다** (`test_13` 이 길이를 고정한다). 추가도 제거도 없다.

그러나 **분류는 네 자리에서 바뀐다.** 이것이 이번 수정에서 가장 솔직하게 적어야 할
부분이다.

| code | `_UNKNOWN_CODES` 포함 | `SimulationStatus` |
| --- | --- | --- |
| `RULE_NOT_IMPLEMENTED` | ○ | `UNKNOWN` |
| `INFORMATION_UNAVAILABLE` | ○ | `UNKNOWN` |
| `CANDIDATE_NOT_ELIGIBLE` | ✕ | **`REFUSED`** |
| `EXECUTION_FORBIDDEN` | ✕ | **`REFUSED`** |

즉 M1 · M2 의 네 자리는 **시뮬레이션 분류가 `UNKNOWN` 에서 `REFUSED` 로 바뀐다.**
숨기지 않고 `test_15` 에서 그 사실 자체를 고정했다.

**그런데 이것이 AI 의 결정을 바꾸지 않는다** — 그 까닭은 §12 에서 측정으로 보인다.
그리고 **이 변화는 옳은 방향이다**: 조건이 확실히 거짓이거나 출처가 금지한 수는
"모르겠다" 가 아니라 "두지 않는다" 이기 때문이다.

---

## 11. UNKNOWN_CODES

**`agent/simulation.py` diff = 0.** `_UNKNOWN_CODES` 는 전후로 같은 5 멤버다.

```
CARD_DEFINITION_UNAVAILABLE
COST_NOT_IMPLEMENTED
EFFECT_LIST_UNRELIABLE
INFORMATION_UNAVAILABLE
RULE_NOT_IMPLEMENTED
```

**집합을 건드려서 결과를 맞추지 않았다.** 그것이 가장 하기 쉬운 잘못된 수정이었다
— M1 을 고친 뒤 분류가 바뀌는 것이 싫어서 `CANDIDATE_NOT_ELIGIBLE` 을 이 집합에
넣으면, "모른다" 의 뜻이 통째로 오염된다. `test_14` 가 집합을 원소 단위로
고정하고, 고의 위반 `V11`(끼워 넣기) · `V12`(빼기) 가 둘 다 잡혔다.

---

## 12. AI / Search 영향

**결론: 없다.** 추정이 아니라 두 가지로 보였다.

**(1) 소스 측정 — `UNKNOWN` 과 `REFUSED` 를 가르는 production 코드가 없다.**

`SimulationStatus` 를 비교하는 production 자리는 전부 다음 둘뿐이다.

| 자리 | 비교 | `UNKNOWN` 과 `REFUSED` 를 가르는가 |
| --- | --- | --- |
| `agent/search.py:311` | `result.status is not SimulationStatus.SUPPORTED` | **아니다** — 둘 다 같은 갈래 |
| `agent/simulation.py:85` `is_usable` | `self is SimulationStatus.SUPPORTED` | 아니다. 게다가 **production 호출 0곳** |

그리고 순위를 만드는 `SearchCandidate.ordering_key()` 는 **점수가 없으면**
`(1, 0, 0, canonical)` 을 돌려준다. `UNKNOWN` 도 `REFUSED` 도 `value is None` 이므로
**완전히 같은 키**다.

```python
if self.value is None:
    return (1, 0, 0, self.action.canonical_state())
```

즉 `UNKNOWN` ↔ `REFUSED` 는 **보고용 구분**이고 결정 입력이 아니다. 이것은 3-E-37 이
"48개 중 결정 입력으로 비교되는 코드는 `OK` · `RULE_NOT_IMPLEMENTED` ·
`EXECUTION_FORBIDDEN` 셋뿐" 이라고 측정한 것과 같은 결의 사실이다.

**(2) 실제 탐색 측정 — 후보 · 상태 · 순위 · 선택이 전부 같다.**

seed 11 의 실제 듀얼에서 `SearchPolicy` 를 돌렸다 (§7 표).
후보 수 1 · 점수 매긴 수 1 · 시뮬레이션 1 · 상태 `['supported']` ·
순위 키 `[('0','-1','-1000')]` · 고른 수 `end_phase P0` — **전후 동일**.

측정한 시나리오에서는 M1·M2 자리가 탐색에 아예 올라오지 않는다
(`activate_card` 가 `activation-timing (Phase 2-C/2-F)` 로 보류 중이다).
그래서 **올라왔다면 어떻게 되는지**를 (1) 로 따로 보인 것이다.

---

## 13. Hidden information

**샌 것 없음.**

- 가려진 카드를 묻는 조건(`IsMonster(InstanceId(9999))`)은 전과 같이
  `CONDITION_UNKNOWN` · `INFORMATION_UNAVAILABLE` 이다. **금지로 바뀌지 않았다**
  (`test_19`, §16-3 negative test).
- M2 가 쓰는 `EXECUTION_FORBIDDEN` 은 **출처(provenance)** 에서 나오는 사실이고
  판 위의 가려진 정보와 무관하다. `EffectProvenance` 는 카드 DB 의 출처 메타데이터다.
- 관측은 전과 같이 `GameStateView.from_state(state, viewer=action.actor)` 로
  **행위자 시점**에서 만든다. 이 줄은 건드리지 않았다.
- `test_18` 이 상대 손패가 관측에 들어오지 않는지 직접 확인한다.

---

## 14. RNG

**소비 없음 · 상태 불변.**

| 측정 | Before | After |
| --- | --- | --- |
| `duel.rng_state` (seed 11, 탐색 전) | `(3, (1864931981, 4086898439, 346675919, …))` | **같음** |
| `duel.rng_state_after_search` | 위와 같은 상태 | **같음** |

탐색을 끝까지 돌린 뒤에도 난수원 상태가 **탐색 전과 같다** — 시뮬레이션이 실제 판의
난수를 쓰지 않는다는 기존 성질이 그대로다.

합성 상태(`new_state()`)는 seed 없이 만들어 **난수원이 아예 없다.** 처음에 그것을
RNG 불변의 증거로 쓰려다 틀렸고, 실제 seed 를 가진 듀얼에서 다시 측정했다.

---

## 15. state_hash

**불변.**

| 측정 | Before | After |
| --- | --- | --- |
| `state_hash.before_activate` | `de33c797…56d347` | 같음 |
| `state_hash.after_activate` | `de33c797…56d347` | 같음 |
| `duel.state_hash` | `5adaf2a465ee9f3d7e2b1e229adbb7465202f18e3cd36e4dd947fd162927af9e` | **같은 해시** |
| `duel.state_hash_after_search` | 같은 값 | 같음 |

거절은 판을 건드리지 않는다는 기존 성질이 그대로다 — 거절된 발동의 `deltas` 가 0 이고
체인 길이가 0 이다. `test_18` 이 이 해시를 **문자열 그대로** 박아 두었다. 판이
바뀌면 거기서 깨진다.

---

## 16. 실제 카드 시나리오

§20 이 요구한 세 시나리오를 실제로 돌렸다.

**M1 — 조건이 명백히 `FALSE` 인 효과**

```
activate(state, synthetic(activation=Always(ConditionResult.FALSE)))
→ status  ActivationStatus.CONDITION_FALSE
   code    ValidationCode.CANDIDATE_NOT_ELIGIBLE     ← 기대값
   missing None
   chain   0,  deltas 0
```

해결 계층도 같다: `ResolutionStatus.CONDITION_FALSE` · `CANDIDATE_NOT_ELIGIBLE`.

**M2 — `TEXT_DERIVED` 출처**

```
activate(state, synthetic(provenance=EffectProvenance.text_derived(...)))
→ status  ActivationStatus.FORBIDDEN
   code    ValidationCode.EXECUTION_FORBIDDEN        ← 기대값
   missing "executable implementation from official script"
```

해결 계층: `ResolutionStatus.FORBIDDEN` · `EXECUTION_FORBIDDEN`.

**실제 카드 데이터 위에서도 확인했다.** `tests/engine/test_effect_library.py::
test_a_text_derived_effect_changes_nothing` 은 공식 DB 에서 온 실제 카드 정의를 쓰고,
이 Phase 전에는 "`RULE_NOT_IMPLEMENTED` 가 붙는다 — 알려진 DETAIL" 이라고 적혀
있었다. 이제 `EXECUTION_FORBIDDEN` 을 확인하고, 판이 그대로인지(`state_hash` 동일)를
함께 본다.

**M3 — `event_relation` 이 `INVALID` 인 경우**

```
reachability  production 도달 0 (dormant)
decision      수정하지 않음 — 기존 code 유지
```

§6 의 세 가지 까닭대로다. 지금 잘못된 결과를 내는 production 경로가 **없다.**

---

## 17. 테스트

### 17.1 새 파일

`tests/test_validation_code_minimal_fix.py` — **24개** (요구 최소 20개).
§15 의 A–T 와 §16 의 negative test 6가지를 전부 덮는다.

| 분류 | 테스트 |
| --- | --- |
| A 조건 FALSE → 후보 거부 | `test_01` (발동) · `test_02` (해결) · `test_03` (두 계층 일치) |
| B UNKNOWN 유지 | `test_04` |
| C TRUE 유지 | `test_05` |
| D·E `TEXT_DERIVED` → 금지 / 나머지 유지 | `test_06` · `test_07` |
| F 금지 ≠ 숨은 정보 | `test_08` |
| G·H M3 dormant · 미수정 | `test_09` · `test_10` |
| (범위) dormant resolver 미수정 | `test_11` |
| J 진짜 미구현 유지 | `test_12` |
| T 새 code 없음 | `test_13` |
| K `_UNKNOWN_CODES` 불변 | `test_14` |
| L `SimulationStatus` 분류 | `test_15` |
| M `GateVerdict` 불변 | `test_16` |
| N·O `legal_actions` · 탐색 불변 | `test_17` |
| P·Q `state_hash` · RNG 불변 | `test_18` |
| R hidden information | `test_19` |
| §16 negative 6종 | `test_20` |
| 5 UNKNOWN ≠ FALSE ≠ 허가 | `test_21` |
| 6·7·8 UNKNOWN ≠ 패배 ≠ 0점 | `test_22` |
| S 회귀 | `test_23` |
| §18 diff 모양 | `test_24` |

### 17.2 기존 테스트 수정 — 삭제 0 · skip 추가 0 · assertion 약화 0

수정한 것은 **5개 파일 · 17개 테스트 함수 + 4곳의 모듈 상수**다.
(수정 전 메모에 "19개" 라고 적었는데, AST 로 함수 단위 비교를 해 보니 실제로는
본문 변경 9 + 개명 8 = **17개**였다. 측정한 수로 고쳐 적는다.)

테스트 **개수는 파일마다 전후 동일**하다 — 지우거나 더한 테스트가 없다.

| 파일 | 함수 | 왜 바뀌었나 |
| --- | --- | --- |
| `tests/engine/test_effect_library.py` | `test_a_text_derived_effect_changes_nothing` | **틀린 가정이 아니었다.** 이 테스트는 당시의 사실(`RULE_NOT_IMPLEMENTED`)을 정확히 적고 있었고, 주석에 "알려진 DETAIL" 이라고 **이미 M2 를 지목**해 두었다. 3-E-38 이 그 DETAIL 을 고쳤으므로 기대값을 `EXECUTION_FORBIDDEN` 으로 옮기고, 주석을 "이 Phase 가 고쳤다" 로 다시 썼다. |
| `tests/test_validation_code_consistency.py` | `test_11_the_remaining_invalid_sites_are_the_measured_three` | **3-E-26 의 가정이 틀렸었다.** 당시 보고서는 "확실한 거부를 말하는 코드가 enum 에 없다" 고 적었지만, `CANDIDATE_NOT_ELIGIBLE` 은 **있었고** 같은 파일이 이미 쓰고 있었다. 그 잘못된 전제 위에서 3곳을 고정했던 것을 1곳(`engine/trigger.py`, M3)으로 줄였다. |
| `tests/test_unimplemented_rule_semantics_audit.py` | (모듈 상수) `RULE_NOT_IMPLEMENTED_MENTIONS` 75 → 76 | 사실 기록. 코드 등장이 2 줄고(69→67) 까닭을 적은 주석이 3 늘었다(6→9). 이 상수가 가리키는 요지("등장이 생성의 수십 배다")는 그대로다. |
| `tests/test_rule_not_implemented_code_audit.py` | 상수 `STRING_OCCURRENCES` 75→76 · `PROSE_OCCURRENCES` 6→9 · `CODE_OCCURRENCES` 69→67 · `CONTRACT_VIOLATIONS` 16→13 | **틀린 가정이 아니었다.** 3-E-36 은 당시 사실을 자리마다 정확히 고정했고, **고치면 깨지도록** 일부러 그렇게 설계했다. 그 설계가 의도대로 작동해서 이번 수정이 무엇을 건드렸는지 여기서 먼저 드러났다. |
| 〃 | `test_02` · `test_04` · `test_08` · `test_14` · `test_05`(개명) · `test_10`(개명) · `test_11`(개명) | `test_04` · `test_08` 은 "코드와 규칙 이름은 다른 사실" · "같은 코드가 여러 상태에 붙는다" 를 보이는 데 **조건 거짓**을 예로 썼다. 그 예가 더 이상 해당 코드를 쓰지 않으므로, **같은 사실을 아직 그 코드를 쓰는 자리**(정의 미등록)로 보이도록 바꿨다 — 주장은 그대로고 예만 옮겼다. `test_10`/`test_11` 은 이름 자체가 "효과 계층은 이 코드를 쓰지 않는다" 였는데 이제 **쓴다**. 사실이 바뀌었으므로 이름과 기대를 함께 뒤집었다. |
| `tests/test_validation_code_rejection_semantics_audit.py` | 상수 `CODE_OCCURRENCES` 69→67 · `REJECTION_PRODUCTIONS` 58→54 | 사실 기록. 처음에 56 을 예상했는데 측정값은 **54** 였다 — `_AVAILABILITY_REFUSAL` 의 두 새 값이 **생성(production)이 아니라 튜플 멤버십**으로 세어지기 때문이다(멤버십 1→3). 67 = 54 + 8 + 1 + 3 + 1 로 맞는다. 예상을 측정으로 고쳤다. |
| 〃 | `test_09` · `test_16` · `test_21` · `test_03`(개명) · `test_05`(개명) · `test_06`(개명) · `test_07`(개명) · `test_08`(개명) | 3-E-37 이 측정한 **어긋남 그 자체**를 고정하던 테스트들이다. 어긋남을 고쳤으니 같은 자리가 이제 반대 사실을 말한다. 특히 `test_09` 는 "`EXECUTION_FORBIDDEN` 은 바로 이 경우를 위해 만들어졌는데 **정작 그 경우가 쓰지 않는다**" 였고, 이제 **쓴다**. `test_07` 은 "트리거 계층과 행동 계층이 같은 사실에 다른 코드를 쓴다" 였고, 이제 **같은 코드를 쓴다**. |

모든 수정은 **기대값을 약하게 만들지 않는다** — `assert` 를 지우거나 `in` 으로
느슨하게 바꾼 곳이 없고, 바뀐 사실을 **다시 정확히 고정**했다.

**이 절을 쓰는 동안 내가 적은 수 하나를 고쳤다.** 처음에
`CONTRACT_VIOLATIONS` 주석에 "네 자리를 지웠다 (16 → 12)" 라고 적었는데, 실제
집합을 세어 보니 **16 → 13** 이었다. 네 자리를 고쳤지만 셋만 줄어든다 — 발동
계층의 출처 금지(M2-a)는 `_AVAILABILITY_REFUSAL` **표 안의 튜플**이라 "상태와
짝지은 결과 자리" 로 세어지지 않고, 애초에 그 목록에 없었다. 주석을 측정값으로
고치고 그 까닭을 그 자리에 적었다.

### 17.3 고의 위반 (deliberate violation)

§15 의 테스트가 **정말로 지키는지** 확인하려고, 고친 자리를 되돌리고 범위를 넘고
불변식을 깨는 **16가지**를 하나씩 주입하고, 매번 새 테스트 1개 파일 + 관련 기존
테스트 5개 파일을 돌린 뒤 원복했다.

**16/16 전부 잡혔다.** 조용히 지나간 주입은 **없다.**

| # | 주입한 잘못 | 파일 | 깨진 테스트 수 | 맨 처음 깨진 테스트 |
| --- | --- | --- | --- | --- |
| V01 | M1-a 되돌리기 — 발동 계층 조건 거짓에 다시 `RULE_NOT_IMPLEMENTED` | `engine/activation.py` | **17** | `test_validation_code_minimal_fix.py::test_01_a_false_condition_is_a_candidate_refusal_in_the_activation_layer` |
| V02 | M1-b 되돌리기 — 해결 계층 조건 거짓에 다시 `RULE_NOT_IMPLEMENTED` | `engine/effect/executor.py` | **13** | `test_validation_code_minimal_fix.py::test_02_a_false_condition_is_a_candidate_refusal_in_the_resolution_layer` |
| V03 | M2-a 되돌리기 — 발동 계층 출처 금지에 다시 `RULE_NOT_IMPLEMENTED` | `engine/activation.py` | **10** | `test_validation_code_minimal_fix.py::test_06_a_text_derived_source_is_execution_forbidden_in_both_layers` |
| V04 | M2-b 되돌리기 — 해결 계층 출처 금지에 다시 `RULE_NOT_IMPLEMENTED` | `engine/effect/executor.py` | **14** | `test_validation_code_minimal_fix.py::test_06_a_text_derived_source_is_execution_forbidden_in_both_layers` |
| V05 | 범위 넘기기 — 미검증(`UNVERIFIED`)까지 금지로 | `engine/activation.py` | **5** | `test_validation_code_minimal_fix.py::test_07_the_other_two_availabilities_keep_rule_not_implemented` |
| V06 | 범위 넘기기 — 미등록(`NO_IMPLEMENTATION`)을 후보 거부로 | `engine/activation.py` | **5** | `test_validation_code_minimal_fix.py::test_07_the_other_two_availabilities_keep_rule_not_implemented` |
| V07 | 범위 넘기기 — 해결 계층 미검증까지 금지로 | `engine/effect/executor.py` | **8** | `test_validation_code_minimal_fix.py::test_07_the_other_two_availabilities_keep_rule_not_implemented` |
| V08 | **UNKNOWN 을 FALSE 로 접기** — 모름을 후보 거부로 | `engine/activation.py` | **15** | `test_validation_code_minimal_fix.py::test_04_an_unknown_condition_keeps_its_old_codes` |
| V09 | 모름의 두 까닭 합치기 — `INFORMATION_UNAVAILABLE` → `RULE_NOT_IMPLEMENTED` | `engine/activation.py` | **18** | `test_validation_code_minimal_fix.py::test_04_an_unknown_condition_keeps_its_old_codes` |
| V10 | **새 `ValidationCode` 멤버 추가** (§7 금지) | `engine/validation.py` | **12** | `test_validation_code_minimal_fix.py::test_13_no_new_validation_code_was_added` |
| V11 | `_UNKNOWN_CODES` 에 `CANDIDATE_NOT_ELIGIBLE` 끼워 넣기 | `agent/simulation.py` | **9** | `test_validation_code_minimal_fix.py::test_01_a_false_condition_is_a_candidate_refusal_in_the_activation_layer` |
| V12 | `_UNKNOWN_CODES` 에서 `RULE_NOT_IMPLEMENTED` 빼기 | `agent/simulation.py` | **11** | `test_validation_code_minimal_fix.py::test_14_the_unknown_codes_set_itself_did_not_change` |
| V13 | **M3 를 같이 고치기** (§8 가 금지한 범위 확장) | `engine/trigger.py` | **8** | `test_validation_code_minimal_fix.py::test_10_m3_still_carries_the_old_code_and_that_is_recorded_not_hidden` |
| V14 | 확실한 거부에 없는 규칙 이름 적기 (`missing` 오염) | `engine/activation.py` | **3** | `test_validation_code_minimal_fix.py::test_01_a_false_condition_is_a_candidate_refusal_in_the_activation_layer` |
| V15 | 금지의 `missing` 문구 바꾸기 | `engine/activation.py` | **1** | `test_validation_code_minimal_fix.py::test_06_a_text_derived_source_is_execution_forbidden_in_both_layers` |
| V16 | **판정(`status`)까지 바꾸기** — 조건 거짓을 미구현 상태로 | `engine/activation.py` | **9** | `test_validation_code_minimal_fix.py::test_01_a_false_condition_is_a_candidate_refusal_in_the_activation_layer` |

읽을 점 몇 가지:

- **V01 ~ V04** (고친 것을 되돌리기) 는 각각 10 ~ 17개를 깨뜨린다. 이번 수정이
  한 자리의 문자 하나가 아니라 **여러 테스트가 함께 지키는 사실**이 되었다는 뜻이다.
- **V05 ~ V07** (범위 넘기기) 는 `test_07` 에서 **가장 먼저** 깨진다 — 세 갈래를
  갈라 둔 테스트가 의도대로 "뭉개면 깨지는" 역할을 한다.
- **V08 · V09** (UNKNOWN 을 접기 · 모름의 두 까닭 합치기) 가 15개 · 18개로 가장
  많이 깨뜨린다. 이 Phase 들이 가장 오래 지켜 온 선이 가장 두껍게 보호되어 있다.
- **V13** (M3 를 같이 고치기) 이 잡힌다는 것은 중요하다. **좋아 보이는 수정도
  범위를 넘으면 깨진다** — 이번 Phase 가 M3 를 일부러 남겼다는 사실이 테스트로
  고정되어 있다는 뜻이다.
- **V15** 는 **단 1개**만 깨뜨렸다 (`test_06`). 가장 얇게 지켜지는 자리다 —
  `missing` 문구는 사람이 읽는 설명이고 코드와 따로 흔들릴 수 있다. 그 사실을
  적어 둔다.
- **V16** (`status` 까지 바꾸기) 가 9개를 깨뜨린다. 판정과 이유를 **함께** 고정해
  두었으므로, 이유를 고치는 척하며 판정을 바꾸는 수정은 통과하지 못한다.

주입 전후로 다섯 production 파일의 `md5` 를 비교해 **원복을 확인**했다
(`engine/activation.py` · `engine/effect/executor.py` · `engine/validation.py` ·
`agent/simulation.py` · `engine/trigger.py` 전부 일치).

### 17.4 Full regression

```
$ python -m pytest -q -p no:randomly
3874 passed, 4 skipped in 360.56s (0:06:00)
```

| 항목 | 기준선 (3-E-37 종료 시) | 이번 Phase 종료 시 |
| --- | --- | --- |
| passed | 3850 | **3874** (+24, 새 파일) |
| failed | 0 | **0** |
| skipped | 4 | **4** (증가 없음) |
| 삭제한 테스트 | — | **0** |
| 약화한 assertion | — | **0** |

§19 가 말한 기준선 "3850 passed / 4 skipped" 를 repository 에서 다시 확인했고
그대로였다. 증가분 24 는 새 파일 `tests/test_validation_code_minimal_fix.py` 의
테스트 수와 **정확히** 같다 — 기존 파일의 테스트 수는 하나도 변하지 않았다.

---

## 18. Safety invariants

§17 이 요구한 12개를 전부 다시 검사했다.

| # | 불변식 | 결과 | 지키는 테스트 |
| --- | --- | --- | --- |
| 1 | `CONDITION_FALSE` ≠ `RULE_NOT_IMPLEMENTED` | ○ **이번에 고친 것** | `test_01` `test_02` `test_20` |
| 2 | `TEXT_DERIVED` 금지 ≠ `RULE_NOT_IMPLEMENTED` | ○ **이번에 고친 것** | `test_06` `test_20` |
| 3 | `EXECUTION_FORBIDDEN` 유지 | ○ 멤버 · 뜻 그대로, 이제 실제로 쓰인다 | `test_06` `test_13` |
| 4 | `CANDIDATE_NOT_ELIGIBLE` 유지 | ○ 멤버 · 뜻 그대로 | `test_01` `test_13` |
| 5 | UNKNOWN ≠ FALSE | ○ | `test_04` `test_21` |
| 6 | UNKNOWN ≠ 패배 | ○ | `test_22` |
| 7 | `RULE_NOT_IMPLEMENTED` ≠ 패배 | ○ | `test_22` |
| 8 | `RULE_NOT_IMPLEMENTED` ≠ 0점 | ○ `value is None` 이지 0 이 아니다 | `test_22` |
| 9 | 숨은 정보 ≠ 금지 | ○ | `test_08` `test_19` |
| 10 | `SimulationStatus` 가 임의로 승패를 만들지 않음 | ○ enum 5 멤버 불변, 분류 변화는 §10 에 기록 | `test_13` `test_15` |
| 11 | RNG 소비 없음 | ○ 측정 (§14) | `test_18` |
| 12 | state mutation 없음 | ○ 측정 (§15) | `test_18` |

그리고 §16 의 **여섯 가지 잘못된 변환**이 하나도 없다 (`test_20` 이 한 번에 본다).

| # | 금지된 변환 | 현재 |
| --- | --- | --- |
| 1 | UNKNOWN → `CANDIDATE_NOT_ELIGIBLE` | 없음 |
| 2 | `TEXT_DERIVED` → `RULE_NOT_IMPLEMENTED` | 없음 (고쳤다) |
| 3 | hidden information → `EXECUTION_FORBIDDEN` | 없음 |
| 4 | 진짜 미구현 → `CANDIDATE_NOT_ELIGIBLE` | 없음 |
| 5 | condition FALSE → `RULE_NOT_IMPLEMENTED` | 없음 (고쳤다) |
| 6 | source forbidden → `RULE_NOT_IMPLEMENTED` | 없음 (고쳤다) |

---

## 19. Production diff

```
engine/activation.py        | 31 ++++++++++++++++++++-----------
engine/effect/executor.py   | 11 ++++++++---
```

- **`ValidationCode` enum diff = 0** — `engine/validation.py` 는 한 글자도 바뀌지 않았다.
- `agent/` · `core/` · `analysis/` · `sources/` diff = 0.
- `engine/` 안에서도 `trigger.py` · `trigger_chain.py` · `effect/resolution.py` ·
  `condition.py` 전부 diff = 0.
- **비슷해 보이는 코드를 같이 고치지 않았다.** `RULE_NOT_IMPLEMENTED` 는 여전히
  production 에 67곳 있고, 그중 3-E-36 이 "계약 위반" 으로 세어 둔 자리가 **13곳**
  남아 있다. 맞는 멤버가 enum 에 **없어서** 남긴 것들이다 (구조 오류 · 예외 ·
  응답 거절). 새 멤버를 만들지 않았으므로 지금 고칠 수 없다.

**3-E-37 보고서의 수 하나를 바로잡는다.** 그 보고서는 이번 수정 후
`REJECTION_PRODUCTIONS` 가 56 이 되리라 적었다. 실제 측정값은 **54** 다.
`_AVAILABILITY_REFUSAL` 의 두 새 값이 함수 호출 인자가 아니라 **튜플 멤버십**으로
세어지기 때문이다 (멤버십 1 → 3). 합은 67 = 54 + 8 + 1 + 3 + 1 로 맞는다.

---

## 20. Final Decision

**A. MINIMAL_FIX_COMPLETE**

하나만 고른다. 까닭을 셋으로 적는다.

1. **M1 · M2 수정 완료.** 네 자리 모두 **기존** `ValidationCode` 멤버로 옮겼다.
   새 멤버 0 · 새 status 0 · 새 추상 0 · `ValidationCode` enum diff 0.
2. **M3 는 dormant 로 처리.** production 도달 0 을 AST 로 재측정하고(§6),
   고치지 않았다는 사실을 테스트로 **드러내** 두었다. 숨기지 않았다.
3. **AI / Search 영향이 안전하게 측정되었다.** `state_hash` · RNG ·
   `legal_actions` · 탐색 후보 · 순위 키 · 고른 수가 **전부 동일**하고(§7 · §12),
   `UNKNOWN` ↔ `REFUSED` 를 가르는 production 결정 코드가 **없다**는 것을
   소스에서 확인했다.

**B 가 아닌 까닭.** B(`M3_REQUIRES_FUTURE_ARCHITECTURE`)는 "M3 때문에 별도
architecture phase 가 **필요하다**" 는 판정이다. 그렇게 말하려면 M3 가 지금 무언가를
막고 있어야 한다. 막고 있지 않다 — 도달 0 이다. M3 는 **미해결 과제가 아니라 기록된
dormant 사실**이고, 트리거 파이프라인을 실제로 연결하는 Phase 가 오면 그때 같이
답할 질문이다. 그 Phase 를 지금 요구하지 않는다.

**C 가 아닌 까닭.** C(`AI_SEMANTIC_CHANGE_DETECTED`)는 "Simulation/AI/Search 의
**실제 의미**가 바뀌었다" 는 판정이다. 네 자리의 `SimulationStatus` 분류가
`UNKNOWN` → `REFUSED` 로 바뀐 것은 사실이고 §10 에 적었다. 그러나 그 분류를
**읽고 다르게 행동하는 production 코드가 없다** (§12). 레이블이 바뀌었고 행동은
바뀌지 않았다. "의미가 바뀌었다" 로 적으면 측정보다 센 말이 된다.

**D 가 아닌 까닭.** D(`PRODUCTION_BUG`)는 "잘못된 Gate/Action/Simulation **결과**를
고쳤다" 는 판정이다. 고친 것은 `code` 필드 하나이고, `validity` · `status` ·
허가/거절 자체는 전후 동일하다. 잘못된 **결과**는 없었다 — 잘못된 **이유**가
있었다. 둘을 구별해서 적는 것이 이 Phase 들의 규칙이다.

**E 가 아닌 까닭.** 막힌 것이 없다. 네 자리 모두 기존 코드로 안전하게 표현되고,
측정에 필요한 정보가 전부 repository 안에 있었다. 공식 재정을 새로 조회할 필요도
없었다.

---

## 21. Next Phase Candidate

**하나만 제안한다.**

> **Phase 3-E-39 — `SimulationStatus` / `_UNKNOWN_CODES` semantic audit**
> (§23 의 후보 2번)

까닭:

- 이번 Phase 가 **처음으로** `UNKNOWN` ↔ `REFUSED` 분류를 움직였다 (네 자리, §10).
  움직이고 나서 "그런데 production 은 이 둘을 가르지 않는다" 는 것을 알았다 (§12).
  **쓰이지 않는 구분**이 거기 있다는 뜻이고, 그것이 옳은 설계인지는 아직 묻지 않았다.
- `SimulationStatus.is_usable` 은 **production 호출이 0곳**이다. `ordering_key` 는
  `UNKNOWN` 과 `REFUSED` 에 **같은 키**를 준다. 즉 AI 는 "모른다" 와 "두지 않는다" 를
  **구별하지 않고 똑같이 뒤로 보낸다.** 사람이라면 다르게 다룰 두 가지다.
- 그리고 `_UNKNOWN_CODES` 는 48개 중 5개를 **손으로 고른 집합**이다. 왜 그 5개인지,
  남은 43개 중 `UNKNOWN` 쪽에 있어야 할 것이 없는지는 측정된 적이 없다.

**이번 Phase 에서 그것을 구현하지 않았다.** 다음 Phase 의 범위와 금지 사항은
사용자가 정한다.
