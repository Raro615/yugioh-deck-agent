# Phase 2-AC — Random Selection Completeness / Dynamic Count & Candidate Resolution

기준 커밋: `877833d` (Phase 2-AB) · 2585 passed / 4 skipped

```
Effect
  → SelectionCount        몇 개를 고르는가      판을 읽는다 (수)
  → CandidateResolver     무엇을 고를 수 있는가   판을 읽는다 (후보)
  → RandomSource          자리 번호를 고른다     둘 다 모른다
  → RandomOutcome → Selection
  → 기존 CardOperation → StateDelta → Event → EventJournal
```

한 줄 목표: **후보군과 선택 수를 분리하고, 동적 수량과 불확실한 후보를
안전하게 처리하면서 결정론과 정보 경계를 유지한다.**

---

## 1. 변경 파일 (§25-3)

| 파일 | 변경 |
|---|---|
| `engine/effect/target.py` | `SelectionCount` · `CountKind` · `CountOutcome` · `ResolvedCount` · `ZoneCountTerm` · `Shortfall` 추가 / `RandomSelectionSpec.count` 타입 변경 · `minimum`/`maximum` **삭제** |
| `engine/effect/executor.py` | `_resolve_count` 추가 · `_roll_selection` 이 수/후보/부족을 따로 처리 · 후보 계산에서 장수 제거 · `undecided` 와 `unchecked` 분리 |
| `engine/effect/library.py` | 의적의 입문서(69091732) 등재 |
| `tests/engine/test_selection_count.py` | **신규** — 43 함수 / 47 케이스 |
| `tests/engine/test_real_card_execution.py` · `test_random_selection.py` | 단언 갱신 3건 (§20) |
| `docs/phase2ac-selection-count.md` · `engine/__init__.py` | 문서 |

**새 모듈 0개.** `CountResolver` 클래스도, `RandomEngine` 도, `EventBus`
도 만들지 않았다. 수를 답하는 일은 값 타입(`SelectionCount.resolve`)과
실행기의 메서드 하나(`_resolve_count`)로 끝난다.

---

## 2. 먼저 센 것 — 실제 corpus (§1 · §13 · §25-17)

`RandomSelect` 는 **142장의 파일**에 나온다. 그러나 정확히는

| 사실 | 수 |
|---|---:|
| 문자열이 나오는 파일 | 142 |
| **실제 호출** | **142건 / 141장** |
| 호출이 아니라 함수 값으로 넘기는 것 (`c6075533`) | 1 |
| 한 파일에서 두 번 부르는 카드 (`c74191528`) | 1 |

> Phase 2-AB 보고서의 "142장 / 호출 143회" 는 문자열을 센 값이었다.
> 괄호까지 보면 **141장 / 142건**이다. 결론은 달라지지 않지만 숫자는
> 정확한 쪽으로 고친다.

### 2-1. 고를 장수 (§2-1 · §2-2)

| 수 | 호출 | 비율 |
|---|---:|---:|
| 고정 1장 | 122 | 86% |
| 고정 2장 | 6 | 4% |
| 고정 3장 | 2 | 1% |
| **고정이 아님** | **12** | **8%** |

동적 수량은 **실재한다.** 8% 는 추측이 아니라 센 값이다.

### 2-2. 그 12건의 수는 어디서 오는가 (§2-3)

| 수가 오는 곳 | 건 | 카드 | 지금 |
|---|---:|---|---|
| **자리 장수 산술** | 4 | 42141493 · 84192580 · 87126721 · 41482598 | **DERIVED** |
| 플레이어가 선언한 수 | 4 | 10691144 · 22593417 · 45222299 · 49238328 | UNKNOWN |
| 앞선 조작의 결과 수 | 3 | 41181774 · 48814566 · 26949946 | UNKNOWN |
| 체인 파라미터 | 1 | 48576971 | UNKNOWN |

공식 카드 텍스트가 같은 말을 한다.

```
42141493  "...so the number of cards in your hand is
           the number of cards your opponent controls +6"   ← 자리 장수 산술
41482598  "Randomly discard the same number of cards you drew" ← 앞선 조작 결과
41181774  "...discard the same number of random cards"         ← 앞선 조작 결과
10691144  "Banish up to 2 random cards from your opponent's hand"
          → Lua: ct = Duel.SelectOption(...)+1               ← 플레이어 선언
```

