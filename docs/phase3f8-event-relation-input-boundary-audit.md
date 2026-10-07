# Phase 3-F-8 — EVENT_RELATION 입력 경계 설계 감사

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-8 — EventRelation Input Boundary / Candidate-vs-Controller Design Audit |
| 모드 | **AUDIT-ONLY** (production diff 0) |
| Base | Phase 3-F-7 (`64b783a` 작업 · `9bec29c` 보고서) |
| 3-F-7 최종 판정 | **C. CROSS_LAYER_RELATION_GAP** |
| **실제 HEAD (측정)** | `9bec29c Phase 3-F-7 보고서: commit SHA · push 결과 기록` |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,234 passed / 4 skipped |
| 새 테스트 | `tests/test_event_relation_input_boundary_audit.py` — **20건** |

`git log` 로 HEAD 를 확인했고 작업 트리는 깨끗했다. 3-F-7 보고서의 판정 줄도
읽어 **C** 임을 확인했다.

---

## 2. 현재 `_event_relation` signature

```
_event_relation(self, spec: TriggerSpec, event: TimingEvent) -> GateVerdict
```

### caller — production 에 **정의 하나 · 호출 하나**뿐이다 (`test_01`)

9개 루트의 모든 `.py` 를 읽어 이 이름이 나오는 자리를 셌다. **2곳이고 둘 다
`engine/trigger.py`** 다.

| 자리 | 내용 |
| --- | --- |
| `engine/trigger.py:1306` | 정의 |
| `engine/trigger.py:1276` | 호출 — `self._event_relation(spec, event),` |

caller 가 넘기는 것은 **선언과 사건 둘뿐**이다. 그리고 **그 호출 자리는
`judge` 안이고, 거기에 후보가 이미 있다** (`judge(candidate, spec, event)`).
이 사실이 §16 의 비용 결론을 그대로 정한다.

| | |
| --- | --- |
| 반환 타입 | `GateVerdict` (= `EligibilityGate` + `ValidationResult`) |
| production caller | **없음** (dormant 계층이다) |
| dormant caller | `TriggerEligibilityJudge.judge` 하나 |

---

## 3. 실제 field consumption

docstring 을 떼고 **AST 로** 읽는 속성을 셌다 (`test_02`).

| 입력 | signature 에 존재 | 실제 읽음 | 판단에 필요 | 제거 가능 |
| --- | :---: | :---: | :---: | :---: |
| `event.point` | ○ | **○** | ○ | ✗ |
| `event.note` | ○ | **○** | ○ (`UNIMPLEMENTED` 설명) | ✗ |
| `event.operation` | ○ | **○** | ○ | ✗ |
| `event.from_zone` | ○ | **○** | ○ | ✗ |
| `event.to_zone` | ○ | **○** | ○ | ✗ |
| `event.actor` | ○ (객체 안) | **✗** | **○ (관계에 필요)** | — |
| `event.delta` | ○ (객체 안) | ✗ | ✗ (종류는 3-F-6 의 문제) | — |
| `event.effect_ref` | ○ (객체 안) | ✗ | ✗ | — |
| `spec.point` | ○ | **○** | ○ | ✗ |
| `spec.operations` | ○ | **○** | ○ | ✗ |
| `spec.from_zones` | ○ | **○** | ○ | ✗ |
| `spec.to_zones` | ○ | **○** | ○ | ✗ |
| `spec.activates_from` | ○ (객체 안) | ✗ | ✗ (자리 관문의 것) | — |
| `spec.condition` | ○ (객체 안) | ✗ | ✗ (조건 관문의 것) | — |
| `candidate.controller` | **✗** | ✗ | **○ (관계에 필요)** | — |
| 그 밖의 candidate 필드 9개 | ✗ | ✗ | **✗** | — |

### 지금은 **남는 입력이 없다**

넘기는 두 객체를 **둘 다** 실제로 쓴다 — 죽은 매개변수가 없다. 그러므로
A 설계의 결함은 "과하게 받는다" 가 **아니라 "모자란다"** 다. 모자란 것은
정확히 둘이다: `event.actor`(객체 안에 있는데 읽지 않는다)와
`controller`(서명에 아예 없다).

---

## 4. Candidate 전체 필요성 조사

후보 10개 필드를 **출처로** 갈랐다 (`test_03` — `TriggerCollector._judge` 의
`base` 대입을 코드에서 읽었다).

