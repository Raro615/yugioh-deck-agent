# Phase 2-W — Real Card Execution Expansion

기준 커밋: `2d760d5` (Phase 2-V Effect Operation Integration)

```
공식 스크립트 (c*.lua)          ← 12,702개를 실제로 읽었다
    ↓  손으로 옮김 (추측 금지)
LibraryEntry                    ← 근거(파일 · 줄)를 함께 들고 다닌다
    ↓  EffectActivator → Chain → ChainResolver        (2-Q · 2-F-2)
    ↓  EffectExecutor → OPERATION_HANDLERS            (2-D-2 · 2-V)
GameState → StateDelta → ObservedEvent → TimingEvent  (2-D-3 · 2-J)
```

**새 구조를 만든 단계가 아니다.** Phase 2-M ~ 2-V 가 만든 경로가 실제
카드에서도 **같은 경계**를 지키는지 본다. 엔진 코드는 한 줄도 바뀌지
않았다 — 늘어난 것은 목록과 테스트뿐이다.

---

## 1. 실제 카드 조사 결과 (§1 · §2)

`c*.lua` **12,702개를 실제로 스캔**했다. 추측이 아니라 파일을 읽어서
걸렀다.

### 1단계 — 판을 바꾸는 호출이 전부 옮길 수 있는 것인가

`Duel.*` 호출을 전부 뽑아, 이 엔진이 표현할 수 있는 열 가지
(`Draw` · `Recover` · `Destroy` · `SendtoGrave` · `SendtoHand` ·
`SendtoDeck` · `Remove` · `Release` · `DiscardHand` · `SpecialSummon`)
와 판을 바꾸지 않는 보조 호출만 쓰는 스크립트를 남겼다.

**1,377장**이 남았다.

| 종류 | 후보 수 |
|---|---:|
| SPECIAL_SUMMON | 405 |
| RETURN_TO_HAND | 353 |
| DESTROY | 303 |
| SEND_TO_GRAVE | 174 |
| DRAW | 150 |
| RETURN_TO_DECK | 119 |
| BANISH | 112 |
| DISCARD | 93 |
| CHANGE_LIFE | 53 |
| RELEASE | 6 |

### 2단계 — 후보 조건이 **판정 가능한가**

여기가 결정적이다. 발동 · 대상 · 조건 함수 안에 `IsAbleTo*` ·
`IsCanBe*` · `aux.*` 같은 술어가 있으면 그것은 **규칙 관문**이고, 이
엔진에 그 계층이 없으므로 **옮길 수 없다.** 없는 채로 실행하면 추측이
된다.

발동형 마법 / 함정(`EFFECT_TYPE_ACTIVATE` + `EVENT_FREE_CHAIN`) ·
단일 효과 카드로 좁혀 세어 보면:

| 종류 | 관문 술어 때문에 제외 |
|---|---:|
| RETURN_TO_HAND | **81장 중 80장** |
| SPECIAL_SUMMON | **67장 전부** |
| BANISH | **14장 전부** |
| RETURN_TO_DECK | 16장 중 13장 |
| SEND_TO_GRAVE | 24장 중 20장 |
| DESTROY | 73장 중 47장 |

막고 있는 것은 언제나 같은 세 술어다.

| 술어 | 묻는 것 | 막는 종류 |
|---|---|---|
| `Card.IsAbleToHand` | 패로 갈 수 있는가 | RETURN_TO_HAND |
| `Card.IsAbleToRemove` | 제외될 수 있는가 | BANISH |
| `Card.IsAbleToDeck` | 덱으로 갈 수 있는가 | RETURN_TO_DECK |
| `Card.IsCanBeSpecialSummoned` | 특수 소환될 수 있는가 | SPECIAL_SUMMON |

**이것이 STRUCTURAL-48 · 64 의 실제 크기다.** "관문이 없다" 는 추상적인
TODO 가 아니라, 실제 카드 **200장 이상**을 막고 있는 구체적인 구멍이다.

