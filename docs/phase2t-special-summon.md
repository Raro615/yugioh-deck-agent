# Phase 2-T — Special Summon Core

기준 커밋: `057ad98` (Phase 2-S Activation Timing / Spell Speed Core)

```
PlayerAction(SPECIAL_SUMMON)
    ↓  ActionValidator            해도 되는가 → **언제나 UNKNOWN**
    ↓  ActionExecutor             허가된 것만 넘긴다
    ↓  SpecialSummonHandler
    ↓  SummonProcedure            계획 → 적용 → 확인  ← 일반 소환과 **같은 코드**
GameState  +  MonsterSummoned(summon=SPECIAL)
    ↓  EventReader
TimingEvent(MONSTER_SUMMONED)  →  TriggerCandidate   (그 다음은 Phase 2-F)
```

**소환법을 구현한 단계가 아니다.** 특수 소환이라는 상태 변화가 지나갈
**공통 길**을 내고, 그 길이 기존 구조와 충돌하지 않는지 확인한다.

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/summon.py` | **신규** — `SummonPlacement` · `SummonProcedure` · `SummonError` (공통 절차) |
| `engine/special_summon.py` | **신규** — `SpecialSummonExecutor` · `SpecialSummonHandler` |
| `engine/normal_summon.py` | **리팩터링** — 공통 절차에 위임 (복사하지 않으려고) |
| `engine/action.py` | `PlayerActionKind.SPECIAL_SUMMON` · `PlayerAction.special_summon()` |
| `engine/effect/delta.py` | `SummonKind.SPECIAL` |
| `engine/action_validation.py` | `_special_summon` 요구 목록 + `_MISSING_RULE` |
| `engine/action_execution.py` | `UNSUPPORTED_REASON[SPECIAL_SUMMON]` |
| `tests/engine/test_special_summon.py` | 신규 — 49개 |
| `tests/engine/test_action_execution.py` · `test_action_validation.py` · `test_player_action.py` | **표본 추가** (§14) |
| `docs/phase2t-special-summon.md` · `engine/__init__.py` | 문서 |

---

## 2. 재사용한 기존 abstraction

새로 만든 것은 **공통 절차 하나**뿐이다.

| 재사용 | 어디서 |
|---|---|
| `GameState.move` · `locate` · `find_instance` · `zone` | Phase 2-A |
| `ZoneContainer.free_slots` · `slot` | Phase 2-A |
| `PlayerAction` · `PlayerActionKind` | Phase 2-B-1 |
| `ActionValidator` · `Requirement` · `UnimplementedRule` | Phase 2-B-2 |
| `ActionExecutor` · `ActionHandler` · `ActionStatus` | Phase 2-G |
| `MonsterSummoned` · `StateDelta` | Phase 2-D-2 · 2-I |
| `EventReader` · `ObservedEvent` · `TimingEvent` | Phase 2-J |
| `TriggerCollector` · `TriggerCollection` | Phase 2-F-3-A |
| `ValidationResult` · `ValidationCode` | Phase 2-B-2 |

**새 ValidationCode 0개.** 새 GameState · EventBus · Chain · TargetResolver ·
handler registry **0개**.

---

## 3. 실행 흐름

`SpecialSummonExecutor.plan()` → `SummonPlacement` (판을 읽기만 한다) →
`SummonProcedure.place()` (여기서만 바뀐다) → `MonsterSummoned`.

성공 시:

| 보는 것 | 결과 |
|---|---|
| 자리 | `HAND`/`GRAVE` → `MZONE` |
| `InstanceId` | **같은 카드** (새로 만들지 않는다) |
| `card_id` · `owner` · `controller` | 그대로 |
| 표시 형식 | `FACEUP_ATTACK` (고를 수 없다 — STRUCTURAL-61) |
| **일반 소환권** | **건드리지 않는다** |

실패 시 `deltas == ()` · `state_hash` 불변 · 기록 없음.

### 일반 소환과 **같은 코드**를 쓴다 (§3)

`SummonProcedure` 는 절차가 아니라 **값**이다. 다른 것만 값으로 적는다.

| | 일반 소환 | 특수 소환 |
|---|---|---|
| `from_zones` | `{HAND}` | `{HAND, GRAVE}` |
| `summon` | `NORMAL` | `SPECIAL` |
| 소환권 | **쓴다** | **쓰지 않는다** |

마지막 줄은 공통 파일에 **없다**. "쓸 수도 있고 안 쓸 수도 있는" 칸을
만들면 언젠가 특수 소환이 조용히 소환권을 먹는다. 그래서 소환권 기록은
`normal_summon.py` 가 자기 쪽에서 하고, `special_summon.py` 에는
`RuleUsageRegistry` 라는 이름조차 나오지 않는다 (테스트가 AST 로 확인).

`normal_summon.py` 는 **리팩터링했다** — 자리 찾기 · 이동 · 착지 확인이 두
벌이 되지 않도록. 기존 62개 테스트는 그대로 통과한다.

---

## 4. Validation

`ActionValidator` 는 `SPECIAL_SUMMON` 에 **언제나 `UNKNOWN`** 을 돌려준다.

| 확인 | 통과 못 하면 |
|---|---|
| 자신이 쥔 카드인가 | `INVALID` / `SOURCE_NOT_CONTROLLED` |
| 몬스터인가 | `INVALID` / `SOURCE_WRONG_CARD_TYPE` |
| 몬스터 존에 빈 칸이 있는가 | `INVALID` / `ZONE_FULL` |
| 그 자리에서 나오는 것을 옮겼는가 | **`UNKNOWN`** / `RULE_NOT_IMPLEMENTED` |
| **이 카드를 특수 소환할 수 있는가** | **`UNKNOWN`** / `RULE_NOT_IMPLEMENTED` |

### 세 가지를 합치지 않는다

- **"안 된다"** — 마법 카드를 몬스터 존에 놓는 것 → `INVALID`
- **"모른다(정보)"** — 상대의 패, 자기 덱 → `UNKNOWN` / `HIDDEN_CARD`
- **"모른다(규칙)"** — 소환 조건, 제외 존에서 나오는 특수 소환 →
  `UNKNOWN` / `RULE_NOT_IMPLEMENTED`

특히 §10: 덱 · 제외 · 엑스트라 덱에서 나오는 특수 소환은 **실제로 있다.**
`INVALID` 로 적으면 거짓이므로 `UnimplementedRule` 로 `UNKNOWN` 을 낸다.

페이즈 제약도 넣지 않았다 — 특수 소환은 상대 턴에도 일어나고, 언제 되는지는
그 효과가 정한다. 지금 메인 페이즈로 못박으면 틀린 채로 굳는다.

---

## 5. MonsterSummoned Event

기존 타입을 **그대로** 쓴다. 새 Delta 도 새 Event 도 만들지 않았고, 더한
것은 `SummonKind.SPECIAL` 값 하나다.

| §7 이 요구한 것 | 어디에 |
|---|---|
| Event ID | `ObservedEvent.event_id` (내용에서 나온다) |
| Instance ID | `MonsterSummoned.card` |
| card_id | 인스턴스로 판에서 읽는다 (Delta 에 박지 않는다) |
| owner · controller | `owner` · `player` |
| from_zone · to_zone · to_index | 그대로 |
| summon kind | `summon=SPECIAL` |
| turn · phase | `EventContext` |
| actor | `ObservedEvent.actor` |

**"어떤 카드가" 와 "어떤 방법으로" 를 분리한다** — `SummonKind` 에
융합 · 싱크로 · 엑시즈 · 링크를 미리 넣지 않았다. 절차 없이 이름만 있으면
그 칸이 "이 소환은 융합이다" 라고 주장하게 된다 (STRUCTURAL-62).

`MONSTER_SUMMONED` 는 `CARD_MOVED` 와 **합치지 않는다** — "소환되었을 때" 와
"필드로 보내졌을 때" 는 다른 사건이다.

---

## 6. Trigger pipeline — 사건까지만

`engine/summon.py` 와 `engine/special_summon.py` 에는 `Chain` ·
`ChainResolver` · `TriggerCollector` · `TriggerChainIntegrator` ·
`EffectExecutor` 가 **이름으로도 없다** (테스트가 AST 로 확인).

§9 의 사건 identity: 하나의 `MonsterSummoned` 에서 후보가 여럿 나와도
`TriggerCollection.event` 가 **하나**다. 서로 다른 사건에서 나온 것처럼
흩어지지 않는다.

---

## 7. 실제 카드 / synthetic (§14)

**조건을 만족하는 실제 카드가 없다.** 라이브러리의 실행 가능한 효과 셋
(욕망의 항아리 · 은혜의 단비 · 싸이크론) 중 특수 소환을 하는 것은 하나도
없고, 특수 소환하는 실제 카드의 조건을 **추측해서 구현하지 않는다.**

그래서 §14 가 허용한 대로 synthetic 시나리오를 쓰되, 판에 올라가는 카드는
**실제 카드**다 — 엘리멘틀 히어로 페더맨(21844576) · 버스트레이디
(58932615) · 블랙홀(53129443, 몬스터가 아닌 것). 각자의 `card_id` 를
유지한 채 나오는 것을 확인한다.

"라이브러리에 특수 소환하는 효과가 없다" 는 사실 자체를 테스트로 고정해
두었다 — 생기는 날 이 테스트가 깨지고, 그때 실제 카드 경로를 잇는다.

---

## 8. Failure matrix (§15)

전부 `deltas == ()` · `state_hash` 불변.

| # | 상황 | 결과 |
|---|---|---|
| 1 | `source` 없음 | `INVALID` / `SOURCE_REQUIRED` |
| 2 | 몬스터 존이 가득 참 | `INVALID` / `ZONE_FULL` · 실행기는 `SpecialSummonError` |
| 3 | 존재하지 않는 `InstanceId` | `UNKNOWN` / `HIDDEN_CARD` |
| 4 | 상대의 패 (가려짐) | `UNKNOWN` / `HIDDEN_CARD` |
| 5 | 지원하지 않는 자리 (제외 존) | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` |
| 6 | 덱 안의 카드 | `UNKNOWN` / `HIDDEN_CARD` (보이지도 않는다) |
| 7 | 행위 종류 불일치 | `SpecialSummonError` |
| 8 | 고른 뒤 자리를 떠난 카드 | `SpecialSummonError` |
| 9 | 남의 카드 | `SpecialSummonError` |
| ✔ | 허가받은 정상 소환 | `EXECUTED` |

