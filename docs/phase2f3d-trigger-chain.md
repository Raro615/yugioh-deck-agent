# Phase 2-F-3-D — Trigger → Chain 최소 통합 계층

기준 커밋: `09dfdf8` (Phase 2-F-3-C)
*(요청서의 `09fdff8` 은 오타로 보이며, 실제 커밋은 `09dfdf8` 이다.)*

```
TimingEvent
    ↓  TriggerCollector           (F-3-A)
    ↓  TriggerEligibilityJudge    (F-3-B)
    ↓  TriggerOrdering            (F-3-C)
    ↓  TriggerChainIntegrator.plan(chain, ordering)
TriggerChainPlan
    ↓  .extend(chain, plan)
새 Chain          ← 해결은 여전히 ChainResolver 의 일
```

---

## 1. 이번 단계의 책임

**잇기만 한다.** 후보를 다시 모으지 않고, 적격성을 다시 판정하지 않고,
순서를 다시 정하지 않는다. 앞 세 계층의 결과를 그대로 받는다.

작업 전 검수에서 확인한 핵심 사실:

| `ChainLink` 가 요구하는 것 | 트리거 계층이 줄 수 있는가 |
|---|---|
| `sequence` | 체인이 정한다 ✓ |
| `actor` | `candidate.controller` ✓ |
| `effect_ref` | `candidate.effect_ref` ✓ |
| `source` | `candidate.source` ✓ |
| `selections` | **줄 수 없다** |
| `payments` | **줄 수 없다** |

이 두 줄이 이번 단계 설계 전체를 결정했다.

---

## 2. TriggerCandidate 와 ChainLink 의 차이

| | 뜻 |
|---|---|
| `TriggerCandidate` | 이 사건 때문에 발동 **후보**가 될 수 있다 |
| `TriggerEligibility` | 지금까지 본 관문을 통과했는가 |
| `ChainLink` | **실제로 발동하기로 결정된** 효과 하나 |

가운데에서 오른쪽으로 가려면 후보가 갖고 있지 않은 정보 — 무엇을 대상으로
골랐는가, 비용으로 무엇을 냈는가 — 가 필요하다.

**없으면 링크를 만들지 않는다.** 빈 선택과 빈 영수증으로 채워 넣으면
대상 없이 해결되는 효과와 비용을 안 낸 효과가 조용히 판에 들어간다.

```python
if definition.requires_target: → NOT_INSERTABLE ("대상 선택 (@primary)")
if definition.has_cost:        → NOT_INSERTABLE ("비용 지불 영수증 (…)")
```

`TriggerChainEntry` 는 `INSERTABLE` 일 때만 `link` 를 갖고, 그 불변식을
생성 단계에서 강제한다 — 못 들어가는 후보에 링크를 만들어 두지 않는다.
있으면 누군가 쓴다.

---

## 3. ELIGIBLE / INELIGIBLE / UNKNOWN / FORBIDDEN

| 적격성 | 통합 판정 | 어디로 |
|---|---|---|
| `ELIGIBLE` + 정보 충분 | `INSERTABLE` | `entries` → 링크 생성 |
| `ELIGIBLE` + 정보 부족 | `NOT_INSERTABLE` | `entries` (`blocked`) |
| `INELIGIBLE` | `NOT_INSERTABLE` | `skipped` |
| `FORBIDDEN` | `NOT_INSERTABLE` | `skipped` |
| `UNKNOWN` | `UNKNOWN` | **`unresolved`** |

`ChainInsertion` 은 세 값뿐이다 (`INSERTABLE` / `NOT_INSERTABLE` /
`UNKNOWN`). 구체적인 이유는 기존 `ValidationCode` 와 `reason` / `notes` 가
말한다 — 새 어휘를 만들지 않았다.

**`UNKNOWN` 을 `NOT_INSERTABLE` 과 합치지 않는다.** 그 항목의 `reason` 에
"트리거가 없다는 뜻이 아닙니다" 가 들어가고, 조건 계층이 남긴 이유가
`notes` 로 그대로 흐른다.

`permits_insertion` 은 `INSERTABLE` 일 때만 참이라, `UNKNOWN` 이 허가로
새어 나가지 못한다.

