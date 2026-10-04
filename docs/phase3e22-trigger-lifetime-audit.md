# Phase 3-E-22 — TriggerCandidate → PlayerAction Translation / Event Lifetime Audit

## 1. HEAD / Base

| | |
|---|---|
| Base (지시) | `4c68023` |
| 실제 HEAD | `4c68023` — Phase 3-E-21 (동일) |
| Working tree | clean · `git diff --stat` 비어 있음 |
| Branch | `claude/pensive-goodall-te1egy` |

## 2. BLOCKER / Engine 변경

**BLOCKER: NO** · **Engine 변경: NO** (`git diff -- engine/ agent/ core/ analysis/
sources/` 0줄). 추가한 것은 `tests/test_trigger_lifetime_audit.py` (12개)와 이 문서.

## 3. 핵심 질문의 답

> **번역 지점은 존재하지 않는다.** 그리고 그것은 "아직 구현되지 않은 것" 이다 —
> 현재 어떤 정상적인 실행도 틀리게 하지 않는다.
>
> 다만 이으려면 **먼저 정해야 하는 것**이 하나 있고, 이번 감사가 그것을
> 특정했다: 후보를 만들려면 **사건(event)** 이 필요한데, 지금 구조에는 사건을
> 들고 있을 자리가 없고 `GameState` 는 **의도적으로** 그 자리가 아니다.

## 4. Current legal_actions Audit

| 단계 | 현재 구현 | production caller | PlayerAction 연결 | 상태 |
|---|---|---|---|---|
| Event | `StateDelta`(전부) · `PhaseChanged` · `EffectResult.deltas` | 만들어지기만 한다 | — | **생성됨 · 버려짐** (3-E-20) |
| Candidate 생성 | `TriggerCollector.collect` | 없음 (`event_pipeline` 만, 그 모듈도 unreachable) | 없음 | dormant |
| Candidate 보존 | **없다** | — | — | **자리 자체가 없다** |
| Candidate 검증 | `TriggerEligibilityJudge` | 없음 | 없음 | dormant |
| Candidate → PlayerAction | **없다** | — | — | **함수가 없다** (`test_03`) |
| PlayerAction → Activation | `EffectActivator.can_activate` / `.activate` | `duel.py:604` · `:901` · `response.py:572` | **필수 인자** | **production** |
| Activation → ChainLink | `activate` 안에서 `Chain.push` | 같음 | 간접 | **production** |

§3 의 아홉 질문:

| # | 질문 | 답 |
|---|---|---|
| 1 | `legal_actions()` 가 `TriggerCandidate` 를 읽는가 | **아니다** |
| 2 | `legal_actions()` 가 `TriggerCandidate` 를 생성하는가 | **아니다** |
| 3 | 과거 Event 를 참조하는가 | **아니다** — `_activation_actions` 의 AST 에 `event`·`journal`·`trigger`·`collect` 라는 이름이 **하나도 없다** (`test_02`) |
| 4 | 현재 `GameState` 만 보고 재계산하는가 | **그렇다.** 발동 출처는 손 + SZONE 이고, 효과 목록은 `activatable_effects(card_id)`(정적 목록)다 |
| 5 | Candidate → PlayerAction 변환 함수가 있는가 | **없다** |
| 6 | 그 함수의 production caller | 해당 없음 |
| 7 | `_activation_actions()` 가 일반 발동과 유발 발동을 구분할 수 있는가 | **구분할 입력 자체가 없다** (사건을 받지 않는다) |
| 8 | `ACTIVATE_EFFECT` 하나로 둘을 표현할 수 있는가 | **표현은 된다** (3-E-21). 구분이 필요하면 그것은 **후보 생성 쪽**의 일이다 |
| 9 | `effect_ref` 만으로 Candidate identity 가 충분한가 | **아니다** — 아래 §6 |

한 가지 더: `_activation_actions` 는 사건을 읽지 않지만 **과거의 사실 하나는
읽는다** — `_set_this_turn` 이 `state.rule_uses` 에서 "이 턴에 세웠는가" 를
가져온다. 즉 **"관문이 필요한 과거" 를 값으로 넘기는 선례가 이미 있다**
(ADR-007, Phase 3-E-15).

## 5. TriggerCandidate Lifetime — 일곱 경우