### 3단계 — 남은 것에서 고르기

공식 DB 의 카드 텍스트와 Lua 를 나란히 놓고 대조했다. **카드 텍스트를
번역하거나 추측하지 않았다** — 저장소의 공식 데이터를 그대로 읽었다.

---

## 2. 실제 executable 카드 목록 (§17-2)

`LUA_VERIFIED` + `EffectRef` + 등록된 구현 = **`EXECUTABLE`** (ADR-006).

### 실행된다 (8장)

| 카드 | 번호 | Operation | Phase |
|---|---|---|---|
| 욕망의 항아리 | 55144522 | `DRAW` ×1 (2장) | 2-K |
| 은혜의 단비 | 66719324 | `CHANGE_LIFE` ×2 | 2-K |
| 싸이크론 | 5318639 | `DESTROY` (대상) | 2-O |
| **치료의 신 다이안 켓** | 84257639 | `CHANGE_LIFE` | **2-W** |
| **욕망의 선물** | 5915629 | `DRAW` (**상대가** 뽑는다) | **2-W** |
| **갑부 고블린** | 70368879 | `DRAW` + `CHANGE_LIFE` | **2-W** |
| **육신보살** | 15103313 | `SEND_TO_GRAVE` (대상) | **2-W** |
| **벌금** | 92595643 | `DISCARD` ×2 (고르기) | **2-W** |

싸이크론은 `EXECUTABLE` 이지만 **해결이 파괴 관문에서 멈춘다** (§9).
"실행 권위" 와 "규칙 판정" 은 다른 질문이다.

### 실행되지 않는다 (4장) — **빼 버리지 않는다**

| 카드 | 번호 | 막는 것 |
|---|---|---|
| 블랙홀 | 53129443 | 파괴 의미 + 존 전체 일괄 처리 (STRUCTURAL-10) |
| 죽은 자의 소생 | 83764718 | `IsCanBeSpecialSummoned` + 표시 형식 (STRUCTURAL-61 · 64) |
| **강제 탈출 장치** | 94192409 | `IsAbleToHand` (STRUCTURAL-48) |
| **로스트** | 24623598 | `IsAbleToRemove` + `aux.SpElimFilter` (STRUCTURAL-48) |

뒤의 둘이 이번에 더해진 이유는 **BANISH 와 RETURN_TO_HAND 가 실제
카드로 검증되지 않은 까닭을 코드 안에 남겨 두기 위해서**다. 목록에서
빼면 "왜 못 하는가" 가 사라진다.

---

## 3. Operation 별 실제 coverage (§13 · §17-3)

| Operation | 분류 | 근거 |
|---|---|---|
| `DRAW` | **A. 실제 카드 실행됨** | 욕망의 항아리 · 욕망의 선물 · 갑부 고블린 |
| `CHANGE_LIFE` | **A. 실제 카드 실행됨** | 은혜의 단비 · 다이안 켓 · 갑부 고블린 |
| `SEND_TO_GRAVE` | **A. 실제 카드 실행됨** (신규) | 육신보살 |
| `DISCARD` | **A. 실제 카드 실행됨** (신규) | 벌금 |
| `DESTROY` | **A′. 실제 카드가 관문에서 멈추는 것까지** | 싸이크론 — 판정을 받으면 실행되고, 판정이 없으면 `UNCHECKED_RULES` |
| `BANISH` | B. synthetic 전용 | 후보 14장 전부 `IsAbleToRemove` |
| `RETURN_TO_HAND` | B. synthetic 전용 | 후보 81장 중 80장이 `IsAbleToHand` |
| `RETURN_TO_DECK` | B. synthetic 전용 | 후보 대부분 `IsAbleToDeck` |
| `RELEASE` | B. synthetic 전용 | 후보 6장, 전부 다른 계층 필요 |
| `SPECIAL_SUMMON` | B. synthetic 전용 | 후보 67장 전부 `IsCanBeSpecialSummoned` |
| `MOVE` | **C. 설계상 실제 카드가 될 수 없다** | `LibraryEntry` 가 거부한다 (ADR-002) |
| `UNKNOWN` | C. 실행되지 않는다 | `SUPPORTED` 밖 |

