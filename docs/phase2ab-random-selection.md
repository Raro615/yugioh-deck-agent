# Phase 2-AB — Random Selection Operation Core

기준 커밋: `35b7d36` (Phase 2-AA 동적 관측 권한) · 2541 passed / 4 skipped

> **이름에 대하여.** 요청서의 제목은 "Phase 2-AA" 였지만 그 이름은 직전
> 단계(동적 관측 권한, `35b7d36`)가 이미 쓰고 있다. 같은 이름을 두 개
> 만들면 나중에 어느 쪽인지 알 수 없으므로 이 단계는 **2-AB** 로 적는다.
> 내용은 요청서 §1~§22 그대로다.

```
EffectDefinition
  → TargetSpec.at_random(RandomSelectionSpec)   선언
  → CandidateResolver                           후보를 **센다** (판을 읽는다)
  → RandomSource.choose_many                    자리 번호를 **고른다** (카드를 안 본다)
  → RandomOutcome → Selection                   골라진 카드
  → 기존 CardOperation                          실제 상태 변경
  → StateDelta → Event → EventJournal           기존 통로 그대로
```

한 줄 목표: **Phase 2-Z 의 재현 가능한 난수를 실제 효과의 무작위 선택에
잇는다.** (STRUCTURAL-73)

---

## 1. 변경 파일 (§22-1)

| 파일 | 변경 |
|---|---|
| `engine/randomness.py` | `RandomSource.choose_many` **추가** (+45줄) |
| `engine/effect/target.py` | `TargetRequirement.RANDOM` · `RandomSelectionSpec` · `TargetSpec.at_random` / `is_random` / `is_pending` |
| `engine/effect/executor.py` | `_resolve_selection` · `_roll_selection` · `_authoritative_candidates` |
| `engine/activation.py` | 무작위 바인딩은 발동 시점에 **묶지 않는다** (+18줄) |
| `engine/effect/library.py` | 무정의 말살(73148972) 등재 · `RANDOM_TARGET` |
| `tests/engine/test_random_selection.py` | **신규** — 37 함수 / 44 케이스 |
| `tests/engine/test_operation_integration.py` · `test_effect_library.py` · `test_randomness.py` · `test_real_card_execution.py` | 기존 단언 갱신 (§9) |
| `docs/phase2ab-random-selection.md` · `engine/__init__.py` | 문서 |

**새 RandomSelector · SelectionEngine · RandomOperation · ChoiceEngine
0개.** 새 모듈도 0개다 — `randomness.py` 는 Phase 2-Z 것이고, 나머지는
전부 기존 파일에 줄이 붙었다.

---

## 2. 기존 구조 조사 결과 (§2 · §14)

먼저 무엇이 이미 있었는지 세었다.

| 있던 것 | 쓸 수 있었나 |
|---|---|
| `RandomSource.choose` (Phase 2-Z) | **그렇다** — 1개만 고른다 |
| `RandomOutcome` (purpose · draw · candidates · selected) | 그대로 |
| `CandidateResolver` (Phase 2-N) | 그대로 |
| `CandidateSource` (Phase 2-N) | 그대로 |
| `ChoiceSpec` | **아니다** — `chooser` 를 전제한다 |
| `TargetRequirement` (NONE · TARGETING · CHOOSING) | **모자란다** — 셋 다 "누가 고른다" |
| `CardOperation.send_to_grave` 등 | 그대로 |

없던 것은 둘이다.

1. **"아무도 고르지 않는다" 를 적을 자리** — `ChoiceSpec.chooser` 는
   기본값이 있어서 "없다" 를 표현할 수 없다.
2. **여러 장을 겹치지 않게 고르는 난수 API** — `choose` 는 1장이다.

그래서 더한 것도 정확히 둘이다.

---

## 3. Random Selection ≠ Player Choice (§3 · §14)

이 단계의 전부가 이 구분이다.

|  | `ChoiceSpec` | `RandomSelectionSpec` |
|---|---|---|
| 누가 고르는가 | `chooser` | **칸이 없다** |
| 몇 장 | `minimum` ~ `maximum` | `count` 하나 |
| 후보를 **봐야** 하는가 | 그렇다 | **아니다** |
| 상대 패에서 고를 수 있는가 | 규칙상 별도 공개가 필요하다 | **그냥 된다** |

