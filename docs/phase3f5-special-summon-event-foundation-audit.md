# Phase 3-F-5 — SPECIAL_SUMMON Operation/Event 데이터 계층 감사

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-5 — SPECIAL_SUMMON Operation/Event Data-Layer Audit |
| 모드 | **AUDIT-ONLY** (production diff 0) |
| Base | Phase 3-F-4 (`f9d95de` 작업 · `5608f17` 보고서) |
| 3-F-4 최종 판정 | **B. SCENARIO_FOUNDATION_INSUFFICIENT** |
| **실제 HEAD (측정)** | `5608f17 Phase 3-F-4 보고서: commit SHA · push 결과 기록` |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,177 passed / 4 skipped |
| 새 테스트 | `tests/test_special_summon_event_foundation_audit.py` — **19건** |

프롬프트에 적힌 SHA 를 믿지 않고 `git log` 로 확인했다. HEAD 는 `5608f17`
이고 작업 트리는 깨끗했다. 3-F-4 보고서의 판정 줄도 직접 읽어 **B** 임을
확인했다. 3-F-3 의 weight 결론과 3-F-4 의 네 단계 분리는 **다시 측정하지
않았다.**

---

## 2. Operation 과 Event 의 정의 — 이 Phase 의 축

| | 뜻 | 질문 |
| --- | --- | --- |
| **Operation** | 효과/플레이어가 **하려는 일** | "무엇을 하려고 했는가" |
| **Event** | 게임 상태에서 **일어난 일** | "무엇이 실제로 발생했는가" |

이 둘을 하나의 값으로 취급하지 않았다. 측정 결과 **코드도 둘을 합치지 않고
있다** — 그리고 그 분리를 지키려고 치른 대가가 §6 과 §10 에서 드러난다.

세 어휘가 **서로 다른 타입**임을 `test_01` 이 확인했다.

```
OperationKind.SPECIAL_SUMMON      "효과가 특수 소환을 한다"      (하려는 일)
PlayerActionKind.SPECIAL_SUMMON   "플레이어가 특수 소환을 고른다" (고른 행위)
TimingPoint.MONSTER_SUMMONED      "몬스터가 소환되었다"          (일어난 사건)
```

값 문자열이 앞의 둘은 똑같다 (`"special_summon"`) 는데 **다른 enum** 이고
(ADR-001), `TimingPoint` 에는 **특수 소환이라는 이름이 아예 없다** —
`{point.value for point in TimingPoint}` 에 `"special"` 을 포함하는 것이
하나도 없다.

---

## 2-B. Operation 과 Event 의 대조표 (§4)

물음표를 추측으로 채우지 않았다. 각 칸이 **어느 측정에서 나왔는지** 함께
적는다. "LIVE 소비자" 는 `Duel` 에서 실제로 닿는 코드이고, "DORMANT 소비자"
는 존재하지만 production 호출이 0인 코드다.

| 개념 | 의미 | 생성 주체 | 현재 존재 | LIVE 소비자 | DORMANT 소비자 |
| --- | --- | --- | --- | --- | --- |
| `OperationKind.SPECIAL_SUMMON` | **하려는 일** — 효과가 몬스터를 특수 소환한다 | 효과 정의(`EffectDefinition.operations`) 를 **손으로 등재**할 때 | **있다** (`operation.py:90`) + 실행기 등록 (`executor.py:1943`) | `EffectExecutor` — `_plan_summon_operation` / `_apply_special_summon` (**등재 효과 0개라 실제로는 도달하지 않는다**, `test_12`) | 없음 |
| `SummonKind` | **소환의 종류** — `{normal, special}` | 소환 절차가 값으로 들고 있다 (`SPECIAL_SUMMON_PROCEDURE.summon`) | **있다** (`delta.py:468`) | `SummonProcedure.to_delta` → `MonsterSummoned` (live 실행기가 쓴다, `test_05`) | 없음 — `TriggerSpec` 이 이 값을 **읽지 못한다** (`test_13`) |
| `MonsterSummoned` | **일어난 사실** — 몬스터가 소환되었다 | `SummonProcedure.place` 뒤 `placement.to_delta(...)` | **있다** (`delta.py:497`) | `ActionExecution.deltas` 에 담긴다 — 그리고 `DuelStep` 이 **버린다** (`test_09`) | `TimingEvent.from_delta` · `EventReader` |
| `TimingEvent` | **사건 하나** — `point` + `delta` 참조 | `TimingEvent.from_delta` / `timing_for` / `EventReader` | **있다** (`trigger.py:219`) | **없다** — `duel.py` 에 이름이 등장하지 않는다 (`test_09`) | `EventReader` · `TriggerCollector` · `TriggerEligibilityJudge` · `EventPipeline` |
| `TimingPoint` | 사건의 **종류 이름** (enum 8개) | 상수 — 아무도 만들지 않는다 | **있다** (`trigger.py:85`) · 소환은 **`MONSTER_SUMMONED` 하나**뿐 | **어휘만** — `activation_timing.py` 가 import 하고 `ActivationTiming.point` 칸을 갖는다. `Duel` 은 그 칸을 **채우지 않고**, 검증기는 **읽지 않는다** (§6) | `TriggerSpec.point` · `matches` · `watching` |
| `TriggerSpec.point` | **"이 효과는 이런 일이 일어나면 후보가 된다"** 는 선언 | `TriggerRegistry.register` — **손으로만** (자동 생성 없음) | **있다** (`trigger.py:425`) — 그러나 소환 종류 · 행위자 칸이 **없고** `MONSTER_SUMMONED` 에는 기존 필터 셋도 **금지**된다 | **없다** — `duel.py` 에 `TriggerRegistry` 가 없다 | `TriggerRegistry.watching` · `TriggerCollector.collect` · `TriggerEligibilityJudge._event_relation` |

표에서 읽어야 할 세 줄:

1. **`SummonKind` 는 live 에서 만들어지고 dormant 에서 읽히지 않는다.**
   값은 생산되는데 소비자가 없다.
2. **`TimingPoint` 만 LIVE 와 DORMANT 양쪽에 이름이 걸려 있다** — 그런데
   LIVE 쪽은 칸만 있고 채우지도 읽지도 않는다.
3. **`TriggerSpec.point` 는 dormant 전용이고, 그 선언이 특수 소환을 가리킬
   수 없다** — 이것이 §10 의 결론으로 이어진다.

---

## 3. `OperationKind.SPECIAL_SUMMON` 조사 (§3 Q1)

