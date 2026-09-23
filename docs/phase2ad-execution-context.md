# Phase 2-AD — Effect Choice & Execution Result Context Core

기준 커밋: `ab46299` (Phase 2-AC) · 2632 passed / 4 skipped

```
Player Choice                       Operation Result
  Effect                              Operation A
   ↓ DeclaredNumberSpec (규칙)         ↓ OperationResult (얼마나 했는가)
   ↓ DeclaredNumber     (입력)         ↓ ResultRef(번호, 칸)  ← 명시적
   ↓ ExecutionValues  ──────────────────┘
   ↓ 후속 Operation
   ↓ StateDelta → Event → EventJournal   (기존 통로 그대로)
```

한 줄 목표: **사람이 선언한 값과 앞선 조작의 결과를 실행 중에 명시적으로
가리킬 수 있게 하되, 판과 분리하고 네 가지 경계를 유지한다.**

STRUCTURAL-81 · 82 를 다룬다.

---

## 1. 변경 파일 (§28-3)

| 파일 | 변경 |
|---|---|
| `engine/execution.py` | **신규** — `ValueRef` · `NumberDomain` · `DeclaredNumberSpec` · `DeclaredNumber` · `DeclarationOutcome` · `ResultField` · `ResultRef` · `OperationResult` · `ExecutionValues` |
| `engine/effect/target.py` | `CountKind.DECLARED` · `CountKind.FROM_RESULT` · `SelectionCount.resolve(zone_size, values)` |
| `engine/effect/operation.py` | `DrawOperation.count` 가 `SelectionCount` 도 받는다 |
| `engine/effect/definition.py` | `declarations` 필드 · `_check_value_links` (뒤를 가리키면 거부) |
| `engine/effect/resolution.py` | `ResolutionContext.declarations` |
| `engine/effect/executor.py` | `_check_declarations` · 계획 단계가 결과를 쌓는다 · `_resolve_count` → `_resolve_number` |
| `tests/engine/test_execution_context.py` | **신규** — 39 함수 / 46 케이스 |
| `test_effect_model.py` · `test_selection_count.py` | 단언 갱신 2건 (§22) |
| `docs/phase2ad-execution-context.md` · `engine/__init__.py` | 문서 |

**새 EventBus · ReplayEngine · RandomEngine · EffectEngine 0개.** 새 모듈은
`engine/execution.py` 하나이고, `engine/effect/` 안의 파일 목록은 그대로다
(기존 경계 테스트가 그것을 지킨다).

---

## 2. 실행 문맥은 이미 있었다 (§1 · §8)

먼저 조사한 결과, §8 이 말한 `EffectExecutionContext` 의 **절반은 이미
있었다.**

| 이미 있던 것 | 상태 |
|---|---|
| `ResolutionContext` (effect_ref · controller · source · selections · cost_selections) | 있었다 |
| "문맥에는 값 타입만" 이라는 규칙 | 있었다 (그 파일의 docstring) |
| plan → apply 구조 | 있었다 (Phase 2-V) |
| 계획 단계가 확정한 `_Step` | 있었다 |
| **선언한 수를 담을 자리** | 없었다 |
| **앞선 조작의 결과를 담을 자리** | 없었다 |

그래서 새 문맥 클래스를 만들지 않았다. 대신 **둘로 나눠 붙였다.**

```
사람이 넣어 주는 입력      → ResolutionContext.declarations
해결 중에 생기는 값        → ExecutionValues  (실행기가 만든다)
```

나누는 기준이 있다. `ResolutionContext` 는 **부르는 쪽이 채우는 계약**이고
직렬화되어야 한다. 앞선 조작의 결과는 부르는 쪽이 알 수 없고 **해결이
진행되면서 생긴다.** 한 타입에 담으면 "밖에서 넣은 것" 과 "안에서 생긴
것" 이 섞이고, 그 순간 밖에서 결과를 위조할 수 있게 된다.

---