**이 엔진이 판에서 계산할 수 있는 것은 첫 줄 하나뿐이다.** 나머지 셋은
플레이어 선언 계층 · 조작 결과 전달 계층 · 체인 파라미터 계층을 요구하고,
그 셋은 여기 없다. 그래서 `UNKNOWN` 이고, **숫자로 바꾸지 않는다.**

### 2-3. 패턴 (§13 A~G · §22)

A · B · C 는 서로 배타적이고, D ~ G 는 그 위에 겹쳐지는 성질이다.

| 패턴 | 호출 | 대표 |
|---|---:|---|
| A 고정 1장 | 122 | 10131855 |
| B 고정 N장 | 8 | 10236520 |
| C 동적 수 | 12 | 10691144 |
| D 후보에 조건 (호출 줄에 보이는 것) | 6 | 22593417 |
| E 고른 뒤 이동 | 126 | 10131855 |
| F 고른 뒤 효과 등록 / 발동 | 37 | 10312660 |
| G 결과에 따른 분기 | 41 | 10312660 |

D 가 6 인 것은 **한 줄만 보고 센 값**이다. 나머지는 그룹을 앞에서 여러
줄에 걸쳐 조립하므로 한 줄로는 셀 수 없다. 늘려 적지 않는다.

E 의 목적지: `SendtoGrave` 78 · `Remove` 19 · `SendtoDeck` 12 ·
`SendtoHand` 10 · `Destroy` 6 · `Draw` 1.

### 2-4. 지금 닿을 수 있는가 (§14 · §22)

| 카드 141장 | 수 | 왜 |
|---|---:|---|
| 몬스터 효과 | 90 | 유발 · 지속 효과 계층이 없다 |
| 주문/함정 + 조건부 발동 시점 | 32 | 발동 시점 · 선택지 계층이 없다 |
| **주문/함정 단순 발동** | **14** | 지금 계층으로 닿는다 |
| 그 밖 | 5 | — |

14장을 하나씩 읽었다. 그중 **의적의 입문서(69091732)** 하나를 등재했다
(§5). 나머지 13장이 걸리는 것은 무작위 선택이 아니라 **다른 계층**이다 —
선택지 제시(1781310 · 16598965), 카드명 선언(15800838 · 33423043),
몬스터 종류 조건(6859683 은 `Card.IsType(TYPE_FUSION)` 을 요구하는데
조건 계층에 몬스터 종류 술어가 없다), 여러 효과의 순차 적용(36092504).

**추측으로 규칙을 만들어 늘리지 않았다.**

---

## 3. 만든 것 — `SelectionCount` (§3 · §25-5)

```python
SelectionCount.fixed(2)                       # CountKind.FIXED
SelectionCount.derived(                       # CountKind.DERIVED
    (ZoneCountTerm(PlayerRef.CONTROLLER, Zone.HAND, -1),), constant=4
)
SelectionCount.unknown("player-declared number")   # CountKind.UNKNOWN
```

`DERIVED` 는 **표현식 언어가 아니다.** 자리 장수의 덧셈과 뺄셈, 딱 실제
카드 네 장이 요구하는 만큼이다.

```
악몽의 신기루 41482598   SetLabel(4-ht)                      → 4 - (자신 패)
멀차미 3장             hand - (상대 필드 + 6)                → 패 - 상대필드 - 6
```

둘 다 `ZoneCountTerm` 두 개 이하로 적힌다. 더 일반적인 것을 만들지
않았다 — 요구가 없는 표현력은 검증할 수 없는 표현력이다.

숫자 하나를 그대로 적는 길(`count=1`)은 막지 않았다. **뜻이 같기
때문**이고, `SelectionCount.of` 가 같은 뜻을 제 타입으로 옮길 뿐이다.

---

## 4. 수와 후보는 서로를 읽지 않는다 (§4)

이 단계에서 가장 실질적인 변화다.

| 전 (2-AB) | 후 (2-AC) |
|---|---|
| `_roll_selection` 이 후보를 센 뒤 `spec.choice.count` 를 읽었다 | `_resolve_count` 와 `_authoritative_candidates` 가 **따로** 답한다 |
| 후보 계산에 `minimum`/`maximum` 을 넘겼다 | **넘기지 않는다** — 후보를 세는 데 장수는 쓰이지 않는다 |
| `RandomSelectionSpec.minimum`/`maximum` | **삭제** — 장수를 두 이름으로 부르지 않는다 |