| Case | 지금 일어나는 일 | 그대로 이었을 때의 문제 |
|---|---|---|
| A 사건 → 후보 → 즉시 `legal_actions()` | 후보 생성 호출이 없어 **유발 후보 0** | — |
| B 같은 상태에서 두 번 호출 | **완전히 동일** (실측, `test_01`) | 중복 없음 — 좋은 성질 |
| C 아무 것도 하지 않고 다시 호출 | 상태가 같으니 **같은 답** | 유발이라면 **창이 영원히 닫히지 않는다** (사건이 지나갔음을 모른다) |
| D 다른 행동 뒤 다시 호출 | 상태가 바뀌어 **다시 계산** | 유발이라면 **창이 소리 없이 닫힌다** — C 와 **정반대 방향의 오류**, 원인은 같다 |
| E 임의 유발 → `PASS` | `PASS` 는 체인·우선권만 움직인다 | **"포기했다" 를 적는 자리가 없다** → 상태가 같으면 다시 후보가 된다 |
| F 한 사건에서 여러 후보 | `TriggerCollection` 이 한 사건에 여럿을 담고 `identity` 로 결정론적 정렬 | "그중 하나를 처리했다" 를 적는 자리가 없다 |
| G 다른 사건에서 같은 효과 | **identity 가 같다** (실측, `test_05`) | 두 번째 유발을 첫 번째로 오인할 수 있다 |

**C 와 D 가 핵심이다.** 사건을 기억하지 않는 구조는 유발에 대해 **두 가지 방향
모두로** 틀릴 수 있다 — 너무 오래 열려 있거나, 너무 일찍 닫힌다. 이것이
"구현되지 않았다" 와 다른 이야기인 이유이고, 동시에 **지금은 해가 없는** 이유다
(유발 후보가 0개이므로 C·D·E·F·G 중 어느 것도 현재 실행에서 일어나지 않는다).

## 6. Event Identity

| 질문 | 답 |
|---|---|
| 1. 후보가 어느 사건 때문인지 식별 가능한가 | **후보 단독으로는 불가능.** `identity = (point, card_id, ordinal, source, controller)` — 사건 **종류**(`TimingPoint`)만 있고 사건 **인스턴스**가 없다 |
| 2. 같은 `EffectRef` 가 여러 사건에서 발생하면 구별되는가 | **아니다** (`test_05` 실측: 두 사건의 후보 identity 가 완전히 같다) |
| 3. 연속으로 여러 번 유발하면 구별되는가 | 아니다 (같은 근거) |
| 4. "발생 시점" 을 복원할 수 있는가 | **아니다.** `TimingEvent` 필드는 `point · delta · effect_ref · actor · note` — 번호도 시각도 없다 |
| 5. "아직 처리되지 않음" 을 표현할 수 있는가 | **아니다.** `TriggerStatus` 는 `ELIGIBLE/INELIGIBLE/UNKNOWN/FORBIDDEN` 으로 **적격성**만 말한다 |

**사건 번호는 이미 있다 — 다른 계층에.** `EffectEvent.sequence` ·
`CostPaymentEvent.sequence` 가 바로 그것이고, 저널 모듈이 "무작위 UUID 도,
시각도, 객체 주소도 쓰지 않는다. `sequence` 가 identity 다" 라고 적어 두었다
(`test_04`). 문제는 둘이다: ① `TimingEvent` 가 그 번호를 **받지 않는다**
② production 에는 `EventJournal` 이 **붙어 있지 않다** (3-E-20).

> `EffectRef` 는 "어떤 효과인가" 이고, `sequence` 는 "몇 번째 사건인가" 다.
> 지금 트리거 계층은 전자만 갖고 있다.

**보강 하나**: `GameState` 안에 사건 모양의 기억이 **하나** 있다 —
`CardInstance.previous_state`(직전 위치 · 표시 형식 · 컨트롤러). 조건 술어
`previous_location` 758건이 그것을 쓴다. 그러나 그것은 **마지막 상태**이고
"무슨 일이 몇 번 있었는가" 가 아니다 — ADR-002 가 가른 "파괴" 와 "묘지로
보내기" 를 구분하지 못한다.

## 7. Duplicate / Stale / Collision