| field | 출처 | 성격 | EVENT_RELATION 에 필요? |
| --- | --- | --- | --- |
| `point` | `event.point` | **사건의 복사본** | ✗ 이미 사건을 받는다 |
| `effect_ref` | `spec.effect_ref` | **선언의 복사본** | ✗ 이미 선언을 받는다 |
| `requirement` | `spec.requirement` | **선언의 복사본** | ✗ 판정에 쓰지 않는다 (SEGOC 용) |
| `wording` | `spec.wording` | **선언의 복사본** | ✗ 어휘만 보존 |
| `source` | `card.instance_id` | **새 사실** | ✗ 어느 **자리**인가는 `_activation_zone` 의 질문 |
| **`controller`** | `card.controller` | **새 사실** | **○ 유일하게 필요** |
| `status` | 판정 갈래 | **앞선 판정의 출력** | ✗ **위험** |
| `code` | 판정 갈래 | **앞선 판정의 출력** | ✗ **위험** |
| `reason` | 판정 갈래 | **앞선 판정의 출력** | ✗ **위험** |
| `notes` | 판정 갈래 | **앞선 판정의 출력** | ✗ **위험** |

**4 복사본 · 2 새 사실 · 4 판정 출력.** 관계에 필요한 것은 `controller`
하나다.

### 🔴 마지막 넷이 B 설계의 실제 위험이다

`status` · `code` · `reason` · `notes` 는 **수집기가 이미 내린 판정**이다.
관문이 그것을 읽을 수 있게 되면 **그 관문의 답이 앞선 결정에 의존**할 수
있다. 지금 당장 읽지 않아도, 읽을 수 있는 구조를 만드는 것이 비용이다.

그 위험을 이 파일이 **이미 이름으로 적어 두었다** — `engine/trigger.py` 에
"같은 사실이 두 코드로" · "Phase 3-E-26" 이 들어 있고, 그것이 수집기와 관문이
**같은 거부를 다른 이유로 적지 않게** 맞춰 둔 자리다. 후보를 통째로 넘기는
것은 그 경계를 **구조적으로** 허무는 쪽이다.

> **"혹시 필요할지도 모른다" 만으로 Candidate 전체를 전달하는 것을 허용하지
> 않는다** (§11). 측정된 필요는 정수 하나다.

---

## 5. Controller-only 조사

`test_09` — **controller 하나로 지금의 관계를 전부 표현할 수 있다.**
감사 쪽에서만 계산해 보였다 (production 에 함수를 더하지 않았다).

```
actor is None                                   → UNKNOWN
actor == controller                             → SELF
actor == PlayerRef.OPPONENT.resolve(ctx)        → OPPONENT
그 밖                                            → 2인 게임에서는 닿지 않는다
```

| 질문 (§4) | 답 |
| --- | --- |
| 이것으로 현재 relation 판정을 모두 표현할 수 있는가 | **그렇다** — SELF · OPPONENT · UNKNOWN 셋이 다 나온다 |
| 향후 확장에 정보가 부족하지 않은가 | §10 의 아홉 관계 중 여덟이 이 둘로 갈린다. 부족한 하나는 **입력이 아니라 사건 데이터**의 문제다 (§7) |
| spec 이 이미 필요한 정보를 주는가 | **그렇다** — 관문이 읽는 선언 축 넷이 모두 있고, 관계 어휘도 `PlayerRef` 로 이미 있다 |
| candidate 전체를 전달하지 않아도 되는가 | **그렇다** — 필요한 것이 정수 하나다 |
| hidden information boundary 가 더 명확해지는가 | **그렇다** — 넘기는 것이 "공개된 플레이어 번호 하나" 로 줄어 경계가 눈에 보인다 |

---

## 6. Spec + Event 조사 (A 설계)

### **원리적으로 불가능하다** (`test_10`)

"상대인가" 는 기준이 있어야 답할 수 있고, **그 기준이 사건에 없다.** 같은
`MonsterSummoned(player=1)` 사건이 후보에 따라 SELF 이기도 OPPONENT 이기도
한다 (3-F-7 §8 의 R2/R3).

선언에도 없다 — `TriggerSpec` 아홉 필드에 `actor`/`player` 가 든 이름이
하나도 없다 (3-F-6 이 측정, 여기서 재확인).

> A 는 "지금 그대로" 이므로 **변경 비용 0** 이다. 그리고 요구를 표현하지
> 못한다. **비용이 싸다는 이유로 고를 수 없는** 전형이다.

---

## 7. Minimal relation input 조사

### 최소 입력 집합은 **열한 개**다 (`test_11`)

지금 읽는 아홉(event 5 · spec 4)에 **둘**을 더하면 된다.

```
spec.point · spec.operations · spec.from_zones · spec.to_zones
event.point · event.operation · event.from_zone · event.to_zone · event.note
+ event.actor            ← 이미 사건 객체 안에 있다 (읽기만 하면 된다)
+ controller             ← 후보에서 오는 **정수 하나**
```

후보에서 오는 것은 **하나**이고, 그 하나가 정수다.

### §11 — "최소 입력" 의 함정도 함께 본다

최소가 항상 좋다고 가정하지 않았다. 향후 `EventRelation` 이 더 필요할
가능성을 하나씩 따졌다.

