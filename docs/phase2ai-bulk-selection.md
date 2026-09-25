# Phase 2-AI — Effect Execution Integration & Real Card Coverage

기준 커밋: `756983c` (Phase 2-AH) · 2821 passed / 4 skipped
→ 이번 단계: **2847 passed / 4 skipped**

```
Effect
  └ @primary = 패 전부                      TargetRequirement.ALL   ← 2-AI
  ├ 0번  return_to_deck(@primary)  ─┐
  ├ 1번  shuffle(DECK)              │ OperationResult(0).attempted
  └ 2번  draw(ResultRef(0, ─────────┘
              ATTEMPTED_COUNT))
```

한 줄 목표: **2-AD ~ 2-AH 의 사슬을 실제 카드 하나에 태운다.**

> 요청서는 §5 중간에서 잘려 들어왔다 (§0 ~ §5 까지 받았다). §6 이후의
> 지시와 완료 보고서 형식을 보지 못했으므로, 이 문서는 앞 단계들이 쓰던
> 형식을 그대로 따른다. 받은 범위 — §0 역할 · §1 Severity · §2 절대 하지
> 말 것 · §3 2-AH 기반 · §4 Repository Audit · §5 목표 흐름 — 은 전부
> 다뤘다.

---

## 1. §4 Repository Audit — 코딩 전에 한 조사

### A. 실제 Effect Execution pipeline

우회로는 없다. 실제 카드가 지나는 길은 하나다.

```
PlayerAction.activate_effect
  → EffectActivator.activate            engine/activation.py:389
      권한(authorization) → 발동 조건 → 비용 → 대상 검사
      └ 대상 검사: TargetResolver.validate                (2-N)
  → Chain / ChainLink                                      (2-F-2)
  → ChainResolver.resolve_top           engine/chain.py:557
  → EffectExecutor.execute              engine/effect/executor.py:420
      ├ _plan(state, …)                 executor.py:485    판을 읽기만 한다
      │    board = state.project()                         (2-AH)
      │    for index, operation:
      │        _check_requirements  ← ExecutionValues       (2-AH)
      │        _check_guards        ← board · values        (2-AG)
      │        _plan_operation      → _Step
      │        values = values.with_result(step.result(index))
      │        _apply(board, step)      투영에 반영
      └ for step: _apply(state, step)   진짜 판
  → StateDelta → EventJournal → ObservedEvent → TimingEvent
```

핵심은 **plan/apply 경계**다. 계획이 하나라도 걸리면 `EffectResult` 가
돌아가고 그때 판은 한 글자도 바뀌지 않았다.

### B. Phase 2-AH 구조물의 실제 사용 여부 — **가장 큰 발견**

§4-B 가 시킨 대로 "테스트에서만 존재하는가" 를 쟀다. 결과:

| 계층 | 등재 카드 사용 (2-AI 전) | synthetic 테스트 |
|---|---:|---|
| `TargetRequirement.RANDOM` (2-AA·AB) | **2장** (73148972 · 69091732) | 있음 |
| `SelectionCount` DERIVED / DECLARED (2-AC) | **0장** | 있음 |
| `declarations` / `DeclaredNumber` (2-AD) | **0장** | 있음 |
| `ResultRef` / `FROM_RESULT` (2-AD·AE) | **0장** | 있음 |
| `Partial.AS_MANY_AS_POSSIBLE` (2-AF) | **0장** | 있음 |
| `OperationGuard` (2-AG) | **0장** | 있음 |
| `OperationRequirement` (2-AH) | **0장** | 있음 |

측정 방법은 그대로 다시 돌릴 수 있다 —
`EFFECT_LIBRARY` 의 각 `definition` 에서 `guards` · `requirements` ·
`declarations` 의 길이와 각 `SelectionCount.kind` 를 센다. 2-AI 전의
모든 항목이 `0` 이었다.

**이 격차가 이번 단계의 실제 동기다.** 2-AC ~ 2-AH 는 여섯 단계 연속으로
"실제 카드 0장 등재" 였고, 그 사실을 각 단계의 census 테스트가 정직하게
들고 있었다. 계층은 정확했지만 아무 카드도 지나가지 않았다.

### C. 실제 카드 corpus 의 구조 분류 (§4-C — 카드 이름이 아니라 **효과
구조** 기준)