**B 를 A 로 억지로 옮기지 않았다.** 옮기려면 관문 계층을 지어내야 하고,
그것이 이 프로젝트가 하지 않기로 한 일이다.

---

## 4. 실제 카드 A — 치료의 신 다이안 켓 (84257639)

공식 텍스트: **"①: 자신은 1000 LP 회복한다."**

```
c84257639.lua
  s.tg :  chk==0 → true                       조건 없음
          Duel.SetTargetPlayer(tp)            대상은 플레이어 (카드가 아니다)
          Duel.SetTargetParam(1000)
  s.op :  Duel.Recover(p,d,REASON_EFFECT)
                ↓
  LifeChangeOperation(delta=1000, who=CONTROLLER)
```

**목록에서 가장 단순한 항목이다.** 대상도 비용도 조건도 없다.
은혜의 단비와의 차이는 하나 — **상대 LP 는 그대로다.** 그 차이가
`who` 하나로 표현되고, 테스트가 그것을 본다.

trace: `ACTIVATED` → `RESOLVED` → `CHANGE_LIFE` → `LifeChanged(MINE, +1000)`
→ `LIFE_CHANGED`.

---

## 5. 실제 카드 B — 욕망의 선물 (5915629)

공식 텍스트: **"상대는 덱에서 카드를 2장 드로우한다."**

```
Duel.SetTargetPlayer(1-tp)                    ← 여기가 전부다
Duel.SetTargetParam(2)
Duel.Draw(p,d,REASON_EFFECT)
      ↓
DrawOperation(count=2, who=OPPONENT)
```

욕망의 항아리와 **같은 일을 다른 사람이** 한다. 새 조작을 만들지
않았다 — 뽑는 주체를 조작 밖에 두지 않았기 때문에 `who` 하나로 갈린다.

발동 조건도 **상대** 덱을 본다 (`IsPlayerCanDraw(1-tp,2)` →
`ZoneCountAtLeast(OPPONENT, DECK, 2)`). 내 덱이 두꺼워도 상대 덱이
얇으면 `CONDITION_FALSE` 다 — 테스트가 그것을 확인한다.

`IsPlayerCanDraw` 중 **덱 장수 부분만** 옮겼다. "드로우를 막는 효과" 는
이 엔진에 없다 (욕망의 항아리와 같은 이유).

---

## 6. 실제 카드 C — 갑부 고블린 (70368879)

공식 텍스트: **"①: 자신은 덱에서 1장 드로우한다. 그 후, 상대는 1000
LP 회복한다."**

**한 효과가 서로 다른 두 종류의 일을 한다** — 이 목록에서 처음이다
(은혜의 단비는 같은 종류를 두 번 했다).

```
(DrawOperation(1, CONTROLLER), LifeChangeOperation(+1000, OPPONENT))
      ↓ 같은 실행기, 표에서 **다른 수행기 둘**
CardDrawn  +  LifeChanged
      ↓
CARD_DRAWN  +  LIFE_CHANGED
```

Phase 2-V 의 표가 실제 카드 하나 안에서 두 번, 다른 종류로 불린다.

### 옮기지 못한 것

`if Duel.Draw(...)>0 then ... Duel.Recover(...) end` 의 **조건부
연결**이다. 이 실행기는 계획을 전부 마친 뒤에 적용하므로 드로우가
부분적으로 성공하는 일이 없다 — 덱이 모자라면 `INSUFFICIENT_CARDS` 로
**둘 다** 일어나지 않는다. 두 모델이 갈리는 경우는 "드로우를 막는
효과" 가 있을 때뿐이고 그 계층이 없다. **STRUCTURAL-67** 로 적어 둔다.

