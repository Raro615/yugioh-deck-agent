# Phase 6-B — 게임 엔진 이벤트 기록 계층 연결

- 기준 커밋: `242fc30` (Phase 6-A 조사·설계)
- 작업 브랜치: `claude/pensive-goodall-te1egy`
- 범위: **이벤트 기록의 최소 연결.** 트리거 실행·콤보 플래너·`/combo` 과대
  판정·STRUCTURAL-77 은 건드리지 않았다 (§9).

---

## 0. Phase 6-A 진술의 재검증 결과 (§3-9)

세 진술을 코드로 다시 확인했다. **두 개는 맞았고 하나는 틀렸다.**

| 6-A 의 진술 | 재검증 |
|---|---|
| "`Duel` 에 `EventJournal` 이 없다" | ✅ 맞다. 칸 자체가 없었다 |
| "`duel_resolver()` 에서 `build_executor()` 에 journal 이 전달되지 않는다" | ✅ 맞다. `spell_activation.py:417` 이 인자 없이 불렀다 |
| "`_resolve_chain()` 에서 `resolution.deltas` 가 이벤트 기록으로 연결되지 않는다" | 🔴 **틀렸다 — 결함이 아니다.** 아래 §2 |

### 🔴 `_resolve_chain` 이 `resolution.deltas` 를 읽지 않는 것은 **옳다**

`EffectExecutor.execute()` 가 **판을 바꾼 직후, 그 자리에서** 기록한다
(`executor.py:518`):

```python
if self._journal is not None and result.deltas:
    self._journal.record(effect_ref=…, actor=…, applied=…, deltas=…, source=…)
```

그러므로 `_resolve_chain` 이 같은 deltas 를 다시 적으면 **같은 변화가 두 번
기록된다** — §5-C 가 금지한 바로 그 중복이다. 6-A 가 "연결되지 않았다" 를
"연결해야 한다" 로 읽히게 적었고, 그것이 부정확했다.

---

## 1. 변경 전 실제 이벤트 기록 경로

기록을 **쓸 수 있는** 자리는 처음부터 둘이었고, 둘 다 같은 모양이었다:

```
EffectExecutor.__init__(lookup, journal=None)   ← Phase 2-D-3
    execute(): 판 변경 → EffectResult(RESOLVED, deltas=…)
               → if journal and result.deltas: journal.record(...)

CostPayer.__init__(journal=None)                ← Phase 2-E
    pay(): 판 변경 → if journal and result.deltas: journal.record_payment(...)
```

그런데 듀얼이 쓰는 세 팩토리가 **journal 을 한 번도 넘기지 않았다**:

| 자리 | 변경 전 | 결과 |
|---|---|---|
| `duel_resolver()` | `ChainResolver(build_executor(), …)` | 효과 실행기의 `_journal is None` |
| `duel_activator()` | `EffectActivator(defs, impls)` → `CostPayer()` 기본 생성 | 비용 지불기의 `_journal is None` |
| `duel_executor()` | `ActionExecutor()` | **애초에 `journal` 인자가 없었다** |

그리고 `Duel` 에는 journal 칸이 없었으므로 **공유할 객체 자체가 존재하지
않았다.**

---

## 2. 연결을 막고 있던 정확한 원인

원인은 **셋**이고, 증상 하나가 아니다.

1. **공유할 journal 객체가 없었다.** `Duel` 의 칸이 `state` · `priority` ·
   `chain` · `step` · `first_player` · `_executor` · `_activator` ·
   `_resolver` · `_placement` · `pending_spells` 뿐이었다.
2. **팩토리가 journal 을 넘기지 않았다** (위 표). 인자는 2-D-3 부터 있었다 —
   **쓰지 않은 것**이 끊어진 자리였다.
3. 🔴 **비체인 행동에는 기록할 사건 종류가 없었다.** `EventKind` 가
   `EFFECT` · `COST_PAYMENT` 둘이고, 일반 소환은 **그 둘 다 아니다.**

그리고 **연결하려는 순간 드러난 네 번째 문제**가 있었다:

4. 🔴 **`engine/duel.py` 는 `engine.effect` 를 import 할 수 없다.**
   `tests/engine/test_duel_loop.py::test_e_the_duel_makes_no_rules_of_its_own`
   이 AST 로 고정한다. `EventJournal` 은 `engine/effect/journal.py` 에
   살므로, "duel 이 journal 을 만든다" 는 가장 쉬운 방법이 **그 불변식을
   깨뜨린다.**