스크립트가 있는 카드 **12,702장**을 스크립트의 **모양**으로 나눴다.
한 카드가 여러 칸에 걸릴 수 있으므로 합계는 총수를 넘는다.

| # | 구조 | 스크립트 표지 | 장수 | 엔진의 자리 |
|---|---|---|---:|---|
| 1 | 고르는 것이 없다 | 아래 어느 표지도 없음 | **3,252** | `TargetRequirement.NONE` — 이미 된다 |
| 2 | 고른다 | `SelectMatchingCard` · `SelectTarget` · `:Select` | **8,363** | `TARGETING` / `CHOOSING` — 이미 된다 |
| 3 | **해당하는 것 전부** | `Get(Field|Matching)Group` 을 통째로 넘김 | **3,015** | **없었다 → 2-AI 가 `ALL` 추가** |
| 4 | 무작위 | `RandomSelect` 계열 | **141** | `RANDOM` (2-AB) |
| 5 | 앞선 결과를 뒤가 읽는다 | `GetOperatedGroup` · `local ct=Duel.…` | **408** | `ResultRef` (2-AD) — **이번에 처음 실제 사용** |
| 6 | 플레이어가 수/이름을 선언한다 | `Announce(Number|Level|Card|…)` | **148** | `DeclaredNumber` (2-AD) — 아직 0장 |

3번 중에서 **그룹을 실제로 이동시키는** 것만 좁히면 **1,156장**이다
(`Destroy` 533 · `SendtoGrave` 223 · `SendtoHand` 214 · `Remove` 181 ·
`SendtoDeck` 115 · `Release` 91). 종류별로는 몬스터 692 · 마법 247 ·
함정 217 — **어느 한 종류의 버릇이 아니다.** 그중 필터조차 없는
(`GetFieldGroup` = "존에 있는 것 전부") 것이 **176장**이고 리로드가 그
하나다.

이 수는 `tests/engine/test_bulk_selection.py::measure_bulk_corpus` 가
**테스트 안에서 다시 잰다.** 숫자가 문서에만 있으면 썩는다.

---

## 2. 무엇을 더했는가 — `TargetRequirement.ALL` 하나

§2 는 "이 카드 하나를 처리하기 위해 엔진 구조를 바꾸는 것" 을 금지한다.
그래서 먼저 **구조적 문제인지** 확인했다.

### 기존 요구로 적을 수 있는가?

"패를 전부 덱으로" 를 `CHOOSING` 으로 적으려면:

```python
ChoiceSpec(source=손패, minimum=?, maximum=?)
```

`?` 에 들어갈 수 있는 것은 **지금 후보 수**뿐이다. 그러면

- 명세가 판마다 달라져야 하고,
- 판이 바뀌는 순간 명세가 거짓이 되며,
- `EffectDefinition` 이 불변이라는 성질과도 어긋난다.

`SelectionCount.derived(ZoneCountTerm(...))` (2-AC) 로 장수를 판에서
끌어오는 길도 있다. 그래도 **고르는 사람 칸이 남는다** — "컨트롤러가
자기 패 3장 중 3장을 고른다" 가 되고, 이 카드에는 선택이 없다. 고를 것이
없는 일을 "후보 전부를 고르는 일" 로 적으면 나중에 `CHOOSING` 과 구별이
안 된다.

**진짜 구조 문제라고 판단했다.** 그리고 최소한만 더했다.

```python
class TargetRequirement(str, Enum):
    NONE / TARGETING / CHOOSING / ALL / RANDOM      # ALL 하나 추가

@dataclass(frozen=True, slots=True)
class AllMatchingSpec:
    source: CandidateSource          # 칸이 이것 하나뿐이다
```

**`count` 칸도 `chooser` 칸도 두지 않았다.** 둘 다 **없는 것이 사실**이고,
없는 칸이 곧 그 주장이다. 전부는 수가 아니라 **범위**다.

### `ALL` 과 `RANDOM` 이 같이 가는 자리