```
"상대 패에서 1장을 고른다"      → CHOOSING (고르는 사람이 본다)
"상대 패에서 무작위로 1장"      → RANDOM   (아무도 보지 않는다)
```

`chooser` 칸을 **일부러 두지 않았다.** 두는 순간 "무작위인데 누가 고른다"
가 되고, 구분이 이름만 남는다. `TargetSpec.__post_init__` 이 둘이
어긋나는 조합(RANDOM + `ChoiceSpec`, CHOOSING + `RandomSelectionSpec`)을
생성 시점에 거부한다.

---

## 4. 난수원은 판을 뒤지지 않는다 (§3)

`RandomSource` 는 `InstanceId` 의 **열**을 받고 그중 몇 번째를 고를지만
답한다. `GameState` 를 import 하지도, `locate`/`player`/`zone` 을 부르지도
않는다 — `test_a_counting_candidates_is_not_choosing_them` 이 AST 로 그것을
확인한다 (문자열 검색이 아니다: 문서에 이름이 적히는 것과 코드가 그것을
만지는 것은 다르다).

```
CandidateResolver   판을 읽는다   → (id, id, id, id)
RandomSource        번호만 고른다 → 2
Selection           그 번호의 id
```

`choose_many(candidates, count, replacement=False)` 는 `replacement` 가
거짓이면 남은 것에서 꺼내며 고른다 — 한 장의 카드를 두 번 버릴 수는 없기
때문이다. 후보보다 많이 고르라고 하면 `RandomError` 를 올리고 **난수를
꺼내지 않는다.**

---

## 5. 후보를 누구의 눈으로 세는가 (§5 · §6)

여기가 이 단계에서 가장 오래 걸린 지점이다.

기존 후보 계산은 전부 **고르는 사람의 관측**으로 만들어졌다
(`GameStateView.from_state(state, viewer=context.controller)`). 무작위
선택에는 고르는 사람이 없다. 컨트롤러의 눈으로 상대 패를 세면 **0장**이
나오고, 그러면 "상대 패에서 무작위로 1장" 은 영원히 실행할 수 없다.

그래서 `_authoritative_candidates` 는 **자리 주인의 눈으로** 센다.

```
owner 가 CONTROLLER  → viewer=controller 하나로 센다
owner 가 OPPONENT    → viewer=opponent  하나로 센다
owner 가 None (양쪽) → 0 과 1 을 각각 세서 합친다
```

이것이 정당한 이유는 **세는 주체가 플레이어가 아니라 엔진**이기 때문이다
(요청서 §6 "Random Selection ≠ Information Reveal"). 엔진이 아는 것과
플레이어가 보는 것을 나눈 것은 Phase 2-Y 의 결론이고, 여기서 그 구분이
값을 한다.

**그 관측은 밖으로 나가지 않는다.** 후보 수를 세는 데만 쓰이고, 반환되지도
`self` 에 붙지도 않는다 — `test_j_the_observation_boundary_is_the_actors`
가 AST 로 그것까지 확인한다. 예외를 열었으면 그 예외의 크기도 고정해야
구멍이 되지 않는다.

---

## 6. 무작위 선택 자체는 Operation 이 아니다 (§8)

**`RANDOM_SELECT` OperationKind 를 만들지 않았다.** 판단 근거는 이렇다.

| 질문 | 답 |
|---|---|
| 고르는 것이 **상태를 바꾸는가** | 아니다. 카드가 움직이지 않는다 |
| `StateDelta` 로 적을 것이 있는가 | 없다. 바뀐 칸이 없다 |
| 기존 `Operation` 중 같은 모양이 있는가 | 없다 — 전부 상태 변경이다 |
| 그럼 어디에 속하는가 | **대상 결정** — `TargetRequirement` |

`OperationKind` 는 지금까지 예외 없이 "판이 어떻게 바뀌는가" 였다
(ADR-002 가 그 위에 서 있다). 거기에 상태를 바꾸지 않는 항목을 하나
넣으면 그 어휘의 뜻이 흐려지고, `_apply_*` 가 할 일이 없는 조작이
생긴다. 무작위는 **누가 대상이 되는가**의 문제이므로
`TargetRequirement.RANDOM` 에 탄다.