---

## 7. 추가 실제 카드 (§17-7)

### 육신보살 (15103313) — `SEND_TO_GRAVE`

공식 텍스트: **"자신 필드 위에 존재하는 몬스터 1장을 선택하고 묘지로
보낸다."**

**파괴가 아니다.** 같은 묘지로 가지만 `Duel.SendtoGrave` 이고, 그래서
`reason_names` 가 `("EFFECT",)` 다 — `DESTROY` 가 없다 (ADR-002).
싸이크론은 같은 자리에서 관문에 막히는데 이 카드는 지나간다. 그 차이를
테스트가 나란히 놓고 본다.

**관문 없이 실행해도 되는 이유가 있다.** 스크립트의 후보 조건이 `nil`
이다 — `Duel.SelectTarget(tp,nil,tp,LOCATION_MZONE,0,1,1,nil)`. 강제
탈출 장치의 `Card.IsAbleToHand` 같은 술어가 **원본에 아예 없다.**
그러므로 관문을 건너뛰는 것은 추측이 아니라 원본을 그대로 옮긴 결과다.

`LOCATION_MZONE, 0` 의 뒤쪽 `0` 이 "상대 쪽은 보지 않는다" 이고, 그
자리가 `owner=CONTROLLER` 로 왔다.

### 벌금 (92595643) — `DISCARD`

공식 텍스트: **"자신은 패를 2장 버린다."**

**대상 지정이 아니라 고르기다.** 스크립트에 `EFFECT_FLAG_CARD_TARGET`
이 없으므로 `TargetSpec.choosing` 이다 — 규칙상 "대상으로 한다" 와
다르고, 그 구분은 대상 내성 · "대상이 되었을 때" 트리거에서 갈린다.
싸이크론(`targeting`)과 나란히 두고 확인한다.

**여러 장을 한 번에** 다루는 첫 실제 카드다 (`minimum=maximum=2`).
`AppliedOperation.instances` 가 두 개, `ZoneMoved` 가 두 개 나온다.

발동 조건 `IsExistingMatchingCard(nil,tp,LOCATION_HAND,0,2,e:GetHandler())`
는 **정확히** `ZoneCountAtLeast(CONTROLLER, HAND, 2)` 다 (발동 시점에
이 카드는 마법 / 함정 존에 있으므로 자기 제외가 결과를 바꾸지 않는다).
옮기지 못한 부분이 **없는** 유일한 신규 항목이다.

---

## 8. Effect → Operation → Mutation → Event trace (§5 · §17-8)

여덟 장 전부 **기존 계층만** 지난다. 각 단계에서 무엇을 쓰는가:

| 단계 | 쓰는 것 | Phase |
|---|---|---|
| Card → EffectRef | `LibraryEntry` · `EffectRef(card_id, ordinal)` | 2-K |
| activation | `EffectActivator` · `PlayerAction.activate_effect` | 2-Q |
| target / selection | `TargetSpec` · `ChoiceSpec` · `TargetResolver` | 2-C · 2-N |
| cost | `CostGroup` (여덟 장 다 **비용 없음**) | 2-E |
| ChainLink | `Chain` · `ChainLink` | 2-F-2 |
| resolution | `ChainResolver` | 2-F-2 |
| Operation | `OperationKind` · `Operation` | 2-L |
| Handler | `OPERATION_HANDLERS` | **2-V** |
| mutation | `EffectExecutor` (유일한 문) | 2-D-2 |
| Delta | `CardDrawn` · `LifeChanged` · `ZoneMoved` | 2-D-3 |
| Event | `EventReader` · `ObservedEvent` | 2-J |
| TimingEvent | `TimingEvent.from_delta` · `TimingPoint` | 2-F-3-A |
| journal | `EventJournal` — 한 해결에 정확히 하나 | 2-D-3 |