| 향후 필요할 수 있는 것 | 지금 판단 | 근거 |
| --- | --- | --- |
| `candidate.source` (어느 사본인가) | **필요 없다** | "그 카드가 발동할 수 있는 자리인가" 는 `_activation_zone` 의 질문이고, 그 관문이 이미 후보를 받는다 |
| `effect source` / `trigger source` | **필요 없다** | `spec.effect_ref` 가 이미 선언 쪽에 있다 |
| `card identity` | **필요 없다** — 그리고 **넘기면 안 된다** | 카드 신원은 관측의 문제다. 사건 관문이 그것을 받으면 숨은 정보 경계가 넓어진다 (§13) |
| 사건을 일으킨 **효과** | **지금은 필요 없다** | `event.effect_ref` 가 사건 객체 안에 이미 있다 — 필요해지면 **새 입력 없이** 읽으면 된다 |
| 체인 위치 · 우선권 | **필요 없다** | `ActivationTiming` 의 것이고, 사건 관문이 판을 읽지 않는다는 성격을 깬다 |

> 요구가 늘어도 **대부분 사건 객체 안**에 있다. 후보 쪽에서 더 필요해지는
> 것은 측정 범위에서 발견되지 않았다.

---

## 8. 세 설계 비교표 (§5)

| 기준 | **A** `spec + event` | **B** `candidate + event` | **C** `minimal inputs + event` |
| --- | --- | --- | --- |
| 현재 구현 난이도 | **변경 0** | `engine/trigger.py` **2줄** | `engine/trigger.py` **2줄** |
| 관계 표현력 | **불가능** | 가능 | 가능 |
| 정보 손실 | 관계를 못 본다 | 없음 | 없음 (필요한 것만 받는다) |
| coupling | 가장 낮다 | **가장 높다** — 판정 출력 4개가 들어온다 | 낮다 — 정수 하나 |
| 책임 분리 | 지켜진다 (대신 일을 못 한다) | **흐려진다** — 사건 관문이 후보 판정을 볼 수 있다 | **지켜진다** |
| 재사용성 | — | 후보가 있어야만 부를 수 있다 | **정수만 있으면 부를 수 있다** (시험·다른 호출자) |
| 향후 확장성 | 없다 | 넓다 — 그런데 **필요하지 않은 넓이**다 | 필요해지면 입력을 하나씩 더한다 |
| hidden-info 안전성 | 안전 | 지금은 안전 · **앞으로 위험** (후보에 비공개 칸이 생기면 자동 유입) | **가장 안전** — 받는 것이 공개 정수 하나로 못박힌다 |
| ValidationResult 표현 | 세 코드 다 있다 | 같다 | 같다 |
| 테스트 용이성 | — | 후보 객체를 만들어야 한다 | **정수만 주면 된다** |
| canonical_state 영향 | 없음 | 없음 | 없음 |
| state_hash 영향 | 없음 | 없음 | 없음 |

### 🔴 B 와 C 의 비용이 **같다** (`test_19`)

호출 자리에 후보가 이미 있으므로 두 설계가 **같은 한 줄**이다.

```
B:  self._event_relation(spec, event, candidate)
C:  self._event_relation(spec, event, candidate.controller)
```

고의 위반 1번과 2번으로 실제로 둘을 다 주입했고, **같은 세 테스트가 같은
방식으로** 걸렸다 — 비용 차이가 측정되지 않았다.

> **그러므로 비용으로는 고를 수 없고 의미로만 고를 수 있다.** 프롬프트가
> 요구한 원칙이 여기서 실제로 결정을 한다.

---

## 9. SPECIAL_SUMMON fixture (§9)

증식의 G 를 **구현하지 않았다.** 카드 이름도 패스코드도 쓰지 않았다.
요구를 다섯 조각으로 갈라 측정했다 (`test_12`).

| 조각 | 값 | 어디서 | A | B | C |
| --- | --- | --- | :---: | :---: | :---: |
| `point` | `MONSTER_SUMMONED` | `event.point` | ○ | ○ | ○ |
| `summon_kind` | `SPECIAL` | `event.delta.summon` | ○ | ○ | ○ |
| `actor` | `1` | `event.actor` | ○ | ○ | ○ |
| `controller` | `0` | `candidate.controller` | **✗** | ○ | ○ |
| **`relation`** | `actor == opponent(controller)` | 둘의 비교 | **✗** | ○ | ○ |

**네 조각은 세 설계가 같고, 갈리는 것은 관계 하나다.** 그리고 B 와 C 의
표현력이 **정확히 같다** — 요구를 표현하는 능력으로는 둘을 가를 수 없다.