## 3. 네 가지를 뭉개지 않는다 (§2)

|  | 무엇인가 | 어디 |
|---|---|---|
| 고른 카드 | 사람이 고른 **것** | `Selection` (2-N) |
| 무작위로 고른 카드 | 아무도 고르지 않은 **것** | `RandomSelectionSpec` (2-AB) |
| **선언한 수** | 사람이 정한 **수** | `DeclaredNumber` (2-AD) |
| **조작의 결과** | 판이 정한 **수** | `OperationResult` (2-AD) |

앞의 둘은 "무엇을" 이고 뒤의 둘은 "얼마나" 다. 뒤의 둘끼리도 다르다 —
하나는 사람이 정했고 하나는 판이 정했다. 그래서 `CountKind` 에 갈래가
**둘** 늘었다 (`DECLARED` · `FROM_RESULT`). 하나로 합쳐 "REFERENCE" 라고
부르면 그 구분이 이름에서 사라진다.

이름 공간도 나뉘어 있다. `ValueRef` 는 `TargetRef` 와 **다른 타입**이다 —
같은 타입이면 "2장" 과 "2" 가 한 이름표를 달게 된다.

---

## 4. 선언할 수 있는 수 — 목록이다 (§5 · §25 D)

공식 스크립트를 먼저 읽었다.

```lua
Duel.AnnounceNumber(p,1,2)                       -- {1, 2}
Duel.AnnounceNumber(p,1,2,3)                     -- {1, 2, 3}
Duel.AnnounceNumber(tp,100,200,300,400,500)      -- {100, ..., 500}
Duel.AnnounceNumber(tp,table.unpack(ct))         -- 판에서 만든 목록
```

**범위가 아니라 목록이다.** 그래서 `NumberDomain` 은 허용된 수의 튜플
하나이고, `between(1, 3)` 은 그 목록을 적는 **줄임말**이다. 범위와 목록을
다른 갈래로 두면 "1~3" 과 "{1,2,3}" 이 서로 다른 것처럼 보이는데,
스크립트에서 둘은 같은 것이다.

가운데가 빈 목록(`{1, 2, 4}`)도 그냥 된다 — 목록이 본래 모양이기 때문이다.

호출 60건의 모양:

| 모양 | 건 |
|---|---:|
| 판에서 만든 목록 (`table.unpack(...)`) | 46 |
| 리터럴 연속 (`1,2` · `1,2,3` · `100,200`) | 8 |
| 리터럴 비연속 (`100,200,300,400,500` 등) | 6 |

46건은 목록 자체가 판에서 계산된다. **그것은 이번 단계에서 하지 않았다** —
`NumberDomain` 이 판을 읽기 시작하면 도메인 계산기가 하나 더 생긴다
(STRUCTURAL-85).

---

## 5. 선언의 상태 (§6 · §25 B · C)

| 상태 | 언제 | 답 |
|---|---|---|
| `RESOLVED` | 허용된 수가 들어왔다 | 그 수 |
| `PENDING` | 아직 선언하지 않았다 | `INVALID_TARGET` · `TOO_FEW_SELECTED` |
| `INVALID` | 허용되지 않은 수를 선언했다 | `INVALID_CONTEXT` · `INVALID_AMOUNT` |

**대신 정해 주지 않는다.** `PENDING` 을 1 로 채우면 "1장" 이라는 틀린
규칙이 되고, `INVALID` 의 4 를 3 으로 고치면 규칙을 정한 것은 플레이어가
아니라 실행기다. 어느 쪽이든 **판은 한 글자도 바뀌지 않고 난수도 꺼내지
않는다.**

`ResolvedDeclaration` 은 `bool()` 을 막는다 — `PENDING` 이 거짓이 되면
"아직" 이 "안 된다" 로 접힌다.

### `FORBIDDEN` 은 여기 없다