---

## 3. 채택한 최소 연결 방식과 대안 비교

### 채택: journal 하나를 **팩토리가 만들어** 네 writer 에게 나눠 준다

```
engine/spell_activation.py
    duel_components(journal=None) -> dict
        journal is None  → 새 EventJournal 을 만든다
        journal is False → 기록하지 않는다 (사본용)
        그 밖            → 준 것을 쓴다
    returns {"journal", "_executor", "_activator", "_resolver", "_placement"}
            ← 다섯 값이 **같은 journal 객체**를 공유한다

engine/duel.py
    journal: object | None = None        ← 🔴 주석이 느슨한 것은 의도다
    Duel.start(..., journal=None):  cls(..., **duel_components(journal=journal))
```

`Duel` 은 journal 을 **값으로만** 들고 있고 만들지도 적지도 않는다 —
`record_action(` · `record_payment(` · `.record(` 가 `duel.py` 에 **0회**
(`test_a_the_duel_module_still_imports_no_effect_layer` 가 고정).

### 네 writer 와 **기록 시점**

| writer | 적는 종류 | 시점 | 가드 |
|---|---|---|---|
| `ActionExecutor.execute` | `ACTION` | `ActionStatus.EXECUTED` 결과를 **만든 뒤** | `journal is not None and executed.deltas` |
| `NormalSpellPlacement.place`/`reveal`/`_move_back` | `ACTION` | `state.move` 가 **끝난 뒤** | `journal is None → return` |
| `CostPayer.pay` | `COST_PAYMENT` | 판 변경 뒤 (기존 그대로) | `journal is not None and result.deltas` |
| `EffectExecutor.execute` | `EFFECT` | 판 변경 뒤 (기존 그대로) | `journal is not None and result.deltas` |

🔴 **계획을 완료로 오인할 자리가 구조적으로 없다** (§5-B).
`ActionExecution.__post_init__` 이 이미 못박는다:

```python
if self.status is not ActionStatus.EXECUTED and self.deltas:
    raise ValueError("실행되지 않은 행위는 판을 바꾸지 않습니다.")
```

기록 줄에 닿은 deltas 는 **정의상** 적용이 끝난 변화다. 예외 경로
(`EXECUTION_ERROR`)는 그 앞에서 돌아가고 deltas 를 돌려주지 않는다 —
"반쪽짜리 기록은 없는 것보다 나쁘다" 는 기존 주석 그대로다.

### 검토했고 **버린** 대안

| 대안 | 왜 버렸나 |
|---|---|
| **A. `_resolve_chain` 에서 `resolution.deltas` 를 읽어 적는다** (6-A 가 암시한 방향) | 🔴 `EffectExecutor` 가 이미 같은 deltas 를 적는다 → **중복**. 그리고 `duel.py` 가 journal 을 import 해야 해서 불변식도 깨진다 |
| **B. journal 을 `GameState` 안에 둔다** | 🔴 `state_hash()` 가 "판의 모양" 이 아니라 "어떤 경로로 왔는가" 를 뜻하게 된다. Phase 1 이 세운 "같은 판은 경로와 무관하게 같은 해시" 가 깨진다. journal docstring 이 그 이유를 이미 적어 두었다 |
| **C. 비체인 행동을 `EffectEvent` 로 적는다** | 🔴 `effect_ref` 가 거짓이 된다. 유발 효과가 "효과에 의해" 와 "소환에 의해" 를 영영 가릴 수 없다 (`EventKind` docstring 이 비용/효과를 가른 것과 같은 이유) |
| **D. 비체인 행동은 적지 않는다** | §12 가 "실제로 적용된 상태 변경을 추적할 수 있다" 를 요구하고, 일반 소환이 그 대표 사례다. 그리고 데이터 모델이 적용 완료를 **이미 판별할 수 있으므로** §5-B 의 "판별할 수 없으면 적지 않는다" 가 적용되지 않는다 |
| **E. `duel.py` 가 journal 을 만들고 적는다** | 🔴 AST 불변식 위반 (§2-4) |
| **F. 사본도 journal 을 공유한다** (변경 없음) | 🔴 §5-C-4 위반. 아래 §4 |

### 🔴 탐색 사본의 기록 격리 — 이번에 **필수로** 바뀐 자리

