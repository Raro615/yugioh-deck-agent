# Phase 2-R — Chain Response / Priority Loop

기준 커밋: `aa0735a` (Phase 2-Q Effect Activation Core)

```
Chain [L1]  +  PriorityState(RESPONSE, P1)     ← ResponseState
    ↓  ResponseLoop.act(state, response, PlayerAction)
    ├ PASS             ──►  우선권만 넘어간다. 판도 체인도 그대로
    └ ACTIVATE_EFFECT  ──►  EffectActivator (2-Q)
                            ──►  Chain [L1, L2], 우선권은 상대에게
    ↓  둘 다 연속 패스
ResponseLoop.ready_to_resolve()  →  VALID
    ↓  ResponseLoop.resolve(state, response, ChainResolver)
L2 → L1  (LIFO)
```

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/response.py` | **신규** — `ResponseState` · `ResponseResult` · `ResponseResolution` · `ResponseLoop` |
| `tests/engine/test_chain_response.py` | 신규 — 함수 39개 |
| `docs/phase2r-chain-response.md` | 신규 |
| `engine/__init__.py` | Phase 2-R 항목 |

기존 모듈은 **한 줄도 바꾸지 않았다.**

---

## 2. 조사 — 이미 있던 것

| 필요했던 것 | 이미 있던 것 |
|---|---|
| 차례 · 연속 패스 · 응답 기회 | `PriorityState` · `PriorityHolder` · `ResponseWindow` (2-F-1) |
| "지금 이 자리 차례인가" | `PriorityResolver.may_act` (2-F-1) |
| 링크 쌓기 · LIFO | `Chain` · `ChainLink` · `ChainResolver` (2-F-2) |
| 발동 | `EffectActivator` (2-Q) |
| 트리거 → 체인 | `TriggerChainIntegrator` (2-F-3-D) |

`Chain` 과 `PriorityState` 는 서로를 모르도록 나뉘어 있었고
(2-F-2 의 "우선권은 체인을 모르고, 체인은 우선권을 모른다 — 둘을 잇는 것은
이후 단계의 몫"), **그 "이후 단계" 가 이번이다.** `ResponseState` 는 둘을
나란히 담기만 하고, 어느 쪽에도 새 칸을 만들지 않았다.

`TimingCoordinator` 는 우선권을 **확인만 하고 돌리지 않는다** ("그 규칙은
아직 없다. 지금 만들면 틀린 채로 굳는다"). 이번 단계도 그 태도를 유지하되,
**응답 루프 안에서의 차례 넘김**만 정한다 — 그것은 OCG 규칙을 지어내는 것이
아니라 "응답 루프" 라는 개념 자체의 모양이기 때문이다.

---

## 3. Response Loop

`ResponseLoop.act(state, response, action, selections, cost_selections,
authorization)` → `ResponseResult`.

**순서가 규칙이다.** 차례인지 먼저 보고, 그 다음에 무엇을 하려는지 본다 —
차례가 아닌 사람의 발동이 비용을 치르고 나서 거절되면 되돌릴 수 없다.

| 결과 | 체인 | 판 | 우선권 |
|---|---|---|---|
| `LINK_ADDED` | +1 | 비용만큼 | **상대에게** |
| `PASSED` | 그대로 | 그대로 | 상대에게 (연속 패스 +1) |
| `REFUSED` | 그대로 | 그대로 | **그대로** |

### `ResponseStep` 은 저장하지 않는다

```python
NO_CHAIN        체인이 비었거나 다 풀렸다
AWAIT_RESPONSE  아직 누군가 응답할 차례
RESOLVE         양쪽이 연속으로 패스했다
```

체인과 우선권에서 **읽는다.** 저장하면 둘과 어긋날 수 있고, 어긋난 순간
어느 쪽이 맞는지 알 수 없다. `ResponseState` 의 필드는 `chain` 과
`priority` 둘뿐이고 `step` 은 `property` 다.

빈 체인에서의 연속 패스는 `RESOLVE` 가 **아니다** — 그것은 다른 뜻(페이즈
넘김 등)이고, 그 뜻은 이 계층이 정하지 않는다.

---

## 4. Priority

`PriorityResolver.may_act(seat)` 를 그대로 쓴다. 새 우선권 시스템을 만들지
않았다 (테스트가 `engine/response.py` 에 `PriorityState` 류 클래스가 정의되지
않음을 AST 로 확인한다).

| 전이 | 쓰는 것 |
|---|---|
| 패스 | `priority.passed()` — 상대에게, 연속 패스 +1 |
| 발동 | `priority.acted().give_to(holder.opponent)` — 상대에게, 연속 패스 0 |
| 거절 | **없음** |
| 해결 후 | `priority.closed(AFTER_CHAIN_RULE)` |

### STRUCTURAL-34 는 blocker 가 아니었다 — 다만 그대로 남는다

이번 단계가 정한 것은 **응답 루프 안에서의 차례 넘김**뿐이다. 여전히 정하지
않은 것:

- **누가 응답 기회를 여는가.** `ResponseLoop.opened(...)` 는 부르는 쪽이
  값으로 여는 **도구**이고, "링크가 쌓였으니 자동으로 열린다" 는 규칙이
  아니다.
- **체인이 끝난 뒤 누구에게 우선권이 가는가.** `resolve` 는 지어내는 대신
  기회를 **닫고**, 이유에 `AFTER_CHAIN_RULE` 을 남긴다.

---

## 5. PASS

**효과가 아니다.** `GameState` mutation 없음 · 링크 없음 · 체인 내용 변화
없음 · `state_hash` 불변. 바뀌는 것은 우선권뿐이다 — §5 가 요구한
"GameState mutation 과 Priority state transition 의 구분" 이 그대로 값으로
나온다 (`result.deltas == ()` 인데 `result.priority` 는 달라진다).

차례가 아닌 사람의 패스는 `REFUSED` 이고 우선권도 옮기지 않는다.

---

## 6. ACTIVATE_EFFECT 응답

Phase 2-Q 의 `EffectActivator` 를 **그대로** 부른다. 루프가
`EffectExecutor` · `ChainResolver` · `Operation` 을 직접 부르지 않는다는 것을
테스트가 AST 로 확인한다 (`EffectExecutor` · `execute` · `CardOperation` 이
`engine/response.py` 에 이름으로도 나오지 않는다).

비용은 **응답 시점에** 빠져나가고 (`LifeCost(600)` → 그 자리에서 600),
효과는 해결 때까지 일어나지 않는다.

---

## 7. ChainLink 추가 · 체인 무결성

`chain.push(link)` — **새 체인**을 돌려준다.

| 보는 것 | 확인 |
|---|---|
| 기존 링크의 `effect_ref` | 그대로 |
| 기존 링크의 `selections` | 그대로 |
| 기존 링크의 `payments` | 그대로 |
| 기존 링크 객체 | **같은 객체** (`is` 비교) · `canonical_state()` 동일 |
| `sequence` | `[0, 1]` 결정적 |
| 원래 체인 | 길이 0 그대로 |

---

## 8. Trigger vs Response — 합치지 않는다

| | 왜 링크가 얹히는가 | 순서를 정하는 것 |
|---|---|---|
| **트리거** (2-F-3) | 하나의 **사건** 때문에 여럿이 동시에 후보가 된다 | 순서화 계층 (턴 플레이어 우선) |
| **응답** (2-R) | 우선권을 쥔 **한 사람의 결정** | 우선권 |

§10 이 요구한 두 테스트를 따로 만들었다.

- **Test A** — 하나의 `CardDrawn` 사건에서 필드의 같은 카드 2장이 **동시에**
  후보가 되고, `TriggerChainIntegrator` 가 링크 2개로 만든다.
- **Test B** — 이미 쌓인 체인에 **B 한 사람**이 응답으로 하나를 얹는다.

경계도 코드로 고정했다.

- `engine/response.py` 는 `engine.trigger*` 를 import 하지 않고
  `TriggerCollector` · `TriggerChainIntegrator` · `TriggerOrderer` ·
  `TimingEvent` 를 쓰지도 않는다.
- `engine/trigger_chain.py` 는 `engine.priority` 도 `engine.response` 도
  import 하지 않는다.

---

## 9. 연속 패스 → 10. Resolution

`ready_to_resolve(response) -> ValidationResult` — 새 어휘를 만들지 않았다.

| 상태 | 답 |
|---|---|
| 양쪽 연속 패스 + 남은 링크 | `VALID` |
| 체인 없음 / 다 풀림 | `INVALID` / `CHAIN_EMPTY` |
| 아직 응답 차례 | `INVALID` / `NO_RESPONSE_WINDOW` |

`resolve(state, response, resolver)` 는 허가가 나야만 기존
`ChainResolver.resolve_all` 에 넘긴다. **새 Resolver 를 만들지 않았다.**
허가가 없으면 `steps == ()` 이고 `state` 는 들어온 그대로다.

---

## 11. synthetic A→B 시나리오 (§8)

```
A: 효과 X 발동 (B의 몬스터 대상)   →  Chain[L1], 우선권 → B
B: 효과 Y 발동 (A의 몬스터 대상)   →  Chain[L1,L2], 우선권 → A
A: PASS                            →  우선권 → B, 연속 1
B: PASS                            →  우선권 → A, 연속 2 → step=RESOLVE
resolve                            →  L2(Y) 먼저, L1(X) 나중
```

- 네 번째 패스 직후까지 **양쪽 몬스터 모두 MZONE 에 그대로** 있다.
- `[link.effect_ref for link in chain] == [X, Y]` (발동 순서)
- `[step.link.effect_ref for step in done.steps] == [Y, X]` (**LIFO**)

---

## 12. Failure matrix — 전부 체인 · 판 · 우선권 불변

| 상황 | outcome | code / 발동 상태 |
|---|---|---|
| 차례가 아님 | `REFUSED` | `NOT_PRIORITY_HOLDER` |
| 허가 없음 | `REFUSED` | `ActivationStatus.UNAUTHORIZED` |
| 부적법한 대상 | `REFUSED` | 대상 계층의 코드 |
| 대상 없음 | `REFUSED` | `TOO_FEW_SELECTED` |
| 발동이 아닌 행위 | `REFUSED` | 루프가 다루지 못함 (`missing` 명시) |
| `TEXT_DERIVED` | `REFUSED` | `ActivationStatus.FORBIDDEN` |
| 구현 미등록 | `REFUSED` | `ActivationStatus.NOT_IMPLEMENTED` |
| 비용 부족 | `REFUSED` | `ActivationStatus.COST_UNPAYABLE` |

**거절은 차례를 빼앗지 않는다.** 거절 뒤 같은 사람이 다시 시도해서 성공하는
것을 테스트가 확인한다 — 실패를 패스로 바꾸면 되돌릴 수 없는 차례가 조용히
날아간다.

`ResponseResult` 자체도 모순을 막는다: `LINK_ADDED` 인데 링크가 없거나,
`LINK_ADDED` 가 아닌데 발동이 성공했다고 되어 있으면 `ResponseError` 다.
`__bool__` 은 언제나 `TypeError`.

---

## 13. Determinism · clone

| 보는 것 | 확인 |
|---|---|
| 같은 행위 순서 → 같은 위치 | `ResponseState.canonical_state()` 동일 |
| 같은 행위 순서 → 같은 판 | `state_hash()` 동일 |
| 같은 행위 순서 → 같은 해결 순서 | `ResponseResolution.canonical_state()` 동일 |
| **복제 독립성** | 복제본에서 비용을 치러도 원본 라이프·해시 불변 |
| 읽기만 하는 질문 | `may_act` · `ready_to_resolve` 를 몇 번 불러도 판 불변 |

---

## 14. Hidden information

- A 의 패에만 있는 카드(판 어디에도 없는 번호)를 B 가 대상으로 골라
  거절당해도, `to_dict()` 어디에도 그 `card_id` 가 없다.
- 관측은 **결정하는 자리의 시점**으로 만든다 — `viewer=seat` 뿐임을 AST 로
  확인한다.

---

## 15. AI 경계

PASS 도 발동도 밖에서 온 `PlayerAction` 이다. `engine/response.py` 에
`choose` · `decide` · `score` · `policy` · `best` 라는 함수가 없고
`random` 도 없다.

---

## 16. 남은 것 (기록만)

- **STRUCTURAL-34 (관찰, blocker 아님)** — 우선권 갱신의 **주체**는 여전히
  정해지지 않았다. 이번 단계가 정한 것은 응답 루프 안에서의 차례 넘김뿐이고,
  기회를 여는 것과 체인이 끝난 뒤의 우선권은 지어내지 않았다.
- **STRUCTURAL-57 (신규)** — `ResponseLoop.opened` 가 **규칙이 아니라
  도구**다. "링크가 쌓였으니 응답 기회가 열린다" 를 자동으로 만들지
  않았으므로, 지금은 부르는 쪽이 매번 기회를 열어 줘야 한다. 게임 루프
  계층이 생길 때 채워진다.
- **STRUCTURAL-58 (신규)** — 응답 발동이 "이 시점에 이 효과를 발동해도
  되는가"(스펠 스피드 · 체인 블록 · 체인 중 발동 가능 여부)를 판정하지
  못한다. 여전히 밖에서 오는 허가에 기댄다 (2-Q 의 `UNAUTHORIZED` 와 같은
  자리).
- 15 · 45 · 46 · 48 · 49 · 50 · 51 · 52 · 53 · 54 · 55 · 56 — 변동 없음.
- 아직 없는 것: SEGOC · 스펠 스피드 · 체인 블록 · 데미지 스텝 · 배틀 스텝 ·
  퀵 이펙트 타이밍 전체.

---

## 17. 테스트

`tests/engine/test_chain_response.py` — 함수 **39개**, 실행 **43건**
(G 묶음에 `parametrize` 5갈래). 전부 통과.

| 묶음 | 함수 | 보는 것 |
|---|---|---|
| A. `ResponseState` | 6 | 차례가 값으로 읽힌다 · `step` 은 파생값 |
| B. §8 시나리오 | 2 | A→B→PASS→PASS→**LIFO** |
| C. PASS | 4 | 효과가 아니다 · 우선권만 바뀐다 |
| D. 응답 발동 | 4 | 2-Q 재사용 · 실행기 미호출 |
| E. 체인 무결성 | 3 | 기존 링크 불변 · 해결 후 기회 닫힘 |
| F. 트리거 vs 응답 | 4 | 두 흐름이 서로를 모른다 |
| G. 실패 행렬 | 7 | 체인 · 판 · 우선권 불변 |
| H. 결정론 · 복제 | 4 | 같은 답 · 복제 독립 |
| I. 경계 | 5 | 정보 · 중복 금지 · AI 없음 |

전체 회귀: **2078 passed, 4 skipped** (직전 2035 + 43). 기존 테스트
수정·삭제 **0건**.