`summon_kind` 가 ○ 인 것은 **사건이 그 값을 들고 있다**는 뜻이고, 선언이
그것을 가리킬 수 있다는 뜻이 아니다 (3-F-6 이 측정한 별개 공백).

---

## 10. SELF / OPPONENT / UNKNOWN (§8)

| | 상황 | `event.actor` | `controller` | 기대 | **실제 `EVENT_RELATION`** |
| --- | --- | --- | --- | --- | --- |
| A | 내가 특수소환 | `0` | `0` | SELF | `VALID` / `OK` |
| B | 상대가 특수소환 | `1` | `0` | OPPONENT | **`VALID` / `OK`** (A 와 같다) |
| C | 행위자를 모름 | `None` | `0` | UNKNOWN | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` (사건 자체가 미구현이라서) |

`test_06` 은 B 의 판정을 A 의 판정과 **직접 비교**해서 같음을 고정한다.

### 정보 부재와 FALSE 관계를 가른다 (`test_07`)

`actor is None` 에서 `!=` 는 양쪽 모두 참이 된다. **어느 설계를 고르든
존재를 먼저 묻는 비교여야 한다** — 3-F-7 이 측정한 위험을 이 Phase 는
**설계 요구**로 고정했다.

```
decided = event.actor is not None and event.actor != player     ← 안전
decided = event.actor != player                                 ← 틀린다
```

---

## 11. `PlayerRef.OPPONENT` 활용 (§7)

**새 enum 도 새 Player API 도 만들지 않았다.** 기존 것으로 충분하다.

| 범주 | 기존 구조로 어떻게 적는가 |
| --- | --- |
| `SELF` | `PlayerRef.CONTROLLER.resolve(ConditionContext(player=controller))` |
| `OPPONENT` | `PlayerRef.OPPONENT.resolve(ConditionContext(player=controller))` |
| `ANY` | 선언이 그 축을 **적지 않은 상태** — `None` 이 이미 "선언하지 않았다" 를 뜻한다 (`TriggerSpec` 의 기존 규칙) |
| `UNKNOWN` | `actor is None` — 판정은 `INFORMATION_UNAVAILABLE` 이 가장 가깝다 |

`PlayerRef` 는 **문맥을 받아 번호로 풀린다**. 그 문맥에 필요한 것이 정수
하나(`player=controller`)이므로, **C 설계가 이 어휘와 정확히 맞는다** —
후보 전체가 아니라 컨트롤러 하나가 `ConditionContext` 의 입력이다.

> 즉 `PlayerRef` 를 쓰려면 **컨트롤러 정수가 있으면 되고 그 이상은 필요
> 없다.** 기존 어휘가 최소 입력 설계를 가리킨다.

---

## 12. 정보 손실 분석 (§12)

| 정보 | A | B | C | 비고 |
| --- | :---: | :---: | :---: | --- |
| `event.point` · `operation` · zones | 보존 | 보존 | 보존 | 관문이 읽는다 |
| `event.actor` | **못 읽는다** (객체엔 있다) | 읽을 수 있다 | 읽을 수 있다 | 손실이 아니라 **미사용** |
| `event.delta` (종류) | 객체엔 있다 | 같다 | 같다 | 선언이 못 가리키는 것이 문제 (3-F-6) |
| `candidate.controller` | **없다** | 있다 | 있다 | C 는 값만 받는다 |
| `candidate identity`(`source`) | 없다 | 있다 | **없다** | **이 계층에서 필요하지 않은 것** — 손실이 아니다 |
| `trigger source`(`effect_ref`) | `spec` 에 있다 | 둘 다 있다 | `spec` 에 있다 | 손실 없음 |
| 앞선 판정(`status`·`code`·`reason`·`notes`) | 없다 | **있다** | 없다 | **없는 것이 옳다** |

### 세 설계 **모두에서** 사라지는 것 (`test_16`)

`judge` 의 출력 `TriggerEligibility` 에 **사건이 없다** (3-F-7 §5). 그래서
행위자는 판정 결과에서 되살릴 수 없다 — `to_dict()` 에 `"actor"` 가 들어
있지 않음을 실측했다. 반면 **후보는 남으므로 `controller` 는 되살릴 수
있다.**

> 이것은 **입력 경계와 무관한 별개 손실**이다. 세 설계가 똑같이 갖는다.

---

## 13. hidden-info (§14)

`test_18` — 양방향으로 점검했다.

| 질문 | 답 |
| --- | --- |
| B 가 숨은 정보를 끌고 오는가 | **지금은 아니다.** 후보는 보이는 카드에서만 생기므로 열 필드 전부 공개값이다. `card_id`·`metadata` 같은 칸도 없다 |
| 그러면 B 가 안전한가 | **앞으로 위험하다.** 후보에 비공개 칸이 생기는 날 사건 관문이 **자동으로** 그것을 받게 된다 — 경계가 코드에 적혀 있지 않기 때문이다 |
| C 가 공개 정보까지 빼앗는가 | **아니다.** 관계에 필요한 두 값(`event.actor`·`controller`)이 다 들어온다 |

C 는 받는 것이 "공개된 플레이어 번호 하나" 로 **서명에 못박힌다** — 그것이
hidden-info 경계를 코드로 지키는 방식이다. **현재 경계를 변경하지 않았다.**

---

## 14. ValidationResult (§13)

세 결과를 **새 코드 없이** 적을 수 있다 (`test_17`).

| 관계 결과 | validity / code | 이미 쓰는가 |
| --- | --- | --- |
| SELF · OPPONENT 가 맞는다 | `VALID` / `OK` | ○ |
| 관계가 **확실히** 다르다 | `INVALID` / `CANDIDATE_NOT_ELIGIBLE` | ○ |
| 행위자를 모른다 | `UNKNOWN` / `INFORMATION_UNAVAILABLE` | ○ — 3-E-45 가 "적었는데 읽을 수 없다" 에 쓰려고 만든 그 코드 |
| 사건 자체가 미구현 | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` | ○ |