`agent/simulation.py::Simulator._fork` 는 `dataclasses.replace(duel,
state=clone)` 로 판만 복제하고 **나머지를 공유**했다. journal 이 붙은 뒤로는
그대로 두면 **사본에서 돌린 전개가 진짜 듀얼의 기록에 남는다** — 사본은
버려지는데 기록은 남으므로 그 기록은 실제 판과 **모순된다** (§5-D 위반).

그래서 사본은 `duel_components(journal=False)` 로 **기록하지 않는 한 벌**을
받는다. 미래를 재는 일에 역사가 필요하지 않다.

🔴 `None` ("안 줬다") 과 `False` ("끄겠다") 를 가른 이유가 여기다. 둘을
합치면 "사본이 기록을 안 하는 것" 과 "기본값" 이 같은 값이 되어, 기본이
바뀌면 격리가 조용히 사라진다.

---

## 4. 변경한 파일 및 함수

| 파일 | 변경 | 줄 |
|---|---|---|
| `engine/effect/journal.py` | `EventKind.ACTION` · `ActionEvent` · `EventJournal.record_action` · `__all__` | +99 / −1 |
| `engine/action_execution.py` | `ActionExecutor(journal=None)` · `journal` 프로퍼티 · `execute()` 기록 | +44 / −8 |
| `engine/spell_activation.py` | `NormalSpellPlacement(journal=None)` + `_record` · place/reveal/`_move_back` 기록 · `duel_activator(journal)` · `duel_resolver(journal)` · **`duel_components()` 신규** | +124 / −12 |
| `engine/summon.py` | `summon_executor(journal)` · `duel_executor(journal)` | +12 / −4 |
| `engine/duel.py` | `journal` 칸 · `start(journal=…)` · `duel_components` 배선 | +43 / −3 |
| `engine/trigger.py` | `TimingEvent.from_journal_event` 의 `ActionEvent` 분기 | +19 / −1 |
| `agent/simulation.py` | `_fork` 의 기록 격리 | +22 / −6 |
| `tests/engine/test_event_journal_integration.py` | 신규 회귀 테스트 14개 | +526 |
| `tests/agent/test_search_ai.py` | 🔴 **지뢰선 하나를 새 사실로 갱신** (아래) | +42 / −12 |
| `tests/test_trigger_lifetime_audit.py` | `Duel` 필드 집합 + `duel.py` 가 `journal` 을 **읽지 않는다**는 AST 단정 추가 | +27 / −0 |
| `tests/test_trigger_pipeline_dormant_audit.py` | `trigger.py` 줄수 1,661 → 1,681 | +24 / −4 |
| `tests/test_event_context_actor_provenance.py` | 결과 인구조사 7 → 8, `with_actor` 2 → 3 | +32 / −2 |
| `tests/test_event_reader_actor_input_boundary.py` | `carries_own_actor` 2 → 3, 합집합 4 → 5 | +25 / −3 |
| `tests/test_result_actor_provenance_design_audit.py` | 🔴 **`test_09` 판정을 다시 씀** (§9) | +78 / −23 |
| `tests/test_rule_not_implemented_code_audit.py` | 줄번호 고정값 갱신 | +13 / −5 |
| `tests/test_actor_declaration_scope_audit.py` | 인구조사 8, `carries_actor` 에 `ActionEvent` 추가 | +14 / −3 |

모든 프로덕션 변경이 **가산적**이고, 기본값이 "적지 않는다" 이므로 기존
호출의 동작이 바뀌지 않는다.

### 🔴 기존 테스트 1개를 갱신했다 — 그 테스트가 **설계대로 나를 잡았다**

`tests/agent/test_search_ai.py::test_the_executor_carries_no_per_duel_state`
는 단정 하나였다:

```python
assert ActionExecutor.__slots__ == ("_handlers",)
```

그 docstring 이 이유를 적어 두었다 — *"``ActionExecutor`` 가 들고 있는 것은
수행기 등록부 하나뿐이다 … **여기에 칸이 늘어나면 이 시험이 먼저 깨져야
한다.**"*

Phase 6-B 가 `_journal` 칸을 늘렸고, **그것은 듀얼마다 달라지는 상태다.**
그래서 예전 가정("공유해도 안전하다")이 더 이상 사실이 아니다. 🔴 이 실패는
내 변경의 **위험을 정확히 지목한 것**이고, 그래서 §3 의 사본 격리가 필수가
됐다.