**새 EventBus · EffectEngine · OperationEngine · TargetSystem ·
ChainSystem 0개** (§15). 엔진 파일은 한 줄도 바뀌지 않았다.

---

## 9. DESTROY (§7 · §17-9)

§7 이 요구한 두 경우를 **한 자리에서** 가른다.

| 경우 | 결과 | 판 |
|---|---|---|
| 1. 파괴 규칙을 모른다 | `UNCHECKED_RULES` | **불변** |
| 2. 판정을 받았고 대상도 적법 | `RESOLVED` · `reason=(DESTROY, EFFECT)` | 묘지로 |

두 번째의 판정은 **테스트가 명시적으로 준다** (`DeclaredDestructionRuling`).
저장소가 실제 카드의 재정을 들고 있는 것이 아니다 — `UNKNOWN` 을 `TRUE`
로 바꾸는 것과, 답을 밖에서 받아 그 답대로 실행하는 것은 다르다.
Phase 2-O 의 결론 그대로다.

`build_executor()` 의 기본 판정기가 `UnknownDestructionRuling` 이라는
것도 테스트가 고정한다 — 목록에 실렸다는 사실이 파괴 판정을 대신하지
못한다 (STRUCTURAL-47).

---

## 10. MOVE (§8 · §17-10)

`MOVE` 는 **설계상** 실제 카드가 될 수 없다. `LibraryEntry` 가 거부하고,
테스트가 그 거부를 실제로 확인한다 (`EffectDefinitionError`).

의미 있는 이동끼리의 구분도 `StateDelta` 까지 살아 있다.

| | 목적지 | `ZoneMoved.movement` | `reason_names` |
|---|---|---|---|
| 육신보살 | `GRAVE` | `SEND_TO_GRAVE` | `("EFFECT",)` |
| 벌금 | `GRAVE` | `DISCARD` | `("DISCARD", "EFFECT")` |
| 싸이크론(판정 시) | `GRAVE` | `DESTROY` | `("DESTROY", "EFFECT")` |

**목적지가 셋 다 같다.** 목적지로는 절대 구분할 수 없다는 ADR-002 가
실제 카드 세 장으로 증명된다.

그리고 그 구분이 **무엇을 막는지**도 본다: "파괴되었을 때" 를 기다리는
`TriggerSpec(operations={DESTROY})` 가 묘지로 보내기와 버리기에
**반응하지 않는다**.

---

## 11. SPECIAL_SUMMON (§9 · §17-11)

**실행 가능한 실제 카드가 없다.** 후보 67장이 전부
`IsCanBeSpecialSummoned` 에 걸린다.

Phase 2-U 의 경로 자체는 살아 있고, 기본 판정기가
`UnknownSummonRuling` 이라 **어떤 특수 소환도 허가하지 않는다**.
융합 · 싱크로 · 엑시즈 · 링크 · 의식을 이번에 구현하지 않았다.

죽은 자의 소생은 목록에 남아 있다 — `executable=False` 로, 이유와 함께.

---

## 12. Failure matrix (§10 · §17-12)

§10 의 열둘 중 **실제 카드로 닿을 수 있는 열**. 전부 `applied == ()` ·
`deltas == ()` · `state_hash` 불변.

| 갈래 | status | code |
|---|---|---|
| invalid target (육신보살 + 상대 몬스터) | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| hidden target (벌금 + 상대 패) | `UNCHECKED_TARGET` | `HIDDEN_CARD` |
| stale instance (고른 뒤 제외됨) | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| missing target (안 골랐다) | `INVALID_TARGET` | `TOO_FEW_SELECTED` |
| insufficient selection (벌금에 1장) | `INVALID_TARGET` | `TOO_FEW_SELECTED` |
| missing instance (없는 `InstanceId`) | `UNCHECKED_TARGET` | `HIDDEN_CARD` |
| unknown rule (싸이크론) | `UNCHECKED_RULES` | `RULE_NOT_IMPLEMENTED` |
| TEXT_DERIVED | `FORBIDDEN` | `RULE_NOT_IMPLEMENTED` |
| implementation missing | `NOT_IMPLEMENTED` | `RULE_NOT_IMPLEMENTED` |
| invalid context | `INVALID_CONTEXT` | `EFFECT_REF_CARD_MISMATCH` |