| | `RANDOM` | `ALL` |
|---|---|---|
| 아무도 고르지 않는다 | ✔ | ✔ |
| 밖에서 고른 결과를 받는다 | ✘ | ✘ |
| 발동 시점에 정한다 | ✘ (해결 중) | ✘ (해결 중) |
| 후보를 세는 눈 | 자리마다 그 주인 | 자리마다 그 주인 |
| `looked_at_zones()` | 비어 있다 | 비어 있다 |
| `is_pending` | 언제나 거짓 | 언제나 거짓 |
| 장수 | 있다 (`SelectionCount`) | **없다** |
| 난수를 쓴다 | ✔ | ✘ |

그래서 코드에서도 같은 자리에서 갈라진다.

```python
# engine/activation.py — 발동 시점에 정하지 않고, 밖의 선택도 받지 않는다
if binding.spec.is_random or binding.spec.is_bulk:
    ...

# engine/effect/executor.py — 후보를 권위 있게 세고 다시 판정하지 않는다
if spec is not None and (spec.is_random or spec.is_bulk):
    ...
```

`TargetResolver` 를 태우지 않는 것도 같은 이유다. 저쪽은
`choice.minimum` 을 읽는데 두 명세 모두 그 칸이 없다. (처음 시험을 돌릴
때 `AttributeError: 'AllMatchingSpec' object has no attribute 'minimum'`
로 바로 드러났다 — 활성화 쪽 분기를 `is_random` 만으로 두었기 때문이다.)

### 0장은 실패가 아니다

```python
def _demands_a_card(spec) -> bool:
    if getattr(spec, "is_bulk", False):
        return False
```

필드에 몬스터가 없을 때 "전부 파괴" 는 **실패가 아니라 할 일이 없는
것**이다. 막아야 하는 카드라면 그것은 **발동 조건**이 할 일이다 —
리로드의 `ZoneCountAtLeast(CONTROLLER, HAND, 1)` 이 스크립트의
`if #g==0 then return end` 자리를 대신한다.

---

## 3. 등재한 실제 카드 — 리로드 (22589918)

```
공식 텍스트: 자신의 패를 전부 덱에 넣고 셔플한다.
             그 후, 덱에 넣은 매수만큼의 카드를 드로우한다.
```

```lua
-- c22589918.lua
function s.activate(e,tp,eg,ep,ev,re,r,rp)
    local p=Duel.GetChainInfo(0,CHAININFO_TARGET_PLAYER)
    local g=Duel.GetFieldGroup(p,LOCATION_HAND,0)
    if #g==0 then return end
    Duel.SendtoDeck(g,nil,SEQ_DECKSHUFFLE,REASON_EFFECT)
    Duel.ShuffleDeck(p)
    Duel.BreakEffect()
    Duel.Draw(p,#g,REASON_EFFECT)
end
```

| 스크립트 | 정의 |
|---|---|
| `Duel.GetFieldGroup(p,LOCATION_HAND,0)` | `TargetSpec.all_matching(AllMatchingSpec(HAND, CONTROLLER))` |
| `Duel.SendtoDeck(g,…)` | 0번 `CardOperation.return_to_deck(@primary)` |
| `Duel.ShuffleDeck(p)` | 1번 `ShuffleOperation(DECK, CONTROLLER)` |
| `Duel.Draw(p,#g,…)` | 2번 `DrawOperation(SelectionCount.from_result(ResultRef(0, ATTEMPTED_COUNT)))` |
| `if #g==0 then return end` | `activation=ZoneCountAtLeast(CONTROLLER, HAND, 1)` |

### `ATTEMPTED_COUNT` 인 이유 — 그리고 텍스트와의 차이

`g` 는 **패 전체 그룹**이므로 `#g` 는 실제로 덱에 들어간 수가 아니라
**넣으려 한 수**다. 그래서 `AFFECTED_COUNT` 가 아니라
`ATTEMPTED_COUNT` 다 — 2-AF 가 둘을 가른 이유가 여기서 값을 한다.

**공식 한국어 텍스트는 "덱에 넣은 매수만큼" 이라 `AFFECTED_COUNT` 쪽으로
읽힌다.** 이 정의의 출처는 `EffectProvenance.official_lua` 이므로
**스크립트를 따랐고**, 차이는 라이브러리 주석과 테스트 docstring 에
적어 두었다. 텍스트를 해석해서 스크립트를 고치는 일은 하지 않았다.
어느 쪽이 맞는가는 공식 재정(`https://www.db.yugioh-card.com/yugiohdb/`)
이 답할 일이고 **아직 확인하지 않았다.** 지금 이 정의에서 두 수는 같다
(필터가 `nil` 이라 관문이 없다).