`blocked` 가 비어 있지 않다는 것은 **"다음 계층이 아직 할 일이 있다"** 는
뜻이지 "트리거가 없다" 가 아니다.

---

## 4. TEXT_DERIVED 실행 경계

출처 금지를 **여기서 다시 확인한다.** F-3-B 의 적격성 판정이 이미
`EXECUTION_AUTHORITY` 관문에서 봤지만, 이 지점이 효과가 실행 경로로 들어가는
**마지막 문**이다.

```python
availability = execution_availability(definition, self._implementations)
FORBIDDEN_SOURCE → NOT_INSERTABLE / EXECUTION_FORBIDDEN   (ADR-004)
그 밖의 비-EXECUTABLE → UNKNOWN                            (ADR-006)
```

손으로 만든 `ELIGIBLE` 판정을 넣어도 `TEXT_DERIVED` 는 링크가 되지 않는지를
테스트가 직접 확인한다. `LUA_VERIFIED` 라도 구현이 등록되어 있지 않으면
`UNKNOWN` 이다 — "검증된 의미" 와 "실행 가능" 은 여전히 다른 질문이다.

---

## 5. EffectRef identity

링크는 `EffectRef(card_id, ordinal)` 를 그대로 옮긴다. `EffectSpec.index`
(Lua 변수명 `"e1"`) 를 쓰지 않으므로, 서로 다른 카드가 같은 변수명을 써도
`card_id` 로 갈린다 (직렬화 결과에 `"e1"` 이 없는지도 확인한다).

**Card Definition 과 Card Instance 를 혼동하지 않는다.** 같은 카드 2장이
필드에 있으면 `effect_ref` 는 하나지만 `source` 가 달라 **링크 2개**가
된다.

`actor` 는 `candidate.controller` 다 — 턴 플레이어가 아니다. 상대가
컨트롤하는 카드의 트리거는 `actor=1` 이 되고, 턴 플레이어와 다르다는 것을
테스트가 확인한다.

---

## 6. Ordering 연결

`ordering.canonical_sequence` 를 **그대로** 쓴다. 다시 정렬하지 않으므로
입력 순서가 결과를 바꿀 수 없다 (F-3-C 가 이미 보장한다).

그리고 그 순서가 규칙이 아니라는 사실을 **잃지 않는다**:
`plan.is_rule_ordered` 는 `ordering.is_rule_ordered`(항상 거짓)를 그대로
받고, `unresolved_rules` (SEGOC · 턴 플레이어 순서 · 강제/임의 우선순위 …)
도 그대로 실린다. `needs_decision` 이 "누군가 더 결정해야 한다" 를 말한다.

**F-3-C 가 남긴 STRUCTURAL-29(사건 하나만 다룸)를 이번 단계에서 고치지
않았다.** 단일 `TimingEvent` 범위만 다룬다.

---

## 7. Chain.push 경계

`Chain.push` 는 `ChainLink` 만 받는다. `TriggerChainPlan` ·
`TriggerChainEntry` · `TriggerEligibility` · `TriggerCandidate` 를 넣으면
**전부 `TypeError`** 이고, 테스트가 넷 다 확인한다.

해결이 시작된 체인에는 아무것도 들어가지 않는다. 직접 `push` 하면
`ChainError` 지만, 통합 계층은 **예외 대신 판정**을 돌려준다.

---

## 8. Mutation boundary

`TriggerChainIntegrator` 는 **`GameState` 를 아예 받지 않는다** —
`engine.state` 를 import 하지도 않는다 (AST 로 확인). 관측과 불변 `Chain`
만 다루므로 판을 바꿀 수단이 없다.

`Chain` 이 불변이므로 `extend()` 는 **새 체인을 돌려줄 뿐** 원래 체인을
고치지 않는다. 계획이 비면 들어온 체인을 그대로 돌려준다.

테스트가 계획·삽입 전후로 `state_hash` · `journal_hash` · 라이프 · 모든
`CardInstance` 의 `(id, zone, controller, owner)` 가 동일한지 확인한다.

---

## 9. 자동 Effect 실행을 하지 않는 이유