**답: 그렇다. 이것은 "수행하는 작업" 이다.** 근거 셋을 코드에서 확인했다.

1. `OPERATION_HANDLERS[OperationKind.SPECIAL_SUMMON]` 에 **계획 함수와 적용
   함수가 둘 다 달려 있다** (`EffectExecutor._plan_summon_operation` ·
   `EffectExecutor._apply_special_summon`). 사건에는 그런 것이 붙지 않는다.
2. 그 일을 나르는 `SpecialSummonOperation` 은 `TargetRef` 를 **요구한다** —
   `target_ref="primary"` 같은 문자열을 주면 `TypeError` 가 난다. "누구를"
   없는 소환은 일이 아니다.
3. `CardOperation` 이 **아니다.** 목적지가 의미로 정해지는 다른 일들과 달리
   칸 번호와 표시 형식이 필요하고, 남기는 변화도 `ZoneMoved` 가 아니다.

| 자리 | 내용 |
| --- | --- |
| 정의 | `engine/effect/operation.py:90` (`OperationKind`) · `:707` (`SpecialSummonOperation`) |
| 실행 계획 | `engine/effect/executor.py:1255` `_plan_summon_operation` |
| 실행 적용 | `engine/effect/executor.py:1812` `_apply_special_summon` |
| 등록 | `engine/effect/executor.py:1943` `OPERATION_HANDLERS` |
| 규칙 관문 | `engine/effect/executor.py:1707` — `may_be_special_summoned(instance)` |

---

## 4. `SummonKind` 조사

`{normal, special}` **두 값**이고, `SPECIAL` 은 **실제로 쓰인다** —
`SPECIAL_SUMMON_PROCEDURE.summon is SummonKind.SPECIAL`.

### 🟡 docstring 이 낡았다 (production 변경은 하지 않았다)

`SummonKind` 의 첫 줄은 이렇게 말한다.

> 어떤 소환인가. **지금 있는 것은 일반 소환뿐이다.**

`SPECIAL` 멤버가 그 아래 줄에 Phase 2-T 주석과 함께 **있으므로** 이 문장은
지금 사실이 아니다. `TimingPoint.MONSTER_SUMMONED` 의 docstring 도 같은
상태다 ("지금 나올 수 있는 값은 일반 소환뿐이다").

이 Phase 는 **문서가 아니라 값을 측정했고** (`test_02` 가 멤버 목록을 센다),
docstring 은 고치지 않았다 — AUDIT-ONLY 이고, 주석 수정도 production 파일
변경이다. §19 의 "필요하면 이유를 먼저 기록한다" 에 따라 여기 적어 둔다.

특수 소환 절차의 네 값 (`test_02`):

| 값 | 내용 | 성격 |
| --- | --- | --- |
| `SPECIAL_SUMMON_FROM_ZONES` | `{HAND, GRAVE}` | **범위**이고 규칙이 아니다 |
| `SPECIAL_SUMMON_TO_ZONE` | `MZONE` | EMZ 는 엑스트라 덱 절차와 함께 |
| `SPECIAL_SUMMON_POSITION` | `FACEUP_ATTACK` | **고를 수 없다** (STRUCTURAL-61) |
| `SPECIAL_SUMMON_PROCEDURE.kind` | `PlayerActionKind.SPECIAL_SUMMON` | 일반 소환과 **같은 클래스**의 다른 값 |

파일이 스스로 적어 두었다: "여기 없는 자리는 **'규칙상 안 된다' 가 아니라
'아직 옮기지 못했다'**". 덱 · 제외 · 엑스트라 덱에서 나오는 특수 소환은
실제로 있고, 검증기가 그것을 `RULE_NOT_IMPLEMENTED` 로 말한다.

---

## 5. `MonsterSummoned` 조사 (§3 Q2)

**답: 그렇다. 이것은 "일어난 사건" 의 기록이다.** 단 사건 객체가 아니라
**상태 변화(`StateDelta`)** 다 — 사건은 그 위에 한 겹 더 있다 (§7).

`test_03` 이 확인한 것:

- `CardMovement` 가 **아니다** → `operation` 속성이 없다. 효과의 어휘를
  달지 않는다 (소환은 효과가 아니라 규칙에 따른 행위다).
- `summon` 이 의미를 말한다.
- 종류가 **정규 표현에 들어간다**: `canonical_state()` 에 `"special"` 이
  있고, `to_dict()["summon"] == "special"` 이다.
- 그래서 일반 소환과 특수 소환은 **서로 다른 기록**이다
  (`canonical_state()` 가 다르다).

즉 **사실은 하나도 잃지 않는다.** 잃는 것은 §7 에서 시작된다.

---

## 6. Operation → Mutation → Delta → Event → Timing → Trigger 경로

### 측정 (`test_04` ~ `test_09` · `test_13` · `test_14`)

```
Operation  (SpecialSummonOperation / PlayerAction.special_summon)
   │   CONNECTED      실행기가 실제로 판을 바꾼다 — MZONE 0 → 1
   ▼
State Mutation  (SummonProcedure.place)
   │   CONNECTED      MonsterSummoned(summon=SPECIAL) 1건
   ▼
Delta  (engine.effect.delta.MonsterSummoned)
   │   CONNECTED*     EventReader 가 ActionExecution 을 그대로 읽는다
   ▼
Event  (TimingEvent / ObservedEvent)
   │   PARTIAL        TimingPoint 이름은 하나뿐 — 종류를 꺼낼 창구가 없다
   ▼
TimingPoint  (MONSTER_SUMMONED)
   │   DORMANT        TriggerCollector 는 후보를 만든다 / production 호출 0
   ▼
Trigger Candidate
   │   DORMANT        TriggerEligibilityJudge 는 판정한다 / production 호출 0
   ▼
Eligibility
   │   MISSING        후보를 PlayerAction 으로 되돌리는 다리가 없다
   ▼
Activation
```

`*` **구조로는 이어져 있고 production 에서 호출되지 않는다.**

### 각 경계의 판정