갱신 방식: 지키려던 것("사본과 원본이 섞이지 않는다")은 그대로 두고 **지키는
방법이 바뀐 것**을 적었다. 이름을
`test_the_executor_now_carries_per_duel_state_so_forks_must_not_share_it` 로
바꾸고, 단정을 **1개에서 5개로** 늘렸다 — 새 칸 목록 · 사본이 수행기를
공유하지 **않음** · 진짜는 기록함 · 사본은 기록 안 함 · 그래도 **같은
규칙**으로 돎. 칸이 또 늘어나면 **여전히 여기서 먼저 깨진다.**

---

## 5. 이벤트 생성·기록의 실제 시점 (측정)

마법 한 장의 **전 여정**이 순서대로 적힌다:

```
#0 [action] activate_effect P0: P0 가 #2 를 발동 선언하며 SZONE 에 앞면으로 놓았다 (해결 전)
#1 [effect] 55144522:e[0] P0: P0 가 #5 를 드로우, P0 가 #6 를 드로우
#2 [action] activate_effect P0: P0 의 #2 가 해결을 마치고 GRAVE 로 갔다 (효과가 아니라 규칙)
```

🔴 **발동만으로는 효과 기록이 없다** — 발동 ≠ 해결이라는 Phase 2-Q 의
구분이 기록에도 그대로 나타난다. `test_b_an_effect_resolution_is_recorded_
after_the_state_changed` 가 `[ACTION, EFFECT, ACTION]` 순서를 고정한다.

일반 소환:

```
#0 [action] normal_summon P0: P0 가 #0 를 HAND 에서 MZONE[0] 로 normal 소환 (FACEUP_ATTACK)
```

---

## 6. 지원되는 이벤트 종류와 지원하지 않는 종류

### ✅ 지금 적힌다

| 종류 | 무엇이 | 실측 |
|---|---|---|
| `ACTION` | 일반 소환 · 특수 소환 · 세트(몬스터/마법함정) · 공격 | 한 판에 25건 |
| `ACTION` | 발동 선언 배치 · 해결 뒤 묘지 · 발동 불성립 되돌리기 | 위 §5 |
| `EFFECT` | 등재된 효과의 **적용된** 해결 | 한 판에 3~4건 |
| `COST_PAYMENT` | 치른 비용 | **배선됨, 그런데 0건** (아래) |

### ❌ 적히지 않는다 — 이유와 함께

| 항목 | 이유 |
|---|---|
| **비용 지불** | 배선은 끝났지만 **등재된 16개 효과 중 비용이 선언된 것이 0개**다. 발화되지 않은 경로이고, 그 사실을 숨기지 않는다 |
| 드로우 페이즈 드로우 · 시작 드로우 | `Duel.advance()` 가 `state.draw` 를 직접 부른다. 🔴 그 자리는 `ActionExecutor` 를 거치지 않고, 적게 하려면 `duel.py` 가 journal 을 알아야 한다 (§2-4 위반) |
| 페이즈 전환 · 턴 넘김 | `TurnProgressor` 가 `PhaseChanged` 를 만들지만 journal writer 가 아니다 |
| 승패 기록 | `duel.py` 가 직접 `set_result` 한다 (같은 이유) |
| 전투 데미지 · 라이프 변동 | `AttackHandler` 의 변화는 `ACTION` 으로 적힌다. 그 **안의** 의미(데미지 계산 단계)는 모델에 없다 |
| 유발 효과 · 체인 응답 · 우선권 전환 | 🔴 **이번에 연결한 것이 아니다.** 아래 §9 |

---

## 7. 게임 상태와 기록의 일관성 검증 (§5-D)

실측 (덱 12장 ×2, 한 판 끝까지):

| 불변 조건 | 결과 |
|---|---|
| 기록 켜고/끈 최종 `state_hash()` 동일 | ✅ seed 3 · 7 · 11 · 21 **전부 동일** |
| 기록 켜고/끈 `DuelResult` 동일 | ✅ 전부 동일 |
| 거절된 행위가 성공 사건을 남기지 않음 | ✅ 특수 소환(`UNKNOWN`) · 소환권 소진 후 재소환 — 둘 다 `state_hash` 불변 · 기록 불변 |
| 같은 변화가 두 번 적히지 않음 | ✅ 사건 29건 / 변화 36건 / **중복 0건** |
| 번호에 빈틈 없음 | ✅ `sequence == range(n)` |
| 같은 입력 → 같은 기록 | ✅ `journal_hash()` 재현 |
| 듀얼 간 기록 격리 | ✅ 다른 `EventJournal` 객체, 교차 오염 0 |
| 탐색 사본이 진짜 기록을 더럽히지 않음 | ✅ `Simulator._fork()` → `journal is None`, 진짜 기록 불변 |