세 가지를 테스트가 지킨다.

1. 같은 후보 규칙이면 `minimum`/`maximum` 이 무엇이든 **같은 후보**가
   나온다 (동작으로 확인).
2. `_authoritative_candidates` 안에 `.count`/`.minimum`/`.maximum` 접근이
   **없다** (AST).
3. `_resolve_count` 안에 `CandidateResolver` 도 `GameStateView` 도
   **없다** (AST).

**순서**는 수 → 후보다. 어느 쪽도 난수를 쓰지 않으므로 순서가 결과를
바꾸지 않고, 수를 모르면 후보를 다 세도 소용이 없으므로 이쪽이 싸다.

---

## 5. 실제 카드 — 의적의 입문서 (69091732) (§25-18)

> 상대의 패가 5장 이상일 경우에 발동할 수 있다. 상대의 패를 무작위로
> 1장 버린다. — 공식 한국어 텍스트

```lua
function s.condition(...) return Duel.GetFieldGroupCount(tp,0,LOCATION_HAND)>4 end
local dg=g:RandomSelect(tp,1)
Duel.SendtoGrave(dg,REASON_EFFECT|REASON_DISCARD)
```

| Lua | 옮긴 것 |
|---|---|
| `GetFieldGroupCount(tp,0,LOCATION_HAND)>4` | `ZoneCountAtLeast(OPPONENT, HAND, 5)` |
| `SetTargetPlayer(1-tp)` + `GetFieldGroup(p,LOCATION_HAND,0)` | `CandidateSource(HAND, owner=OPPONENT)` |
| `RandomSelect(tp,1)` | `SelectionCount.fixed(1)` |
| `SendtoGrave(..., REASON_DISCARD)` | `CardOperation.discard` |

이 카드가 새로 보여 주는 것은 하나다 — **발동 조건이 상대 패의 장수**다.
컨트롤러는 그 패를 볼 수 없는데 조건은 장수를 읽는다. 둘은 모순이
아니다: **장수와 정체는 다른 정보**다 (§8 · §9).

실행 기록:

```
seed=3  상대패 5장 → resolved · discard 1장 · draws=1 · journal=1
seed=3  (다시)     → 같은 카드
seed=12            → 다른 카드
        상대패 4장 → condition_false · draws=0 · 판 그대로
```

목록은 이제 **실제 카드 15장 / 실행 가능 11개**다 (14 / 10 에서).

동적 수를 쓰는 실제 카드는 **하나도 등재하지 못했다.** 12장 전부가
다른 계층을 요구한다 (§2-2). 그것이 이번 단계의 사실이다.

---

## 6. 모르는 후보 (§5 · §7 · §25-7)

요청서가 나눈 다섯 경우를 그대로 답한다.

| 경우 | 지금 |
|---|---|
| A 전부 알려짐 | 고른다 |
| B 일부가 `UNKNOWN` | **고르지 않는다.** 빼고 고르면 확률이 달라진다 |
| C 전부가 `UNKNOWN` | 고르지 않는다 — B 와 **다른 문장**으로 답한다 |
| D "후보가 될 수 없다" 는 권위 있는 규칙 | 그런 규칙은 조건이 `FALSE` 를 낼 때이고, 그때는 이미 제외된다. `UNKNOWN` 에는 그런 규칙이 **없다** |
| E 가려진 정보 때문에 생긴 `UNKNOWN` | 여기서는 **생기지 않는다** (아래) |

**B 와 C 를 한 문장으로 뭉치지 않는다.** 어느 쪽이든 고르지 않지만,
고쳐야 할 것이 다르다.

```
후보 4장 중 1장이 후보인지 알 수 없습니다. 모르는 것을 빼고 고르면
확률이 달라지므로 고르지 않습니다: ...
후보 4장이 **전부** 후보인지 알 수 없습니다. ...
```

절대로 하지 않는 것: `[A, B, UNKNOWN, D]` 에서 `UNKNOWN` 을 빼고
`[A, B, D]` 로 고르는 것. 1/4 이 1/3 이 되면 **다른 규칙**이다.
`_authoritative_candidates` 안에 `remove` 도 `discard` 도 없다는 것을
테스트가 확인한다.

---

## 7. `UNKNOWN ≠ HIDDEN` (§5-E · §8 · §25-8)

둘은 **다른 사실**이고 **다른 코드**로 답한다.