### 옮기지 못한 것

- `Card.IsAbleToDeck` — "덱으로 되돌릴 수 있는가" 를 판정할 계층이 없다.
  발동 조건은 `ZoneCountAtLeast` 로만 옮겼고, 조작 쪽에는 관문을
  **선언하지 않았다** (Phase 2-X: 관문은 카드가 적어 둔 것만 옮긴다.
  스크립트의 필터가 `nil` 이다).
- `Duel.BreakEffect()` — 체인 처리의 마디이고 그 계층이 없다.
- `Duel.IsPlayerCanDraw(tp)` — "이 플레이어가 드로우할 수 있는가" 를
  판정할 계층이 없다.

### 시험 중에 사실 하나를 잘못 적었다가 고쳤다

`test_g_a_short_deck_stops_before_the_board_moves` 를 먼저 썼다가
**틀렸다는 것을 실행이 알려 주었다.** 이 카드는 덱이 0장이어도 멈추지
않는다 — 2번이 뽑는 수는 `ResultRef(0, ATTEMPTED)` 이고 0번이 **그
수만큼을 덱에 넣은** 뒤이므로, 뽑기 직전의 덱은 언제나 그 수 이상이다.
시험을 사실 쪽으로 바꾸고(`test_g_this_card_can_never_run_the_deck_out`)
이유를 docstring 에 적었다.

---

## 4. §5 목표 흐름의 실제 실행

```
패 3장 → 0번이 3장을 덱으로 → OperationResult(0).attempted == 3
       → ResultRef(0, ATTEMPTED) → 2번이 3장 드로우
```

`test_f_the_number_drawn_follows_the_hand_not_the_definition` 이 패 1 ·
2 · 5장으로 돌린다. **정의는 그대로이고 뽑는 수만 달라진다.** 드로우 수는
정의 어디에도 적혀 있지 않다.

`EFFECT_LIBRARY` 전체에서 `CountKind.FROM_RESULT` 를 쓰는 조작은
`(RELOAD, 2)` 하나이고, `is_bulk` 대상을 쓰는 카드도 `RELOAD` 하나다 —
테스트가 그것을 단언한다.

---

## 5. 기존 테스트 수정 (삭제 0건, 수정 7건)

전부 **census(장부) 테스트**다. 코드가 틀려서가 아니라 **세는 대상이
늘어서** 깨졌다 — 늘어나면 깨지도록 만들어 둔 것이 그 테스트들의 일이다.

| 파일 | 테스트 | 왜 바뀌었는가 |
|---|---|---|
| `test_real_card_execution.py` | `…is_exactly_fifteen_real_cards` → `…sixteen…` | "지금 열다섯 장" 이 **그때의 사실**이었고 열여섯 번째가 등재됐다 |
| `test_real_card_execution.py` | `…eleven_real_effect_refs…` → `…twelve…` | 같은 이유 |
| `test_real_card_execution.py` | `…operation_coverage_by_real_cards` | `RETURN_TO_DECK` 가 **B(synthetic 전용) → A(실제 카드)** 로 갔다. 억지로 옮긴 것이 아니라 리로드가 실제로 쓴다. `SHUFFLE` 도 들어왔다 |
| `test_operation_integration.py` | `…no_real_card_uses_move_or_special_summon_yet` | 종류 집합만 넓혔다. **요점(MOVE·특수소환에는 아직 실제 카드가 없다)은 그대로** — 리로드는 둘 다 쓰지 않는다 |
| `test_conditional_flow.py` | `test_q_…` → `test_q_phase_2ag_registered_no_real_card_and_none_uses_a_guard` | 한 숫자가 **두 가지를 묶고** 있었다: (1) 2-AG 가 0장 등재 (2) 등재 카드 중 guard 사용 0. (1)은 이름으로 옮기고 숫자는 장부로 16, 진짜 단언인 (2)는 그대로 |
| `test_deferred_resolution.py` | `test_t_…` → `test_t_phase_2ah_…` | 같은 모양. 2-AH 가 0장 등재했다는 사실은 여전히 참이고 바뀐 것은 **다음 Phase** 다 |
| `test_partial_outcome.py` | `test_u_…` → `test_u_phase_2af_…` | 같은 모양. 리로드는 "가능한 만큼" 카드가 **아니므로** `Partial` 단언은 손대지 않았다 |