---

## 9. Determinism · Hidden information

| 보는 것 | 확인 |
|---|---|
| 같은 입력 → 같은 결과 | `ActionExecution.canonical_state()` 동일 |
| 같은 입력 → 같은 판 | `state_hash()` 동일 |
| **Event ID** | 내용에서 나온다 — 두 판에서 같은 값 |
| 복제 독립성 | 복제본에서 소환해도 원본의 카드는 패에 그대로 |
| 읽기만 하는 질문 | `plan` · `validate` 를 몇 번 불러도 판 불변 |
| 정보 경계 | 거절 결과 `to_dict()` 에 상대 카드의 `card_id` 없음 |

---

## 10. 구현하지 않은 것

융합 · 싱크로 · 엑시즈 · 링크 · 의식 · 펜듈럼 소환, 재료 고르기, 카드별
특수 소환 조건, 소생 제한, 표시 형식 고르기, 칸 고르기, 엑스트라 몬스터
존, 소환 무효, "특수 소환되었을 때" 유발 효과의 **수집**, 체인, AI,
전투, 데미지 스텝.

미구현은 전부 `UNKNOWN` 또는 `RULE_NOT_IMPLEMENTED` 로 남아 있다.

---

## 11. 새 TODO

- **STRUCTURAL-61 (신규)** — 표시 형식을 고를 수 없다. 실제 특수 소환은
  앞면 공격 · 앞면 수비를 고르고, 뒷면으로 나오는 것도 있다. 지금 고정한
  `FACEUP_ATTACK` 이 규칙이라고 주장하지 않는다.
