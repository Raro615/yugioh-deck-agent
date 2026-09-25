# Phase 2-AF — Partial Effect Outcome & Value Domain Resolution Core

기준 커밋: `ac87a14` (Phase 2-AE) · 2716 passed / 4 skipped

```
Operation
  → OperationResult
      ├── outcome           규칙대로 되었는가   (2-AE)
      ├── attempted_count   **하려고 한** 수    ← 이번
      └── affected_count    실제로 한 수
  → ResultRef → 후속 Operation

SelectionCount   값을 **정한다**
  → ValueDomain  그 값이 **되는지 본다**        ← 이번
  → Operation
```

한 줄 목표: **일부만 되는 일과 전부 되는 일을 가르고, 계산된 값이 되는지
따로 판정하되, 어느 쪽도 엔진이 임의로 정하지 않는다.**

STRUCTURAL-88 · 89 를 다룬다.

---

## 1. 변경 파일 (§35-2)

| 파일 | 변경 |
|---|---|
| `engine/execution.py` | `ValueDomain` · `ValueDomainKind` · `DomainVerdict` · `ResultField.ATTEMPTED_COUNT` · `OperationResult.attempted_count` + `is_complete`/`is_partial`/`did_nothing` |
| `engine/effect/operation.py` | `Partial` · `CardOperation.partial` |
| `engine/effect/target.py` | `SelectionCount.domain` |
| `engine/effect/executor.py` | 관문이 막은 한 장을 **건너뛰는 길** · `_may_skip` · `_Step.attempted` · 값 도메인 검사 |
| `tests/engine/test_partial_outcome.py` | **신규** — 32 함수 / 38 케이스 |
| `test_operation_result.py` · `test_execution_context.py` | 단언 갱신 2건 (§25) |
| `docs/phase2af-partial-outcome.md` · `engine/__init__.py` | 문서 |

**새 모듈 0개.** 새 EventBus · RandomEngine · ReplayEngine · Expression
Engine 0개. 판정 어휘도 새로 만들지 않았다 — `ActionValidity`
(VALID/INVALID/UNKNOWN)를 그대로 쓴다.

---

## 2. STRUCTURAL-88 조사 — 91곳이 실제로 묻는 것 (§3 · §22)

조작의 반환값을 받아 쓰는 자리를 **무엇을 묻는가**로 다시 세었다.

| 묻는 것 | 건 | 예 |
|---|---:|---|
| C 하나라도 됐는가 (`if ct>0 then …`) | 64 | 10875327 · 16272453 · 17775525 |
| D 하나도 안 됐는가 (`if ct==0 then return end`) | 26 | 11167052 · 13210191 · 14198496 |
| E 처리된 수를 값으로 쓴다 | 39 | 12215894 · 11481610 |
| F **전부** 됐는가 (`dc == ct`) | 4 | 59490397 · 48814566 |
| B 몇 개 이상 됐는가 | 3 | 31222701 · 70569684 |
| A · G 그 밖 | 5 | |

**결정적인 발견은 여기다.** C(64) + D(26) = **90곳이 "몇 개 됐는가" 만
묻는다.** 어느 대상이 됐고 어느 대상이 안 됐는지는 **묻지 않는다.**
F(4) 조차 수끼리 비교한다.

그래서 **대상별 결과를 저장하지 않았다.** §2 가 경고한 그대로다 —
"모든 카드에 per-target result 를 강제로 저장하는 것도 피한다". 필요한
것은 **수 두 개**였다.

---

## 3. 시도한 수와 한 수 (§4 · §5 · §9)

```python
OperationResult(operation_index=0, attempted_count=3, affected_count=2)
```

세 질문이 **파생**된다.

| | 뜻 |
|---|---|
| `is_complete` | 하려던 것을 전부 했다 |
| `is_partial` | 일부만 했다 — **실패가 아니다** |
| `did_nothing` | 하려고 했는데 하나도 못 했다 |

**`failed_count` 를 저장하지 않는다** (§9). 그것은 이 둘의 차이이고,
저장하면 두 값이 어긋날 수 있다.

