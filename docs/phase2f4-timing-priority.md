# Phase 2-F-4 — Priority / Timing Integration

기준 커밋: `ab72fa5` (Phase 2-F-3-D)

```
사건 (TimingEvent)
    ↓  TimingCoordinator.open_window(event, priority, chain)
TimingWindow            사건 · 관측자 · 턴 · 페이즈 · 우선권 · 체인
    ↓  collect_triggers    (F-3-A)
    ↓  order_triggers      (F-3-B + F-3-C)
    ↓  build_trigger_plan  (F-3-D)
    ↓  prepare_chain       → 새 Chain
    ↓  check_priority      (F-1)
TimingOutcome           무엇이 검토되었고, 무엇이 아직 정해지지 않았는가
```

---

## 1. 작업 전 검수

여섯 계층이 이미 있고 서로 맞물린다. **재정의한 것이 하나도 없다.**

| 기존 | 이번 단계에서 |
|---|---|
| `PriorityState` · `PriorityResolver` | 그대로 사용, **변경 없음** |
| `TimingPoint` · `TimingEvent` | 그대로 재사용 (새 사건 타입 없음) |
| `TriggerCollector` · `TriggerEligibilityJudge` · `TriggerOrderer` | 통합기를 통해 그대로 호출 |
| `TriggerChainIntegrator` | 수집→적격성→정리→계획→삽입을 이미 엮어 놓았다 |
| `Chain` · `ChainLink` | 불변 그대로 |
| `EventJournal` · `StateDelta` | **손대지 않았다** — 새 Journal/Event 구조 없음 |
| `ValidationResult` · `ValidationCode` | 우선권 확인 결과로 그대로 사용, **새 코드 0개** |

기존 타입으로 표현할 수 없던 것은 하나뿐이었다: **사건 · 관측자 · 턴 ·
우선권 · 체인을 한 스냅숏으로 묶은 것**. 그것만 만들었다.

---

## 2. 책임 분리

| | 답하는 질문 |
|---|---|
| `PriorityResolver` | 누가 우선권을 가지는가 |
| `TriggerCollector` 외 | 어떤 트리거가 후보이고 발동 가능한가 |
| `TriggerChainIntegrator` | 그 후보를 체인에 넣을 준비가 되었는가 |
| `Chain` | 지금 어떤 링크가 쌓여 있는가 |
| `TimingWindow` | 이 사건 뒤에 어떤 판단 창이 열렸는가 |

`TimingCoordinator` 는 **부르기만** 한다. 소스에
`class TriggerEligibilityJudge` · `_judge` · `_bucket` 이 없는지 테스트가
확인한다.

---

## 3. 우선권을 **갱신하지 않고 확인만 한다**

이 단계에서 가장 조심한 지점이다.

"체인에 링크가 추가되었으니 턴 플레이어에게 우선권이 간다" 는 **규칙**이고,
그 규칙은 아직 없다. 지금 만들면 틀린 채로 굳는다. 그래서

- `TimingOutcome.priority` 는 `window.priority` **그 자체**다
  (`is` 비교로 확인하고, 다르면 생성 단계에서 거부한다)
- 대신 `PriorityResolver.may_act` 로 **확인**한다
- 정할 수 없는 것은 `WINDOW_UNRESOLVED_RULES` 에 남긴다

```python
WINDOW_UNRESOLVED_RULES = (
    "체인에 링크가 추가된 뒤 우선권이 누구에게 가는가",
    "이 시점에 응답 창이 열리는가, 열린다면 어떤 종류인가",
    "놓친 타이밍 (missed timing)",
    "동시에 일어난 여러 사건을 하나의 창으로 묶는 규칙",
    "체인이 끝난 뒤 우선권이 어디로 돌아가는가",
)
```

> **요청서 §7 의 "우선권 갱신/확인" 중 확인만 했다.** 갱신하려면 위 첫 줄의
> 규칙이 필요하고, 그것을 지어내지 않는 쪽을 골랐다.

`holder == turn_player` 를 강제하지 않는다 (F-1 설계 유지). 우선권 상태가
판과 어긋나면 `PriorityResolver` 가 `UNKNOWN`(`PRIORITY_STATE_STALE`) 을
돌려주고, `priority_is_actionable` 은 `VALID` 일 때만 참이다.

PASS 처리는 만들지 않았다 — 소스에 `pass_priority` · `advance_priority` ·
`both_passed` 가 없다.

---

## 4. 트리거가 없어도 아무것도 진행되지 않는다

"트리거가 없으니 다음 페이즈로" 같은 처리를 하지 않는다. Turn progression
은 구현 대상이 아니다. 창을 열고 검토한 뒤 그대로 넘긴다.

`TimingOutcome` 에 `advance_phase` · `next_turn` · `resolve` · `execute` 가
없는지도 테스트가 확인한다.

---

## 5. 기존 체인 보존

`open_window` 는 들어온 `Chain` 을 **그대로** 담는다. 비우지 않는다.

- 기존 링크가 있으면 새 링크가 그 **뒤에** 붙는다 (번호도 이어진다)
- 해결이 시작된 체인에는 아무것도 들어가지 않는다 (F-3-D 가 이미 막는다)
- 준비된 체인은 `resolved_count == 0` 이고 **해결되지 않는다**

`Chain` 이 불변이라 원래 체인은 언제나 그대로 남는다.

---

## 6. 모르는 것의 보존

두 종류가 끝까지 살아 온다.