- **STRUCTURAL-62 (신규)** — `SummonKind.SPECIAL` 은 "어떤 특수 소환법인가"
  를 말하지 않는다. 융합 · 싱크로 · 엑시즈 · 링크가 각자 절차를 가질 때
  그 이름이 생긴다. 지금 구분하려는 트리거는 구분할 수 없다.
- **STRUCTURAL-63 (신규)** — 옮긴 출발 자리가 `{HAND, GRAVE}` 뿐이다.
  덱 · 제외 · 엑스트라 덱에서 나오는 특수 소환은 `UNKNOWN` 으로 막혀 있다.
  특히 자기 덱은 관측에 실리지 않아 `HIDDEN_CARD` 로 먼저 걸린다 —
  덱에서 나오는 소환을 지원하려면 관측 경계부터 정해야 한다.
- **STRUCTURAL-41 (관찰)** — 칸을 고르지 않고 가장 작은 빈 칸을 쓴다. 일반
  소환이 쓰던 방식 그대로이고, 이번 단계에서 고치지 않았다.
- 15 · 34 · 45 ~ 60 — 변동 없음.

---

## 12. 기존 테스트 수정 (§19 의 정직한 보고)

**삭제 0건.** 수정 3개 파일, 전부 **표본 추가**다 — 새 행위 종류가 생기면
"모든 종류를 다 적었는가" 를 확인하는 테스트가 깨지는 것이 정상이고, 그
테스트들이 제 일을 한 것이다.