셋 다 `_event_relation` 이 **이미 쓰는 어휘 안**에 있다. 48개 코드를
늘리지 않았다. **세 설계 모두 이 점에서 동등하다.**

---

## 15. canonical_state / state_hash / RNG (§15)

| 질문 | 답 |
| --- | --- |
| Candidate 전체 전달 여부가 canonical state 에 영향을 주는가 | **아니다** — 입력은 직렬화되지 않는다. 직렬화되는 것은 `GateVerdict`(= gate + `ValidationResult`)뿐이다 |
| relation input 이 serialization 되는가 | **아니다** |
| event/candidate metadata 가 hash 에 들어가는가 | **아니다** — 선언도 후보도 `GameState` 밖이고 `Duel` 이 들고 있지도 않다 (3-F-6 §14) |
| RNG 를 소비하는 경로가 있는가 | **없다** — 판정은 관측만 읽는다 (`test_20` 이 실측) |

**변경하지 않았다.** 비교해 보면 **세 설계가 이 축에서 전부 동등**하므로,
이 축은 선택의 근거가 되지 않는다.

> 참고로 **선언에 칸을 더하는 쪽**은 다르다 — `TriggerSpec.canonical_state()`
> 길이가 9에서 늘고, `watching` 이 그 값으로 정렬하므로 선언 순서가 달라질
> 수 있다 (3-F-6 §14). 그것은 이 Phase 의 질문이 아니다.

---

## 16. 변경 비용 측정 (§19)

추측하지 않고 grep/AST 로 셌다 (`test_19`).

| 항목 | A | B | C |
| --- | --- | --- | --- |
| 변경 파일 수 | **0** | **1** (`engine/trigger.py`) | **1** (`engine/trigger.py`) |
| 변경 함수 수 | 0 | **2** (정의 + `judge` 의 호출 한 줄) | **2** (같음) |
| 새 abstraction | 없음 | 없음 | 없음 |
| 기존 production caller 영향 | — | **1곳** (같은 파일) | **1곳** (같은 파일) |
| `judge` 서명 변경 | 불필요 | **불필요** (이미 후보를 받는다) | **불필요** |
| `judge_all` 영향 | — | 없음 | 없음 |
| 이 관문을 **직접 부르는 테스트** | — | **0개** | **0개** |
| 영향받는 테스트 | — | 서명을 **단정하는** 감사 테스트들 | 같음 |
| hidden-info risk | 없음 | **있다 (앞으로)** | **가장 낮다** |
| semantic coupling | 낮음 | **높음** (판정 출력 4개) | 낮음 |
| future extension cost | 표현 불가 | 넓지만 불필요 | 입력을 하나씩 더한다 |

측정된 숫자:

- `_event_relation` 이 나오는 production 자리: **2** (정의 1 · 호출 1, 같은 파일)
- `judge_all` 을 부르는 production 파일: **1** (`engine/trigger_chain.py`)
- 테스트에서 `_event_relation` 언급: **53회 / 11개 파일**
- 테스트에서 `_event_relation` **직접 호출: 0회** (AST 의 `Call` 노드로 셌다)
- `TriggerSpec(...)` 를 **생성하는** 테스트 파일: **28개** (선언에 칸을 더하는
  쪽의 비용 — 이 Phase 의 범위 밖이지만 대비로 적는다)

> **`judge` 가 이미 후보를 받으므로 세 설계 모두 서명 사슬을 건드리지
> 않는다.** 비용 차이는 B 와 C 사이에서 **0** 이다.

---

## 17. 🔴 이 Phase 가 새로 찾은 상류 결함 — `event.actor` 의 뜻이 사건군마다 다르다