| 항목 | 판정 | 근거 |
|---|---|---|
| Duplicate — `legal_actions()` 두 번 | **IMPOSSIBLE** | 상태의 함수이므로 결과가 같다 (`test_01`) |
| Duplicate — `TriggerCollector` 두 번 | **POSSIBLE** | "이미 모았다" 를 기억하지 않는다 (`test_07`) |
| Stale — 처리·포기한 후보가 다시 나타남 | **POSSIBLE** | 처리 기록이 어디에도 없다 (`test_08`). 지금 발동이 다시 후보가 되지 않는 이유는 **카드가 그 자리를 떠났기 때문**이고 기억 때문이 아니다 |
| Cross-event collision | **POSSIBLE** | identity 가 같다 (`test_05`) |
| Wrong-event reconstruction | **POSSIBLE** | `_judge` 가 사건의 주체를 보지 않는다 — 무관한 카드가 움직인 사건으로도 후보가 된다 (`test_06`) |

### 가장 앞선 공백 — 조건 계층에 사건이 닿지 않는다

`TriggerCollector._judge` 는 `event.point` 만 보고, `ConditionContext` 는
`player · source · effect_ref · targets` 네 칸뿐이다. 그래서 **"이 카드가
파괴되었을 때"** 류를 판정할 근거가 조건 계층에 전달되지 않는다
(`TriggerSpec.matches` 도 `point`/`operations`/`from_zones`/`to_zones` 만 본다 —
"이 카드가 그 사건의 주체인가" 는 묻지 않는다).

즉 번역 지점(`Candidate → PlayerAction`) **앞에** 더 앞선 번역 지점
(`Event → Candidate` 에서 **주체 연결**)이 비어 있다.

## 8. Candidate → PlayerAction 표현 비교

| Candidate 정보 | PlayerAction 에 존재 | 손실 | 향후 필요 |
|---|---|---|---|
| `actor` / `controller` | **있다** (`actor`) | 없음 | — |
| `effect_ref` | **있다** | 없음 | — |
| `source` instance | **있다** (`source`) | 없음 | — |
| event identity | **없다** | **손실** | **필요** — 어느 사건의 유발인지 |
| timing (`point`) | 없다 | 손실 | 아마 필요 없다 — 사건 쪽이 알면 된다 |
| optional / mandatory | 없다 | 손실 | **후보 생성 쪽의 일** (행위는 "고른 결과"다) |
| ordering metadata | 없다 | 손실 | **필요** (RULE-CHAIN-010 의 묶음·순서) |
| target / choice | **있다** (`targets`) | 없음 | — |

**결론: 필드를 더하자는 결론이 아니다.** `PlayerAction` 은 "결정된 행동을
표현하는 불변 명령" 이고 `TriggerCandidate` 는 "발동 가능한 효과의 후보" 다.
책임이 다르다 — 그래서 손실된 넷(event identity · timing · 강제/임의 ·
ordering)은 **행위가 들고 다닐 것이 아니라 후보 쪽이 들고 있다가 소비할 것**
이다. 행위는 그 결정의 결과만 나른다.

## 9. legal_actions Recomputation — 소유권 후보 비교

| 질문 | 답 |
|---|---|
| 1. 유발은 "현재 상태에서 가능한 행동" 인가 | **아니다** |
| 2. "직전 사건이 만든 선택" 인가 | **그렇다** |
| 3. `GameState` 에서 재계산할 수 있는가 | **부분적으로만** — `previous_state` 는 마지막 상태뿐이다 |
| 4. 사건이 사라진 뒤 정확히 복원 가능한가 | **아니다** |
| 5. 복원 불가능하면 언제 보존해야 하는가 | 사건이 만들어지는 순간 (지금은 그 순간에 버려진다) |

| 후보 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **A `GameState`** | 사본·해시가 공짜로 따라온다. `rule_uses` 선례 있음 | **기존 결정과 정면 충돌** — `journal`·`chain`·`pending` 슬롯을 비워 두고 "앞으로도 넣지 않는다"(`canonical_state` 의 설명, `test_09`). 넣으면 "같은 판은 경로와 무관하게 같은 해시" 가 깨진다 | **부적합** (뒤집으려면 별도 결정) |
| **B `ResponseWindow`** | 열린 선택을 담는 자리라는 성질이 같다 | `ResponseState` 는 `chain`+`priority` 의 짝일 뿐 저장소가 아니다. 유발은 체인을 **쌓기 전**이라 의미가 어긋난다 | 보조 가능 |
| **C `Chain` / Chain context** | 결국 체인으로 간다 | 체인은 **발동된 것**의 사슬이다. 아직 발동되지 않은 후보를 담으면 `TriggerCandidate` 가 `ChainLink` 를 상속하지 않은 이유가 무너진다 | **부적합** |
| **D Timing / Event context** | `TimingWindow` 가 이미 "이 사건 뒤에 어떤 판단 창이 열렸는가" 로 설계되어 있다 — **의미가 가장 가깝다** | 그 계층 전체가 미연결 (3-E-20) | **가장 정합** |
| **E 별도 Trigger queue** | SEGOC 의 묶음·순서를 담기 자연스럽다 | **새 subsystem** — 이번 Phase 의 금지 항목 | 보류 |
| **F 현재 구조로 충분** | — | §5 의 C·D·E 가 서로 모순되는 답을 준다 | **아니다** |