| | 무엇인가 | 답 |
|---|---|---|
| `UNKNOWN` | 규칙을 판정할 수 없다 (조건이 `UNKNOWN`) | `UNCHECKED_TARGET` · `INFORMATION_UNAVAILABLE` + 부분/전부 구분 |
| `HIDDEN` | 그 자리를 못 봤다 | `UNCHECKED_TARGET` · `INFORMATION_UNAVAILABLE` + `missing` 에 자리 이름 |

그리고 무작위 선택에서는 **HIDDEN 이 생기지 않는다.** 자리마다 그
주인의 눈으로 세기 때문이다 (Phase 2-AB). 그래도 그 길을 지우지 않았다 —
닿는다면 그것은 "모른다" 가 아니라 "못 봤다" 이고, 그 구분을 코드에서
지우면 다음 사람이 둘을 같은 것으로 읽는다.

수에서도 같은 구분이 선다. 의적의 입문서의 발동 조건은 **상대 패의
장수**를 읽고, 동적 수는 **상대 패의 장수**로 계산될 수 있다. 어느
쪽도 그 패의 **정체**를 열지 않는다.

```
engine authority   상대 패는 5장이다        ← 규칙이 아는 사실
viewer visibility  상대 패는 가려져 있다      ← 관측의 사실
```

---

## 8. "정확히 N" 과 "모자라면 전부" (§11 · §12 · §25-9)

기본은 **정확히 N** 이고, 모자라면 하지 않는다.

그런데 공식 카드 텍스트 두 장이 **부족할 때의 처리를 자기 텍스트에**
적어 두었다.

```
13959634  "Discard 2 random cards from your opponent's hand
           (or their entire hand, if less than 2)"
41482598  "Randomly discard the same number of cards you drew
           (or your entire hand, if you do not have enough cards)"
```

그러므로 이것은 **일반 규칙이 아니라 카드의 선언**이다 (Phase 2-X 에서
관문을 카드가 선언하게 한 것과 같은 발견이다). `Shortfall.TAKE_ALL` 을
선언한 정의만 그 길을 탄다.

**"최대 N장" 과 섞지 않는다.** 실제 카드의 "up to 2 random cards"
(10691144 · 45222299)는 플레이어가 1 이나 2 를 **선언한 뒤** 그 수만큼
무작위로 고르는 것이다 (`Duel.SelectOption` · `Duel.AnnounceNumber`).
수를 정하는 방법의 문제이지 부족할 때의 처리가 아니다. 그래서
`UP_TO` 를 만들지 **않았다** — 그것은 플레이어 선언 계층이고, 그 계층이
생기기 전에 만들면 이름만 있는 갈래가 된다.

`TAKE_ALL` 이 §7 을 어기지 않는 이유: 줄어드는 것은 **고를 수**이지
후보가 아니다. 후보는 전부 남아 있고, 그 안에서의 확률은 그대로다.

### 수 자체의 검증 (§11)

| | 답 |
|---|---|
| `FIXED` 가 0 이하 | 만들 때 거부 (`ValueError`) |
| `DERIVED` 가 0 이하로 계산됨 | `INVALID_OPERATION` · `INVALID_AMOUNT` |
| `UNKNOWN` | `UNSUPPORTED_OPERATION` · `RULE_NOT_IMPLEMENTED` + `missing` |
| 수 > 후보 수 | `INVALID_TARGET` · `TOO_FEW_SELECTED` (선언이 없으면) |

`DERIVED` 가 0 이 되는 것은 **효과가 아니라 발동 조건의 문제**다. 실제
카드가 그렇게 적혀 있다 — 멀차미는 `if dif>0`, 악몽의 신기루는 라벨이
0 이면 발동하지 않는다. 0을 조용히 넘기면 그 조건이 없는 정의가 조용히
아무 일도 안 하게 되고, 그것은 버그가 아니라 **없는 규칙**이 된다.

---

## 9. `FORBIDDEN` 은 어디 있는가 (§10)

요청서는 수의 결과로 `RESOLVED` · `UNKNOWN` · `INVALID` · `FORBIDDEN`
넷을 들었다. 앞의 셋은 `CountOutcome` 에 있고, **`FORBIDDEN` 은 여기
없다.**