| 경계 | 판정 | 근거 (측정) |
| --- | --- | --- |
| Operation → State Mutation | **CONNECTED** | `test_04` — `status=executed`, MZONE +1, 원본 판 불변 |
| State Mutation → Delta | **CONNECTED** | `test_05` — `MonsterSummoned(summon=SPECIAL)`, `HAND → MZONE` |
| Delta → Event | **CONNECTED (구조) / DORMANT (production)** | `test_06` · `test_09` |
| Event → TimingPoint | **PARTIAL** | `test_07` — 사실은 남고 **창구가 없다** |
| TimingPoint → Trigger Candidate | **DORMANT** | `test_08` 후보 생성 성공 / production 호출 0 |
| Trigger Candidate → Eligibility | **DORMANT** | `test_14` 판정은 나온다 / production 호출 0 |
| Eligibility → Activation | **MISSING** | 후보 → 행위 변환 코드가 없다 |

### Delta → Event 가 끊기는 **정확한 자리** (`test_09`)

`engine/duel.py:804` `_apply_board`:

```python
executed = self._executor.execute(self.state, action, authorization=...)
if executed.status is not ActionStatus.EXECUTED:
    return DuelStep(action, False, executed.code, executed.reason)
return DuelStep(action, True, ValidationCode.OK, executed.reason,
                result=self._check_end())
```

`executed` 는 `ActionExecution` 이고 **`.deltas` 에 소환 delta 가 들어 있다**
(`test_09` 가 같은 행위를 사본에서 실행해 확인했다). 그런데:

- `DuelStep` 의 필드는 정확히 `{action, accepted, code, reason, result}` —
  **`deltas` 칸이 없다.**
- `duel.py` 전체에 `EventReader` · `TimingEvent` · `TimingPoint` ·
  `timing_for` · `TriggerRegistry` · `TriggerCollector` · `MonsterSummoned` ·
  `SummonKind` 가 **하나도 등장하지 않는다.**

**이것이 실제 live 에서 일어나는 일이다.** 특수 소환은 관문에서 막히므로
(§8), 측정은 live 가 실제로 허가하는 **일반 소환**으로 했다 — 그 소환은
`accepted=True · code=OK` 로 받아들여지고, 그 안에서 만들어진
`MonsterSummoned(NORMAL)` 은 `DuelStep` 을 통해 밖으로 나오지 못한다.

> **끊긴 것은 자료 구조가 아니라 건네주는 손이다.**
> `EventReader.read` 는 docstring 에 "`ActionExecution` · `ProgressionResult`
> · `EffectResult` — 변화를 들고 있는 것이면 무엇이든" 이라고 적어 두었고,
> `test_06` 이 실제로 `ActionExecution` 을 그대로 읽어 사건을 만들었다.
> 새 EventBus 도 새 graph 도 필요하지 않다.

### 🟠 live 관문에 **빈 소켓**이 이미 있다

`engine/activation_timing.py:256`:

```python
@dataclass(frozen=True, slots=True)
class ActivationTiming:
    chain: Chain
    priority: PriorityState
    point: TimingPoint | None = None
    """지금이 어떤 시점인가. ``None`` 은 **"모른다"** 이지 "시점이 없다" 가 아니다."""
```

`engine/activation_timing.py` 는 **live 경로**다 (`Duel._activation_gate` 의
두 번째 관문). 그리고 `engine.trigger` 에서 `TimingPoint` 를 실제로 import
한다 — dormant 모듈이 아니다.

그런데 측정 결과:

- `Duel._activation_gate` (`engine/duel.py:595`) 는
  `ActivationTiming(self.chain, self.priority, set_this_turn=...)` 로 만든다.
  **`point` 를 넘기지 않으므로 언제나 `None` 이다.**
- `ActivationTimingChecker` 는 어떤 판정에서도 `point` 를 **읽지 않는다** —
  `.point` 가 쓰이는 자리는 `canonical_state()` 와 `to_dict()` 두 곳,
  즉 기록용뿐이다.

**사건이 들어갈 구멍이 live 쪽에 이미 뚫려 있고, 아무도 채우지 않으며
아무도 보지 않는다.** 이것이 Q8 의 가장 정확한 답이다.

---

## 7. "Event 는 Operation 의 다른 이름이 아니다" (§7)

### 네 어휘가 **각각 다른 것**이다 (§9)

`Event` 라는 이름의 클래스는 **없다.** 측정한 실제 어휘:

| 이름 | 무엇인가 | 어디 |
| --- | --- | --- |
| `TimingPoint` | 사건의 **종류 이름** (enum, 8개) | `engine/trigger.py:85` |
| `TimingEvent` | **일어난 사건 하나** — `point` + `delta` 참조 | `engine/trigger.py:219` |
| `ObservedEvent` | `TimingEvent` + `EventContext`(턴·페이즈) + 내용 기반 `event_id` | `engine/event_pipeline.py:142` |
| `JournalEvent` / `EffectEvent` / `CostPaymentEvent` | **다른 축** — 효과 해결·비용 지불의 기록 | `engine/effect/journal.py` |
| `EventRelation` | 클래스가 아니다 — `EligibilityGate.EVENT_RELATION`, dormant 판정기의 5관문 중 하나 | `engine/trigger.py:1023` |

**"특수소환이 발생했다" 를 표현하려면 셋이 다 필요하고, 셋이 다 있다.**

```
MonsterSummoned(summon=SPECIAL)   ← 사실        (StateDelta)
TimingEvent(MONSTER_SUMMONED)     ← 사건 하나   (point + delta)
ObservedEvent(context, timing)    ← 관측된 사건 (+턴·페이즈·식별자)
```

### 잃는 것은 **창구**다 (`test_07`)

```
timing.movement   = None      ← MonsterSummoned 는 CardMovement 가 아니다
timing.operation  = None
timing.from_zone  = None      ← 그런데 timing.delta.from_zone is Zone.HAND
timing.to_zone    = None      ← 그런데 timing.delta.to_zone  is Zone.MZONE
timing.instance   = InstanceId(...)   ← 이것만 예외 처리되어 있다
hasattr(timing, "summon")  →  False
```

`TimingEvent.movement` 는 `isinstance(self.delta, CardMovement)` 를 보고,
`operation`·`from_zone`·`to_zone` 세 속성이 **모두 `movement` 를 거친다.**
`MonsterSummoned` 는 `CardMovement` 가 아니므로 셋 다 `None` 이 된다 —
**delta 가 그 값을 분명히 들고 있는데도.**

`instance` 만 예외가 적혀 있다 ("이동한 사건만 보지 않는다"). 소환 종류에는
그 예외가 없다.

### 일곱 가지를 구분하는가