`test_15` — `TimingEvent.actor` 의 설명은 **"이 사건을 일으킨 플레이어"**
다. 실제로는 사건군마다 다른 것을 가리킨다.

| 사건군 | `from_delta` 가 가져오는 칸 | 실제 의미 | "행위자" 인가 |
| --- | --- | --- | --- |
| `MonsterSummoned` | `delta.player` | 소환한 사람 | **○** |
| `CardDrawn` | `delta.player` | 뽑은 사람 | **○** |
| `LifeChanged` | `delta.player` | LP 가 **바뀐** 사람 | **✗ 당한 쪽** |
| `ZoneMoved` | `delta.to_player` | **도착지의 주인** | **✗** |

측정 사례:

| 사례 | `actor` | 뜻 |
| --- | --- | --- |
| 내가 8000→6000 피해를 입었다 | `0` (나) | **피해를 입힌 쪽이 아니다.** 입힌 쪽은 어디에도 없다 (`LifeChanged` 필드가 `player·before·after` 셋뿐) |
| 상대 몬스터가 파괴되어 상대 묘지로 | `1` | 묘지의 주인. **누가 파괴했는지는 없다** (`ZoneMoved` 에 행위자 칸 없음) |
| 내 카드를 상대 필드로 넘겼다 | `1` (상대) | 출발지는 `0` 인데 `actor` 는 도착지를 고른다 |

### 이것이 §10 확장 목록에 주는 영향

| # | 관계 | 지금 둘(actor·controller)로 되는가 |
| --- | --- | --- |
| 1·2 | 내/상대 **특수소환** | **○** — `actor` 가 소환한 사람이다 |
| 5·6 | 내/상대 **드로우** | **○** — `actor` 가 뽑은 사람이다 (`test_13`) |
| 3·4 | 내/상대 **카드가 파괴됨** | **○ — 다만 이유가 다르다.** "도착지 주인 = 카드 주인" 이라서 우연히 맞는다 (`test_14`) |
| 7 | 특정 카드가 이동함 | ○ — 카드 식별은 `event.instance` 가 한다 |
| 8 | **특정 플레이어가 행동함** | **✗** — 파괴·데미지에서 "누가 했는가" 가 데이터에 없다 |
| 9 | `ANY` actor | ○ — 선언이 적지 않은 상태가 곧 그것이다 |

### 왜 이것이 입력 경계 판정을 **바꾸지 않는가**

이 결함은 **세 설계 모두의 상류**다 — A·B·C 어느 쪽을 골라도 같은
`event.actor` 를 비교한다. 입력 경계를 어떻게 정하든 이 값의 뜻은 달라지지
않는다. 그러므로 **설계 선택과 분리해서** 기록하고, 다음 Phase 로 넘긴다.

다만 판정에 **범위 조건**을 붙인다: 아래 결론은 `actor` 가 실제로 행위자인
**소환·드로우 사건군**에 대해 성립하고, 파괴·라이프 사건군으로 확장하려면
**이 상류 결함을 먼저 정리해야 한다.**

---

## 18. Engine V1 freeze (§16) · Evaluation/Search 불변 (§17)

`test_20` 이 함께 확인한다.

| 확인 | 결과 |
| --- | --- |
| `_event_relation` 서명 | `["spec", "event"]` (변경 없음) |
| `TriggerSpec` 필드 수 | **9** |
| `TriggerCandidate` 필드 수 | **10** |
| `TimingEvent` 필드 | `point·delta·effect_ref·actor·note` (변경 없음) |
| `ValidationCode` 수 | **48** |
| `duel.py` 에 `TriggerRegistry`·`TriggerCollector`·`TriggerEligibilityJudge`·`engine.timing`·`engine.event_pipeline` | **하나도 없음** |
| `state_hash` · RNG | 판정 전후 **불변** |
| 탐색 순위 | 6판 **611결정**, digest `30fa3597a24d4511d8c92ce9f9921412ffada7546675c4d7d5765381402c4175` — **3-F-5 · 3-F-6 · 3-F-7 과 같은 값** |

금지 항목 전부 미실행: `_event_relation` signature/logic 변경 없음 ·
`TriggerSpec`/`Candidate`/`Event` 구조 변경 없음 · 파이프라인 연결 없음 ·
`legal_actions` 변경 없음 · 카드 구현 없음 · Evaluation/Search/weight/depth
변경 없음.

---

## 19. 테스트 결과

### 새 테스트 — `tests/test_event_relation_input_boundary_audit.py` 20건