`TEXT_DERIVED` 출처가 실행을 금지하는 것은 **수의 문제가 아니라 효과의
문제**이고, `ResolutionStatus.FORBIDDEN` 이 이미 한 계층 위에서 답한다
(ADR-004: 출처 검사가 **가장 먼저**다). 같은 이름을 아래에 하나 더 두면
두 곳이 서로 다른 말을 하게 되고, 실제로는 **닿지 않는 갈래**가 된다 —
수를 묻는 자리까지 `TEXT_DERIVED` 효과가 내려오지 않기 때문이다.

기존 어휘를 재사용하라는 §10 의 요구는 이 방향으로 지켰다.

---

## 10. 계획과 적용 · 실패 안전성 (§16 · §25-12)

Phase 2-V 이후의 구조를 **바꾸지 않았다.**

```
plan   수 → 후보 → 부족 판정 → 난수 → Selection → _Step
apply  기존 조작만. 난수를 꺼내지 않는다.
```

`plan_random_selection` / `apply_random_selection` 이라는 이름을 따로
만들지 않은 이유는, 무작위 선택이 **적용 단계를 갖지 않기** 때문이다 —
고르는 것은 상태 변경이 아니다 (Phase 2-AB §8). 있지도 않은 적용 단계에
이름을 붙이면 없는 대칭을 꾸미는 일이 된다.

실패했을 때:

| 어디서 막혔나 | 판 | 난수 |
|---|---|---|
| 수를 모른다 · 수가 잘못됐다 | 그대로 | **꺼내지 않았다** (`draws` 그대로) |
| 후보를 다 못 셌다 · 후보가 모자란다 | 그대로 | **꺼내지 않았다** |
| 고른 **뒤** 다른 조작이 막혔다 | 그대로 (`applied == ()`) | **꺼냈다** — 감추지 않는다 |

마지막 줄이 사실이고, 같은 seed 로 다시 돌리면 같은 자리에서 같은 답이
나오므로 재현은 깨지지 않는다.

---

## 11. 결정론 · 복제 · 해시 · 저널 (§17 ~ §20)

- **결정론** — 같은 seed · 같은 판이면 같은 답. 후보 순서는 여전히
  `CandidateResolver` 의 `_sort_key` 로 정해지고 `set()` 으로 흐트러지지
  않는다. `draws` 는 **고른 장수만큼** 는다 (번호를 N 번 뽑는다).
- **복제** — 복제본에서 고르면 복제본의 난수원만 나아간다. 같은 자리에서
  출발한 또 하나의 복제는 같은 답을 낸다.
- **`state_hash`** — **한 줄도 바꾸지 않았다.** 수를 계산하는 것은 판을
  읽기만 하므로 해시가 움직이지 않고, 카드가 움직여야 움직인다. 선언된
  수는 정의의 일부이지 판의 모양이 아니므로 `canonical_state` 에
  들어가지 않는다.
- **저널** — 새 통로를 만들지 않았다. 저널에는 **이동**이 남고 주사위는
  남지 않으며, 고르지 않은 카드의 정체는 어디에도 실리지 않는다.

---

## 12. 테스트 (§21)

`tests/engine/test_selection_count.py` — **43 함수 / 47 케이스**, 전부 통과.

| 절 | 무엇을 붙잡는가 |
|---|---|
| A | 고정 1 · 2 · 3 · 4장 · 숫자 하나는 FIXED 로 읽힌다 |
| B | 판에서 계산된다 · 같은 판이면 같은 수 · 다른 판이면 다른 수 · **관측이 아니라 판을 읽는다** |
| C | 모르는 수는 실행하지 않는다 · 숫자를 만들어 넣지 않는다 · `bool()` 이 막힌다 |
| D | 0 이하는 태어나지 못한다 · 계산해서 0 이면 `INVALID` · 두 가지를 동시에 주장할 수 없다 |
| E · F | 정확히 N · 모자라면 하지 않는다 (난수도 안 꺼낸다) |
| G | 카드가 선언하면 있는 대로 · 그래도 0장은 안 된다 · **"최대 N장" 과 다르다** |
| H | `UNKNOWN` 후보를 조용히 빼지 않는다 · 부분과 전부가 다른 문장 · `UNKNOWN ≠ HIDDEN` (AST) |
| §4 | 후보 계산이 장수를 안 읽는다 (동작 + AST) · 수 계산이 후보를 안 센다 (AST) · `minimum`/`maximum` 이 없다 · 난수원은 여전히 아무것도 모른다 |
| I · J | 장수를 읽어도 정체는 안 열린다 · `REVEAL_HAND` 는 보이는 것만 바꾼다 |
| K · L | 같은 seed 같은 답 · 다른 seed 다른 답 · 후보 순서가 정렬된다 · 복제 독립 |
| M · N · O · P | 뒤가 막혀도 판은 그대로 (난수는 꺼냈다) · 기존 조작을 탄다 · 저널 1건 · 해시의 뜻 그대로 |
| Q | 실제 카드 의적의 입문서 4건 (`@pytest.mark.real_card`) · 12건의 동적 수 모양이 적히는가 · 악몽의 신기루는 **모양만** 적히고 카드는 등재되지 않았다 |