결과적으로 **무작위 선택이 카드를 옮기지 않는다** (§7). 고른 뒤 실제로
묘지로 보내는 것은 기존 `CardOperation.send_to_grave` 이고, 관문·이벤트·
저널은 전부 하던 대로 지나간다.

---

## 7. 실패 안전성 — 난수를 언제 꺼내는가 (§12)

요청서 §12 는 "먼저 뽑고 나서 Operation 이 실패하면?" 을 묻는다. 기존
구조를 먼저 조사했고, 답은 **이미 있었다**.

실행기는 Phase 2-V 부터 **계획을 전부 끝낸 뒤에야 적용을 시작한다.**
난수는 계획 단계에서 꺼낸다(Phase 2-Z 의 셔플과 같은 자리). 그래서

- 뒤의 조작이 계획에서 막히면 **적용은 한 줄도 시작되지 않는다** —
  `applied == ()` · `deltas == ()` · `state_hash` 그대로 · 저널 0.
- 그러나 **난수는 이미 꺼냈다.** `draws` 가 1 늘어 있다.

이것을 감추지 않는다. 같은 seed 로 다시 돌리면 같은 자리에서 같은 답이
나오므로 **재현은 깨지지 않는다** — `draws` 가 재현 좌표라는 Phase 2-Z 의
정의가 그대로 성립한다. `test_j_a_later_failure_leaves_the_board_alone`
이 그 두 사실(판은 그대로 · 난수는 꺼냈다)을 **함께** 단언한다.

후보를 다 세지 못했을 때는 **아예 꺼내지 않는다** (§13). 몇 개 중에서
고르는지 모르는 채로 돌리면 확률이 틀리기 때문이다 —
`UNCHECKED_TARGET` / `INFORMATION_UNAVAILABLE` 로 멈춘다. `UNKNOWN` 후보가
섞여 있어도 마찬가지다: `undecided` 를 후보에 넣지도 버리지도 않는다.

seed 없는 판에서는 `UNSUPPORTED_OPERATION` / `RULE_NOT_IMPLEMENTED` 이고,
`missing` 에 `"seeded randomness (GameState.create(seed=...))"` 가 적힌다.
**몰래 전역 난수로 돌리지 않는다.**

---

## 8. 발동 시점에는 고르지 않는다 (§7 · §14)

`EffectActivator` 는 대상 이름마다 선택을 묶는다. 무작위 바인딩은
**건너뛴다** — 발동 시점에 정하면 체인이 쌓이는 동안 판이 바뀌어도 이미
정해진 카드가 남고, 그것은 "해결 시점에 무작위로 고른다" 가 아니다.