**어느 테스트의 단언도 약해지지 않았다.** 이름과 숫자가 사실을 따라갔고,
2-AG·AH·AF 각 단계가 "0장 등재" 였다는 기록은 이름 안에 남았다.

---

## 6. 새 테스트 — `tests/engine/test_bulk_selection.py` (26개)

| 절 | 무엇을 보는가 |
|---|---|
| A (2) | corpus 측정을 **테스트 안에서 다시 잰다** — 1,156장 · 176장 · 종류 분포 |
| B (4) | `AllMatchingSpec` 에 `count` 도 `chooser` 도 없다 · 아무도 들여다보지 않는다 |
| C (5) | `ALL` 은 pending 이 없다 · 요구와 명세가 어긋나면 만들어지지 않는다 · `RANDOM` 과 다르다 |
| D (2) | 밖에서 고른 결과를 넣으면 거절하고, 판은 그대로다 |
| E (4) | 리로드 등재 상태 · 옮기지 못한 것이 provenance 에 적혀 있다 · `ATTEMPTED_COUNT` |
| F (5) | **실제 실행** — 패 전부가 덱으로, 되돌린 만큼 드로우, 상대 패는 그대로 |
| G (2) | 패 0장은 발동 조건이 막는다 · 덱이 0장이어도 멈추지 않는다 |
| H (1) | 같은 씨앗이면 같은 판 (셔플이 끼어 있어도) |

F 와 G 는 `@pytest.mark.real_card` 이고, **기존 경로를 우회하지 않는다** —
`EffectActivator` → `Chain` → `ChainResolver` → `EffectExecutor` 를 그대로
지난다.

---

## 7. TODO

- **STRUCTURAL-10 — 부분 해결.** "존 전체 · 그룹 전체" 를 **적을 수
  있게** 됐고 실제 카드 한 장이 돈다. 남은 1,155장 중 대부분은 파괴
  판정기(ADR-006)나 존별 관문이 없어 여전히 실행되지 않는다. 적을 수
  있다는 것과 실행할 수 있다는 것은 다른 말이다.
- **STRUCTURAL-96 (신규 · 🟡)** — **공식 텍스트와 스크립트가 갈리는
  자리를 기록할 곳이 없다.** 리로드의 `#g` 대 "덱에 넣은 매수" 가 그
  예다. 지금은 주석과 docstring 에 적어 두었지만, 그런 차이가 쌓이면
  `EffectProvenance` 옆에 자리가 필요하다. 공식 재정을 확인하기 전에는
  어느 쪽이 맞는지도 모른다.
- **STRUCTURAL-95 · 94(해결) · 93 · 90 · 83 · 86 · 87 — 그대로 둔다.**
- 71 · 74 · 75 · 76 · 77 · 78 — **하나도 건드리지 않았다.**
- `DeclaredNumber` (2-AD) 는 여전히 **실제 카드 0장**이다. corpus 에
  148장이 있다 (`Duel.Announce…`).
- `Partial.AS_MANY_AS_POSSIBLE` (2-AF) · `OperationGuard` (2-AG) ·
  `OperationRequirement` (2-AH) 도 **실제 카드 0장**이다.

---

## 8. 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 0 신규 (10 은 부분 해결) | |
| 🟡 DETAIL | 1 신규 | 96 (텍스트와 스크립트가 갈리는 자리) |
| 🟢 COSMETIC | 0 신규 | |

---

## 9. 이번에 하지 않은 것 (§2)

새 Graph Engine · 새 EventBus · 범용 수식 언어 · Promise/Future 계층 ·
Effect Interpreter 재작성 · 실행 우회로 · **카드 이름 hardcode** ·
Executor 안의 AI 로직 · 모든 카드 한꺼번에 지원 · 테스트 삭제 ·
공식 카드명/텍스트 수동 번역 · 비공식 출처 참조 ·
`scripts/fetch_ocg_rulings.py --all`.

등재는 **한 장**이다. 한 장을 위해 구조를 바꾼 것이 아니라는 근거는 §1-C
의 1,156장이고, 그 수는 테스트가 다시 잰다.

**다음 Phase 는 시작하지 않았다.**