| 파일 | 왜 |
|---|---|
| `test_action_execution.py` | `_sample_action` 이 **모든** 종류의 표본을 요구한다 |
| `test_action_validation.py` | 같은 이유 — 종류마다 어느 계층이 없는지 확인한다 |
| `test_player_action.py` | `analysis.ActionKind` 와 겹치는 이름이 하나 → **둘**로 늘었다. 겹쳐도 **뜻이 다르다**는 것이 요점이고, 그 단언을 오히려 강화했다 (`is not` 비교 추가) |

마지막 항목의 이전 전제("겹치는 이름은 `normal_summon` 하나뿐")는 틀린 것이
아니라 **그때의 사실**이었다. 효과가 몬스터를 특수 소환하는 것과 플레이어가
특수 소환을 선언하는 것은 다른 사건이고, 두 enum 은 끝까지 다른 타입이다.

---

## 13. 테스트

`tests/engine/test_special_summon.py` — **49개**, 전부 통과.

| 묶음 | 수 | 보는 것 |
|---|---|---|
| A. 어휘 | 4 | 특수 소환이 일반 소환과 다른 것임을 값으로 말한다 |
| B. 검증 | 8 | 조건 미상 ≠ 허가 · "안 된다" 와 "모른다" 의 구분 |
| C. 실행 | 6 | 성공 경로 · **소환권을 먹지 않는다** |
| D. `MonsterSummoned` | 5 | 사건이 의미와 시각을 잃지 않는다 |
| E. Trigger | 2 | 사건까지만 · 여러 후보가 한 사건을 공유 |
| F. 공통 코드 | 5 | 복사한 두 번째 시스템이 아니다 |
| G. 실패 행렬 | 9 | 판 불변 |
| H. 결정론 | 5 | 같은 답 · 같은 Event ID · 복제 독립 |
| I. 정보 · 실제 카드 | 5 | 정체 유출 없음 · 실제 카드가 자기로 남는다 |

전체 회귀: **2174 passed, 4 skipped** (직전 2125 + 49).