§6 이 든 네 상태 중 `FORBIDDEN` 은 **선언의 상태가 아니다.**
`TEXT_DERIVED` 출처가 실행을 금지하는 것은 효과의 문제이고, 출처 검사가
**가장 먼저** 답한다 (ADR-004). 허용된 수를 제대로 선언해도 결과는
`ResolutionStatus.FORBIDDEN` 이고, 수를 물어볼 자리까지 오지 않는다.
테스트가 그것을 확인한다 (Phase 2-AC 가 `CountOutcome` 에서 내린 결론과
같다).

---

## 6. 누가 선언하는가 (§7)

기존 어휘를 그대로 쓴다 — `DeclaredNumberSpec.chooser` 는
`ChoiceSpec.chooser` 와 **같은 타입, 같은 해석**의 `PlayerRef` 다. 새
"chooser" 의미를 만들지 않았다.

그래서 **효과의 컨트롤러가 아닌 사람이 선언하는 것**을 적을 수 있다. 실제
카드가 그렇다 — 부작용?(30922149)에서 1~3 을 정하는 것은 뽑는 쪽, 즉
상대다.

```
controller   효과를 발동한 사람
chooser      수를 정하는 사람        ← 다를 수 있다
owner        카드의 주인
beneficiary  권한을 받는 사람 (2-AA)
subject      권한이 열어 주는 자리의 주인 (2-AA)
```

---

## 7. 앞선 결과 — 번호로 가리킨다 (§9 · §10 · §20)

### 식별자를 새로 만들지 않았다

`ResultRef(operation_index, field, multiplier)` 의 `operation_index` 는
정의의 `operations` 안 **자리**다. 정의는 불변이므로 그 자리가 이미 그
조작의 신원이고, 새 ID 체계를 만들 이유가 없다 (§10 이 먼저 확인하라고 한
것).

그리고 **자기보다 앞을 가리켜야 한다**는 것을 정의를 만들 때 검사한다.

```
0번 조작이 1번 조작의 결과를 가리킵니다. 앞선 일만 읽을 수 있습니다 —
아직 일어나지 않은 일에는 결과가 없습니다.
```

이것이 "마지막 결과를 자동으로 쓴다" 를 막는 방식이다. 자동으로 집어
오면, 정의에 일을 하나 끼워 넣는 순간 **조용히 다른 수**가 된다.
가리키지 않은 정의는 앞의 수를 모른다 — 테스트가 그것을 확인한다.

### 칸은 하나뿐이다 — 그리고 그것이 사실이다

`ResultField` 에는 `AFFECTED_COUNT` 하나만 있다. §10 이 든
`selected_count` · `moved_count` · `destroyed_count` 를 따로 두지 않은
이유는, **조작의 종류가 이미 조작에 적혀 있기** 때문이다. 같은 수를
종류별 이름으로 네 번 부르면 어느 것을 읽어야 하는지가 새 문제로 생긴다.

`SUCCEEDED` 는 **일부러 만들지 않았다.** 이 실행기는 계획이 전부 끝난
뒤에야 적용을 시작하므로, 앞의 조작이 실패하면 뒤의 조작은 **아예 시작되지
않는다.** "앞이 성공했는가" 를 뒤에서 물을 수 있는 순간이 존재하지 않고,
있지도 않은 질문에 칸을 만들면 언제나 참인 값을 읽고 규칙을 지켰다고
믿게 된다. corpus 의 92건이 `if ct==0 then return end` 로 하는 일은
**부분 실패 처리**이고, 이 엔진에는 부분 실패가 없다 (STRUCTURAL-84).

`selected_card` 도 두지 않았다. 고른 카드는 이미 `TargetRef` 로 이름이
있고 (Phase 2-N), 수와 카드를 한 참조 체계에 담으면 §2 의 경계가 무너진다.

### 곱셈까지만

`ResultRef.multiplier` 는 실제 카드가 `dr*2000` 을 쓰기 때문에 있다
(부작용? 30922149, 그리고 결과를 계산에 쓰는 10건). 그 이상은 없다 —
**수식 언어가 아니다.**