보관 **위치**에 대해서는 한 가지가 이미 정해져 있다: 흐름의 위치는 `Duel` 이
들고 있고(`chain` · `priority` · `pending_spells` · `step`) **`state_hash()` 에
들어가지 않는다.** 그리고 `Simulator._fork` 가
`dataclasses.replace(duel, state=clone())` 이므로 그 자리에 놓는 것은
**불변 값이어야 한다** (`test_10`).

→ **판정만**: 의미는 **D**, 보관은 **`Duel` 의 흐름 필드(불변 값)**. 구현하지
않는다.

## 10. OPTIONAL / MANDATORY (3-E-21 결론의 재확인)

| 상태 | 지금 `legal_actions()` 의 결과 |
|---|---|
| 1 후보 없음 | 유발 관련 후보 0 |
| 2 후보 있으나 발동 불가 | **`withheld` + `missing`** 으로 표현 가능 (구조는 있다) |
| 3 후보 + 발동 가능 | `ACTIVATE_EFFECT` 로 표현 가능 — **만들어 주는 코드가 없다** |
| 4 후보 + `PASS` | `PASS` 는 이미 모든 응답 창에 있다 |
| 5 후보 + `ACTIVATE_EFFECT` | 발동 경로가 그대로 받는다 |
| 6 이미 처리됨 | **표현할 수 없다** (기록이 없다) |
| 7 다른 유발보다 먼저 처리되어야 함 | **표현할 수 없다** (순서 정보가 행위에 없다) |

"후보가 존재한다" 와 "`ACTIVATE_EFFECT` 가 `legal_actions()` 에 나온다" 사이의
함수는 **없다.** 그리고 이것은 "translation boundary missing" 이 아니라
**트리거 subsystem 전체가 dormant 이므로 아직 그 단계가 아닌 것**이다 — 후보를
만드는 호출이 없으니 번역할 입력도 없다.

Mandatory 쪽은 3-E-21 의 판정 그대로다: 하나뿐이면 `Duel.advance()` 와 같은
"고르지 않는 일" 의 자리, 둘 이상이면 순서가 선택이므로 행위 공간으로 돌아온다
(RULE-CHAIN-010). 이번 감사가 더한 것은 **그 순서를 담을 자리도 지금 없다**는
사실이다 (§8 의 ordering metadata).

## 11. Simulation / Search 영향

**변경 없음.** 인터페이스 요구사항으로만 적는다.

| | 질문 | 답 |
|---|---|---|
| A | 사본 직후 후보가 유지되는가 | 지금은 후보가 없어 해당 없음. 만들 때 **`Duel` 필드는 값으로 공유**되므로 불변이어야 한다 (`test_10`) |
| B | `clone()` 이 후보 문맥을 보존하는가 | `GameState.clone()` 은 판만 복제한다. 후보가 `Duel` 쪽이면 **값 공유**로 따라간다 (불변이면 안전) |
| C | 탐색이 다시 부르면 실제 게임과 다른 후보가 생길 수 있는가 | 지금은 **아니다** (상태의 함수). 유발이 사건 기반이 되면 **사본이 사건을 모르면 달라진다** → 사건을 사본에 함께 넘겨야 한다 |
| D | forced pass 때문에 유발 창이 사라질 수 있는가 | `_settle_forced_passes` 는 **`PASS` 밖에 없는 자리**만 대신 밟는다. 유발 후보가 나타나면 멈춘다 → 안전. 단 유발을 "PASS 뿐인 창" 으로 만들면 자동 소비된다 |
| E | RNG 과 무관한 결정론 문제인가 | **그렇다.** 사건 기억 문제는 난수와 무관하다 |

## 12. Hidden Information

**누출 없음 · `GameStateView` 변경 없음.**

* `TriggerCollector` 는 `GameStateView` 만 받고(`GameState` 는 `TypeError`),
  **보이는 사본만** 훑고, 가려진 자리는 `unchecked` 로 남긴다 (3-E-20 §14).