**`PARTIAL` 이라는 상태를 만들지 않았다** (§4 가 "무조건 만들지 말고
조사하라" 고 한 것). `OperationOutcome` 은 여전히 "규칙대로 되었는가"
(SUCCEEDED · UNKNOWN)에만 답한다 — 셋 중 하나를 규칙이 막고 둘을 했다면
그 둘은 **규칙대로 된 것**이므로, 완결성과 성패는 다른 축이다.

---

## 4. 일부만 하는 것은 **카드가 선언한다** (§8)

§8 이 가장 조심하라고 한 지점이다 — "하나라도 실패하면 전체 실패" 도
"하나라도 성공하면 전체 성공" 도 일반 규칙으로 만들지 말 것.

그래서 **엔진이 정하지 않는다. 카드가 말한다.**

```
2333466   "destroy **as many** other cards on the field **as possible**"
21623008  "Each player sends the top 2 cards of their Deck to the GY
           (**or as many as possible**)"
35699     "Destroy **as many** cards you control **as possible**"
```

공식 영문 텍스트에서 이 문구를 쓰는 카드가 **203장**이다 (몬스터 100 ·
마법 52 · 함정 51). 동사는 destroy 89 · summon 47 · send 8 · banish 7 ·
shuffle 6 · return 6 · tribute 4 · discard 3.

Phase 2-X 가 관문을, 2-AC 가 부족 처리를 카드가 선언하게 한 것과 **같은
발견**이다: 카드가 적어야 아는 것이면 카드가 말하게 한다.

```python
CardOperation(operation=DESTROY, target_ref=..., partial=Partial.AS_MANY_AS_POSSIBLE)
```

적어 두지 않은 카드는 이 길을 타지 않는다 — 기본값
`ALL_OR_NOTHING` 이 곧 "이 카드는 아무 말도 하지 않았다" 는 사실이다.

### 규칙서에 없었다

"내성을 가진 한 장만 남고 나머지는 파괴된다" 를 `data/rules/` 의
구조화 규칙서에서 **찾지 못했다** (0건). 공식 재정도 이 단계에서 받아
오지 않았다. 그래서 그 일반 규칙을 엔진에 심지 않았고, **카드 텍스트가
직접 말한 경우에만** 부분 적용을 허용한다. Phase 2-M 의 STRUCTURAL-49
("안전한 쪽으로 통째로 멈춘다")는 **선언이 없는 카드에서 그대로
유지된다.**

---

## 5. 모르는 것은 건너뛰지 않는다 (§7)

건너뛰려면 **둘이 동시에** 참이어야 한다.

1. 카드가 "가능한 만큼" 이라고 적었다.
2. 규칙이 **"안 된다" 고 답했다** (`ConditionResult.FALSE`).

두 번째가 핵심이다. `UNKNOWN` 은 판정할 규칙이 없다는 뜻이고, 그것을
건너뛰면 "이 카드가 처리됐어야 하는가" 를 **엔진이 정하는 것**이 된다.

| 관문의 답 | `ALL_OR_NOTHING` | `AS_MANY_AS_POSSIBLE` |
|---|---|---|
| TRUE | 한다 | 한다 |
| FALSE | **전부 멈춘다** | **그 한 장만 뺀다** |
| UNKNOWN | 전부 멈춘다 | **전부 멈춘다** |

§7 의 네 갈래는 이렇게 답한다.

```
TARGET FAILED        관문이 FALSE — 선언이 있으면 빼고, 없으면 전체 거절
TARGET UNKNOWN       관문이 UNKNOWN — 언제나 전체 거절
TARGET NOT_APPLIED   고르지 않은 카드. 애초에 대상이 아니므로 결과에 없다
OPERATION FORBIDDEN  출처 금지 — 계획을 시작하기도 전에 답한다 (ADR-004)
```

`NOT_APPLIED` 를 값으로 만들지 않은 이유: 고르지 않은 카드는 **대상이
아니다.** 대상이 아닌 것에 결과를 붙이면 "안 골랐다" 와 "골랐는데 못
했다" 가 같은 자리에 들어간다.

---

## 6. 대상 신원 (§6)

**새 식별자를 만들지 않았다.** 그리고 **저장하지도 않았다.**

- 조작마다 대상 이름은 하나(`target_ref`)이므로, **조작 번호가 곧 그
  대상의 결과를 가리키는 손잡이**다 (2-AD 의 `ResultRef`).
- 막힌 카드의 `InstanceId` 는 결과에 **남기지 않는다.** corpus 가
  요구하지 않고(90/94), 남기면 가려진 카드의 정체가 결과를 통해 샐 길이
  생긴다 (§29).
- `CardInstance` 객체를 결과나 저널에 넣지 않는다 — `canonical_state` 와
  복제가 깨진다.

---

## 7. STRUCTURAL-89 조사 — 도메인이 값마다 묻는 것 (§11 · §20)

`AnnounceNumber` 의 목록을 만드는 `for` 루프를 전부 꺼내 읽었다.

| 값마다 무엇을 판정하는가 | 건 | 지금 |
|---|---:|---|
| **판정 없음** — 산술만 (`t[i]=i*100`) | 6 | **이미 됐다** (2-AE) |
| **판이 그 수를 치를 수 있는가** (`IsPlayerCanDiscardDeckAsCost(tp,i)` · `CheckLPCost(tp,1000*p)`) | 5 | **이번에 된다** (`BOUNDED`) |
| **그 수에 해당하는 카드가 있는가** (`IsExistingMatchingCard(…, i, g)`) | 5 | `RULE_UNRESOLVED` → 언제나 UNKNOWN |
| 그 수를 제외 (`i~=tc:GetLeftScale()`) | 1 | 범위 밖 |
| 이미 만든 목록을 **정렬**하는 코드 | 4 | 도메인 문제가 아니었다 |

§20 이 경고한 그대로다 — `table.unpack` 이 있다고 모두 계산 문제가
아니다. 넷은 **정렬**이었고 여섯은 **산술뿐**이었다.

"판이 그 수를 치를 수 있는가" 는 결국 **"i 가 판의 어떤 양을 넘지
않는가"** 이고, 그것은 이미 있는 `BoardQuantity` 로 그대로 적힌다. 새
규칙이 필요하지 않았다.

---

## 8. `ValueDomain` (§10 ~ §15 · §17 · §18)

세 갈래뿐이다. **corpus 에 없는 종류는 만들지 않았다** (§13).

| 갈래 | 뜻 | 근거 |
|---|---|---|
| `AT_LEAST_ONE` | 1 이상 | 장수를 다루는 모든 값 |
| `BOUNDED` | 판에서 읽은 양을 넘지 않는다 | 위의 5건 |
| `RULE_UNRESOLVED` | **값마다 규칙이 필요한데 없다** | 위의 5건 |

`EXACT` 도 `NON_NEGATIVE` 도 만들지 않았다 — 쓰는 카드를 못 찾았다.

### `RULE_UNRESOLVED` 가 이 단계의 핵심이다

자리표시가 아니라 **지금 엔진의 정직한 상태**다. 이 갈래가 있어서
"적을 수는 있지만 판정할 수 없다" 를 적을 수 있다. 없으면 그런 카드는
아예 표현되지 못하거나, 더 나쁘게는 **조건 없이 통과한다.**

### 값과 도메인은 따로 산다 (§12 · §14)

```
SelectionCount.resolve(…)   →  3          값을 정한다
ValueDomain.validate(3, …)  →  VALID      그 값이 되는지 본다
```

`ValueDomain.validate` 는 **값을 계산하지 않는다.** 이미 나온 값을 받아
판정만 한다. 순서도 그래서 값 → 도메인이다 — 값이 없으면 검사할 것도
없다.

`SelectionCount.domain` 은 그 둘을 잇는 **한 칸**일 뿐 합친 것이 아니다.
`None` 이면 "무엇이든 된다" 가 아니라 **"안 봤다"** 는 뜻이다.

### 셋을 섞지 않는다 (§15 · §17 · §18)

```
VALUE UNKNOWN    값을 계산할 수 없다          → missing 에 없는 계층
DOMAIN UNKNOWN   값은 3인데 되는지 모른다      → missing 에 없는 규칙
INVALID          값은 9인데 8000 을 넘는다
```

셋 다 멈추지만 **다른 것을 고쳐야 한다.** 그리고
`NumberDomain`(고르기 전) ≠ `ValueDomain`(값이 나온 뒤) ≠
`SelectionCount`(몇 개인가) — 타입이 셋 다 다르고, 서로의 메서드를
갖고 있지 않다는 것을 테스트가 확인한다.

---

## 9. 경계와 안전성 (§16 · §23 ~ §29)

| 경계 | 어떻게 지키는가 |
|---|---|
| 실행값 ≠ 판 | `execution.py` 가 `GameState`·`GameStateView` 를 import 하지도 이름을 쓰지도 않는다 (AST) |
| 막힌 카드 ≠ 공개 | 막힌 카드의 정체가 결과·이유·저널 어디에도 없다 |
| 결과 ≠ 사건 | 저널에 `attempted`·`refused`·`partial`·`domain` 이 적히지 않는다 |
| 계획 ≠ 적용 | 부분 적용도 **계획 단계에서 확정**된다 — 적용은 계획한 그대로만 한다 |

**부분 적용은 rollback 을 만들지 않는다** (§23). 어느 카드를 건너뛸지는
계획에서 정해지므로, 적용 도중에 실패해서 반쯤 남는 일이 없다. 뒤의
조작이 막히면 **앞의 부분 적용도 일어나지 않는다.**

**결정론**: 대상 순서는 고른 순서(`Selection`) 그대로이고 집합을 거치지
않는다. 같은 판·같은 판정기면 같은 결과가 나온다.

**복제 독립**: 실행값은 판에 붙어 있지 않고 `execute()` 한 번 안에서만
산다 (2-AD 와 같다).

**`state_hash` 는 한 줄도 바꾸지 않았다.**

---

## 10. 테스트 (§32)

`tests/engine/test_partial_outcome.py` — **32 함수 / 38 케이스**, 전부 통과.

| 절 | 무엇을 붙잡는가 |
|---|---|
| A · B · C | 전부 된다 · 선언하면 되는 것만 한다 · **선언하지 않으면 아무것도 안 한다** · 전부 막히면 일어난 일이 없다 |
| D | `UNKNOWN` 은 **어느 쪽에서도** 건너뛰지 않는다 · 건너뛰려면 선언과 거절이 **동시에** 필요하다 (AST) |
| E · F · G | 시도와 처리를 따로 답한다 · `failed_count` 가 없다 · 세 질문(`is_complete`/`is_partial`/`did_nothing`) · 일부는 실패가 아니다 · 두 수를 각각 가리킨다 · 장수가 없는 일은 둘 다 없다 |
| H ~ K | VALID · INVALID · 도메인 UNKNOWN · **판을 못 봤으면 통과가 아니라 UNKNOWN** · 값 UNKNOWN 과 도메인 UNKNOWN 이 다른 이유로 멈춘다 · 실제 실행에서도 검사된다 |
| L · M | 세 타입이 서로의 메서드를 갖고 있지 않다 · 도메인을 안 적은 것은 "안 봤다" 다 · 모양이 어긋난 도메인은 태어나지 못한다 |
| N | 셋 중 둘만 됐으면 다음 일은 **둘** · 시도한 수는 **셋** |
| O ~ T | 막힌 카드의 정체가 안 샌다 · 값 계층은 관측을 모른다 (AST) · 같은 판이면 같은 결과 · 복제 독립 · 뒤가 막히면 부분 적용도 없다 · 저널엔 일어난 일만 · 해시 그대로 |
| U | 203장의 텍스트가 근거다 · 값마다 판정이 필요한 도메인은 `UNKNOWN` · 치를 수 있는가는 새 규칙이 필요 없다 · **0장 등재** |

---

## 11. 회귀

```
2754 passed, 4 skipped in 37.37s     (기준선 2716 + 38)
```

---

## 12. 실제 카드 (§21 · §30 · §35-23)

**0장 등재했다.**

"가능한 만큼" 카드 203장 중 마법·함정이 103장이지만, 그중 대부분이
**파괴**이고 파괴는 관문을 받는다 — `UnknownDestructionRuling` 이 모든
카드에 `UNKNOWN` 을 답하므로 **어떤 파괴도 일어나지 않는다** (ADR-006).
부분 적용을 만들었다고 그 벽이 사라지지 않는다.

그래서 이번 단계의 검증은 **시험용 판정기**로 했다. 판정기가 "이 한 장은
파괴되지 않는다" 고 답할 때 나머지 둘이 파괴되는지, 그리고 "모르겠다"
고 답할 때 전부 멈추는지를 실제 실행으로 확인한다. 판정기를 실제 카드에
붙이는 것은 파괴 내성을 읽는 계층의 일이고, 그것은 여전히 없다.

---

## 13. TODO (§35-26)

- **STRUCTURAL-88 — 해결(표현).** 시도와 처리를 따로 답하고, 부분 적용을
  카드가 선언할 수 있다. 다만 **조건부 계속**("앞이 하나라도 됐으면 뒤를
  한다")은 여전히 없다 — 아래 91 이 그것이다.
- **STRUCTURAL-89 — 부분 해결.** 도메인 판정 중 "치를 수 있는가" 는
  되고, "그 수에 해당하는 카드가 있는가" 는 `RULE_UNRESOLVED` 로 적히되
  판정되지 않는다 (아래 92).
- **STRUCTURAL-91 (신규 · 🟠)** — **조건부 계속이 없다.** 실제 카드
  64곳이 `if ct>0 then <뒤의 일> end` 이다. 지금은 앞이 부분 적용이어도
  뒤의 일이 **언제나** 일어난다. 이것을 적으려면 조작에 "앞이 하나라도
  됐을 때만" 이라는 조건이 필요하고, 그것은 2-AE 의
  `OperationRequirement` 를 수(``affected_count``)에까지 넓히는 일이다.
  **이번에 넓히지 않았다** — 넓히면 "수를 조건처럼 읽는 것" 을 막아 둔
  2-AE 의 결정과 정면으로 부딪히므로, 어느 쪽이 옳은지 먼저 정해야 한다.
- **STRUCTURAL-92 (신규 · 🟠)** — **조건이 수를 인자로 받지 못한다.**
  "레벨이 i 인 카드가 있는가" 를 판정할 수 없어 도메인 5건이 막힌다.
  조건 계층에 인자를 더하는 일이고, 조건 엔진 재작성과는 다르다.
- **STRUCTURAL-90 (`SelectionCount` 이름) — 그대로 둔다.**
- **83 · 86 · 87 — 그대로 둔다** (§31 의 지시).
- 71 · 74 · 75 · 76 · 77 · 78 — **하나도 건드리지 않았다.**

---

## 14. 판정 (§34)

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 2 신규 | 91 (조건부 계속) · 92 (수를 받는 조건) |
| 🟡 DETAIL | 0 신규 | |
| 🟢 COSMETIC | 0 신규 | |

§34 가 허용하지 않는다고 한 열 가지 — 부분 실패를 전체 실패로 변환,
하나라도 성공하면 전체 성공, 성패를 장수에서 추론, `UNKNOWN` 을 실패나
0 으로 변환, 도메인 `UNKNOWN` 을 `VALID` 로 변환, 대상 신원을 객체나
순서로 저장, 암묵적 마지막 참조, 정보 누출, 판에 실행값 저장, 투기적
수식 언어 — 는 **하나도 하지 않았고**, 각각을 테스트가 막는다.

---

## 15. 기존 테스트 수정 (§26 · §35-25)

**삭제 0건.** 수정 2건.

1. `test_operation_result.py::test_c_count_is_never_read_as_success_in_the_engine` —
   "장수를 0 과 비교하는 코드가 없다" 를 단언했다. 이번에 `did_nothing`
   (`affected_count == 0`)이 생기면서 걸렸는데, **그 비교는 성패 질문이
   아니라 장수 질문**이다. 그래서 검사를 날카롭게 했다 —
   **`OperationOutcome` 을 다루는 함수**가 장수를 읽지 않는지 본다.
   막으려던 것(성패를 장수에서 뽑아내기)을 **더 정확히** 막는다.
2. `test_execution_context.py::test_i_a_failed_operation_still_leaves_no_result` —
   `ResultField` 의 칸 수를 센다. `ATTEMPTED_COUNT` 가 늘었으므로 늘어난
   것을 적어 두고 계속 센다. 이 시험의 일이 원래 "칸이 조용히 늘어나는
   것을 막는 것" 이다.

---

## 16. 이번에 하지 않은 것 (§31)

AI · 덱 빌더 · 지속 효과 전체 · SEGOC · 아키타입 · 융합 조건 · 범용 수식
언어 · 새 EventBus · 새 RandomEngine · 새 ReplayEngine · 부분 적용 카드
203장 자동 구현 · 도메인 사례 자동 구현 · STRUCTURAL-83 · 86 · 87 · 90.

**다음 Phase 는 시작하지 않았다.**