**열 갈래가 일곱 답으로 갈린다.** 겹치는 세 쌍은 겹치는 것이 맞다 —
없는 카드 ≡ 가려진 대상(관측 경계), 안 고름 ≡ 모자라게 고름(같은 사실),
떠난 대상 ≡ 부적법한 대상(더 이상 후보가 아니다). 나머지 넷이 서로
다르다는 것도 테스트가 고정한다.

`TEXT_DERIVED` 갈래는 **실제 카드의 정의에 출처만 바꿔 끼워** 만든다.
카드를 지어내지 않고 ADR-004 의 관문만 시험한다.

### 닿을 수 없는 둘 — 그 사실을 테스트가 적는다

| 갈래 | 왜 닿을 수 없는가 |
|---|---|
| **unsupported operation** | 옮기지 못한 일이 있는 카드는 `operations=()` 로 실리고 구현도 등록되지 않으므로, 실행기에 닿기 전에 `NOT_IMPLEMENTED` 에서 멈춘다. `OperationKind.UNKNOWN` 을 들고 목록에 실린 실제 카드가 **없다** |
| **cost unavailable** | 목록의 실제 카드 중 **비용이 있는 것이 하나도 없다.** 비용 있는 후보(압수 `c17375316` 의 `Cost.PayLP(1000)`)는 패 공개(`ConfirmCards`)를 옮길 수 없어 목록에 넣지 않았다 |

없는 것을 있는 척 만들지 않았다. 두 테스트가 그 사실 자체를 고정한다.

### 발동 관문과 해결 관문이 **둘 다** 있다

조사 중 확인한 것: 부적법한 대상 · 모자란 선택은 **발동 단계에서**
막힌다 (`ActivationStatus.INVALID_TARGET`, 체인에 아무것도 올라가지
않는다). 해결을 직접 불러도 같은 답이 나온다. 하나가 새어도 판이
상하지 않는다.

---

## 13. Hidden information (§11 · §17-13)

| 보는 것 | 확인 |
|---|---|
| 상대 패를 고르면 | `UNCHECKED_TARGET` / `HIDDEN_CARD` — **"모른다"** |
| 상대의 앞면 몬스터를 고르면 | `INVALID_TARGET` / `CANDIDATE_NOT_ELIGIBLE` — **"틀렸다"** |
| 거절 결과 `to_dict()` · `reason` | 상대 카드의 `card_id` 도 `instance_id` 도 없다 |
| 상대가 뽑은 카드 (욕망의 선물) | 내 눈으로 본 사건에 정체가 없다 |

`UNKNOWN` 과 `INVALID` 가 뭉개지지 않는다는 것을 **양쪽 다** 본다.
한쪽만 보면 "전부 UNKNOWN 으로 답한다" 는 구현도 통과한다.

---

## 14. Determinism (§12 · §17-14)

여덟 장 전부에 대해:

| 보는 것 | 확인 |
|---|---|
| 같은 판 · 같은 효과 · 같은 선택 | `EffectResult.canonical_state()` 동일 |
| 같은 판 | `state_hash()` 동일 |
| Event ID | 내용에서 나온다 — 두 판에서 같다 |
| 복제 독립성 | 복제본에서 실행해도 원본 `state_hash` 불변 |
| journal | 한 해결에 정확히 하나, `effect_ref` 가 맞다 |

---

## 15. 실제 카드와 synthetic 의 분리 (§6 · §17-15)