| | 뜻 |
|---|---|
| `TriggerStatus.UNKNOWN` → `plan.unresolved` | 판정할 수 없다 |
| `collection.unchecked` | **볼 수 없어서** 확인하지 못했다 |

`UNKNOWN` 이 `INELIGIBLE` 로도 `FORBIDDEN` 으로도 `FALSE` 로도 바뀌지
않고, 이유(`notes`)가 직렬화 결과까지 그대로 나온다.

`TEXT_DERIVED` 는 후보 분석에는 나타나지만 링크가 되지 않는다 —
`ordering.excluded` 에 `FORBIDDEN` 으로 남고 `plan.skipped` 의 코드는
`EXECUTION_FORBIDDEN` 이다 (ADR-004). 검증된 의미라도 구현이 없으면
`UNKNOWN` 이다 (ADR-006).

---

## 7. 관측 경계

`TimingWindow.viewer` 가 이 창을 만든 관측의 시점을 기록하고, 다른 관측으로
검토하면 **거부한다** — 보이는 것이 다르면 결과가 조용히 어긋나기 때문이다.

관측자가 다르면 `unchecked` 가 실제로 다르다 (`viewer=0` 은 "P1 HAND",
`viewer=1` 은 "P0 HAND"). 가려진 카드는 후보가 되지도, 링크가 되지도,
결과에 나타나지도 않는다.

---

## 8. Mutation boundary

`TimingCoordinator` 는 **`GameState` 를 받지 않는다.** AST 검사로 확인한다.

- import 되지 않는 것: `EffectExecutor` · `CostPayer` · `ChainResolver` ·
  `GameState` · `engine.state` · `engine.payment` · `analysis`
- 호출되지 않는 메서드: `execute` · `_apply` · `pay` · `resolve` ·
  `resolve_top` · `resolve_all` · `move` · `draw` · `change_life` · `push`

검토 전후로 `state_hash` · `journal_hash` · 라이프 · 모든 `CardInstance` 의
`(id, zone, controller, owner)` 가 동일한지 한 테스트가 확인한다.

---

## 9. 구현하지 않은 것

ActionExecutor · 실제 `PlayerAction` 실행 · Summon · Battle · Damage ·
Turn progression · 승패 판정 · AI · 새 Condition/Cost/Effect 엔진 ·
자동 트리거 생성 · 완전한 SEGOC · 완전한 WHEN/IF · 완전한 강제/임의 판정 ·
Spell Speed · 게임 루프 · PASS 진행 · 체인 해결 · 우선권 갱신.

`WINDOW_UNRESOLVED_RULES` 5개 + 앞 계층의 미정 규칙이 모두
`TimingOutcome.unresolved_rules` 에 실려 나간다.

---

## 10. 테스트

`tests/engine/test_timing_priority.py` — 45개.

| 묶음 | 보는 것 |
|---|---|
| A. 사건 → 창 | 5종 사건 전부 · 턴 문맥 읽기 · 판 미보유 · 잘못된 입력 · raw `GameState` 거부 |
| B. 트리거 없음 | 판·기록·체인 불변 · **진행 없음** · 아무도 안 보는 사건 |
| C. ELIGIBLE | 계층별 결과 · identity 보존 · **단계별 개별 호출** · 판정 미재구현 |
| D. UNKNOWN | INELIGIBLE 로 안 바뀜 · 이유 직렬화 · **`unchecked` 보존** · 구현 없음 |
| E. FORBIDDEN | `TEXT_DERIVED` 링크 불가 · 조건 거짓 · 비용 영수증 없음 |
| F. 우선권 | **holder ≠ turn player 허용** · **갱신 안 함** · 파생 필드 · 닫힘 · **어긋남 → UNKNOWN** · VALID 만 허가 · PASS 미구현 |
| G. 가려진 정보 | **두 관측자가 다른 결과** · 가려진 카드 미노출 · 다른 관측 창 거부 |
| H. Mutation | 전체 검토가 판 미접촉 · **AST 실행 경로 차단** · 불변 · `clone()` 독립 |
| I. 체인 보존 | **기존 체인 미초기화** · 해결 중 체인 · 준비된 체인 미해결 |
| J. 결정론 | 같은 입력 같은 결과 · **미정 규칙 전달** · 평문 직렬화 · **`PYTHONHASHSEED` 0/1/12345** · 정해진 순서 유지 |

전체 회귀: **1513 passed, 4 skipped** (F-3-D 기준 1468 + 45).
기존 테스트는 **하나도 삭제·수정하지 않았다.**

---

## 11. FINAL_AUDIT_TODO 추가분

### 🟠 STRUCTURAL
- **STRUCTURAL-34** — 우선권 갱신이 비어 있다. 체인에 링크가 들어가도
  누구 차례가 되는지 아무도 정하지 않는다. 다음 단계가 채워야 한다.
- **STRUCTURAL-35** — `TimingWindow` 는 사건 **하나**만 담는다
  (STRUCTURAL-29 와 같은 뿌리). 동시 사건을 한 창으로 묶는 규칙이 없다.
- **STRUCTURAL-36** — `TimingOutcome.chain` 은 준비된 체인일 뿐, 그것을
  실제 게임 상태로 채택하는 주체가 없다.

### 🟡 DETAIL
- `check_priority` 는 쥔 사람이 없으면 턴 플레이어를 기준으로 묻는다 —
  답("열린 창이 없다")은 맞지만 기준 선택이 임의적이다.
- `unresolved_rules` 가 두 계층의 문자열을 단순히 이어 붙인다
  (STRUCTURAL-24 와 같은 결).