| 구분 | 현재 구조가 보존하는가 | 근거 |
| --- | --- | --- |
| requested special summon | **아니다** | `test_11` — 실패하면 delta 0 · 사건 0 |
| successful special summon | **그렇다** | `test_05` · `test_06` |
| failed special summon | **결과로만** — `ActionExecution.status` / `code` 에 남고 사건이 되지 않는다 | `test_11` |
| partially successful | **구조적으로 불가능** | `_plan_summon_operation` 이 한 장이라도 못 놓으면 효과 **전체**를 멈춘다 (판에 손대기 전) |
| resulting card movement | **그렇다** | `delta.from_zone` / `to_zone` |
| resulting monster presence | **그렇다** | `delta.to_index` · `position` |
| event observed by trigger system | **그렇다** (구조) / **아니다** (production) | `test_08` · `test_09` |

---

## 8. 성공 / 실패 / 부분 성공 (§8)

### live 는 특수 소환을 **UNKNOWN 으로** 막는다 (`test_10`)

```
ActionValidator.validate(PlayerAction.special_summon(...))
  → validity = UNKNOWN          (INVALID 가 아니다)
  → code     = RULE_NOT_IMPLEMENTED
  → missing  = "special-summon-condition (카드마다 다르다)"

Duel.apply(...)  → accepted=False, code=rule_not_implemented
```

"특수 소환할 수 없다" 가 아니라 **"조건을 읽을 계층이 없다"** 이고, 두
답을 합치지 않았다. 이것은 올바른 동작이다.

**막는 것은 실행기가 아니다.** `duel_executor()` 는
`PlayerActionKind.SPECIAL_SUMMON` 에 `SpecialSummonHandler` 를 **이미
등록해 두었다** (`engine/summon.py:336`). 즉 live 듀얼의 실행기는 특수
소환을 할 수 있고, 관문 하나가 허가를 내주지 않는다.

**`UNKNOWN` 을 지키는 것이 둘이다** — 고의 위반 4번에서 하나만 떼어내도
테스트가 통과해 버렸고, 그래서 `test_10` 을 고쳐 둘을 다 못박았다.

1. 요구 목록의 `UnimplementedRule(SPECIAL_SUMMON_CONDITION_RULE)`
2. `_COMPLETE_RULES` 에 `SPECIAL_SUMMON` 이 **없다** — `validate` 는 그
   집합에 든 종류만 `VALID` 로 올린다. 그리고 `_COMPLETE_RULES` 와
   `_MISSING_RULE` 이 겹치지 않는다는 것이 import 시점에 단정되어 있다.

### 🔴 `legal_actions` 는 특수 소환을 **보류 목록에도 남기지 않는다**

`Duel.legal_actions` 는 패의 카드마다 **세 가지만** 만들어 검증기에 묻는다
(`normal_summon` · `set_monster` · `set_spell_trap`). `_withheld_board_actions`
는 `activate_card` 하나만 만든다. 실제 듀얼 한 판을 돌려 확인했다:

```
허가된 종류:  end_phase 84 · normal_summon 60 · set_monster 60 · attack 10
보류된 것  :  ('activate_card', 'activation-timing (Phase 2-C/2-F)') 84
특수 소환  :  허가에도 없고 보류에도 없다
```

`LegalActions.withheld` 는 "빈 목록은 '할 것이 없다' 로 읽히고, 적어 둔 것은
'아직' 으로 읽힌다" 는 **정직성 장치**다. 특수 소환은 그 장치에조차 들어
있지 않아서, 읽는 쪽에서 보면 **아예 존재하지 않는 행위**처럼 보인다.

이것을 이 Phase 에서 고치지 않았다 (§11 이 `LegalActions` 변경을 금지한다).
기록만 남긴다.

### 실패는 완전히 조용하다 (`test_11`)

몬스터 존 5칸을 채워 실패시켰다.

| | 값 |
| --- | --- |
| `status` | `execution_error` (`executed` 가 아니다) |
| `code` | `rule_not_implemented` |
| `deltas` | **0건** |
| `state_hash` | **불변** |
| `EventReader` 가 만든 사건 | **0건** |

"일어나지 않은 일에 사건을 만들지 않는다" — 올바른 침묵이다. 그 대가로
**"시도했다" 를 표현할 방법이 없다.**

---

## 9. 실제 SPECIAL_SUMMON corpus (§5)

### 9.1 스크립트 전체 통계 (`test_15`)

`EffectSpec.code` 를 `repository.all_cards()` 전체에 대해 셌다.

| 항목 | 수 |
| --- | --- |
| 효과 블록 전체 | **34,631** |
| `code` 를 가진 블록 | **30,084** |
| 서로 다른 `code` | **298** |
| 이름에 `SUMMON` 이 든 `code` | **26종 / 5,979블록** |

그 26종이 **두 부류로 갈린다** — 그리고 `EffectSpec.code` 라는 **한 칸**에
섞여 들어온다.

| 부류 | 뜻 | 블록 |
| --- | --- | --- |
| `EVENT_*` | **일어났다** | **3,622** |
| `EFFECT_*` | **이렇게 할 수 없다 / 이런 절차다** (정적 제약) | **2,357** |

상위 항목:

| code | 블록 | 부류 |
| --- | --- | --- |
| `EVENT_SPSUMMON_SUCCESS` | 2,114 | 사건 — 특수 소환 **성공** |
| `EVENT_SUMMON_SUCCESS` | 1,249 | 사건 — 일반 소환 성공 |
| `EFFECT_CANNOT_SPECIAL_SUMMON` | 783 | 제약 |
| `EFFECT_SPSUMMON_PROC` | 606 | 절차 |
| `EFFECT_SPSUMMON_CONDITION` | 514 | 조건 |
| `EVENT_FLIP_SUMMON_SUCCESS` | 165 | 사건 |
| `EVENT_SPSUMMON` | **50** | 사건 — **선언/시도** |
| `EVENT_SPSUMMON_NEGATED` | **3** | 사건 — **무효** |

> **공식 스크립트는 성공 · 선언 · 무효를 서로 다른 이름으로 구분한다.
> 엔진의 `TimingPoint` 에는 소환이 든 이름이 하나뿐이다**
> (`MONSTER_SUMMONED`). §8 의 결론이 데이터로 다시 확인된다.

### 9.2 Lua 원문 기준 분류 (12,702 파일)

`Duel.SpecialSummon(` / `Duel.SpecialSummonStep(` (= 수행) 과
`EVENT_SPSUMMON_SUCCESS` (= 반응) 과 `SUMMON_TYPE_SPECIAL`/`IsSpecialSummoned`
(= 조건 참조) 로 갈랐다.