### 🔴 원자성의 한계 (§5-D 마지막 문장)

**기록과 상태 변경은 원자적이지 않다.** 상태를 먼저 바꾸고 그 다음에 적는다.
그 사이에 예외가 나면 **판은 바뀌었는데 기록이 없다.**

이 순서를 고른 이유: 반대로 하면 **적었는데 판이 안 바뀐** 기록이 남고,
그것이 더 나쁘다 — 없는 역사를 근거로 되감으면 틀린 판이 된다
(`executor.py` 의 기존 주석과 같은 판단).

실패 시 처리: 적는 쪽이 예외를 삼키지 않는다. `EventJournal.append` 는
번호가 어긋나면 `JournalError` 로 **멈춘다** — 조용히 다시 매기지 않는다.

---

## 8. 실패·중복·복수 듀얼 테스트 결과

```
$ python3 -m pytest tests/engine/test_event_journal_integration.py -p no:randomly -q
14 passed in 3.58s
```

| § | 요구 | 테스트 |
|---|---|---|
| 8-1 | journal 생성 및 연결 | `test_a_start_creates_one_journal_shared_by_every_writer` (네 writer 가 **같은 객체**) |
| 8-2 | 기록 없는 기존 호출의 하위 호환 | `test_a_a_caller_that_passes_no_journal_still_works` |
| 8-3 | 비체인 행동의 기록 | `test_b_a_non_chain_action_is_recorded_with_its_real_movement` |
| 8-4 | 효과 해결 후 기록 | `test_b_an_effect_resolution_is_recorded_after_the_state_changed` |
| 8-5 | 적용 상태 구분 | `test_c_an_executed_action_with_no_change_is_not_recorded` |
| 8-6 | 실패한 행동의 성공 이벤트 차단 | `test_b_a_refused_action_leaves_no_event` (두 종류의 거절) |
| 8-7 | 중복 생성 방지 | `test_c_the_same_change_is_never_recorded_twice` (🔴 카드 ID 로 걸러내지 않는다 — `(sequence, canonical_state)` 로 본다) |
| 8-8 | 복수 듀얼 격리 | `test_c_two_duels_keep_their_records_apart` + `test_c_a_search_fork_records_nothing_in_the_real_journal` |
| 8-9 | journal 유무의 최종 상태 동일성 | `test_c_recording_does_not_change_the_final_state` |
| 8-10 | 체인·타이밍·우선권 회귀 | 기존 2,828개 + `test_d_a_recorded_action_is_not_a_timing_point_of_its_own` + `test_j_wiring_the_journal_did_not_turn_on_any_trigger` |
| §3-1 | Engine V1 계약 보존 | `test_a_the_duel_module_still_imports_no_effect_layer` |

### 돌연변이 검사 — 그리고 **두 개가 내 테스트 구멍을 찾았다**

🔴 처음 8종을 돌렸을 때 **두 개가 잡히지 않았다.**