| # | 이름 | §18 항목 |
| --- | --- | --- |
| 01 | the current signature and its single caller | 1 |
| 02 | the signature and the actual reads match exactly | 2 |
| 03 | **what passing the whole candidate would actually add** | 3 |
| 04 | the spec side already carries what the relation needs | 4 |
| 05 | self relation has no judgement | 5 |
| 06 | opponent relation gives the same answer | 6 |
| 07 | an absent actor must not read as opponent | 7 |
| 08 | **design b passes four fields the gate must not read** | 8 |
| 09 | controller alone is enough for the relation | 9 |
| 10 | design a cannot express the relation at all | 10 |
| 11 | the minimal input set is eleven values | 11 |
| 12 | the special summon requirement under three designs | 12 |
| 13 | the draw relation needs nothing more than the summon one | 13 |
| 14 | the destroy relation is about the owner not the agent | 14 |
| 15 | 🔴 **the event actor means different things per event family** | — (새 발견) |
| 16 | the three designs lose different things | — (§12) |
| 17 | the relation result fits the existing validation vocabulary | 16 |
| 18 | neither design widens the hidden information boundary | 15 |
| 19 | **designs b and c cost the same** | — (§19) |
| 20 | this phase changed nothing | 17 · 18 · 19 |

```
$ python3 -m pytest tests/test_event_relation_input_boundary_audit.py -p no:randomly -q
20 passed in 9.46s
```

### 고의 위반 검증 — 7건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | **B 설계** — 후보 전체를 넘긴다 | `test_01` · `test_10` · `test_20` |
| 2 | **C 설계** — 컨트롤러만 넘긴다 | `test_01` · `test_10` · `test_20` |
| 3 | 관문이 `event.actor` 를 읽기 시작한다 | `test_02` · `test_11` |
| 4 | `TriggerCandidate` 에 `actor` 칸을 더한다 | `test_03` · `test_08` · `test_20` |
| 5 | `ZoneMoved` 에 행위자 칸을 더한다 | `test_14` |
| 6 | `from_delta` 가 이동에서 `source_player` 를 쓴다 | `test_15` |
| 7 | `duel.py` 가 `TriggerCollector` 를 import 한다 | `test_20` |

**1번과 2번이 같은 세 테스트에 같은 방식으로 걸렸다** — 그것 자체가 §8 의
"비용이 같다" 를 보여 주는 측정이다.

주입 파일 3개(`trigger.py` · `effect/delta.py` · `duel.py`)는 전부 백업에서
복원하고 md5 로 확인했다 (모두 `OK`).

### 🟡 내가 쓴 측정 하나가 처음에 틀렸다 — production 이 아니라 테스트를 고쳤다

`test_19` 에서 "테스트가 `_event_relation` 을 직접 부르는 횟수" 를 정규식으로
셌고 **2** 가 나왔다. 실제 호출이 아니라 **내가 쓴 정규식 리터럴
`r"\._event_relation\("` 자신이 두 번 걸린 것**이었다.

문자열이 아니라 **AST 의 `Call` 노드**를 세는 쪽으로 고쳤다. 이 저장소가
3-E-44 부터 지켜 온 규칙이고, 이번엔 **세는 쪽 코드에도** 적용해야 했다.
production 은 고치지 않았다.

### 전체 회귀