| 분류 | 파일 수 |
| --- | --- |
| 아무것도 없음 | 6,906 |
| **A** 수행만 | **3,620** |
| **B** 반응만 | **1,039** |
| **A+B** 수행 + 반응 | **898** |
| **C** 조건 참조만 | **84** |
| A+B+C | 58 |
| B+C | 50 |
| A+C | 47 |

합계: 수행하는 카드 **4,623장** · 반응하는 카드 **2,045장**.

### 9.3 실제 카드 다섯 장 (`test_16`)

이름으로 추론하지 않고 Lua · 파서 `code` · 등재 상태를 **한 장씩 읽었다.**

#### ① 83764718 죽은 자의 소생 — 분류 **A · D**

| 항목 | 값 |
| --- | --- |
| card | 마법 |
| source (Lua) | `Duel.SpecialSummon(tc,SUMMON_WITH_MONSTER_REBORN,tp,tp,false,false,POS_FACEUP)` |
| operation 표현 | `EFFECT_LIBRARY` 에 **있다** — `operations=()` |
| condition 표현 | 없다 (`activation` 없음) |
| event 표현 (`code`) | `EVENT_FREE_CHAIN` — **유발 조건 없음** |
| trigger 표현 | 없다 |
| executable | **False** |
| LIVE / DORMANT | LIVE 목록에 실려 있고 **실행되지 않는다** |
| validation | 발동 후보가 되지 않는다 (구현 없음) |

> **이 항목이 이 Phase 의 데이터 계층 답이다.** "아직 안 했다" 가 아니라
> **읽고 나서 거절했다** — 거절 이유가 둘 다 적혀 있다:
> `IsCanBeSpecialSummoned` (소환 조건 판정 계층이 없다) 와 `POS_FACEUP`
> (표시 형식 선택, STRUCTURAL-61).
> 실행 불가 항목은 16개 중 **3개**이고 (블랙홀 · 죽은 자의 소생 · 로스트),
> 각자 이유가 적혀 있다.

#### ② 23434538 증식의 G — 분류 **B**

| 항목 | 값 |
| --- | --- |
| card | 몬스터/효과 |
| event 표현 (`code`) | `EVENT_FREE_CHAIN` · **`EVENT_SPSUMMON_SUCCESS`** · **`EVENT_SPSUMMON_SUCCESS`** · `EVENT_CHAIN_SOLVED` |
| 등재 | **없다** |
| 필요한 것 | 특수 소환 사건 + **누가** 했는가 + 체인 해결 사건 |

**구현하지 않았다** (§13 · §20). 요구사항 예시로만 읽었다.

#### ③ 1005587 연옥의 함정 속으로 — 분류 **B** (함정)

| 항목 | 값 |
| --- | --- |
| card | **함정** |
| event 표현 (`code`) | **`EVENT_SPSUMMON_SUCCESS`** · `EFFECT_DISABLE` |
| 등재 | 없다 |
| LIVE | **범위 밖** — 함정 발동은 `TRAP_TRIGGER_MISSING` 으로 `UNKNOWN` (3-F-4) |

같은 사건에 반응하는 **함정**을 일부러 넣었다. 3-F-4 가 측정한 함정 경계가
특수 소환 사건에도 그대로 걸린다는 것을 보이기 위해서다.

#### ④ 10117149 분보그005 — 분류 **A + B + 정적 제약**

| 항목 | 값 |
| --- | --- |
| source (Lua) | `Duel.SpecialSummon(` **그리고** `EVENT_SPSUMMON_SUCCESS` |
| event 표현 (`code`) | `EFFECT_CANNOT_SPECIAL_SUMMON` · `EVENT_SUMMON_SUCCESS` · **`EVENT_SPSUMMON_SUCCESS`** · `EFFECT_UPDATE_ATTACK` · `EVENT_DESTROYED` |
| 등재 | 없다 |

한 장에 **제약 · 일반소환 사건 · 특수소환 사건 · 지속 수치 · 파괴 사건**이
다 들어 있다. `code` 한 칸이 다섯 가지 다른 성격을 나른다.

#### ⑤ 10065487 낙인상실 — 분류 **C · D** (가장 중요한 반례)

| 항목 | 값 |
| --- | --- |
| card | 마법 |
| source (Lua) | `Duel.SpecialSummonStep(` **그리고** `IsSpecialSummoned` |
| event 표현 (`code`) | `EVENT_FREE_CHAIN` · `EVENT_PHASE` — **`SPSUMMON` 이 한 글자도 없다** |
| 등재 | 없다 |

> **`code` 를 Operation 으로 읽으면 틀린다.** 이 카드는 특수 소환을
> **수행하고** 특수 소환 여부를 **조건으로도 참조**하는데, 파서가 뽑아내는
> `code` 에는 그 사실이 전혀 없다. `code` 는 "이 효과 블록이 **언제
> 걸리는가**" 이고 "**무엇을 하는가**" 가 아니다.

다섯 장 중 **등재된 것은 죽은 자의 소생 하나**뿐이다.

---

## 10. LIVE / DORMANT 경계

| 모듈 | production importer | 성격 |
| --- | --- | --- |
| `engine/activation_timing.py` | `duel.py` | **LIVE** — `TimingPoint` 를 import 하고 `point` 칸을 갖는다 (쓰지 않는다) |
| `engine/trigger.py` | `activation_timing` · `event_pipeline` · `timing` · `trigger_chain` · `trigger_order` | 어휘만 LIVE 로 새어 나간다 |
| `engine/event_pipeline.py` | **0** | DORMANT |
| `engine/timing.py` | **0** | DORMANT |
| `engine/trigger_chain.py` | `timing.py` | DORMANT |
| `engine/trigger_order.py` | `timing.py` · `trigger_chain.py` | DORMANT |

- `engine/special_summon.py` 와 `engine/summon.py` 는 **LIVE** 다 —
  `duel_executor()` 가 `SpecialSummonHandler` 를 등록하고 `Duel` 이 그것을
  쓴다.
- `agent/` 다섯 모듈은 `engine.trigger` · `engine.event_pipeline` ·
  `SummonKind` · `MonsterSummoned` · `SPECIAL_SUMMON` 을 **하나도** 모른다
  (`test_19`).

### 3-E dormant 구조와의 관계 (§10 의 핵심 질문)

> "이 dormant 구조가 SPECIAL_SUMMON event 를 표현하기 위한 **완성된 데이터
> 구조**인가, 아니면 **일부만 존재하는 설계 잔재**인가?"