* `TriggerCandidate` 는 `EffectRef` · `InstanceId` · `controller` 같은 식별자만
  담는다.
* **"유발이 있다" 와 "그 카드가 무엇인가" 는 이미 갈려 있다** — 가려진 카드는
  `card_id` 가 `None` 이라 후보가 되지 않고, 그 사실이 `unchecked` 로 남는다.
* 비공개 사실을 관문에 넘기는 **선례**도 있다: `_set_this_turn` 이
  `state.rule_uses` 를 읽어 값으로 넘긴다 — 관측을 넓히지 않는 길이다
  (`test_11`).

## 13. Real Card Corpus

| 계층 | 유발 효과의 존재 |
|---|---|
| 데이터 (`c*.lua`) | **있다** |
| parser (`EffectSpec.code`) | **있다** — 전 corpus 34,680 블록 중 `EVENT_*`(FREE_CHAIN 제외) **11,484개 (33.11%)** |
| analysis (`trigger_event`) | **있다** (그대로 복사) |
| engine (구조) | **있다** (`TriggerSpec` … `TriggerChainIntegrator`) |
| engine (등록) | **0개** — `TriggerRegistry` 에 등록된 선언이 없다 |
| production execution | **불가능** — `EFFECT_LIBRARY` 16개 전부 `EVENT_FREE_CHAIN` (`test_12`) |

(참고 분포: `EFFECT_*` 13,728 · `EVENT_*` 유발 11,484 · `EVENT_FREE_CHAIN`
4,914 · `None` 4,554.)

"실제 카드가 없다" 와 "구조가 없다" 는 다르다 — **데이터는 가장 많고, 실행은
0** 이다.

## 14. Final Decision Table

| 질문 | 판정 |
|---|---|
| TriggerCandidate production 생성 경로 | **없음** (dormant `TriggerCollector` 뿐) |
| TriggerCandidate production 보존 경로 | **없음** — 자리 자체가 없다 |
| TriggerCandidate → PlayerAction 변환 지점 | **없음** |
| 변환 지점 production caller | 해당 없음 |
| legal_actions() 가 Event 를 기억하는가 | **아니다** (상태의 함수) |
| legal_actions() 재호출 시 duplicate 가능성 | **IMPOSSIBLE** |
| stale candidate 가능성 | **POSSIBLE** (처리 기록이 없다) |
| 서로 다른 Event 의 동일 EffectRef 충돌 | **POSSIBLE** (identity 동일) |
| clone 후 candidate lifetime | 지금은 해당 없음 · 만들 때 **불변 값이어야 함** |
| OPTIONAL Trigger 표현 가능 여부 | **가능** (`ACTIVATE_EFFECT` / `PASS`) — 만들어 주는 코드가 없다 |
| MANDATORY Trigger 표현 가능 여부 | **가능** (`advance()` 선례) — 순서 정보를 담을 자리는 없다 |
| PlayerAction 이 canonical boundary 인가 | **그렇다** (3-E-21 에서 확정) |
| TriggerChainIntegrator production 사용 | **아니다** |
| Search 영향 | **없음** (요구사항만 기록) |
| Hidden information 영향 | **없음** |
| STRUCTURAL-34 영향 | **없음 (unaffected)** |
| Engine 변경 필요 여부 | **아니다** |

## 15. Structural Decision

**B. AUDIT-ONLY / FUTURE ARCHITECTURE GAP.**

`C` 가 아닌 이유: `legal_actions()` 와 실제 실행이 **같은** canonical path 를
쓰고 있고(3-E-13 이 관문을 하나로 합쳤다), 지금 잘못 표현되는 정상 행동이
없다. §7 의 네 가지 POSSIBLE 은 **유발 후보가 0개이므로 현재 실행에서 일어나지
않는다.** "구현되지 않았다" 를 `C` 로 올리지 않는다.