### 없는 결과는 0 이 아니다

가리킨 조작의 결과가 없거나(`ExecutionLookupError`) 그 조작에 장수가
없으면(`LifeChangeOperation`) **`UNKNOWN` 으로 멈춘다.** 0 으로 때우면
뒤의 일이 "0장을 다뤘다" 고 읽고 조용히 지나간다.

---

## 8. `OperationResult` ≠ `ObservedEvent` (§11 · §22)

| | 무엇인가 | 누구를 위한 것인가 |
|---|---|---|
| `OperationResult` | 그 일이 얼마나 했는가 | **지금 해결** 중의 참조 |
| `StateDelta` | 판의 어디가 어떻게 바뀌었는가 | 사건 만들기 |
| `ObservedEvent` | 무슨 사건이 일어났는가 | 기록 · 반응 |

앞의 일을 뒤의 일이 읽을 때 **`EventJournal` 을 뒤지지 않는다.** 저널은
**역사**이고 실행 문맥은 **지금 해결의 중간 결과**다. 역사를 뒤져 수를
짐작하면 같은 효과가 두 번 돌았을 때 어느 것을 읽었는지 알 수 없다.

`engine/execution.py` 안에 `EventJournal` · `ObservedEvent` ·
`EventReader` 라는 이름이 **하나도 없다는 것**을 AST 로 확인한다. 저널
통로(`Operation → StateDelta → EventReader → ObservedEvent →
EventJournal`)는 한 줄도 바뀌지 않았다.

---

## 9. 값이 사는 기간 (§12)

**해결 한 번** 이다. `execute()` 가 `ExecutionValues` 를 만들고, 조작을
하나 계획할 때마다 결과가 하나 붙은 **새 값**이 생기고, `execute()` 가
끝나면 사라진다.

더 긴 수명을 만들지 않았다. 체인 링크를 넘어 앞 효과의 결과를 읽는 실제
카드는 `e:SetLabelObject` 로 **효과 객체 사이에** 값을 넘기는데, 그것은
지속 효과 계층의 문제이고 여기 없다 (STRUCTURAL-76 과 같은 자리).
필요하지 않은 장기 저장 구조를 미리 만들지 않는다.

값이 불변이라 복제 독립은 따로 지킬 것이 없다 — 판에 붙어 있지 않기
때문이다 (§16).

---

## 10. 계획과 적용 (§17)

결과는 **계획 단계에서 확정**된다. 적용은 계획한 그대로만 하므로, 뒤의
일이 읽는 수와 실제로 일어날 일이 어긋나지 않는다.

| 어디서 막혔나 | 판 | 난수 |
|---|---|---|
| 선언하지 않았다 (`PENDING`) | 그대로 | 꺼내지 않았다 |
| 허용되지 않은 수 (`INVALID`) | 그대로 | 꺼내지 않았다 |
| 묻지 않은 수가 들어왔다 | 그대로 | 꺼내지 않았다 |
| 가리킨 결과가 없다 | 그대로 | 꺼내지 않았다 |
| 그 조작에 장수가 없다 | 그대로 | 꺼내지 않았다 |
| 출처가 금지한다 (`TEXT_DERIVED`) | 그대로 | 꺼내지 않았다 |
| 앞의 일이 막혔다 | 그대로 | 꺼내지 않았다 |
| 고른 **뒤** 다른 일이 막혔다 | 그대로 | **꺼냈다** — 감추지 않는다 |

마지막 줄은 Phase 2-AB 와 같은 사실이고, 같은 seed 면 같은 자리에서 같은
답이 나오므로 재현은 깨지지 않는다.

---

## 11. 선언은 난수가 아니다 (§14 · §25 J · K)

사람이 수를 정하는 데 **게임 난수를 쓰지 않는다.** `engine/execution.py`
안에 `RandomSource` · `randomness` · `choose` 라는 이름이 하나도 없고,
`engine.randomness` 를 import 하지도 않는다 (AST 로 확인).

