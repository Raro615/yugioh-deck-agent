# Duel Engine 설계

**기준 커밋:** `9202bd2` (Add an incremental card data update pipeline)
**상태:** 설계 단계. 구현 전.

이 문서는 현재 저장소의 카드 데이터와 Effect Analysis 계층 위에 듀얼 엔진을
어떻게 올릴지 정한다. 모든 수치는 추정이 아니라 저장소의 실제 데이터를
측정한 값이다.

---

## 목차

1. [현재 코드 구조 분석](#1-현재-코드-구조-분석)
2. [발견된 구조적 결함](#2-발견된-구조적-결함)
3. [전체 아키텍처](#3-전체-아키텍처)
4. [모듈 구조](#4-모듈-구조)
5. [GameState](#5-gamestate)
6. [Card Definition / Card Instance](#6-card-definition--card-instance)
7. [Event / Context](#7-event--context)
8. [Condition Evaluator](#8-condition-evaluator)
9. [Action / Legal Action](#9-action--legal-action)
10. [Legal Action 생성](#10-legal-action-생성)
11. [Effect Resolution](#11-effect-resolution)
12. [Chain](#12-chain)
13. [State Transition](#13-state-transition)
14. [Summon System](#14-summon-system)
15. [지속 효과](#15-지속-효과)
16. [AI 경계](#16-ai-경계)
17. [구현 로드맵](#17-구현-로드맵)
18. [테스트 전략](#18-테스트-전략)
19. [위험 요소](#19-위험-요소)
20. [Phase 1 최소 범위](#20-phase-1-최소-범위)

---

## 1. 현재 코드 구조 분석

실측 6,654줄. 재사용 가능성으로 분류했다.

| 모듈 | 줄 수 | 엔진에서의 위치 | 판정 |
|---|---:|---|---|
| `core/constants.py` | 373 | TYPE/RACE/ATTRIBUTE 비트마스크 | **그대로 사용** |
| `sources/script_constants.py` | 110 | **엔진 어휘 988개** | **그대로 사용** |
| `core/card_model.py` | — | 카드 **정의** | **읽기 전용 참조** |
| `core/card_repository.py` | — | 정의 저장소 + 인덱스 | **읽기 전용 참조** |
| `analysis/effect_model.py` | 622 | 효과 명세 | **입력 데이터** |
| `analysis/predicate_model.py` | 182 | 조건 술어 + readiness | **Evaluator 입력** |
| `analysis/effect_analyzer.py` | 855 | Lua 심층 분석 | **입력 데이터** |
| `core/provenance.py` | 238 | 출처 · `AnalysisStatus` | **권위 판정에 사용** |
| `analysis/relationship.py` | 285 | 카드 관계 | 엔진 불필요 (AI 계층용) |
| `core/card_search.py` | — | 검색 | **엔진 불필요** |
| `core/query_parser.py` | 589 | 한국어 질의 | **엔진 불필요** |

### 핵심 발견: 어휘가 이미 있다

`ScriptConstants.others` 에 EDOPro 엔진 상수 **988개**가 이미 로드되어 있다.

| 접두사 | 개수 | 용도 |
|---|---:|---|
| `LOCATION_*` | 22 | 존 |
| `POS_*` | 8 | 표시 형식 |
| `PHASE_*` | 10 | 페이즈 |
| `REASON_*` | 28 | 이벤트 원인 |
| `STATUS_*` | 31 | 카드 상태 |
| `SUMMON_TYPE_*` | 12 | 소환 종류 |
| `TIMING_*` | 28 | 발동 시점 |
| `RESET_*` | 20 | 효과 소멸 |

분석 계층이 내놓는 문자열(`'GRAVE'`, `'MZONE'`, `REASON_COST`)이 곧 엔진의
어휘다. **번역 계층이 필요 없다.** 이것이 이 설계의 핵심 전제다.

### 의존 / 독립 경계

| 엔진이 의존 (읽기 전용) | 엔진이 소유 |
|---|---|
| `CardRepository` → 카드 정의 | `GameState` 전체 |
| `EffectAnalyzer` → 효과 명세 | `CardInstance` 상태 |
| `ScriptConstants` → 엔진 어휘 | 규칙 판정 |
| `AnalysisStatus` → 권위 판정 | 이벤트 · 체인 |

엔진은 `core/` 와 `analysis/` 를 **수정하지 않는다**. 현재 `core/` 와
`sources/` 가 `analysis` 를 참조하지 않는 단방향 의존을 유지하고,
`engine/` 이 양쪽을 읽기만 한다.

---

## 2. 발견된 구조적 결함

설계가 반드시 다뤄야 할, 실측으로 확인한 문제.

### 결함 1 — 효과 식별자가 불안정하다

`EffectSpec.index` 가 카드 안에서 중복된다. 12,687장 중 **56장**.

```
이차원의 고전장－사르갓소 → ['e1', 'e2', 'e2']
```

체인 링크가 "어느 효과인가"를 가리켜야 하므로
**`EffectRef(card_id, ordinal)` 이라는 새 식별자가 필요**하다.

### 결함 2 — Card 는 가변이고 공유된다

```python
r.get(2511) is r.get(2511)   # True
```

`Card` 는 가변 dataclass 이고 리포지토리가 같은 객체를 돌려준다.
GameState 가 `Card` 를 직접 바꾸면 **전역 카드 정의가 오염된다.**
CardInstance 분리는 선택이 아니라 필수다.

### 결함 3 — 실행 파라미터가 대부분 부족하다

액션 + 선택 + 개수를 모두 갖춘 효과는 **25.4%** (1,608 / 6,339).
나머지는 "무엇을 하는지"는 알아도 "몇 장을 어떻게"를 모른다.

### 결함 4 — 조건을 완전히 판정할 수 있는 효과는 8.5%뿐

| 효과 단위 판정 가능성 | 건수 | 비율 |
|---|---:|---:|
| 조건 없음 (판정 불필요) | 14,727 | 55.9% |
| **전부 평가 가능** | **2,234** | **8.5%** |
| 문맥 필요 leaf 포함 | 3,580 | 13.6% |
| 미해석 leaf 포함 | 3,816 | 14.5% |
| 조건 있으나 트리 없음 | 1,995 | 7.6% |

**이 숫자가 설계 전체를 결정한다.** 조건 없음 + 전부 평가 가능 = **64.4%**
가 완전 판정 가능하고, 나머지 **35.6%** 는 3-값 논리로 다뤄야 한다.

### 부수 결함 — 타이밍 정보 미수집

`SetHintTiming` (퀵 효과 발동 시점) 을 현재 `EffectSpec` 이 수집하지 않는다.
표본 4,000장 중 **568장**이 사용한다. Phase 3.5 에서 보완한다.

---

## 3. 전체 아키텍처

```
Card Data (sources/)          ← 변경 없음
        ↓
Card Analysis (analysis/)     ← 변경 없음, 읽기 전용
        ↓
┌─────────────────────────────────────────┐
│ engine/                                 │
│   state     GameState · CardInstance    │
│   events    GameEvent · Context         │
│   rules     Evaluator · ActionGenerator │
│   exec      Executor · Chain · Summon   │
│   registry  카드별 구현 등록             │
└─────────────────────────────────────────┘
        ↓ legal actions        ↑ selected action
        AI (별도 패키지)
```

---

## 4. 모듈 구조

```
engine/
  vocabulary.py      ScriptConstants 를 Zone/Phase/Position/Reason 으로 노출
  ids.py             InstanceId · EffectRef          ← 결함 1 해결
  state/
    card_instance.py 듀얼 중 카드 상태 (정의는 참조만)
    zones.py         Zone 컨테이너
    player.py        PlayerState
    game_state.py    GameState (조립만, 규칙 없음)
    turn.py          턴 · 페이즈 진행
  events/
    event.py         GameEvent
    context.py       EventContext · ChainContext · EffectContext · ResolutionContext
    journal.py       이벤트 로그 (replay)
  rules/
    evaluator.py     조건 트리 → Tri-value
    legality.py      Action 검증
    generator.py     Legal Action 생성
    timing.py        Phase/Step/Priority
  exec/
    action.py        Action 정의
    executor.py      Action → StateDelta
    chain.py         Chain 처리
    summon.py        소환 시스템
    continuous.py    지속 효과 계층
  registry/
    effect_impl.py   카드별 효과 구현 등록          ← 결함 3 해결
  duel.py            퍼사드
```

---

## 5. GameState

거대 클래스를 피하기 위해 **상태(데이터)와 규칙(로직)을 분리**한다.
`GameState` 는 조립만 하고 규칙을 담지 않는다.

```
GameState
 ├ players: tuple[PlayerState, PlayerState]   # 인덱스 0/1 고정
 ├ turn: TurnState        (turn_number, turn_player, phase, step)
 ├ chain: ChainState      (links, 현재 처리 위치)
 ├ pending: list[GameEvent]
 ├ journal: EventJournal  (replay 근거)
 └ result: DuelResult | None

PlayerState
 ├ life_points: int
 └ zones: dict[Zone, ZoneContainer]
          DECK / HAND / EXTRA / MZONE / **EMZONE** / SZONE / GRAVE / REMOVED / FZONE / PZONE
```

> **구현과의 차이 (Phase 1 반영됨).** 설계 초안은 `PlayerState` 에
> `normal_summon_used` / `turn_flags` 를 두었지만, 실제 구현에서는 **뺐다.**
> "일반 소환을 몇 번 했는가", "이번 턴에 드로우했는가" 는 턴 진행 **규칙에
> 속하는 상태**다. Phase 1 에 넣어두면 규칙을 구현하기도 전에 규칙의 모양을
> 못박게 된다. Phase 4 의 타이밍 계층이 들어올 때 함께 정한다.
> `tests/engine/test_player_state.py::test_player_state_carries_no_rule_state`
> 가 이 필드들이 다시 생기지 않는지 감시한다.

### 엑스트라 몬스터 존은 별도 존이다

`EMZONE` 은 메인 몬스터 존과 **다른 존**이다 (`LOCATION_EMZONE = 0x1000`,
`LOCATION_MZONE = 0x4`). 같은 존으로 뭉뚱그리면 "엑스트라 덱 몬스터를 몇 장
놓을 수 있는가" 가 통째로 틀어진다. 칸 수도 5 와 1 로 다르다.

### 존은 두 종류다 — 순서 존과 칸 존

| 종류 | 존 | 성질 |
|---|---|---|
| `ORDERED` | DECK · HAND · EXTRA · GRAVE · REMOVED · OVERLAY | 순서가 의미를 갖고 칸 번호가 없다 |
| `SLOTTED` | MZONE(5) · EMZONE(1) · SZONE(5) · FZONE(1) · PZONE(2) | 칸이 고정. **가운데가 비어도 양옆이 밀려나지 않는다** |

칸 존에서 `sequence` 는 **칸 번호**다. 몬스터 존 1번이 비었다고 2번 몬스터가
1번으로 당겨지면 안 되므로, `ZoneContainer` 는 빈 칸까지 들고 있고
`canonical_state()` 도 빈 칸을 표현한다.

용량을 넘기면 `ZoneFull` 로 거부하는데, 이는 **규칙 판정이 아니라 표현 불가**를
알리는 것이다. "소환해도 되는가" 는 Phase 4 가 판정한다.

존마다 공개 범위(`ZoneVisibility`)도 선언한다 — DECK 은 `HIDDEN`,
HAND · EXTRA 는 `OWNER_ONLY`, 나머지는 `PUBLIC`. 개별 카드의 앞면/뒷면과는
별개의 값이다.

### once-per-turn 은 별도 레지스터

현재 분석이 `LimitScope` 를 세 가지로 구분한다. 키가 다르므로 한 곳에
뭉뚱그리면 안 된다.

| 스코프 | Lua | 건수 | 키 |
|---|---|---:|---|
| 카드 단위 | `SetCountLimit(1)` | 2,566 | `(player, instance_id)` |
| 카드명 단위 | `SetCountLimit(1,id)` | 5,399 | `(player, card_id)` |
| 효과 단위 | `SetCountLimit(1,{id,n})` | 2,478 | `(player, card_id, ordinal)` |

```
UseRegistry                      # engine/state/use_registry.py — GameState 가 하나만 소유
 ├ per_card:      dict[(player, instance_id), int]
 ├ per_card_name: dict[(player, card_id), int]
 └ per_effect:    dict[(player, card_id, ordinal), int]
```

> **구현과의 차이 두 가지 (Phase 1 반영됨).**
> 1. 설계 초안은 `set` 세 개였지만 실제로는 **횟수 카운터**다.
>    `SetCountLimit(2..4, ...)` 를 쓰는 효과가 실측 53건 있어서 "썼다/안 썼다"
>    로는 표현되지 않는다. "몇 번까지 허용인가" 는 여전히 Phase 4 다.
> 2. `per_card` 키에 `player` 를 넣었고, 레지스트리를 `PlayerState` 가 아니라
>    `GameState` 가 하나만 갖는다. 키가 전부 `(player, ...)` 로 시작하므로
>    플레이어마다 따로 둘 이유가 없고, 따로 두면 "상대의 카드명 제약" 을
>    볼 때 두 곳을 봐야 한다.
>
> `PerCardKey` 와 `PerCardNameKey` 는 둘 다 `(int, int)` 다. **한 딕셔너리에
> 담으면 "인스턴스 7번" 과 "카드 ID 7" 이 같은 칸을 쓴다.** 세 표를 반드시
> 분리해야 하는 이유다.
>
> 리셋 시점은 Phase 1 이 정하지 않는다. `clear()` 를 제공할 뿐이고, 턴이
> 넘어갈 때 부르는 것은 규칙이라 Phase 4 의 몫이다.

---

## 6. Card Definition / Card Instance

```
CardInstance
 ├ instance_id: InstanceId        # 듀얼 내 고유
 ├ card_id: int                   # CardRepository 조회 키 (정의를 복사하지 않음)
 ├ owner / controller: int
 ├ zone: Zone, sequence: int
 ├ position: int                  # POS_* 값 그대로
 ├ previous: PreviousState        # location / position / controller
 ├ counters: dict[str, int]
 ├ equipped_to: InstanceId | None
 ├ materials: list[InstanceId]
 ├ temporary_effects: list[AppliedEffect]
 └ status_flags: int              # STATUS_* 비트마스크
```

정의 접근은 프로퍼티로만 한다.

```python
@property
def definition(self) -> Card:
    return self._repository.get(self.card_id)   # 읽기 전용
```

`CardInstance` 는 `Card` 를 **복사하지도, 상속하지도, 변경하지도 않는다.**
결함 2 의 유일한 안전한 해법이다.

`previous` 는 장식이 아니다. 조건 술어 `previous_location` 758건,
`previous_position`, `previous_controller` 가 이 필드 없이는 평가 불가다.

---

## 7. Event / Context

현재 조건 술어가 요구하는 문맥을 역산해 설계한다.

| 술어 | 실측 건수 | 필요한 문맥 |
|---|---:|---|
| `group_exists` | 1,330 | `EventContext.event_group` |
| `battle` | 1,154 | `BattleContext` |
| `chain_effect_type` | 962 | `ChainContext.current_link.effect` |
| `player_comparison` | ~990 | `EffectContext.controller` + `GameEvent.player` |
| `event_reason` | 928 | `GameEvent.reason` |
| `previous_location` | 758 | `CardInstance.previous` |

```
GameEvent          무슨 일이 일어났는가
 ├ kind, reason (REASON_*), player
 ├ cards: list[InstanceId]
 ├ source_effect: EffectRef | None    ← "왜 발생했는가"
 └ snapshot: dict[InstanceId, PreviousState]

EventContext       eg / ep / ev / r / re / rp 대응
ChainContext       현재 체인, 링크 위치, 상대 효과
EffectContext      e / tp — 지금 평가 중인 효과
ResolutionContext  위 셋 + GameState 참조 (평가의 단일 진입점)
```

**Evaluator 는 `ResolutionContext` 하나만 받는다.** 문맥이 없으면
`UNKNOWN` 을 반환하지 조용히 `False` 가 되지 않는다.

---

## 8. Condition Evaluator

가장 중요한 부분. **`unknown` 을 임의로 true/false 로 처리하지 않는다.**

```
TriValue = TRUE | FALSE | UNKNOWN

AND:  하나라도 FALSE            → FALSE
      FALSE 없고 UNKNOWN 있음   → UNKNOWN
      전부 TRUE                 → TRUE

OR:   하나라도 TRUE             → TRUE      ← 단락 평가가 UNKNOWN 을 구제
      TRUE 없고 UNKNOWN 있음    → UNKNOWN
      전부 FALSE                → FALSE

NOT:  TRUE ↔ FALSE, UNKNOWN → UNKNOWN
```

OR 단락 평가가 중요하다. 현재 OR 노드가 **1,413개**이므로, 한 가지만
확실히 참이면 나머지가 미해석이어도 전체가 TRUE 가 된다. 조건 트리를
평탄화하지 않고 보존한 덕이다.

결과는 판정 근거를 함께 낸다.

```
ConditionVerdict
 ├ value: TriValue
 ├ certainty: CERTAIN | PLAUSIBLE | UNDECIDABLE
 ├ unknown_leaves: list[ConditionNode]   # 무엇 때문에 모르는가
 └ trace: list[LeafVerdict]              # AI 설명 · 학습용
```

AI 가 "확실히 합법 / 가능성 있음 / 판단 불가"를 구분하는 근거가 된다.

---

## 9. Action / Legal Action

```
Action (불변)
 ├ kind: ActionKind
 ├ player: int
 ├ source: InstanceId | None
 ├ effect: EffectRef | None
 ├ targets: tuple[InstanceId, ...]
 └ choices: tuple[Choice, ...]      # 비용 · 모드 선택
```

같은 Action 은 항상 같은 결과를 낸다 (결정론).

### 지금 가능한 것 / 나중 것

| 지금 (엔진 규칙만으로 가능) | 나중 (효과 구현 필요) |
|---|---|
| `Draw`, `Pass`, `EndPhase` | `Activate*` (효과 실행) |
| `NormalSummon`, `TributeSummon`, `Set` | `SpecialSummon` (효과 유래) |
| `FlipSummon`, `ChangePosition` | 체인 응수 |
| `DeclareAttack` | 소환법별 절차 |

### Action 이 아닌 것

`Destroy` / `Banish` / `AddToHand` / `Discard` / `Send` 는 **Action 이 아니라
효과의 결과**다. AI 가 고르는 것이 아니므로 `StateDelta` 로 표현한다.
이 구분을 흐리면 AI 가 규칙을 계산하게 된다.

---

## 10. Legal Action 생성

```
GameState
  → CandidateGenerator     phase / priority 로 후보 나열
  → CostChecker            비용 지불 가능한가
  → ConditionEvaluator     발동 조건 (3-값)
  → TargetResolver         대상 후보가 있는가
  → LegalAction 목록
```

각 단계는 **독립 함수**여야 테스트가 가능하다.

| 등급 | 조건 |
|---|---|
| `LEGAL` | 조건 TRUE + 비용 가능 + 대상 존재 |
| `PLAUSIBLE` | 조건 UNKNOWN, 나머지 충족 |
| `ILLEGAL` | 조건 FALSE 또는 비용 불가 |

기본 정책은 **`LEGAL` 만 반환**하고, AI 가 원하면 `PLAUSIBLE` 을 함께
요청한다. 미검증 행동이 조용히 합법으로 섞이지 않는다.

---

## 11. Effect Resolution

> "텍스트에 파괴한다고 적혀 있으니 파괴한다" — 이 구조는 만들지 않는다.

```
EffectRef
  → EffectRegistry.lookup()
      ├ 있으면 → EffectImplementation (카드별 검증된 구현)
      └ 없으면 → UnimplementedEffect (실행 거부)
  → ExecutionPlan
  → StateDelta
```

`EffectAnalysis` 는 **구현을 고르고 검증하는 데** 쓰고, 그 자체가 실행자가
되지 않는다. 결함 3 (파라미터 완전 25.4%) 이 그 근거다.

### 권위 판정 — 엔진이 강제한다

```python
if card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED:
    raise NotDuelReady(card_id)   # 실행 거부
```

| 상태 | 건수 | 듀얼 실행 |
|---|---:|---|
| `lua_verified` | 12,687 | 허용 |
| `text_derived` | 1,440 | **거부** |

`text_derived` 카드는 검색 · 덱 구성에는 쓰이지만 듀얼 실행에는 쓰이지
않는다. 엔진 진입점에서 차단하므로 하위 계층이 실수할 수 없다.

---

## 12. Chain

```
ChainLink
 ├ index: int
 ├ player: int
 ├ source: InstanceId
 ├ effect: EffectRef                   ← 결함 1 때문에 새 식별자 필요
 ├ targets, paid_costs
 ├ activation_context: EventContext    # 발동 시점 스냅숏
 └ status

ChainState
 ├ links: list[ChainLink]
 ├ resolving_index                      # 역순 처리
 └ pending_responses: list[int]
```

**발동 시점 문맥을 스냅숏으로 고정**하는 것이 핵심이다. 해결 시점에는
상태가 이미 바뀌어 있으므로, `IsPreviousLocation` 같은 조건은 스냅숏
없이 평가할 수 없다.

Legal Action 연결: `ChainState` 가 열려 있으면 후보 생성기가 퀵 효과 ·
카운터 함정만 나열한다. 여기서 `SetHintTiming` 미수집이 문제가 되므로
**Phase 3.5 에서 타이밍 수집을 먼저 추가**해야 한다.

---

## 13. State Transition

```
Action → validate() → plan() → apply() → StateDelta → events → GameState'
```

`GameState` 를 여기저기서 직접 바꾸지 않고 **`StateDelta` 만이 상태를
바꾼다.**

```
StateDelta
 ├ moves: list[ZoneMove]
 ├ attribute_changes, lp_changes
 ├ caused_by: Action | GameEvent
 └ events_emitted: list[GameEvent]
```

`EventJournal` 에 `(state_hash, action, delta, state_hash')` 를 기록하면
**결정론적 replay** 가 성립한다. 난수(주사위 · 동전)는 seed 를 journal 에
넣어 재현한다.

---

## 14. Summon System

소환법마다 조건이 다르므로 **공통 인터페이스 + 절차별 구현**으로 둔다.

```
SummonProcedure (프로토콜)
 ├ summon_type: int              # SUMMON_TYPE_* 그대로
 ├ can_perform(state, instance) -> TriValue
 ├ enumerate_materials(state, instance) -> list[MaterialChoice]
 └ build_plan(state, instance, choice) -> ExecutionPlan
```

현재 데이터가 소환법 식별을 돕는다.

- `type_mask` 로 FUSION / SYNCHRO / XYZ / LINK / RITUAL 구분
- 소환 절차 헬퍼가 이미 수집됨: `PROC_ADDPROCEDURE` 1,789 ·
  `PROC_ADDPROCMIX` 323 · `PROC_ADDEQUIPPROCEDURE` 242 등
- 등록 효과 안의 소환 절차 605건은 발동 효과가 아니므로 Action 생성에서 분리

구현 순서: **Normal → Tribute → Flip → 일반 Special → Ritual → Fusion →
Synchro → Xyz → Link**. 앞의 넷은 카드별 구현이 거의 필요 없고, 뒤로
갈수록 소재 조합 탐색이 커진다.

---

## 15. 지속 효과

```
ContinuousEffectLayer
 ├ 등록된 지속 효과 (조건 + 적용 범위 + 변경)
 ├ recompute(state) -> DerivedState
 └ 상태가 바뀔 때마다 재계산 (캐시)
```

`DerivedState` 는 원본 상태와 **분리**한다. 공격력 증가를 `CardInstance` 에
직접 쓰면 효과가 사라질 때 되돌릴 수 없다.

| 효과 종류 | 처리 |
|---|---|
| Continuous | 파생 상태 재계산 |
| Replacement | 이벤트 발생 전 가로채기 |
| Triggered | 이벤트 → 체인 후보 |
| Ignition / Quick | Action 후보 |

분석 계층의 `EffectSpec.effect_types`
(SINGLE / FIELD / CONTINUOUS / TRIGGER_O / QUICK_O / IGNITION) 가
**이미 이 분류를 제공한다.**

---

## 16. AI 경계

```
GameState(읽기 전용 뷰) → LegalActions → AI → Action → Engine → GameState'
```

세 가지를 강제한다.

1. AI 에는 **읽기 전용 뷰**만 넘긴다 (`GameStateView`)
2. AI 는 `Action` 객체만 돌려준다 — 상태를 만들지 않는다
3. 규칙 계산은 전부 엔진 안에 있다

| AI 종류 | 필요한 접점 |
|---|---|
| Rule-based | `LegalActions` 직접 |
| MCTS | `apply()` 결정론 + `clone()` |
| RL | `GameStateView` 인코딩 + `StateDelta` 보상 |
| LLM | `ConditionVerdict.trace` · `describe_ko()` 가 설명 재료 |

---

## 17. 구현 로드맵

| Phase | 내용 | 의존 | 검증 기준 |
|---|---|---|---|
| **1** | 어휘 · ID · CardInstance · Zone · Player · GameState · Turn/Phase | 없음 | 카드 정의 불변, 존 이동 정확 |
| **2** | Event · Journal · StateDelta · 기본 Action · 결정론 replay | 1 | 같은 입력 → 같은 출력 |
| **3** | ConditionEvaluator (3-값) | 1, analysis | `evaluable` 8.5% 정확 판정 |
| **3.5** | **`EffectSpec` 에 `SetHintTiming` 수집 추가** | analysis 수정 | 퀵 효과 시점 판단 |
| **4** | LegalActionGenerator + Cost / Target | 2, 3 | 등급 구분 동작 |
| **5** | Chain | 4 | 체인 순서 · 스냅숏 |
| **6** | EffectRegistry + Executor (소수 카드) | 5 | `text_derived` 차단 |
| **7** | Summon System | 6 | 소환법별 |
| **8** | Continuous / Replacement | 7 | 파생 상태 |

Phase 3.5 만 `analysis/` 를 건드리고, 나머지는 `engine/` 신규 파일이다.

---

## 18. 테스트 전략

기존 218개를 유지하면서 `tests/engine/` 을 별도로 둔다.

| 층 | 내용 |
|---|---|
| 단위 | Zone 이동, TriValue 진리표, UseRegistry 스코프 |
| 시나리오 | 실제 카드로 소환 · 발동 · 체인 |
| 결정론 | 같은 초기 상태 + 같은 Action 열 → 같은 최종 상태 해시 |
| Replay | Journal 재생 결과 일치 |
| 회귀 | 카드 정의 불변 (`repository.get(id)` 비교) |

**결정론 테스트가 가장 중요하다.** `GameState` 에 정규 해시를 두고,
난수는 seed 로 재현한다.

### `state_hash()` 가 지켜야 하는 것 (Phase 1 구현 결과)

`InstanceId` 는 **만들어진 순서**를 담는다. 그 값을 그대로 해시에 넣으면
"같은 판이지만 카드를 다른 순서로 놓아 만든 상태" 가 다른 해시를 갖는다.
그래서 해시 직전에 정해진 순회 순서(플레이어 → `PLAYER_ZONES` 순 → 존 안의
순서 → 그 카드의 소재)대로 **0 부터 다시 번호를 매긴다**
(`GameState.instance_numbering()`). 원본 `instance_id` 는 손대지 않는다.

`UseRegistry.per_card` 의 키에도 `instance_id` 가 들어 있으므로 같은 함수로
바꿔 넣는다. 그러지 않으면 인스턴스 배정 순서가 레지스트리를 통해 해시에
새어 나온다.

해시에 **넣지 않는 것**: `InstanceIdAllocator` 의 다음 번호, `seed`, 난수원의
내부 상태. 전부 논리적인 판 상태가 아니다 — 같은 판이면 어떤 seed 로
도달했든 같은 해시다.

### 무작위는 주입된 seed 에서만 나온다

`GameState.create(..., seed=1234, shuffle=True)` 만 셔플한다. 기본값은
받은 순서 그대로다.

- `shuffle=True` 인데 `seed` 가 없으면 `ValueError` 로 **거부한다.**
  재현할 수 없는 상태를 조용히 만들지 않는다.
- 전역 `random` 을 쓰지 않는다. 듀얼마다 `random.Random(seed)` 를 하나 갖고,
  seed 없이 `state.rng` 를 꺼내려 하면 `RuntimeError` 다.
- `clone()` 은 난수원을 **상태째 복제**한다. 사본에서 셔플해도 원본의 다음
  난수는 변하지 않는다.

### `clone()` 과 `InstanceId`

사본은 같은 세계의 사본이므로 `instance_id` 값을 **바꾸지 않는다.** 그래야
사본으로 수를 읽어본 뒤 원본에 같은 `InstanceId` 로 지시할 수 있다. 할당기도
함께 복제해서 두 갈래가 같은 다음 번호에서 이어간다 — 갈라진 세계선끼리
번호가 겹치는 것은 충돌이 아니다.

---

## 19. 위험 요소

| 위험 | 근거 | 완화 |
|---|---|---|
| **효과 구현이 병목** | 파라미터 완전 25.4% | 레지스트리로 카드별 점진 추가. 미구현은 명시적 거부 |
| **조건 판정 불가 35.6%** | 실측 | 3-값 논리 + 등급. 절대 추측하지 않음 |
| **효과 식별자 부재** | `EffectSpec.index` 중복 **4,883장** (초안의 56장은 오기) | Phase 1 에서 `EffectRef(card_id, ordinal)` 도입 |
| **카드 정의 오염** | Card 가변 · 공유 | CardInstance 분리 + 회귀 테스트 |
| **타이밍 정보 없음** | `SetHintTiming` 미수집 | Phase 3.5 |
| **지속 효과 재계산 비용** | 매 상태 변화마다 | 파생 상태 캐시 + 무효화 |
| **범위 폭발** | 14,127장 전체 구현은 비현실적 | **특정 덱(예: 라뷰린스 15장)부터** |

---

## 20. Phase 1 최소 범위

**목표:** 규칙 판정 없이, 듀얼 상태를 **정확하고 불변하게** 표현한다.

### 포함

| 파일 | 내용 |
|---|---|
| `engine/vocabulary.py` | `ScriptConstants` 를 Zone/Phase/Position/Reason 으로 노출 (새로 정의하지 않음) |
| `engine/ids.py` | `InstanceId`, `EffectRef(card_id, ordinal)` |
| `engine/state/card_instance.py` | 정의는 프로퍼티 참조, 상태만 소유 |
| `engine/state/zones.py` | 존 컨테이너, 순서 보존 이동 |
| `engine/state/player.py` | LP 와 존 10 개. 규칙 상태는 담지 않는다 |
| `engine/state/use_registry.py` | `UseRegistry` 3-스코프 (듀얼 전체에 하나) |
| `engine/state/game_state.py` | 조립 + `clone()` + `state_hash()` + seed |
| `engine/state/turn.py` | 턴 · 페이즈 진행 (효과 없음) |

### 제외

Action · 조건 평가 · 체인 · 효과 실행 · 소환법 · 지속 효과

### 완료 기준

1. 덱 40장으로 초기 상태 생성 → 5장 드로우 → 존 수량이 정확
2. 카드를 존 사이로 옮겨도 `repository.get(id)` 가 **변하지 않음**
3. `clone()` 후 원본과 사본이 서로 영향 없음
4. 같은 조작 순서 → 같은 `state_hash()`
5. `state_hash()` 가 `instance_id` **배정 순서에 좌우되지 않음**
6. `setup(seed=1234)` 를 두 번 하면 같은 `state_hash()`
7. EMZ 가 메인 몬스터 존과 **다른 존**이고 칸 수가 1
8. 칸 존에서 가운데를 빼도 양옆이 밀려나지 않음
9. `UseRegistry` 가 카드 / 카드명 / 효과 스코프를 구분
10. **기존 테스트 전부 통과** (`tests/engine/` 136개 포함 571 passed / 4 skipped)

Phase 1 은 규칙을 전혀 담지 않으므로 구현 · 검증이 명확하고, 이후 모든
단계의 토대가 된다.

---

## 미결 사항

구현 전에 확인이 필요한 결정 두 가지.

1. **Action 에서 `Destroy` / `Banish` 를 제외한 것** — 이들을 효과의 결과로만
   두는 설계. AI 가 직접 "파괴한다"를 고르는 구조를 원한다면 재검토 필요.
2. **`text_derived` 카드의 듀얼 실행 차단** — 덱에 그런 카드가 섞이면 그 덱은
   시뮬레이션할 수 없다.

   > **2026-09 감사 정정.** 이 항목에 적혀 있던 1,440장은 잘못된 수치였다.
   > 당시 `text_derived` 가 "Lua 가 없는 카드" 전부를 담고 있어서, 효과 자체가
   > 없는 통상 몬스터까지 섞여 있었다. 그대로 차단하면 푸른 눈의 백룡이 함께
   > 막힌다. `AnalysisStatus.NO_EFFECT` 를 분리한 뒤 실측하면
   > **차단 대상은 806장**이고, 효과가 없어 차단할 이유가 없는 카드가 746장이다.