**신규 STRUCTURAL ID 없음.** §18 의 네 조건 중 1번("현재 architecture 에서 실제
실행 불가능")이 성립하지 않고, 2번도 성립하지 않는다 — 이미 등록된 TODO 가
덮는다:

* **STRUCTURAL-31** (2-F-3-D) — "대상/비용을 채워 줄 계층이 없다"
  (3-E-21 이 그 계층의 정체를 `PlayerAction` → `EffectActivator` 로 특정했다).
* `UNRESOLVED_ORDER_RULES` — SEGOC · 묶음 순서 · 강제/임의 우선순위 ·
  **같은 플레이어의 순서 선택** · trigger placement.
* 이번 감사가 더한 것은 그 목록에 들어갈 **사실 하나**다: *사건 identity 와
  사건 주체가 후보·조건 계층에 전달되지 않는다.* ID 를 새로 만들지 않고 이
  문서에 기록한다.

## 16. 기존 TODO

| ID | 상태 |
|---|---|
| STRUCTURAL-31 / -32 / -33 | **유지** (31 은 이번 감사가 성격을 더 좁혔다) |
| STRUCTURAL-34 | 유지 — unaffected |
| STRUCTURAL-124 / -128 / -131 / -133 | 유지 |
| STRUCTURAL-134 · SET_ACTIVATION_MISSING | RESOLVED 유지 |
| SET_ACTIVATION_TIMING · SET_ACTIVATION_EXECUTION · SET_CARD_EFFECT_EXECUTION | 유지 |
| AFTER_CHAIN_RULE · UNRESOLVED_PROGRESSION_RULES · UNRESOLVED_ORDER_RULES | 유지 |

## 17. Tests

신규 `tests/test_trigger_lifetime_audit.py` — **12개**.

| # | 검증 |
|---|---|
| 01 | `legal_actions` 는 같은 상태에서 두 번 부르면 동일하다 |
| 02 | 후보 생성이 사건·저널·트리거를 읽지 않는다 (AST) |
| 03 | `TriggerCandidate` 와 `PlayerAction` 을 **코드로** 함께 다루는 모듈이 없다 |
| 04 | 사건 번호는 저널에 있고 `TimingEvent` 에는 없다 |
| 05 | 서로 다른 두 사건의 후보 identity 가 같다 |
| 06 | 후보가 사건의 주체를 모른다 · `ConditionContext` 에 사건 자리가 없다 |
| 07 | 같은 사건을 두 번 모으면 후보가 두 벌 나온다 |
| 08 | "처리했다" 를 적는 자리가 없다 (`Duel` 필드 고정) |
| 09 | `GameState` 가 역사를 담지 않기로 한 결정 (`canonical_state`) |
| 10 | 사본은 판만 복제하고 흐름은 값으로 공유한다 |
| 11 | 비공개 사실은 관측이 아니라 **값으로** 관문에 간다 |
| 12 | 유발 metadata 11,484개 vs 등록 0개 |

고의 위반 5건 — 전부 잡혔다 (넣고 → 실패 확인 → `git checkout` 되돌림):

| | 위반 | 잡은 테스트 |
|---|---|---|
| A | 후보 생성이 `state.journal` 을 읽는다 | 02 |
| B | `TimingEvent` 에 `sequence` 를 더한다 | 04 |
| C | `ConditionContext` 에 `event` 를 더한다 | 06 |
| D | `GameState` 가 역사를 해시에 넣는다 | 09 |
| E | `Duel` 에 처리 기록 필드를 더한다 | 03 · 08 |

전체: **3605 passed · 4 skipped · 0 failed · 358s.**
Regression **0** · 신규 12 · 수정 **0** · 삭제 **0** · skip 증가 **0**.

## 18. 다음 Phase 후보 — 정확히 하나

> **`Event → TriggerCandidate` 의 주체 연결 감사** — `ConditionContext` 에
> 사건이 없다는 사실의 범위를 재는 감사.
>
> 이번 감사는 번역 지점이 **두 개** 비어 있음을 보여 주었고, 뒤쪽
> (`Candidate → PlayerAction`)보다 앞쪽이 더 근본적이다: 조건 계층에 사건이
> 닿지 않으면 "이 카드가 파괴되었을 때" 를 **판정할 수조차 없고**, 그러면
> 후보를 만들어도 전부 `UNKNOWN` 이거나 거짓 `ELIGIBLE` 이 된다
> (`test_06` 이 후자를 실측했다).
>
> 그래서 다음 질문은 이것이다: **지금 `Condition` 어휘(술어 목록) 중 몇 개가
> "사건"을 필요로 하는가?** `previous_location` 758건처럼 이미 과거를 묻는
> 술어가 있으므로, 그 술어들이 실제로 무엇을 요구하는지 세어 보면 "사건을
> 어디까지 전달해야 하는가" 의 크기가 정해진다. 그 크기를 모르는 채로 사건
> 전달 구조를 만들면 또 추측이 된다.

다음 Phase 는 지시 없이 진행하지 않는다.
