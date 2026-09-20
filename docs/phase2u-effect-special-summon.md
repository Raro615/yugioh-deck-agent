# Phase 2-U — Effect-driven Special Summon Integration

기준 커밋: `ef665a2` (Phase 2-T Special Summon Core)

```
Card Effect
    ↓  EffectActivator → ChainLink → ChainResolver     (2-Q · 2-R)
    ↓  EffectExecutor
    ↓  OperationKind.SPECIAL_SUMMON
    ↓  SummonRuling           "이 카드를 특수 소환해도 되는가"  ← 관문
    ↓  SummonProcedure        ← Phase 2-T 와 **같은 절차**
GameState  +  MonsterSummoned(summon=SPECIAL, reasons=SPSUMMON·EFFECT)
    ↓  EventReader
TimingEvent(MONSTER_SUMMONED)  →  TriggerCandidate     (그 다음은 2-F)
```

**소환법을 구현한 단계가 아니다.** 효과가 몬스터를 특수 소환하는 **공통
길**을 기존 구조에 잇고, 이을 때 아무 구분도 무너지지 않는지 본다.

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/effect/operation.py` | `OperationKind.SPECIAL_SUMMON` · `SpecialSummonOperation` · `REASON_NAMES` |
| `engine/effect/semantics.py` | 관문 표에 특수 소환 추가 · `SummonRuling` · `UnknownSummonRuling` · `DeclaredSummonRuling` |
| `engine/effect/executor.py` | `summoning=` 판정기 · 소환 dispatch · `_Step.placements` |
| `engine/summon.py` | `plan_for()` 분리 · `SummonPlacement.from_player` · 컨트롤 검사 위치 이동 |
| `engine/normal_summon.py` | `from_player` 채움 |
| `engine/special_summon.py` | import 고리 해소 (지연 import) |
| `engine/effect/library.py` | 죽은 자의 소생(83764718) **실행 불가** 항목 |
| `tests/engine/test_effect_special_summon.py` | 신규 — 48개 |
| `tests/engine/test_semantic_effects.py` | 목록 단언 2건 갱신 (§15) |
| `docs/phase2u-effect-special-summon.md` · `engine/__init__.py` | 문서 |

---

## 2. 재사용한 기존 abstraction

새로 만든 것은 **Operation 하나와 판정기 하나**뿐이다.

| 재사용 | 어디서 |
|---|---|
| `SummonProcedure` · `SummonPlacement` | **Phase 2-T** |
| `EffectExecutor` 의 operation dispatch · 계획-후-적용 | Phase 2-D-2 |
| `TargetResolver` · `CandidateSet` (`_check_target`) | Phase 2-N |
| 관문 구조 (`RULE_GATED` · `GATING_RULES` · `MISSING_GATE`) | Phase 2-M |
| `MonsterSummoned` · `SummonKind.SPECIAL` | Phase 2-I · 2-T |
| `REASON_NAMES` (이유 모델) | Phase 2-L |
| `EventReader` · `ObservedEvent` · `TimingEvent` | Phase 2-J |
| `EffectActivator` · `Chain` · `ChainResolver` · `ResponseLoop` | 2-Q · 2-F-2 · 2-R |
| `ValidationResult` · `ValidationCode` | Phase 2-B-2 |

**새 ValidationCode 0개.** 새 GameState · EventBus · Chain · TriggerCollector ·
TargetResolver · EffectExecutor · SpecialSummonEngine **0개**.

---

## 3. Operation → Special Summon

### `SpecialSummonOperation` 은 `CardOperation` 이 아니다

`CardOperation` 의 일들은 목적지가 `DESTINATION` 표로 정해지고 실행기가
`state.move(card, destination)` 로 옮긴다. 소환은 그 모양이 아니다 — **칸
번호와 표시 형식**이 필요하고, 남기는 변화도 `ZoneMoved` 가 아니라
`MonsterSummoned` 다.

그 표에 끼워 넣으면 "몬스터 존으로 옮겼다" 와 "특수 소환되었다" 가 같은
기록이 되고, "특수 소환되었을 때" 트리거를 영영 구분할 수 없다 (ADR-002 가
파괴와 묘지로 보내기를 가른 것과 같은 이유).

### `PlayerActionKind` 와 합치지 않는다 (§2)

값이 같은 문자열이지만 **다른 enum** 이다 (ADR-001).

| | 뜻 |
|---|---|
| `PlayerActionKind.SPECIAL_SUMMON` | 고르는 주체가 **고르는 행위** |
| `OperationKind.SPECIAL_SUMMON` | 효과 해결 중에 **수행되는 일** |

둘은 같은 절차(`SummonProcedure`)를 쓰지만 같은 어휘가 아니다.

### 효과로 소환되었다는 사실 (§4)

기존 이유 모델을 그대로 쓴다. 새 `SpecialSummonReason` 을 만들지 않았다.

```python
REASON_NAMES[OperationKind.SPECIAL_SUMMON] = ("SPSUMMON", "EFFECT")
```

두 이름 모두 `constant.lua` 에 실재한다 (`REASON_SPSUMMON` · `REASON_EFFECT`).
`AppliedOperation.reason_names` 가 그것을 들고 나간다.

---

## 4. 전체 실행 흐름

`_plan_summon_operation` 의 순서가 규칙이다. **판에 손대기 전에** 전부 끝난다.

1. 일이 가리키는 이름이 정의에 있는가 / 골라졌는가
2. 고른 대상이 규칙에 맞는가 — **Phase 2-N `TargetResolver`**
3. **이 카드를 특수 소환해도 되는가** — 관문
4. 어디에 놓을 수 있는가 — **Phase 2-T `SummonProcedure.plan_for`**

### 관문: 모르면 소환하지 않는다

"이 카드를 특수 소환할 수 있는가" 는 카드마다 다르다 (소생 제한, 융합·싱크로·
엑시즈의 정규 소환 여부, "패에서 특수 소환할 수 있다", 턴 1회 제약 …). 그
계층이 없으므로 기본 판정기는 `UnknownSummonRuling` 이고, **어떤 특수 소환도
일어나지 않는다.**

`EffectExecutor(summoning=...)` 를 주지 않으면 `UNCHECKED_RULES` 이고 판은
그대로다. Phase 2-M 의 `DestructionRuling` 과 **같은 구조·같은 표**를 쓴다 —
새 관문을 만들지 않았다.

### 상대의 묘지에서도 소환한다 — 이번 단계가 고친 것

Phase 2-T 의 `SummonProcedure` 는 "소환하는 사람이 그 카드를 이미
컨트롤한다" 를 요구했다. 플레이어가 선언하는 소환에는 맞지만 **효과에는
틀렸다** — 죽은 자의 소생은 상대의 묘지에서 자신 필드로 소환한다.

그래서 컨트롤 검사를 `plan(state, action)`(행위 경로)로 옮기고,
`plan_for(state, card, player)`(효과 경로)에서는 빼냈다. 대신
`SummonPlacement.from_player` 를 더해 **어느 쪽 자리에서 나왔는지**를
정확히 적는다 — 없으면 "떠났는가" 를 엉뚱한 쪽에서 확인하게 된다.

결과: `owner=상대` · `controller=자신` 이 올바르게 남고
`MonsterSummoned.changed_side` 가 참이다.

---

## 5. Target / Selection (§6)

새 `TargetResolver` 를 만들지 않았다. 정의의 `TargetSpec` → 기존
`CandidateResolver` → `TargetResolver.validate` 를 그대로 지나고, **`LEGAL`
일 때만** 통과한다.

**실행기는 고르지 않는다.** `SpecialSummonOperation` 은 `TargetRef`(이름)만
들고 있고, 실제로 골라진 카드는 `ResolutionContext` 에 있다. 대상 미지정
검색(§7)은 지원하지 않으며, 표현할 수 없는 것은 기존 실패 어휘로 남는다 —
**임의의 카드를 고르지 않는다.**

---

## 6. Event pipeline (§15)

`MonsterSummoned` → `EventReader` → `ObservedEvent` → `TimingEvent
(MONSTER_SUMMONED)`. 새 EventBus 없음. 하나의 소환에서 여러
`TriggerCandidate` 가 나와도 `TriggerCollection.event` 는 **하나**다.

`CARD_MOVED` 와 합치지 않는다. 실행기는 `engine.chain` · `engine.trigger` ·
`engine.response` · `engine.priority` 를 import 하지 않고 `ChainResolver` ·
`TriggerCollector` · `resolve_all` 이라는 이름도 쓰지 않는다 (AST 확인).

---

## 7. 실제 카드 (§8)

**죽은 자의 소생(83764718)을 라이브러리에 실었다 — `executable=False` 로.**

모양은 이 경로에 정확히 맞는다 (`EFFECT_FLAG_CARD_TARGET`, `LOCATION_GRAVE`
양쪽, `Duel.SpecialSummon(tc, …, POS_FACEUP)`). 그런데 옮길 수 없는 것이 둘이다.

| Lua | 왜 못 옮겼는가 |
|---|---|
| `s.filter = c:IsCanBeSpecialSummoned(e, SUMMON_WITH_MONSTER_REBORN, tp, false, false)` | **"이 몬스터를 특수 소환할 수 있는가"** — 카드마다 다른 소환 조건. 추측 없이 옮길 수 없다 |
| `POS_FACEUP` | 앞면 공격 · 앞면 수비를 **고를 수 있다**. 고르는 계층이 없다 (STRUCTURAL-61) |

첫 번째가 결정적이다. "아무 몬스터나" 로 옮기면 소생 제한을 무시한 소환이
판에 올라온다. 그래서 하는 일을 **적지 않은 채로** 싣는다 — 빼 버리면 "왜
못 하는가" 가 사라진다 (블랙홀과 같은 자리).

성공 경로는 synthetic 정의로 검증한다. 판에 올라가는 카드는 실제 카드
(페더맨 · 버스트레이디)다.

---

## 8. Failure matrix (§11)

전부 `applied == ()` · `deltas == ()` · `state_hash` 불변.

| # | 상황 | status / code |
|---|---|---|
| 1 | 대상 없음 | `INVALID_TARGET` / `TOO_FEW_SELECTED` |
| 2 | 부적법한 대상 | `INVALID_TARGET` / `CANDIDATE_NOT_ELIGIBLE` |
| 3 | 모르는 대상 (상대 패) | `UNCHECKED_TARGET` / `HIDDEN_CARD` |
| 4 | 몬스터 존이 가득 참 | `INVALID_TARGET` |
| 5 | 고른 뒤 자리를 떠난 카드 | `INVALID_TARGET` |
| 6 | 존재하지 않는 `InstanceId` | `UNCHECKED_TARGET` / `HIDDEN_CARD` |
| 7 | **소환 조건 미상** | `UNCHECKED_RULES` |
| 8 | 소환 불가로 판정됨 | `INVALID_TARGET` / `CANDIDATE_NOT_ELIGIBLE` |
| 9 | `TEXT_DERIVED` | `FORBIDDEN` |
| 10 | 구현 미등록 | `NOT_IMPLEMENTED` |
| 11 | 다른 효과의 `EffectRef` | `INVALID_CONTEXT` / `EFFECT_REF_CARD_MISMATCH` |

**앞선 일도 함께 취소된다.** `DrawOperation` + 소환을 한 정의에 넣고 판정기를
주지 않으면 드로우도 일어나지 않는다 — 새 rollback 을 만든 것이 아니라
기존 계획-후-적용 그대로다 (§11).

---

## 9. Hidden information · 10. Determinism

| 보는 것 | 확인 |
|---|---|
| 거절 결과 `to_dict()` | 상대 카드의 `card_id` 없음 |
| 관측 경계 | 상대 패의 카드는 `HIDDEN_CARD` — "없다" 가 아니다 |
| 같은 입력 → 같은 결과 | `EffectResult.canonical_state()` 동일 |
| 같은 입력 → 같은 판 | `state_hash()` 동일 |
| Event ID | 내용에서 나온다 — 두 판에서 같은 값 |
| 실패도 결정적 | `UNCHECKED_RULES` 결과가 두 판에서 같다 |
| 복제 독립성 | 복제본에서 소환해도 원본의 카드는 묘지에 그대로 |

두 경로가 **같은 자리에 같은 표시 형식으로** 놓는다는 것도 확인한다
(`state_hash` 가 같다). 그러면서 `AppliedOperation.reason_names` 는 효과
경로에만 `EFFECT` 를 남긴다 — 같은 결과, 다른 기록.

---

## 11. 구현하지 않은 것

융합 · 싱크로 · 엑시즈 · 링크 · 의식 · 펜듈럼 소환, 재료 고르기, 엑스트라
덱에서의 특수 소환, 소환 조건 parser, 대상 미지정 검색, 표시 형식 고르기,
칸 고르기, 소환 무효, 자동 체인 생성, SEGOC, AI.

미구현은 전부 `UNKNOWN` / `RULE_NOT_IMPLEMENTED` / `NOT_IMPLEMENTED` 로
남아 있다.

---

## 12. 새 TODO

- **STRUCTURAL-64 (신규)** — 소환 조건 계층(`IsCanBeSpecialSummoned` 에
  해당하는 것)이 없다. `SummonRuling` 이 그 자리를 **비워 둔 채로** 표시하고
  있고, 그때까지 효과로 몬스터가 나오려면 판정을 밖에서 받아야 한다.
  죽은 자의 소생이 실행 불가인 첫 번째 이유다.
- **STRUCTURAL-65 (신규)** — 대상을 지정하지 않는 특수 소환("덱에서 조건에
  맞는 몬스터를 특수 소환")을 표현할 수 없다. 검색 계층을 만들지 않았고
  (§7), 임의의 카드를 고르지도 않는다.
- **STRUCTURAL-61 (계속)** — 표시 형식을 고를 수 없다. 죽은 자의 소생이
  실행 불가인 두 번째 이유다.
- **STRUCTURAL-62 · 63 (계속)** — 소환법 이름 없음 · 출발 자리가
  `{HAND, GRAVE}` 뿐.
- 15 · 34 · 41 · 45 ~ 60 — 변동 없음.

---

## 13. 기존 테스트 수정 (§17 의 정직한 보고)

**삭제 0건.** `tests/engine/test_semantic_effects.py` 의 **목록 단언 2건**만
갱신했다.

| 이전 | 왜 바뀌었는가 |
|---|---|
| `test_the_semantic_kinds_are_exactly_the_three` → `..._every_semantic_kind_carries_its_unchecked_rules` | 의미를 주장하는 일이 넷이 되었다. 카드가 몬스터 존에 들어가는 것과 "특수 소환되었다" 는 다른 사실이다. **단언을 약화하지 않았다** — 모든 의미가 "보지 않은 규칙" 을 들고 다니는지 계속 확인한다 |
| `test_only_destruction_is_gated_for_now` → `..._sending_and_discarding_are_still_ungated` | 관문이 둘이 되었다. 보내기·버리기가 여전히 관문 없음(STRUCTURAL-48)이라는 요점은 그대로다 |

두 테스트의 이전 전제는 틀린 것이 아니라 **그때의 사실**이었고, 목록이
늘어날 때 깨지도록 되어 있었다 — 그것이 그 테스트들의 일이다.

---

## 14. 테스트

`tests/engine/test_effect_special_summon.py` — **48개**, 전부 통과.

| 묶음 | 수 | 보는 것 |
|---|---|---|
| A. Operation 어휘 | 5 | `CardOperation` 이 아니다 · `PlayerActionKind` 와 별개 |
| B. 관문 | 6 | 모르면 소환하지 않는다 |
| C. 성공 경로 | 6 | HAND·GRAVE → MZONE · owner/controller · **상대 묘지에서** |
| D. Event pipeline | 4 | `MONSTER_SUMMONED` · 여러 후보가 한 사건 |
| E. 발동 → 체인 → 해결 | 4 | 발동만으로는 나오지 않는다 · 체인 미호출 |
| F. 절차 공유 | 4 | 두 경로가 같은 자리에, 다른 기록으로 |
| G. 실패 행렬 | 10 | 판 불변 · 앞선 일도 취소 |
| H. 결정론 · 복제 | 4 | 같은 답 · 같은 Event ID · 복제 독립 |
| I. 정보 · 실제 카드 | 5 | 정체 유출 없음 · 죽은 자의 소생은 실행 불가 |

전체 회귀: **2222 passed, 4 skipped** (직전 2174 + 48).