`real_card` 표식을 등록했다 (`tests/conftest.py` 의 `pytest_configure`).

```
pytest -m real_card        84개 — 공식 스크립트에서 읽은 실제 카드
pytest -m "not real_card"  2,302개 — synthetic 과 구조 테스트
```

`tests/engine/test_real_card_execution.py` **전체**가 `real_card` 다.
synthetic 정의는 이 파일에 **하나도 없다** — 실패 행렬의
`TEXT_DERIVED` 갈래조차 실제 카드(다이안 켓)의 정의에 출처만 바꿔
끼운다.

거꾸로 `tests/engine/test_operation_integration.py`(Phase 2-V)의
synthetic 테스트는 **그대로 둔다.** 실행 경로의 *모양*을 시험하는 일과
카드의 *의미*를 주장하는 일은 다른 일이고, 하나가 다른 하나를 대체하지
않는다.

---

## 16. 구현하지 않은 것 (§15 · §17-16)

이번 단계에서 **만들지 않은 것**: 새 `EventBus` · 새 `EffectEngine` ·
새 `OperationEngine` · 새 `TargetSystem` · 새 `ChainSystem` · AI ·
Deck Builder · Card Search Engine · 융합 / 싱크로 / 엑시즈 / 링크 /
의식 소환.

**엔진 코드를 바꾸지 않았다.** `engine/` 에서 달라진 파일은
`effect/library.py`(목록 7항목 추가)와 `__init__.py`(문서)뿐이다.

여전히 표현할 수 없는 것: 관문 계층(`IsAbleTo*` · `IsCanBe*`) · 패 공개
(`ConfirmCards`) · 무작위 선택(`RandomSelect`) · 존 전체 일괄 처리 ·
전투 · 효과 데미지와 라이프 감소의 구분 · 표시 형식 선택 · 조건부
연결(`if Duel.Draw(...)>0 then`).

---

## 17. 새 TODO (§16 · §17-17)

- **STRUCTURAL-67 (신규 · 🟠)** — 앞 일의 **결과에 따라** 뒤 일이
  달라지는 효과를 표현할 수 없다. 갑부 고블린의
  `if Duel.Draw(...)>0 then ... end` 가 그것이다. 지금은 계획-후-적용
  덕에 같은 결과에 닿지만, 드로우를 막는 효과가 생기면 갈린다.
- **STRUCTURAL-68 (신규 · 🟠)** — 관문 계층(`IsAbleToHand` ·
  `IsAbleToRemove` · `IsAbleToDeck`)이 없어 **실제 카드 200장 이상**이
  막혀 있다. STRUCTURAL-48 의 실측값이다: RETURN_TO_HAND 후보 81장 중
  80장, BANISH 14장 전부, SPECIAL_SUMMON 67장 전부.
- **STRUCTURAL-66 (범위 축소)** — "의미 있는 이동 여섯이 synthetic
  전용" 이었는데, 육신보살과 벌금이 `SEND_TO_GRAVE` · `DISCARD` 를 A 로
  옮겼다. 남은 것은 `BANISH` · `RELEASE` · `RETURN_TO_HAND` ·
  `RETURN_TO_DECK` 넷이다. **약화가 아니라 실측 갱신이다.**
- STRUCTURAL-10 · 47 · 48 · 50 · 61 ~ 65 — 변동 없음.
- 15 · 34 · 41 · 45 ~ 60 — 변동 없음.

---

## 18. BLOCKER / STRUCTURAL / DETAIL / COSMETIC (§17-18)

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | architecture 를 깨뜨린 것이 없다. 엔진 코드가 바뀌지 않았고 기존 2,302개가 그대로 통과한다 |
| 🟠 STRUCTURAL | 2 신규 | STRUCTURAL-67(조건부 연결) · 68(관문 계층의 실측 크기) |
| 🟡 DETAIL | 1 | `SEND_TO_GRAVE` 와 `DISCARD` 가 같은 `TimingPoint.CARD_MOVED` 를 쓴다. 구분은 `ZoneMoved.movement` 와 `TriggerSpec.operations` 에 있으므로 **잃어버리지는 않았지만**, 시점만 보는 쪽에서는 갈리지 않는다 |
| 🟢 COSMETIC | 0 | |