선언이 정하는 것은 **몇 장인지**이고, **어느 카드인지**는 여전히 난수원이
정한다. 같은 seed · 같은 선언이면 같은 카드가 나오고, seed 가 다르면
다른 카드가 나온다 (Phase 2-AB 의 결정론 그대로).

---

## 12. 숨은 정보 (§13 · §25 N)

수를 선언하는 것과 패를 공개하는 것은 다른 일이다. 상대 패에서 무작위로
2장을 버려도 **남은 패는 여전히 가려져 있고**, 결과 어디에도 남은 카드의
정체가 실리지 않는다. Phase 2-AA 의 `ObservationPolicy` 는 한 줄도
건드리지 않았다.

---

## 13. `state_hash` (§23 · §25 P)

**한 줄도 바꾸지 않았다.** 선언한 수도 앞선 결과도 판의 모양이 아니므로
`canonical_state` 에 들어가지 않는다 — `EventJournal` · `PriorityState` ·
`Chain` · 난수원의 위치를 뺀 것과 같은 이유다. 값을 만들기만 하면 해시가
움직이지 않고, 그 선언이 실제로 카드를 움직였을 때 움직인다.

---

## 14. 실제 corpus (§18 · §28-19)

### A. 플레이어가 수를 선언하는 카드

`Duel.AnnounceNumber` — **54장 / 호출 60건.**

| 지금 닿는가 | 장 |
|---|---:|
| 몬스터 효과 (유발/지속 계층 필요) | 33 |
| 주문/함정 단순 발동 | 16 |
| 주문/함정 + 조건부 발동 시점 | 4 |
| 그 밖 | 1 |

### B. "최대 N장" — **선언이지 부족 처리가 아니다**

Phase 2-AC 에서 확인한 것이 여기서 이어진다. 실제 카드의
"up to 2 random cards"(10691144 · 45222299)는 `SelectOption` /
`AnnounceNumber` 로 **수를 선언한 뒤** 그만큼 고르는 것이다. 이제 그
선언을 적을 수 있으므로, **STRUCTURAL-81 이 막고 있던 모양이 열렸다.**

### C. 앞선 조작의 결과를 참조하는 카드

두 가지가 **다른 모양**으로 존재한다.

| 모양 | 장 | 이 엔진의 답 |
|---|---:|---|
| `Duel.GetOperatedGroup()` — **암묵적** "방금 그 일" | 311 | 옮기지 않는다 (§9 가 금지한 모양) |
| 반환값을 변수로 받아 쓴다 — **명시적** | 66 | `ResultRef` 로 적을 수 있다 |

명시적인 66장이 그 수를 **어떻게** 쓰는가 (호출 자리 기준):

| 쓰임 | 건 | 이 엔진 |
|---|---:|---|
| 뒤 조작의 인자로 쓴다 (`Duel.Draw(p,ct)`) | 33 | **된다** |
| 계산에 쓴다 (`SetLabel(ct)` · `ct*2000`) | 10 | 곱셈까지 된다 |
| 성공 여부만 본다 (`if ct==0`) | 92 | **안 된다** — 부분 실패가 없다 |
| 그 밖 | 4 | — |

`GetOperatedGroup` 311장을 옮기지 않은 것은 게으름이 아니라 **판단**이다.
그 API 가 하는 일이 정확히 "바로 앞 조작의 결과를 이름 없이 집어 오는
것" 이고, §9 가 금지한 것이 그것이다. 같은 효과를 옮기려면 그 조작에
번호를 붙여 명시적으로 가리키면 된다 — 표현력이 줄지 않는다.

---

## 15. 실제 카드 (§21 · §28-20)

**0장 등재했다.** 이번에도 그것이 사실이다.

가장 가까운 카드는 **부작용? (30922149)** 이다. 한 장에 이번 단계의 두
문제가 나란히 있다.