### 기존 테스트 수정 (§20 · §25-20)

**삭제 0건.** 수정 3건.

1. `test_random_selection.py::test_q_ruthless_denial_uses_both_kinds_of_selection` —
   `count == 1` 이라고 단언했다. 그때는 수가 **숫자**였기 때문이다. 이제
   수는 값이고 "고정" 이 타입에 적혀 있으므로
   `count == SelectionCount.fixed(1)` 과 `kind is CountKind.FIXED` 로
   바꿨다. **약해진 것이 아니라 한 줄 늘었다** — 1 이라는 값과 그것이
   고정 수라는 사실을 따로 확인한다.
2. `test_real_card_execution.py::test_a_..._fourteen_real_cards` → 15장.
   이 테스트의 일이 원래 "늘어나면 깨지는 것" 이다.
3. 같은 파일의 실행 가능 10 → 11.

---

## 13. 회귀

```
2632 passed, 4 skipped in 36.12s     (기준선 2585 + 47)
real_card 표시만: 101 passed
```

---

## 14. TODO (§25-21)

- **STRUCTURAL-79 — 해결.** 동적 수량을 선언할 수 있고, 계산할 수 없는
  수는 `UNKNOWN` 으로 남는다.
- **STRUCTURAL-80 — 해결(정책 확정).** 후보 조건이 `UNKNOWN` 이면
  고르지 않는다. 부분과 전부를 구분해 답하고, 조용히 빼지 않는다.
  실제 빈도는 여전히 못 쟀다 — 무작위 카드 중 후보에 조건이 붙은 것이
  6건뿐이고 그중 등재된 것이 없기 때문이다. **못 쟀다는 것이 답이다.**
- **STRUCTURAL-81 (신규 · 🟠)** — **플레이어가 수를 선언하는 계층이
  없다.** `Duel.SelectOption` · `Duel.AnnounceNumber` 로 수를 정하는
  카드가 무작위 선택에서만 4장이고, "최대 N장" 텍스트가 전부 이 모양이다.
- **STRUCTURAL-82 (신규 · 🟠)** — **앞선 조작의 결과 수를 뒤 조작이 읽을
  수 없다.** "the same number of random cards" 가 3장이다. `_Step` 이
  결과 수를 들고 있지만 다음 조작에 전달되지 않는다.
- **STRUCTURAL-83 (신규 · 🟡)** — **몬스터 종류(융합/싱크로/…) 조건이
  없다.** 성공확률 0%(6859683)가 그것 하나 때문에 막힌다. 아키타입 조건
  부재(STRUCTURAL-77)와 **다른 문제**다.
- STRUCTURAL-71 · 73(해결됨) · 74 · 75 · 76 · 77 · 78 — **하나도 건드리지
  않았다** (§23).

---

## 15. 판정 (§24)

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 2 신규 | 81 (수 선언 계층) · 82 (조작 결과 전달) |
| 🟡 DETAIL | 1 신규 | 83 (몬스터 종류 조건) |
| 🟢 COSMETIC | 0 | |

`UNKNOWN` 을 숨기거나 부분 후보를 임의로 제거한 곳은 **없다**. §24 가
BLOCKER 로 규정한 그 두 가지를 테스트가 AST 와 동작 양쪽에서 막는다.

---

## 16. 이번에 하지 않은 것 (§23)

AI · 덱 빌더 · 지속 효과 전체 · SEGOC · 새 EventBus · 새 RandomEngine ·
새 ReplayEngine · 카드 이름 기반 분기 · 142장 자동 구현 · 셔플 카드 ·
동전 · 주사위 · STRUCTURAL-74 · 75.

**다음 Phase 는 시작하지 않았다.**