```
$ python3 -m pytest tests/test_event_relation_input_boundary_audit.py -p no:randomly -q
20 passed in 9.46s

$ python3 -m pytest -p no:randomly -q
4254 passed, 4 skipped in 351.60s (0:05:51)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-7 직후 (baseline) | 4,234 | 4 |
| Phase 3-F-8 (이번) | **4,254** | 4 |
| 차이 | **+20** | 0 |

**+20 이 이번에 더한 시험 수와 정확히 같다.** skip 4건은 baseline 과 동일한
기존 skip 이다.

### 기존 테스트 처리

**수정 0건 · 삭제 0건 · skip 추가 0건 · assertion 약화 0건.**
production diff 가 0 이므로 기존 계약이 깨질 자리가 없었다.

---

## 20. production diff

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**0.** 추가한 것은 테스트 하나와 이 보고서뿐이다.

---

## 21. 최종 판정

### **A. MINIMAL_RELATION_INPUTS_SUFFICIENT**

> EventRelation 에는 Candidate 전체가 필요 없으며 필요한 최소 relation
> input 만 전달하는 것이 가장 적절하다.

근거:

1. **필요한 후보 정보가 정수 하나다.** 후보 10개 필드 중 4개는 (spec, event)
   의 복사본, 2개는 새 사실, 4개는 앞선 판정의 출력이고, 관계에 필요한 것은
   `controller` 뿐이다 (`test_03` · `test_09`).
2. **B 는 관문에 "앞선 판정" 을 넘긴다.** `status`·`code`·`reason`·`notes`
   를 읽을 수 있게 되는 것이 비용이고, 같은 파일이 그 위험을 이미
   Phase 3-E-26 으로 적어 두었다 (`test_08`).
3. **A 는 요구를 표현하지 못한다.** 비교 기준이 사건에도 선언에도 없다
   (`test_10`).
4. **최소 입력으로 지금의 관계가 전부 표현된다.** SELF · OPPONENT ·
   UNKNOWN 셋이 `PlayerRef` 와 정수 하나로 나온다 (`test_09`), 그리고
   기존 어휘(`PlayerRef` + `ConditionContext(player=…)`)가 **정확히 그
   모양의 입력**을 요구한다 (§11).
5. **비용으로 고른 것이 아니다.** B 와 C 의 비용이 **같다** (`test_19`,
   고의 위반 1·2 가 같은 방식으로 걸렸다). 비용이 동등한 상태에서
   coupling · 책임 분리 · hidden-info 경계 · 테스트 용이성이 모두 C 를
   가리킨다.

### 범위 조건 (반드시 함께 읽는다)

이 결론은 **`event.actor` 가 실제로 행위자인 사건군** — 소환 · 드로우 —
에 대해 성립한다. 파괴 · 라이프 사건군에서 `actor` 는 각각 "도착지 주인" ·
"당한 쪽" 을 뜻하므로(§17), 같은 비교가 **다른 질문에 답하게 된다.**
그 상류 결함은 세 설계 모두에 공통이고 입력 경계와 **독립**이다.

### 왜 B 가 아닌가

"혹시 필요할지도 모른다" 를 근거로 삼는 것이 §11 이 금지한 것이다. 측정
범위에서 후보의 다른 필드가 필요해지는 사례를 **찾지 못했고**(§7 의 표),
반대로 넘겨서는 **안 되는** 필드 넷을 찾았다.

### 왜 C(SPEC_EVENT_BOUNDARY_SUFFICIENT) 가 아닌가

그 판정은 "Candidate context 전달이 불필요하다" 를 뜻하고, 그러면 관계를
판정할 수 없다. 3-F-7 이 이미 `(spec, event)` 로는 불가능함을 측정했고 이
Phase 가 재확인했다 (`test_10`). **Candidate 의 값 하나는 필요하다** —
"context 전달" 과 "값 하나 전달" 은 다르다.

### 왜 D 가 아닌가

D 는 "세 설계 **모두** semantic contract 가 충분히 정의되지 않았다" 다.
측정 결과 `EVENT_RELATION` 의 계약은 명확하고(3-F-7 §11 재확인), 결과
어휘도 이미 셋이 다 있다(`test_17`). 불명확했던 것은 **입력 경계 하나**이고,
이 Phase 가 그것을 정했다. §17 의 결함은 `EventRelation` 의 계약이 아니라
**`TimingEvent.actor` 의 의미**에 있으므로 D 로 적으면 결함을 잘못
지목한다.

### 왜 E 가 아닌가

§17 은 **예상하지 못한 발견**이지만 "더 큰 구조 문제" 는 아니다 — 원인이
`from_delta` 의 세 줄로 특정되고, 각 delta 가 어떤 사람 칸을 갖는지에서
직접 따라온다. 새로운 모순이 아니라 **이름이 과하게 약속한 것**이다.

---

## 22. 다음 Phase 후보 (1개)

**Phase 3-F-9 — `TimingEvent.actor` 가 사건군마다 다른 것을 가리키는 문제:
의미 감사**

§17 하나만 본다. 입력 경계는 이 Phase 가 정했고, **그 경계로 비교할 값의
뜻이 흔들리는 것**이 이제 유일하게 남은 상류 문제다. 그것을 정리하기 전에
관계 비교를 production 에 넣으면, 소환에서는 맞고 파괴에서는 조용히 다른
질문에 답하는 코드가 된다.

그 Phase 가 답해야 할 것:

1. `actor` 라는 **한 이름**이 세 뜻을 나르는 것이 의도였는지, 아니면
   `ZoneMoved`/`LifeChanged` 가 들어올 때 따라온 것인지 — 커밋 역사와
   docstring 을 읽어 **측정**한다.
2. 각 사건군이 "행위자" 를 **알 수 있는가.** 파괴·데미지에서 그 정보가
   애초에 delta 에 없다면, 그것은 이름 문제가 아니라 **데이터 문제**다 —
   어느 쪽인지 갈라야 한다.
3. 지금 `actor` 를 읽는 자리가 **몇 곳인가** (`EventContext` ·
   `ObservedEvent.actor` · `trigger_chain` 등). 뜻을 좁히면 그 자리들이
   어떻게 되는지 센다.
4. 뜻을 좁히는 것과 **사건군별로 다른 이름을 주는 것** 중 어느 쪽이
   기존 결정(소환을 `CARD_MOVED` 에서 가른 것, 페이즈에 `actor` 를 적지
   않은 것)과 일관되는가.

**이 Phase 는 그 작업을 하지 않았다. 다음 Phase 는 임의로 진행하지 않는다.**