밖에서 무작위 대상의 선택을 넣어 주면 **거부한다**
(`TARGET_COUNT_MISMATCH`, "무작위로 정해집니다. 고른 결과를 밖에서 넣을
수 없습니다"). 넣을 수 있으면 무작위가 아니다.

`TargetSpec.is_pending` 도 무작위에서는 거짓이다 — 기다릴 사람이 없으므로
"아직 안 골랐다" 라는 상태가 아예 없다.

---

## 9. 숨은 정보 (§6 · §16)

무작위로 골랐다고 해서 **공개되지 않는다.**

- 상대 패에서 1장을 무작위로 묘지에 보내면, 묘지로 간 그 카드만 보인다.
  **남은 패는 여전히 가려져 있다** (`concealed=True`).
- `RandomOutcome.public_summary()` 는 후보의 **수**만 말하고 `InstanceId`
  를 말하지 않는다. 내부 기록(`to_dict()`)과 공개 요약이 다른 값이다.
- `ObservedEvent` / `EventJournal` 어디에도 고르지 않은 카드의 정체가
  적히지 않는다.
- Phase 2-AA 의 관측 권한과 **독립이다.** 권한이 있어도 무작위 선택의
  결과가 달라지지 않고, 권한이 없어도 무작위 선택은 된다.

---

## 10. 실제 카드 — 무정의 말살 (73148972) (§15)

`c73148972.lua` 는 이 저장소의 공식 스크립트다.

```lua
local g=Duel.SelectTarget(tp,nil,tp,LOCATION_MZONE,0,1,1,nil)   -- 플레이어가 고른다
...
local g=Duel.GetFieldGroup(tp,0,LOCATION_HAND):RandomSelect(tp,1) -- 아무도 안 고른다
Duel.SendtoGrave(g,REASON_EFFECT)
```

**한 카드 안에 두 선택이 나란히 있다.** 이 구분을 검증하기에 이보다 나은
카드가 없어서 골랐다.

| Lua | 옮긴 것 |
|---|---|
| `SelectTarget(tp,nil,tp,LOCATION_MZONE,0,1,1,nil)` | `TargetSpec.targeting(ChoiceSpec(...CONTROLLER MZONE 1장))` |
| `GetFieldGroup(tp,0,LOCATION_HAND):RandomSelect(tp,1)` | `TargetSpec.at_random(RandomSelectionSpec(...OPPONENT HAND, count=1))` |
| `IsExistingTarget(...MZONE...)` + `GetFieldGroupCount(tp,0,LOCATION_HAND)>0` | `And((ZoneCountAtLeast(CONTROLLER, MZONE, 1), ZoneCountAtLeast(OPPONENT, HAND, 1)))` |
| `Duel.SendtoGrave(tc, ...)` · `Duel.SendtoGrave(g, ...)` | `CardOperation.send_to_grave` 2개 |

옮기지 **못한** 것도 적는다: `tc:IsRelateToEffect(e)` 와 해결 시점의
`tc:IsControler(tp)` 재확인은 싸이크론과 같은 이유로 남았다
(STRUCTURAL-50). 관문은 원본에 `IsAbleToGrave` 가 없으므로 **선언하지
않았다** (육신보살과 같은 자리, Phase 2-X).

### 실행 기록 (§22-10)

```
seed=7  status=resolved applied=2 draws=1 journal=1
        상대패 [55144522, 66719324, 5318639, 83764718] → [55144522, 66719324, 83764718]
seed=7  (다시)                                          → 같은 카드 (5318639)
seed=99 상대패 [55144522, 66719324, 5318639, 83764718] → [55144522, 66719324, 5318639]
        (83764718 이 갔다 — **seed 가 다르면 결과가 다르다**)
```

목록은 이제 **실제 카드 14장 / 실행 가능 10개**다 (13 / 9 에서).

---

## 11. 실제 카드 범위 조사 (§15)

`RandomSelect` 를 쓰는 실제 카드는 **142장** (호출 143회)이다.

| 호출 자리에 존이 그대로 적힌 것 | 수 |
|---|---:|
| `LOCATION_HAND` | 23 |
| `LOCATION_EXTRA` | 1 |
| 그 외 (그룹을 앞에서 따로 만든다) | 119 |

119개는 그룹을 여러 줄에 걸쳐 조립하므로 한 줄만 보고 옮길 수 없다.
**추측해서 옮기지 않았다** — 이번에 옮긴 것은 한 줄로 읽히는 무정의
말살 하나다. 나머지는 각자의 조건·필터가 확인될 때 옮긴다.

---

## 12. 테스트 (§19)

`tests/engine/test_random_selection.py` — **37 함수 / 44 케이스**, 전부
통과.

| 절 | 무엇을 붙잡는가 |
|---|---|
| A | 여섯 자리(자기/상대 × 패·필드·묘지) 전부에서 후보를 센다 · 난수원이 판을 안 본다 |
| B · C | 정확히 N 장 · 같은 seed 는 같은 결과 · 다른 seed 는 다른 결과 |
| D | `clone()` 뒤 양쪽이 서로 영향을 주지 않는다 |
| E · F | 후보 0 · 후보 부족 — 난수를 **꺼내지 않는다** |
| G · H | `UNKNOWN` 후보 · 못 본 자리 — 멈춘다 |
| I · N | 고른 뒤 실제 조작이 돈다 · `StateDelta` · 저널 1건 |
| J | 뒤의 일이 막히면 판은 그대로 · **난수는 꺼냈다** |
| K · L · M | 남은 패가 안 보인다 · 요약에 정체가 없다 · 저널에 없다 |
| O | `state_hash` 의 뜻이 그대로다 (난수 위치는 안 섞인다) |
| P | 플레이어 선택과 섞이지 않는다 (명세 교차 검증 · 발동 시 주입 거부) |
| Q | 무정의 말살 end-to-end (`@pytest.mark.real_card`) |

### 기존 테스트 수정 (§21 · 테스트 정책)

**삭제 0건.** 수정 4건이고, 각각 기존 단언이 무엇을 잘못 가정했는지 적는다.

1. `test_effect_library.py::test_the_library_makes_no_decisions_...` —
   원문에 `"random"` 이 있는지 **문자열로** 보고 있었다. 그 검사는
   `TargetRef("random")` 까지 잡는데, 그것은 목록이 무작위를 *쓰는* 것이
   아니라 **카드의 스크립트가 무작위로 고른다고 적어 둔 것**이다. 막아야
   하는 것은 목록이 전역 난수를 부르는 일이므로 AST 로 `import random` ·
   `random.*` 호출을 본다. **더 좁은 것을 더 정확히** 막는다.
2. `test_randomness.py::test_j_coin_and_dice_were_deliberately_left_out` —
   공개 API 목록에 `choose_many` 를 더했다. 이 테스트의 뜻("동전·주사위는
   일부러 안 만들었다")은 그대로다 — 늘어난 것은 고르는 **장수**뿐이다.
3. `test_real_card_execution.py` — 목록 13→14, 실행 가능 9→10. 이
   테스트의 일이 원래 "늘어나면 깨지는 것" 이다.
4. `test_operation_integration.py::test_j_the_observation_boundary_is_the_actors` —
   "모든 `viewer=` 는 `*.controller` 다" 라고 단언했다. 이번에 §5 의
   예외가 생겼으므로 **예외를 허용하되 그 크기를 고정**했다:
   `_authoritative_candidates` 안에서만, 이름은 `owner` 로만, 그리고 그
   관측이 반환되지도 `self` 에 저장되지도 않는다는 것까지 단언한다.
   **느슨해진 것이 아니라 두 줄이 더 늘었다.**

---

## 13. 회귀 (§21)

```
2585 passed, 4 skipped in 38.06s
```

기준선 2541 + 44 = 2585. **기존 테스트는 한 건도 잃지 않았다.**

---

## 14. TODO (§20)

- **STRUCTURAL-73 — 해결.** "무작위로 1장 고른다" 를 효과가 선언할 수
  있고, 실제 카드 하나가 그것으로 돈다.
- **STRUCTURAL-76 · 77 · 78 — 그대로 둔다** (§20 의 지시).
- **STRUCTURAL-79 (신규 · 🟡)** — `RandomSelectionSpec.count` 는 고정
  수다. "패의 절반" · "X 장까지" 처럼 **수가 판에서 계산되는** 무작위
  선택은 아직 적을 수 없다. 그런 실제 카드가 몇 장인지 세지 않았으므로
  **급하다고 말하지 않는다.**
- **STRUCTURAL-80 (신규 · 🟡)** — 후보 조건(`CandidateSource.require`)이
  `UNKNOWN` 이면 무작위 선택 전체가 멈춘다. 옳은 기본값이지만, 실제
  카드에서 이것이 얼마나 자주 막히는지는 옮긴 카드가 한 장뿐이라
  모른다.
- 그 밖의 기존 TODO 는 **하나도 건드리지 않았다.**

---

## 15. 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 0 신규 (73 해결) | |
| 🟡 DETAIL | 2 신규 | 79 (계산되는 장수) · 80 (조건 UNKNOWN 의 실제 빈도 미측정) |
| 🟢 COSMETIC | 0 | |

---

## 16. 이번에 하지 않은 것 (§20)

- 동전·주사위 (Phase 2-Z 에서 이미 유보)
- 무작위 **효과 선택** (여러 효과 중 무작위로 하나)
- 무작위 **덱 파괴**·무작위 발동
- AI 정책 · 확률 평가 — AI 난수는 여전히 다른 계층이다
- 지속 효과 계층 · 아키타입 조건 (76 · 77)
- 셔플 자동 호출 (STRUCTURAL-71)

**다음 Phase 는 시작하지 않았다.**