```lua
if ct==2 then ac=Duel.AnnounceNumber(p,1,2)      -- 상대가 수를 선언한다
else ac=Duel.AnnounceNumber(p,1,2,3) end
local dr=Duel.Draw(p,ac,REASON_EFFECT)            -- 그 수만큼 뽑는다
... Duel.Recover(tp,dr*2000,REASON_EFFECT)        -- 뽑은 수 x2000 회복
```

세 줄 중 **앞의 두 줄은 이제 적을 수 있다.** 마지막 줄이 막힌다 —
`LifeChangeOperation.delta` 가 아직 고정 수만 받기 때문이다. 억지로
등재하지 않았다 (§21). 모양만 테스트에 적어 두었고, **적을 수 있다는 것과
실행할 수 있다는 것을 섞지 않는다.**

라이프 증감의 양을 열지 않은 이유는 범위다. 드로우 매수를 연 것은 실제
카드 33곳이 `Duel.Draw(p, ct)` 를 쓰기 때문이고, 라이프까지 열면 데미지와
회복의 구분(효과 데미지 ≠ 라이프 감소)이 함께 따라온다. 그것은 이 단계가
할 일이 아니다 (STRUCTURAL-86).

---

## 16. 테스트 (§25)

`tests/engine/test_execution_context.py` — **39 함수 / 46 케이스**, 전부
통과.

| 절 | 무엇을 붙잡는가 |
|---|---|
| A | 1·2·3 을 선언하면 그만큼 일어난다 · 같은 입력이면 같은 결과 |
| B | 0·4·-1·99 는 거부 (고쳐 주지 않는다) · 묻지 않은 수도 거부 |
| C | 선언하지 않으면 시작하지 않는다 · `PENDING` 은 거짓이 아니다 |
| D | 목록이 본래 모양 · 빈/중복/역순 도메인 거부 · EXACT·RANGE·비연속 ENUM 이 끝까지 돈다 |
| §7 | 컨트롤러가 아닌 사람이 선언할 수 있다 · `ValueRef ≠ TargetRef` · 묻고 안 쓰면 정의가 거부 |
| E | 이름으로 읽는다 · 실행 밖에서 물으면 그렇다고 답한다 · 판에 남지 않는다 |
| F | 0번이 2장 보내면 1번이 2장 뽑는다 · 1·3장도 따라간다 · 곱셈 |
| G | **가리키지 않으면 안 쓴다** · 뒤/자기 자신을 가리키면 거부 · `results[-1]` 이 없다 |
| H | 없는 결과는 0 이 아니다 · 장수가 없는 조작은 `UNKNOWN` |
| I | 앞이 막히면 뒤는 시작 안 한다 · `SUCCEEDED` 가 없는 이유 |
| J · K | 선언은 난수를 쓰지 않는다 (동작 + AST) · 무작위의 결정론은 그대로 |
| L · M | 복제본의 선언이 원본에 새지 않는다 · 뒤가 막혀도 판은 그대로 · `FORBIDDEN` 이 먼저 |
| N · O · P | 선언이 카드를 공개하지 않는다 · 저널엔 이동만 · 해시는 실제 변화에만 |
| Q | 부작용?(30922149)의 **모양만** 적히고 카드는 등재되지 않았다 |

### 기존 테스트 수정 (§22 · §28-22)

**삭제 0건.** 수정 2건.

1. `test_effect_model.py::test_draw_and_life_operations` — `draw.count == 2`
   라고 단언했다. 그때는 매수가 **숫자**였기 때문이다. 이제 매수는 값이고
   "고정" 이 타입에 적혀 있으므로 `SelectionCount.fixed(2)` 와
   `kind is CountKind.FIXED` 로 바꿨다. **약해지지 않았다** — 2라는 값과
   그것이 고정 수라는 사실을 따로 확인하므로 한 줄 늘었다.