**답: 둘 다 아니다. 사건 쪽은 완성되어 있고, 선언 쪽은 특수 소환을 가리킬
수 없다.** 그리고 그 결함이 `UNKNOWN` 이 아니라 **확신 있는 승인**으로
나타난다.

#### 사건 쪽 — 완성되어 있다

`test_06` · `test_08` 이 실제로 `ActionExecution` → `ObservedEvent` →
`TriggerCandidate` 를 만들어 냈다. 새 자료 구조가 하나도 필요하지 않았다.

#### 선언 쪽 — 특수 소환을 **가리킬 수 없다** (`test_13`)

셋이 겹친다.

1. `TriggerSpec` 의 필드는 정확히 아홉 개이고
   (`effect_ref · point · requirement · wording · operations · from_zones ·
   to_zones · activates_from · condition`) **소환 종류를 적을 칸이 없다.**
2. `MONSTER_SUMMONED` 시점에는 기존 세 필터조차 **금지**된다 —
   `__post_init__` 이 `TriggerError` 를 던진다
   ("`monster_summoned` 시점에는 `operations` 를 걸 수 없습니다. 카드
   이동이 아닌 사건입니다").
3. 그래서 `matches()` 는 `point` 하나만 비교하게 되고, `actor` 도 보지
   않는다 (그 함수 본문을 AST 로 떼어내 `"actor"` 와 `"summon"` 이 **없음**을
   확인했다).

실측:

| 사건 | `delta.summon` | `actor` | 하나의 선언이 잡는가 |
| --- | --- | --- | --- |
| 내 일반 소환 | `normal` | 0 | **잡는다** |
| 내 특수 소환 | `special` | 0 | **잡는다** |
| 상대 특수 소환 | `special` | 1 | **잡는다** |

#### 🔴 그 결과가 `UNKNOWN` 이 아니다 (`test_14`)

dormant 다섯 관문 중 `EVENT_RELATION` 을 세 경우에 대해 실제로 돌렸다.

| 경우 | `EVENT_RELATION` |
| --- | --- |
| 내 일반 소환 | `VALID` / `OK` |
| 내 특수 소환 | `VALID` / `OK` |
| 상대 특수 소환 | `VALID` / `OK` |

**셋 다 똑같다.** "상대가 특수 소환했을 때" 를 뜻하는 선언이 있었다면,
**내 일반 소환에도 승인이 난다.**

이것이 왜 "일부만 있다" 보다 나쁜가: Phase 3-E-45 가 `_event_relation` 에
세 번째 답을 만들어 두었다 — 선언이 적어 둔 필터를 사건에서 **읽을 수 없으면**
`UNKNOWN / INFORMATION_UNAVAILABLE` 을 낸다. 그 정직한 길이 여기서는
**닿을 수 없다.** 적을 칸이 없으므로 "적었는데 읽을 수 없다" 가 성립하지
않고, `unreadable` 이 빈 채로 `matches()` 가 `True` 를 낸다.

> 즉 dormant 구조는 **설계 잔재가 아니고 완성품도 아니다.** 사건을 나르는
> 절반은 제대로 서 있고, 선언이 사건을 **좁히는** 절반이 `CARD_MOVED`
> 전용으로만 지어져 있다. 특수 소환은 `CARD_MOVED` 가 **아니도록** 일부러
> 갈라 놓은 사건이므로 (ADR-002 와 같은 이유), 그 결정의 대가를 선언 쪽이
> 아직 치르지 않았다.

**그러므로 "dormant 이므로 필요하다" 고 결론내리지 않는다.** 지금 필요한
것은 연결이 아니라, 선언이 소환 종류와 행위자를 **적을 수 있게** 되는 일이고,
그것은 Engine V1 의 자료 구조 변경이다 (§11).

---

## 11. 증G / 후와로스 / 드롤 요구사항과의 관계 (§13)

세 카드 모두 **구현하지 않았다.** 각자 무엇을 요구하는지만 `code` 로 읽었다
(`test_17`). 셋이 요구하는 것이 **서로 다르다.**

| 카드 | `code` | 필요한 것 |
| --- | --- | --- |
| 증식의 G (23434538) | `EVENT_SPSUMMON_SUCCESS` ×2 · `EVENT_CHAIN_SOLVED` | ① 특수 소환 사건 ② **누가** 했는가 ③ 체인 해결 사건 |
| 마루챠미 후와로스 (42141493) | `EVENT_SPSUMMON_SUCCESS` · `EFFECT_CANNOT_ACTIVATE` · `EVENT_PHASE` · `EVENT_CHAIN_SOLVED` ×2 | 위 셋 + **정적 제약** + 페이즈 사건 |
| 드롤 & 로크 버드 (94145021) | **`EVENT_CUSTOM`** · `EFFECT_CANNOT_TO_HAND` · `EFFECT_CANNOT_DRAW` | **특수 소환과 무관** — 스크립트가 자기 사건을 직접 만든다 |

드롤의 `code` 에는 `SPSUMMON` 이 **한 글자도 없다.** 프롬프트가 말한 대로
"특수소환이 아니라 card acquisition 관련 event/condition" 이고, 측정이
그것을 확인했다.

### 엔진에 대응 이름이 없는 것

`TimingPoint` 는 여덟 개다 (`card_moved · card_drawn · life_changed ·
effect_resolved · cost_paid · monster_summoned · phase_changed ·
unimplemented`).

| 공식 `code` | 엔진 대응 |
| --- | --- |
| `EVENT_SPSUMMON_SUCCESS` | `MONSTER_SUMMONED` (**종류를 좁힐 수 없다**) |
| `EVENT_CHAIN_SOLVED` | **없다** — `EFFECT_RESOLVED` 는 효과 하나의 해결이고 체인 전체가 아니다 |
| `EVENT_CUSTOM` | **없다** — 스크립트가 만드는 사건을 받을 자리가 없다 |
| `EVENT_PHASE` | `PHASE_CHANGED` (단 "스탠바이에" 같은 타이밍 규칙은 없다) |
| `EFFECT_CANNOT_ACTIVATE` 등 정적 제약 | **사건 계층의 일이 아니다** — 별개 축 |

**이 셋 중 어느 것도 "특수소환 사건 하나" 로 환원되지 않는다.** 패트랩을
범위 밖에 둔 판단이 측정으로 지지된다.

---

## 12. Evaluation / Search 와의 분리 (§12)

- `agent/evaluation.py` **변경 0** · Search **변경 0** · weight 결정 **없음**.
- `OpponentResourceFeature` 를 건드리지 않았다.
- 3-F-3 의 weight 결론과 3-F-4 의 네 단계 분리를 **다시 측정하지 않았다.**
- 탐색 순위를 **실제로 돌려** 못박았다 (`test_19`): 6판 **611결정**,
  digest `30fa3597a24d4511d8c92ce9f9921412ffada7546675c4d7d5765381402c4175`,
  두 번 돌려 동일.
- `agent/` 다섯 모듈에 `engine.trigger` · `engine.event_pipeline` ·
  `SummonKind` · `MonsterSummoned` · `SPECIAL_SUMMON` 이 **하나도 없다.**

금지 항목 전부 미실행: W 숫자 확정 없음 · board/LP weight 변경 없음 ·
ranking/depth/algorithm 변경 없음 · 카드별 hardcode 없음.

---

## 13. hidden information (§14)

`test_18` — **상대의** 특수 소환을 내 관측으로 읽었다.

| 확인 | 결과 |
| --- | --- |
| 사건의 `actor` | `1` (상대) — 공개 사실이다 |
| `delta.summon` | `special` |
| 소환된 카드를 내가 보는가 | **본다** — `MZONE` 에 앞면으로 나왔으므로 공개 정보다 |
| 상대의 **남은 패** | `concealed=True` · `cards == ()` · `size` 만 읽힌다 |

3-F-2 가 세운 경계와 **같다**: 장수는 공개, 내용은 가려짐. 숨은 패 접근 ·
덱 내용 접근 · 카드 신원 추정 · Opponent Model 은 하나도 하지 않았다.

---

## 14. state_hash / RNG (§15)

| 확인 | 결과 |
| --- | --- |
| 사건을 **읽는** 일이 판을 바꾸는가 | 아니다 — `state_hash` 불변 (`test_18`) |
| 사건을 읽는 일이 난수를 쓰는가 | 아니다 — `rng` 표현 불변 (`test_18`) |
| **실패한** 특수 소환이 판을 바꾸는가 | 아니다 — `state_hash` 불변 (`test_11`) |
| 성공한 소환이 **원본** 판을 바꾸는가 | 아니다 — 사본에서만 (`test_04`) |
| `state_hash` / RNG semantics 변경 | **없음** (production diff 0) |

`EventReader` 는 `GameStateView` 만 받는다 — `GameState` 를 넘기면
`TypeError` 를 던지므로 "사건을 읽는 일이 판을 바꿀" 구조적 여지가 없다.

---

## 15. 테스트 결과

### 새 테스트 — `tests/test_special_summon_event_foundation_audit.py` 19건

| # | 이름 | §16 항목 |
| --- | --- | --- |
| 01 | the operation kind is a job not an event | 1 · 12 |
| 02 | summon kind says which summon and only that | 2 |
| 03 | monster summoned is the fact not the job | 3 |
| 04 | the operation actually changes the board | 4 |
| 05 | the mutation leaves a special summon delta | 5 |
| 06 | the delta becomes an event without anything new | 6 |
| 07 | the event keeps the summon kind but exposes no way to read it | 7 |
| 08 | the event does reach a trigger candidate | 8 |
| 09 | **the live duel drops the delta at its own door** | 9 |
| 10 | the live gate refuses a special summon and says unknown | 10 |
| 11 | a failed special summon leaves no event at all | 11 |
| 12 | no registered effect performs a special summon | 1 · 12 |
| 13 | **a declaration cannot say special nor whose** | 12 |
| 14 | **the dormant gate answers valid for all three** | 9 · 12 |
| 15 | the script corpus separates events from restrictions | — (§5) |
| 16 | five real cards show the four relationships | — (§5) |
| 17 | the three example cards need three different things | — (§13) |
| 18 | reading summon events breaks no boundary | 13 · 14 · 15 |
| 19 | this phase changed no production code and no ranking | 16 |

```
$ python3 -m pytest tests/test_special_summon_event_foundation_audit.py -p no:randomly -q
19 passed in 10.87s
```

### 고의 위반 검증 — 7건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `MONSTER_SUMMONED` 시점에 필터를 허용한다 | `test_13` |
| 2 | `TimingEvent` 에 `summon` 접근자를 더한다 | `test_07` |
| 3 | 등재 효과 하나를 `SPECIAL_SUMMON` 연산으로 바꾼다 | `test_12` |
| 4a | 검증기에서 `UnimplementedRule` 요구를 뺀다 | `test_10` |
| 4b | `SPECIAL_SUMMON` 을 `_COMPLETE_RULES` 에 넣는다 | `test_10` |
| 5 | `DuelStep` 에 `deltas` 칸을 더한다 | `test_09` |
| 6 | `MonsterSummoned` 를 `CARD_MOVED` 로 옮긴다 | `test_06` · `test_08` · `test_13` · `test_14` |

#### 4번이 처음에는 **빠져나갔다**

`UnimplementedRule` 요구를 떼어내도 19건이 전부 통과했다. `UNKNOWN` 을
지키는 자리가 **둘**인데 (`_MISSING_RULE` / `_COMPLETE_RULES` 쪽이 최종
결정권) `test_10` 이 하나만 보고 있었기 때문이다.

**테스트를 고쳤다** — 두 자리를 각각 못박아 4a·4b 가 **따로** 잡히게 했다.
production 은 고치지 않았다.

주입 파일 4개는 전부 백업에서 복원하고 md5 로 확인했다 (`trigger.py` ·
`effect/library.py` · `action_validation.py` · `duel.py` 모두 `OK`).

### 전체 회귀

```
$ python3 -m pytest tests/test_special_summon_event_foundation_audit.py -p no:randomly -q
19 passed in 10.87s

$ python3 -m pytest -p no:randomly -q
4196 passed, 4 skipped in 399.04s (0:06:39)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-4 직후 (baseline) | 4,177 | 4 |
| Phase 3-F-5 (이번) | **4,196** | 4 |
| 차이 | **+19** | 0 |

**+19 가 이번에 더한 시험 수와 정확히 같다.** skip 4건은 baseline 과 동일한
기존 skip 이다.

### 기존 테스트 처리

**수정 0건 · 삭제 0건 · skip 추가 0건 · assertion 약화 0건.**
production diff 가 0 이므로 기존 계약이 깨질 자리가 없었다.

---

## 16. production diff

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**0.** 추가한 것은 테스트 하나와 이 보고서뿐이다.

§19 가 요구한 대로, **필요하다고 판단했지만 하지 않은 변경**을 아래에
적는다.

| 하고 싶었던 것 | 왜 필요한가 | 왜 하지 않았는가 |
| --- | --- | --- |
| `SummonKind` · `TimingPoint.MONSTER_SUMMONED` docstring 정정 | 지금 문장이 사실과 다르다 (§4) | 주석도 production 파일 변경이다. AUDIT-ONLY |
| `TimingEvent.summon` 접근자 | delta 가 든 사실을 꺼낼 창구가 없다 (§7) | Engine V1 구조 변경. 고의 위반 2번으로 **금지 대상임을 확인**했다 |
| `TriggerSpec` 에 소환 종류 · 행위자 칸 | 선언이 사건을 좁힐 수 없다 (§10) | 같음. 이것이 다음 Phase 의 질문이다 |
| `DuelStep` 에 `deltas` | live 가 delta 를 버린다 (§6) | §11 이 `GameState`/live 경로 변경을 금지한다 |
| `legal_actions` 의 `withheld` 에 특수 소환 | 정직성 장치에 빠져 있다 (§8) | §11 이 금지한다 |

---

## 17. 최종 판정

### **B. SPECIAL_SUMMON_EVENT_FOUNDATION_PARTIAL**

근거:

1. **Operation 과 Event 는 이미 충분히 구분되어 있다.** 세 어휘가 서로 다른
   타입이고 (`OperationKind` · `PlayerActionKind` · `TimingPoint`),
   `MonsterSummoned` 는 효과의 어휘를 일부러 달지 않으며, 성공한 소환만
   사건이 된다. 이 축에서는 A 라고 말할 수 있다.
2. **그런데 Event → Trigger 가 실제로 연결되지 않는다** — 그것이 B 의
   조건이다. 두 군데가 각각 다른 이유로 끊긴다.
   - **production 연결 없음**: `Duel` 이 `ActionExecution` 을 받고 delta 를
     버린다. `DuelStep` 에 칸이 없고 `EventReader` 를 부르지 않는다.
     이것은 자료 구조 문제가 **아니다** (§6 이 같은 구조로 전 경로를 실제로
     통과시켰다).
   - **선언 불가**: `TriggerSpec` 이 소환 종류도 행위자도 적을 수 없고,
     그 결과가 `UNKNOWN` 이 아니라 **`VALID/OK`** 로 나온다 (§10).
3. **누락 지점이 정확히 식별되었다** — B 의 두 번째 조건.
   - `engine/trigger.py` `TriggerSpec` — 종류 · 행위자 칸 없음, 필터 금지
   - `engine/trigger.py` `TimingEvent` — `summon` 창구 없음
   - `engine/duel.py` `DuelStep` — `deltas` 칸 없음
   - `engine/duel.py` `_activation_gate` — `ActivationTiming.point` 를 채우지
     않음 (소켓은 이미 있다)
   - `engine/duel.py` `legal_actions` — 특수 소환을 후보도 보류도 만들지 않음
   - `engine/effect/library.py` — `SPECIAL_SUMMON` 을 쓰는 등재 효과 0개
     (죽은 자의 소생은 **읽고 거절**한 상태로 실려 있다)

### 왜 A 가 아닌가

A 는 "Event/Timing/Trigger 계층으로 연결할 데이터 foundation 이 **이미**
존재한다" 를 요구한다. 사건을 **나르는** 데이터는 존재한다. 그러나 선언이
사건을 **좁히는** 데이터가 존재하지 않고, 그 부재가 조용한 오답을 만든다
(`test_14`). "연결만 하면 된다" 가 아니므로 A 라고 적으면 거짓이 된다.

### 왜 C 가 아닌가

C 는 "production scenario 로 만들려면 Engine V1 변경이 필요하다" 다.
그것은 **사실이지만** (§16 의 표가 변경 다섯 가지를 적고 있다), C 를 고르면
"무엇이 없는지는 아직 모른다" 로 읽힌다. 이번 Phase 는 누락 지점을 정확히
짚었고, 그것이 B 와 C 를 가르는 기준이다. Engine V1 변경 필요성은 B 의
결론 **안에** 적어 둔다.

### 왜 D 가 아닌가

예상 밖의 더 큰 구조 문제는 없었다. §10 의 `VALID/OK` 는 **예상보다 나쁜
답**이지만, 그 원인(`CARD_MOVED` 전용으로 지어진 필터)이 기존 설계 결정의
직접적 대가로 설명되고 새로운 모순이 아니다.

---

## 18. 다음 Phase 후보 (1개)

**Phase 3-F-6 — `TriggerSpec` 이 소환 종류와 행위자를 선언할 수 있는가:
자료 구조 설계 감사**

§10 이 짚은 **하나**만 본다. 이 Phase 가 "production 연결" 과 "선언 불가"
둘을 발견했는데, 연결은 선언이 가능해진 **뒤**에만 의미가 있다 — 지금
연결하면 §10 의 `VALID/OK` 가 그대로 production 에 들어간다.

그 Phase 가 답해야 할 것:

1. 소환 종류를 선언에 적는 방법이 **몇 가지**인가 — `TriggerSpec` 에 칸을
   더하는 것 · `condition` 으로 미는 것 · `TimingPoint` 를 쪼개는 것.
   각자 무엇을 깨뜨리는지 측정한다 (`TimingPoint` 쪼개기는 `MONSTER_SUMMONED`
   를 쓰는 기존 테스트를 건드린다).
2. 행위자("상대가") 를 어디서 비교해야 하는가 — `matches()` 인가
   `_event_relation` 인가. 둘은 성격이 다르다 (데이터 비교 vs 관문 판정).
3. 적을 수 있게 되면 `_event_relation` 의 **3-E-45 세 번째 답**
   (`UNKNOWN/INFORMATION_UNAVAILABLE`) 에 실제로 닿는가. 닿지 않으면
   종류 칸을 더해도 조용한 오답이 남는다.
4. `__post_init__` 의 "`CARD_MOVED` 가 아니면 필터 금지" 가 **왜** 그렇게
   적혔는지 다시 읽는다 — 그 금지가 지키려던 것을 깨지 않는 설계여야 한다.

**이 Phase 는 그 작업을 하지 않았다. 다음 Phase 는 임의로 진행하지 않는다.**