1. **`executed.deltas` 가드를 지웠는데 13개 전부 통과.** "변화 없는 실행을
   적지 않는다" (§5-B) 를 재는 테스트가 없었다 → `test_c_an_executed_
   action_with_no_change_is_not_recorded` 추가.
2. **`_fork` 의 격리를 지웠는데 13개 전부 통과.** 테스트가 사본을 **직접**
   `dataclasses.replace(..., **duel_components(journal=False))` 로 만들고
   있었다 — 내 헬퍼를 시험한 것이고 프로덕션 `Simulator._fork` 를 시험한
   것이 아니었다 → 실제 `Simulator._fork()` 를 부르도록 고쳤다.

고친 뒤 11종 전부 포착:

| 돌연변이 | 결과 |
|---|---|
| `ActionExecutor` 기록 제거 | **4 failed** |
| 변화 없는 실행도 기록 | **1 failed** (`test_c_an_executed…no_change`) |
| writer 들이 journal 을 공유하지 않게 | **3 failed** |
| 효과 해결 기록 제거 | **3 failed** |
| 마법 배치 기록 제거 | **1 failed** |
| 탐색 사본이 진짜 journal 공유 (`**{}`) | **1 failed** |
| 탐색 사본이 journal 물려받기 | **1 failed** |
| `ActionEvent` 시점 분기 제거 | **1 failed** |
| `sequence` 검사 제거 | **1 failed** |
| (복원 후) | **14 passed** |

---

## 9. 기존 엔진 전체 회귀 테스트 결과

```
$ python3 -m pytest tests/engine -p no:randomly -q
2842 passed in 78.24s (0:01:18)
```

Phase 6-A 기록은 **2,828 passed** 였다. 차이 **+14**는 전부 이번에 추가한
`tests/engine/test_event_journal_integration.py` 의 테스트다 — `tests/engine/`
안에서는 **삭제 0건, 수정 0건, skip 0건.**

🔴 **`tests/engine/` 밖에서 회귀 1건이 났고, 그것을 숨기지 않는다.**

```
$ python3 -m pytest tests/ -p no:randomly -q -x --ignore=tests/engine
FAILED tests/agent/test_search_ai.py::test_the_executor_carries_no_per_duel_state
1 failed, 271 passed in 185.20s
```

그 테스트는 **의도된 지뢰선**이었고 설계대로 내 변경을 잡았다 (위 §4).
갱신 뒤:

```
$ python3 -m pytest tests/agent/test_search_ai.py -p no:randomly -q
42 passed in 16.91s
```

🔴 **엔진 테스트만 돌리고 끝냈으면 이 회귀를 놓쳤다.** `tests/engine` 은
2,842개가 통과했지만 `agent/` 의 계약이 깨져 있었다 — Phase 6-B 지시서가
"엔진 테스트 전체" 를 요구했는데, 그것만으로는 충분하지 않았다는 사실을
적어 둔다.

### 전체 스위트 — 묶음으로 끝까지 돌렸다 (최종)

🔴 **처음 시도는 아무것도 증명하지 못했다.** `tests/ --ignore=tests/engine`
한 번에 돌린 백그라운드 작업이 30분 상한에서 죽어 **출력 0바이트**로
끝났다. 이 저장소에는 한 파일에 6~7분 걸리는 감사 테스트가 여럿 있어
단일 실행으로는 끝나지 않는다. 그래서 파일 목록을 4묶음으로 나누고
상한을 올려 다시 돌렸다.

| 범위 | 1차 실행 | 고친 뒤 |
|---|---|---|
| `tests/engine` (2,842개) | ✅ 2,842 passed (1:18~1:22) | — |
| `tests/agent` + `tests/rules` + `tests/rulings` | ✅ 529 passed, 4 skipped (4:43) | — |
| 묶음 0 (25파일) | 706 passed + **1 failed** (22:27) | ✅ 해당 파일 28 passed |
| 묶음 1 (22파일) | 551 passed + **3 failed** (11:57) | ↓ |
| 묶음 2 (22파일) | 545 passed + **5 failed** (12:15) | ↓ |
| 묶음 1+2 재검증 (44파일) | — | ✅ **1,104 passed** (22:00) |
| 묶음 3 (22파일) | 463 passed + **3 failed** (7:46) | ✅ **466 passed** (6:50) |

**최종 실패 0건.** 묶음 0 은 고친 파일만 다시 돌렸고(28 passed) 나머지
24개 파일은 1차에서 이미 통과했다 — 전체를 다시 22분 돌리지 않았다는
사실을 그대로 적는다.

### 🔴 밖에서 난 12건은 전부 "고정된 수치가 움직인 것"이고, 프로덕션 결함은 0건이다

| 파일 | 테스트 | 움직인 고정값 |
|---|---|---|
| `test_actor_declaration_scope_audit.py` | `test_13` | 결과 타입 인구조사 7 → 8 |
| `test_event_context_actor_provenance.py` | `test_05` · `test_08` | 인구조사 7 → 8, `with_actor` 2 → 3 |
| `test_event_reader_actor_input_boundary.py` | `test_15` | `carries_own_actor` 2 → 3, 합집합 4 → 5 |
| `test_result_actor_provenance_design_audit.py` | `test_01` · `test_02` | 생산자 서명이 `journal=` 을 받게 됨 |
| `test_result_actor_provenance_design_audit.py` | `test_09` | 🔴 **이 Phase 가 일부러 뒤집은 사실** |
| `test_rule_not_implemented_code_audit.py` | `test_02` · `test_05` | `trigger.py` 줄번호 +20, `action_execution.py` +23 |
| `test_trigger_lifetime_audit.py` | `test_08` | `Duel` 필드 집합에 `journal` 추가 |
| `test_trigger_pipeline_dormant_audit.py` | `test_01` · `test_25` | `trigger.py` 1,661 → 1,681 줄 |

네 종류로 나뉜다 — **인구조사 5건 · 줄수 2건 · 줄번호 2건 · 구조 3건.**

🔴 **인구조사 5건은 모두 같은 하나의 사실을 가리켰다.** `ActionEvent` 은
`actor` 를 직접 들고 있지만 **`.action` 칸이 없다** (journal 이
`engine.action` 을 import 하면 안 되므로 행위 종류가 문자열로 건너온다).
그래서 "actor 를 스스로 들고 있는 결과" 는 2 → 3 으로 늘었는데
"action 에서 끌어낼 수 있는 결과" 는 2에서 **그대로**다. 다섯 군데가
같은 구분을 각자 고정해 둔 덕분에, 내가 그 구분을 뭉개지 않았다는 것이
다섯 번 확인됐다.

#### `test_09` 를 다시 썼다 — 이름이 가리키던 사실이 사라졌다

옛 이름은 `test_09_production_never_records_the_journal_events` 였고 그
단정은 **쓰여진 시점에 참이었다** (§1: 기록 계층에 production 호출자가
없었다). Phase 6-B 가 바로 그것을 뒤집었으므로 이름과 함께 판정을
`test_09_production_now_records_the_journal_events_through_the_duel` 로
바꾸고, 셋으로 쪼개 각각을 측정값으로 고정했다:

1. **효과 해결은 기록된다** — `EffectEvent` 가 실제 이동과 함께 남는다.
2. **행위도 기록되지만 `.action` 없이** 기록된다 — 위의 구분 그대로.
3. 🔴 **비용 경로는 배선만 됐고 이벤트는 0건이다** — 등재된 효과 16개 중
   비용을 선언한 것이 하나도 없어 `CostPayer` 가 발화할 기회가 없다.
   `journal_builders == {"engine/spell_activation.py": 1}` 로 "만드는
   자리는 한 곳" 이라는 사실만 고정했다.

🔴 **지시서의 "엔진 테스트 전체" 는 충분하지 않았다.** `tests/engine` 이
2,842개 통과하는 동안 그 밖에서 12개가 깨져 있었다. 다음 Phase 는
처음부터 **전체를 묶음으로** 쓸어야 한다.

---

## 10. 남아 있는 구조적 차단 문제

🔴 **이번 단계가 트리거 실행을 켠 것이 아니다** (§6). 기록이 이어졌어도:

1. **`Duel` 은 트리거 계층을 import 하지 않는다.** `engine.trigger` ·
   `trigger_order` · `trigger_chain` · `timing` · `event_pipeline` 의
   production 호출자는 여전히 0개다
   (`test_j_wiring_the_journal_did_not_turn_on_any_trigger` 가 고정).
2. **등재된 효과 정의가 전부 `EFFECT_TYPE_ACTIVATE` 모양**(16/16)이다 —
   `TRIGGER_O` · `IGNITION` · 지속이 0개.
3. **조건 술어 3개** (`IsMonster` · `IsSpellTrap` · `IsTurnPlayer`) —
   아키타입 술어가 없다 (STRUCTURAL-77, 단독 병목 148장).
4. **효과 몬스터의 일반 소환이 `UNDETERMINED`** — 메인덱 몬스터의 7.7%만
   소환 허가 (`summon_rules.py:195`).
5. **드로우 · 페이즈 전환 · 승패가 기록되지 않는다.** `duel.py` 가
   직접 하는 세 자리이고, 적게 하려면 그 파일이 journal 을 알아야 한다 —
   AST 불변식과 충돌한다. 🔴 **해결하려면 그 세 변화도 writer 를 거치게
   해야 하고, 그것은 이번 범위가 아니다.**
6. **`EventKind.ACTION` 에 대응하는 공식 타이밍 포인트가 없다.**
   `from_journal_event` 가 `TimingEvent.unimplemented` 를 돌려준다 — 행위가
   만든 변화는 `timing_for(delta)` 가 따로 옮기므로 사건 자체에 이름을
   붙이면 같은 소환이 두 시점이 된다.
7. **기록과 상태 변경이 원자적이지 않다** (§7).
8. 비용 지불 경로가 **발화되지 않았다** (등재 효과 중 비용 선언 0개).

### 이전 단계에서 열어 둔 채 유지

STRUCTURAL-15 · 34(남은 절반) · 35 · 36 · 77 · Phase 4-C 의 파괴 실행
미구현과 `DuelRunner._step` 분류 결함 · `/combo` 의 일반 소환 과대 판정.

---

## 11. Phase 6-C 의 선행 조건

Phase 6-A 로드맵의 6-C(아키타입 술어)는 **이번 단계와 독립**이고 지금 바로
가능하다. 다만 **사건→트리거 배선(6-A 가 6-B 로 적은 나머지 절반)** 을
하려면 이번 결과 위에 다음이 필요하다:

1. ✅ **journal 이 사건을 들고 있다** — 이번에 됐다. `EventReader` 가 읽을
   입력(`JournalEvent` · `StateDelta`)이 실제 듀얼에서 생성된다.
2. ❌ **`Duel` 이 journal 을 **읽어** 트리거 수집기에 넘기는 자리.** 아직
   없다. `duel.py` 가 `engine.trigger` 를 import 해야 하므로, 그때
   `test_e_the_duel_makes_no_rules_of_its_own` 의 금지 목록
   (`engine.effect` · `engine.condition`) 과 **충돌하지 않는지** 확인해야
   한다 — 트리거는 그 목록에 없으므로 가능해 보이지만, 🔮 추측이므로
   먼저 측정한다.
3. ❌ **`ActionEvent` 의 타이밍 포인트 정책.** 지금은 `unimplemented` 다.
   트리거를 켜면 "소환으로 발동하는 효과" 가 `MonsterSummoned` 쪽에서
   오는지 확인해야 한다.
4. ❌ **동시 사건 처리 (STRUCTURAL-35).** 한 행위가 여러 delta 를 만들면
   창이 여럿이 된다 — 일반 소환은 delta 1개이므로 당장은 문제가 아니지만,
   전투는 아니다.

---

## 12. Git 커밋 및 푸시 결과

브랜치 `claude/pensive-goodall-te1egy` 에만 올렸다. 기존 커밋을 amend ·
rewrite · force push 하지 않았다.

| 커밋 | 내용 |
|---|---|
| `f66b638` | 프로덕션 배선 — `EventKind.ACTION` · `ActionEvent` · `duel_components()` · 포크 격리 |
| `6aebfcd` | 회귀 테스트 14개 + 발화한 지뢰선 1개 갱신 |
| `f4f6eb3` | 이 보고서 |
| `4897a6f` | `journal` 칸·가드가 움직인 고정값 3건 |
| `451a01c` | 인구조사·줄수 고정값 8건 |
| `2dc3f84` | 묶음 0 에서 난 마지막 인구조사 고정값 1건 |

이 절의 §9 최종 수치 확정이 마지막 커밋이다.

---

## 결론 — 다음 단계가 활용할 수 있는 인터페이스

```python
duel = Duel.start(repo, decks=…, seed=…)        # 기록 켜짐 (기본)
duel = Duel.start(repo, decks=…, seed=…, journal=False)   # 기록 끔
duel = Duel.start(repo, decks=…, seed=…, journal=기존기록) # 이어 적기

duel.journal                 # EventJournal | None
len(duel.journal)            # 사건 수
duel.journal[i]              # JournalEvent (sequence 가 identity)
duel.journal.events          # tuple — 밖에서 덧붙일 수 없다
duel.journal.of_kind(EventKind.ACTION | EFFECT | COST_PAYMENT)
duel.journal.deltas()        # 모든 변화를 순서대로
duel.journal.canonical_state()   # 같은 판인가 비교용
duel.journal.journal_hash()      # 재현 검증용
event.to_dict()              # 직렬화 (리플레이 입력의 재료)
```

**한계를 함께 적는다**: 드로우 · 페이즈 전환 · 승패 · 유발 효과는 들어
있지 않고, 비용 지불은 배선만 되어 있다. 이 기록으로 Duel Simulator 리플레이를
만들려면 최소한 드로우가 더 필요하다 (§10-5).

🔴 **Phase 6-C 를 자동으로 시작하지 않는다. 사용자 검토를 기다린다.**