2. `test_selection_count.py::test_the_count_resolver_never_counts_candidates` —
   메서드 이름이 `_resolve_count` → `_resolve_number` 로 바뀌었다. 답하는
   것이 "고를 장수" 만이 아니게 됐기 때문이다 (드로우 매수도 같은 자리에서
   답한다). 검사 내용은 그대로다 — **하는 일이 넓어졌지 후보를 보게 된
   것은 아니다.**

`test_effect_mutation_safety.py` 의 기존 테스트 하나가 **실제 구멍을
잡았다.** 생성 방어를 우회해 날것의 정수를 넣는 시험인데, 매수를 값
타입으로 바꾸면서 그 방어가 사라졌다. 테스트가 옳고 코드가 틀렸으므로
`_resolve_number` 에 같은 방어를 되살렸다 — 테스트는 고치지 않았다.

---

## 17. 회귀

```
2678 passed, 4 skipped in 36.70s     (기준선 2632 + 46)
```

---

## 18. TODO (§28-23)

- **STRUCTURAL-81 — 해결.** 플레이어가 수를 선언하는 계층이 생겼고,
  컨트롤러가 아닌 사람도 선언할 수 있다.
- **STRUCTURAL-82 — 해결.** 앞선 조작의 결과를 **번호로** 가리킬 수 있고,
  암묵적 참조는 구조적으로 막혀 있다.
- **STRUCTURAL-84 (신규 · 🟠)** — **부분 실패가 없다.** 앞 조작이 0장을
  다뤘을 때 뒤에서 분기하는 실제 카드가 92곳이다. 이 엔진은 앞이 막히면
  전체를 거절하므로 그 분기를 표현할 자리가 없다. 어느 쪽이 옳은지는
  규칙 문제이고, 공식 근거 없이 정하지 않는다.
- **STRUCTURAL-85 (신규 · 🟠)** — **도메인이 판에서 계산되지 않는다.**
  `AnnounceNumber` 호출 60건 중 46건이 고를 수 있는 수의 목록 자체를
  판에서 만든다 (`table.unpack(ct)`).
- **STRUCTURAL-86 (신규 · 🟡)** — **라이프 증감의 양이 고정 수뿐이다.**
  부작용?의 `dr*2000` 이 여기 걸린다. 열려면 효과 데미지와 라이프 감소의
  구분이 함께 와야 한다.
- **STRUCTURAL-87 (신규 · 🟡)** — `Duel.GetOperatedGroup` 311장은
  **옮기지 않기로 했다.** 표현력의 문제가 아니라 그 API 의 모양이 암묵적
  참조라서다. 옮길 때는 번호를 붙여 명시적으로 옮긴다.
- **STRUCTURAL-83 (몬스터 종류/융합 조건) — 그대로 둔다** (§24 의 지시).
- 71 · 74 · 75 · 76 · 77 · 78 — **하나도 건드리지 않았다.**

---

## 19. 판정 (§27)

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 2 신규 | 84 (부분 실패) · 85 (계산되는 도메인) |
| 🟡 DETAIL | 2 신규 | 86 (라이프 양) · 87 (암묵 참조 API) |
| 🟢 COSMETIC | 0 | |

§27 이 "절대 허용하지 않는다" 고 한 일곱 가지 — 암묵적 마지막 결과,
`INVALID` 보정, `PENDING` 임의 결정, `UNKNOWN` 변환, 선언에서 난수 소비,
숨은 정보 누출, 판에 실행 문맥 저장 — 은 **하나도 하지 않았고**, 각각을
테스트가 막는다.

---

## 20. 이번에 하지 않은 것 (§24)

AI · 덱 빌더 · 지속 효과 전체 · SEGOC · 조건 계층 재작성 · 아키타입 ·
융합 조건 · 새 EventBus · 새 ReplayEngine · 새 RandomEngine · 선언 카드
54장 자동 구현 · 결과 참조 카드 자동 구현 · STRUCTURAL-83.

**다음 Phase 는 시작하지 않았다.**