---

## 19. 전체 테스트 (§17-19)

`tests/engine/test_real_card_execution.py` — **84개**, 전부 통과.

| 묶음 | 수 | 보는 것 |
|---|---:|---|
| A. 조사 결과 | 4 | 목록 12장 · executable 8장 · 거절 이유 · Operation coverage |
| B. 다이안 켓 | 2 | `CHANGE_LIFE` — 상대는 그대로 |
| C. 욕망의 선물 | 2 | `DRAW` — **상대가** 뽑는다 · 상대 덱을 본다 |
| D. 갑부 고블린 | 3 | 두 종류 · 두 수행기 · 덱이 비면 둘 다 안 한다 |
| E. 육신보살 | 3 | `SEND_TO_GRAVE` ≠ 파괴 · 관문 불필요 · 자기 쪽만 |
| F. 벌금 | 4 | `DISCARD` ×2 · 고르기 ≠ 대상 지정 · 1장 거부 · 발동 조건 |
| G. 근거 대조 | 24 | 인용한 `Duel.*` 가 원본에 있다 · `LUA_VERIFIED` · 공식 DB 에 있다 |
| H. DESTROY | 3 | 관문에서 멈춘다 · 판정을 받으면 실행된다 · 기본값은 `UNKNOWN` |
| I. MOVE / 의미 | 3 | `MOVE` 는 거부된다 · 목적지가 같아도 다른 일 · 파괴 트리거가 안 뛴다 |
| J. SPECIAL_SUMMON | 2 | 실제 카드 없음 · 경로는 살아 있고 허가하지 않는다 |
| K. 실패 행렬 | 5 | 열 갈래 판 불변 · 닿을 수 없는 둘 · 발동 관문 |
| L. 숨은 정보 | 3 | 모른다 vs 틀렸다 · 정체 유출 없음 |
| M. 결정론 | 26 | 같은 답 · 같은 Event ID · 복제 독립 · journal |

전체 회귀: **2386 passed, 4 skipped** (직전 2302 + 84).

---

## 20. 기존 테스트 수정 / 삭제 (§17-20)

**삭제 0건. 수정 2건** — 둘 다 목록이 늘어나면 깨지도록 되어 있던
단언이다.

| 테스트 | 이전 전제 | 왜 바뀌었는가 |
|---|---|---|
| `test_operation_integration.py::test_h_no_real_card_uses_move_or_special_summon_yet` | 실행 가능 카드가 쓰는 종류 = `{DRAW, CHANGE_LIFE, DESTROY}` | **그때의 사실**이었다. 육신보살 · 벌금이 `SEND_TO_GRAVE` · `DISCARD` 를 더했다. 요점(MOVE 와 특수 소환에는 여전히 실제 카드가 없다)은 그대로이고, 단언을 약화하지 않았다 — 정확한 새 집합으로 갱신했다 |
| `test_effect_library.py::test_the_library_makes_no_decisions_about_whether_to_use_an_effect` | 원문에 `"choose"` 라는 **낱말**이 없다 | **전제가 틀렸다.** 그 검사는 `ChoiceSpec(chooser=...)` 처럼 "누가 고르는가" 를 규칙으로 적은 자리까지 잡는다 (`chooser` 안에 `choose` 가 있다). 고르는 주체를 명세에 적는 것은 목록이 고르는 것이 아니라 **카드가 그렇게 적혀 있다**는 뜻이다. 낱말 검색을 AST 검사(정의하거나 부르는 **함수 이름**)로 바꾸고 `random` 금지를 더했다 — 원래 의도보다 **강해졌다** |