"트리거 발생 → 체인에 넣음 → 효과 실행" 을 한 번의 호출로 만들지 않는다.
그 사이에 **우선권과 응답 기회**가 있고, 그 계층이 무엇을 할지는 이 모듈이
정하지 않는다. 자동으로 해결하면 상대가 체인에 응답할 자리가 사라진다.

`ChainResolver` · `EffectExecutor` · `CostPayer` 를 import 하지 않고,
`.resolve` · `.execute` · `.pay` 를 호출하지 않는다 (AST 로 확인).
링크를 쌓은 뒤에도 `resolved_count == 0` 이고 패 장수도 그대로다.

---

## 10. 현재 미구현 영역

`UNRESOLVED_ORDER_RULES` (SEGOC · 턴 플레이어 순서 · 강제/임의 우선순위 ·
같은 플레이어의 선택 순서 · trigger placement) · `UNCHECKED_RULES`
(timing window · 놓친 타이밍 · WHEN/IF · 스펠 스피드 · 턴 1회) ·
대상 선택 · 비용 지불 · 여러 사건의 통합 · 우선권 자동 진행 · ActionExecutor ·
Summon · Battle · Damage · Turn progression · AI.

기존 파일은 **하나도 수정하지 않았다** (`engine/__init__.py` 의 설명 한
항목 제외).

---

## 11. 테스트

`tests/engine/test_trigger_chain.py` — 41개.

| 묶음 | 보는 것 |
|---|---|
| ELIGIBLE → 링크 | 정확히 링크 생성 · 인스턴스 보존 · 새 체인 반환 · 다른 체인 계획 거부 · 번호 이어짐 · 해결 중 체인 |
| 상태 처리 | INELIGIBLE · FORBIDDEN · **UNKNOWN 분리 + 이유 보존** · 승격 차단 · 모든 후보가 한 통에 |
| 실행 권한 | TEXT_DERIVED 분석 가능/승격 불가 · **위조된 ELIGIBLE 도 차단** · 검증됨 ≠ 구현됨 · 정의 없음 |
| 정보 부족 | **대상 필요 → 빈 선택으로 안 채움** · 비용 → 영수증 없음 · 막힘 ≠ 없음 · 불변식 강제 |
| identity | 같은 카드 2장 · **같은 `e1` 충돌 없음** · actor ≠ 턴 플레이어 · 미삽입도 identity 보존 |
| 결정론 | 재정렬 안 함 · 같은 입력 같은 계획 · 미정 규칙 전달 · 평문 직렬화 · **`PYTHONHASHSEED` 3종** |
| Mutation | 판·기록·라이프·인스턴스 불변 · `GameState` 미수용 · 실패 시 무변화 · 불변 계획 · `clone()` 독립 |
| 자동 실행 금지 | **링크를 쌓아도 해결 안 됨** · resolver/executor 미import·미호출 · 후보를 push 불가 · 우선권 미접촉 |
| 여러 · 빈 후보 | 정해진 순서 그대로 · 빈 계획이 예외 아님 · 아무도 안 보는 사건 · **다섯 계층 통합** |

전체 회귀: **1468 passed, 4 skipped** (F-3-C 기준 1427 + 41).
기존 테스트는 **하나도 삭제·수정하지 않았다.**

---

## 12. 발견된 문제

### 🟠 STRUCTURAL
- **STRUCTURAL-31** — `blocked`(대상/비용 미정)를 채워 줄 계층이 아직
  없다. 트리거 효과는 그 둘이 정해지기 전까지 체인에 들어가지 못한다.
- **STRUCTURAL-32** — 실행 권한을 F-3-B 와 여기서 **두 번** 확인한다.
  방어로는 옳지만 판정이 두 곳에 있다.
- **STRUCTURAL-33** — `plan` 이 `base_chain` 에 묶여 있어 체인이 바뀌면
  다시 세워야 한다 (`extend` 가 거부한다).
- 기존 STRUCTURAL-2~30 — 건드리지 않았다.

### 🟡 DETAIL
- `_missing_execution_inputs` 의 코드 선택이 문자열(`"대상" in missing[0]`)에
  의존한다.
- `ChainInsertion` 3값과 `TriggerStatus` 4값의 대응이 다대일이다.
