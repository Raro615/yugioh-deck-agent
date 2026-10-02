# Phase 3-E-8 — STRUCTURAL-130 Resolution · Typed Exclusion / Partial Semantics

Base: `e014451` (Phase 3-E-7 · STRUCTURAL-130 Audit)
범위: STRUCTURAL-130 하나.
Engine 변경: **없음** (`git diff --stat engine/` 비어 있음).
점수 변경: **없음** — 손으로 만든 판 840개와 실제 말뭉치 4449회 평가에서
`(terminal, heuristic, terms)` 가 **전부 동일**하다.

---

## 0. 결론

`excluded` 가 범주를 들게 되었고, `partial` 이 `UNKNOWN` 만 본다.

```
excluded: tuple[str, ...]                      excluded: tuple[Exclusion, ...]
partial = bool(self.excluded)        ──▶       partial = any(범주 is UNKNOWN)
```

실제 말뭉치에서 `partial` 이 **99.64% → 0%** 로 떨어졌다. 그런데 **제외 기록은
줄지 않았다** — 3031회 평가에서 `DESIGNED_OUT` 4902건 + `WITHHELD` 5017건이
그대로 쌓인다. 빠진 것을 숨긴 것이 아니라 **범주가 갈렸다.**

---

## 1. 먼저 확인한 사실 (§1)

### 1-1. `partial` / `excluded` 를 읽는 **production 코드가 없다**

```
grep -rn "partial\|excluded" agent/ app/ core/ scripts/   (evaluation.py 제외)
→ 관련 결과 0건
```

`search.py` · `policy.py` · `heuristic.py` · `arena.py` · `runner.py` 어디에서도
읽지 않는다. 순위는 `StateValue.ordering_key() = (terminal.rank, heuristic)` 이고
`partial` 은 **들어가지 않는다.**

그래서 **`partial` 의 의미를 바꾸는 것은 Search ranking 을 바꿀 수 없다**
(§11 의 요구가 구조적으로 보장된다). 지금 `partial` 은 **사람과 테스트에게만
말하는 깃발**이다.

### 1-2. `excluded.append` 가 있던 자리 (수정 전 6곳)

| # | 문구 | 조건 |
|---|---|---|
| 1 | 내 몬스터 N마리의 공격력을 모른다 | `_zone_attack` 의 `unknown` (내 쪽) |
| 2 | 상대 몬스터 N마리의 공격력을 모른다 | `_zone_attack` 의 `unknown` (상대 쪽) |
| 3 | 내 뒷면 몬스터 N마리의 공격력은 세지 않았다 | `withheld` (내 쪽) |
| 4 | 상대 뒷면 몬스터 … 세지 않았다 | `withheld` (상대 쪽) |
| 5 | 상대 패 N장의 값을 모른다 | `opponent.hand.size` |
| 6 | 묘지 / 제외 존 / 필드 존 / 펜듈럼 존 / 엑스트라 덱 … 값을 매기지 않았다 | 설계상 제외 |

---

## 2. Exclusion 구조 (§2 · §7)

repository 의 기존 스타일에 맞췄다 — `Terminal(str, Enum)` 과 같은 꼴의 Enum,
`frozen=True, slots=True` dataclass.

```python
class ExclusionCategory(str, Enum):
    DESIGNED_OUT = "designed_out"
    UNKNOWN = "unknown"
    WITHHELD = "withheld"


@dataclass(frozen=True, slots=True)
class Exclusion:
    category: ExclusionCategory
    note: str
```

`StateValue` 에 더한 것은 **둘뿐**이다 (§7 — getter 를 무작정 늘리지 않는다).

| 이름 | 왜 필요한가 |
|---|---|
| `notes -> tuple[str, ...]` | 기존 테스트와 `describe_ko` 가 문구를 본다 |
| `of_category(category)` | 범주별로 꺼낸다. `has_unknown` / `has_withheld` / `has_designed_out` 세 개를 따로 만들지 않고 이 하나로 덮는다 — `partial` 이 이미 `has_unknown` 이다 |

---

## 3. 세 범주의 의미와, 기존 의미를 어디로 보냈는가 (§3)

### 3-1. 가르는 기준은 **왜 못 셌는가** 하나다

| 범주 | 왜 못 셌는가 | partial |
|---|---|---|
| `DESIGNED_OUT` | 값이 보이는데 **항으로 두지 않기로 했다.** 질문을 하지 않은 것이다 | 아니다 |
| `UNKNOWN` | **다 보이는데 숫자가 나오지 않는다.** 값 자체가 결정되지 않는다 | **그렇다** |
| `WITHHELD` | **합법적으로 볼 수 없다.** 관측 경계 밖이고, 어떤 평가자도 더 잘할 수 없다 | 아니다 |

### 3-2. 6곳의 매핑

| # | 문구 | 범주 | 근거 |
|---|---|---|---|
| 1 | 내 몬스터 … 공격력을 모른다 (공격력에 숫자가 없다) | **UNKNOWN** | 내 카드는 정의가 늘 읽힌다. 못 세는 이유는 `?` 다 |
| 2a | 상대 몬스터 … (가려져 있다) | **WITHHELD** | `definition is None` — 경계 밖이다 |
| 2b | 상대 몬스터 … (공격력에 숫자가 없다) | **UNKNOWN** | 앞면 `?` 카드. 다 보이는데 숫자가 없다 |
| 3 | 내 뒷면 몬스터 … 세지 않았다 | **DESIGNED_OUT** | ↓ §3-3 |
| 4 | 상대 뒷면 몬스터 … 세지 않았다 | **DESIGNED_OUT** | 같은 근거. 뒷면 열람 권한이 있을 때만 도달 |
| 5 | 상대 패 N장의 값을 모른다 | **WITHHELD** | 장수는 보이고 **내용은** 보이지 않는다 |
| 6 | 묘지 · 제외 존 · 필드 존 · 펜듈럼 존 · 엑스트라 덱 | **DESIGNED_OUT** | `GRAVE_IS_COUNTED = False` 의 근거 그대로 |

\#2 가 **하나에서 둘로 갈라졌다.** 예전에는 "가려져서 못 읽는다" 와 "읽히는데
숫자가 없다" 가 같은 문구로 보고되었고, **그것이 STRUCTURAL-130 이 `partial` 을
쓸 수 없게 만든 뿌리**였다.

### 3-3. §4 가 요구한 보고 — 기존 `withheld` 의 의미를 바꿨다

**§4 의 단서 조항에 해당하는 자리가 있었으므로 먼저 적는다.**

Phase 3-E-6 이 `_zone_attack` 에 `withheld` 라는 이름을 넣었고, 그 뜻은
이번 §3 의 `WITHHELD` 와 **다르다.**

| | 3-E-6 의 `withheld` | 이번 Phase 의 `WITHHELD` |
|---|---|---|
| 대상 | **내** 뒷면 몬스터의 공격력 | 상대 뒷면의 정체 · 상대 패의 내용 |
| 가려져 있는가 | **아니다** — 내 카드이고 정의가 읽힌다 | **그렇다** — 관측 경계 밖이다 |
| 왜 안 세는가 | 뒷면은 공격하지 않으므로 그 값이 **지금 들어올 피해가 아니다** | 값을 **볼 수 없다** |

§3 의 정의("정보가 존재할 수 있지만 viewer 에게 **공개되지 않아** 합법적으로
사용할 수 없는 것")에 비추면 내 뒷면 몬스터는 `WITHHELD` 가 **아니다.** 값을
알면서 항으로 두지 않기로 한 것이므로 `DESIGNED_OUT` 이다.

**3-E-6 의 구분이 사라진 것이 아니라 쪼개졌다.**

```
3-E-6:  "모른다"  ──┬──▶  WITHHELD      (가려져서 못 읽는다)
                    └──▶  UNKNOWN       (읽히는데 숫자가 없다)
        "세지 않았다" ──▶  DESIGNED_OUT  (알면서 세지 않기로 했다)
```

문구는 **한 글자도 바꾸지 않았다.** 바뀐 것은 기계가 읽을 범주가 생긴 것이다.

그래서 내부 변수 이름도 함께 고쳤다 — `withheld` 가 두 가지 뜻을 갖는 상태로
두면 다음 사람이 반드시 틀린다.

```python
@dataclass(frozen=True, slots=True)
class _ZoneAttack:
    total: int = 0
    hidden: int = 0          # 정의를 못 읽는다          → WITHHELD
    indeterminate: int = 0   # 읽히는데 숫자가 없다      → UNKNOWN
    not_attacking: int = 0   # 알지만 뒷면이라 안 센다   → DESIGNED_OUT
```

### 3-4. §3 안에서 겹쳐 있던 한 줄 — 어떻게 읽었는지 적는다

§3 은 `UNKNOWN` 의 예로 **"상대 face-down 카드의 공격력"** 을 들고,
`WITHHELD` 의 예로 **"상대 face-down 카드의 정의"** 를 든다. 코드에서 이 둘은
**같은 한 가지 상황**이고 제외 사유도 하나다 — 공격력을 못 세는 **이유가**
정의가 가려진 것이기 때문이다.

**택한 해석: 경계가 이유를 가른다** → 상대 뒷면 몬스터는 `WITHHELD`.

근거:

1. §3 `WITHHELD` 가 "상대 face-down 카드의 정의" 와 "기타 Observation
   Boundary 밖의 정보" 를 명시한다. 못 세는 **원인**이 바로 그 정의다
2. §3 `UNKNOWN` 은 "**실제 평가 불확실성**" 이라고 적는다 — 평가가 받을
   자격이 있던 값을 못 구한 경우다. 상대 뒷면은 평가의 실패가 아니다
3. §4 가 `WITHHELD → partial=False` 의 근거로 든 문장("관측 경계 때문에 알 수
   없는 정보이며, 현재 Evaluation 이 **합법적으로 처리한 결과**")이 상대 뒷면에
   정확히 들어맞는다
4. 이렇게 두면 두 범주가 **원인으로 서로 겹치지 않는다** — 이번 Phase 의
   목적이 바로 그 분리다

**대안 해석의 결과도 측정했다.** 가려진 것까지 `UNKNOWN` 으로 셌다면
동일 말뭉치에서 `partial` 이 **65.89%** 가 된다 (0% 가 아니라).

| 해석 | partial (무작위 seed 1–6, 3031회) |
|---|---|
| 택함 — 가려짐 → `WITHHELD` | **0.00%** |
| 대안 — 가려짐 → `UNKNOWN` | 65.89% |

뒤집는 비용은 `_zone_attack` 의 `hidden` 을 쓰는 `exclude(...)` 한 줄의 범주
인수뿐이다. 다른 판단이라면 한 줄로 바꿀 수 있게 두었다.

---

## 4. Partial 의미 (§4)

```python
@property
def partial(self) -> bool:
    return any(item.category is ExclusionCategory.UNKNOWN for item in self.excluded)
```

### 진리표 — **여덟 가지 전부** 실제 엔진 상태로 확인했다

| 들어 있는 범주 | partial |
|---|---|
| (없음) | False |
| `DESIGNED_OUT` | False |
| `UNKNOWN` | **True** |
| `WITHHELD` | False |
| `DESIGNED_OUT` + `UNKNOWN` | **True** |
| `DESIGNED_OUT` + `WITHHELD` | False |
| `UNKNOWN` + `WITHHELD` | **True** |
| 셋 모두 | **True** |

조합을 만드는 재료 (한 재료가 한 범주만 만든다):

| 범주 | 재료 |
|---|---|
| `DESIGNED_OUT` | 내 뒷면 통상 몬스터 (사파이어 드래곤) |
| `UNKNOWN` | 내 앞면 공격력 `?` 몬스터 (저주받은 하인 킹) |
| `WITHHELD` | 상대 패 3장 |

---

## 5. Score 영향 (§5) — **차이 0**

3-E-7 의 `agent/evaluation.py` 를 그대로 불러와 같은 관측에 두 평가자를 돌리고
`(terminal, heuristic, terms)` 를 전부 비교했다.

| 비교 대상 | 비교 횟수 | 차이 |
|---|---|---|
| 손으로 만든 판 (7존 × 3표시형식 × 5카드 × 2좌석 × 2패 × 2관점) | **840** | **0** |
| 실제 듀얼 · 무작위 seed 1–6 | **3031** | **0** |
| 실제 듀얼 · `allowed[0]` seed 1,2 | **443** | **0** |
| 실제 듀얼 · ATK `?` 덱 seed 1–4 | **975** | **0** |

대표 판의 점수는 테스트에 **숫자로 못 박았다**
(`test_03_the_score_did_not_move`).

| 판 | heuristic |
|---|---|
| 빈 필드 | 0 |
| 내 MZONE 앞면 1900 | +2400 |
| 내 MZONE 뒷면 1900 | +500 |
| 상대 MZONE 앞면 1900 | −2400 |
| 상대 MZONE 뒷면 1900 | −500 |
| 내 앞면 `?` | +500 |
| 내 **EMZONE** 앞면 1900 | +2400 (STRUCTURAL-132 유지) |
| 내 제외 존 1장 | 0 |
| 상대 패 3장 | 0 |

---

## 6. §6 — 문자열 참조 호환

`excluded` 의 문구를 직접 보던 자리는 **테스트뿐**이었다 (§1-1). 그 자리들을
`.excluded` → `.notes` 로 옮겼다. **판정의 강도는 한 글자도 바꾸지 않았다** —
문구도 그대로다.

`Exclusion` 을 `str` 하위 클래스로 만들면 기존 코드가 한 줄도 안 바뀌지만
**그 길은 가지 않았다.** §6 이 금지한 "새 구조 때문에 기존 의미를 몰래
문자열로 되돌리는" 일이 바로 그것이고, 그러면 범주가 있으나 아무도 안 보는
상태가 된다.

---

## 7. Observation Boundary (§8) — 침범 없음

새로 읽은 관측 **0개**. `card_id` · 상대 패 내용 · 덱 · RNG 를 읽지 않는다.

- 상대 뒷면 카드가 무엇이든 **점수와 범주가 같다** (실측: 사파이어 드래곤과
  저주받은 하인 킹이 같은 점수, 같은 `WITHHELD`)
- 가려진 `card_id` 를 점수에 흘리는 위반을 주입했을 때 기존
  `test_02_the_evaluator_reads_no_hidden_channel` 이 잡았다
- `WITHHELD` 는 `WITHHELD` 로, `UNKNOWN` 은 `UNKNOWN` 으로 남는다

---

## 8. §9 — 대표 사례 재검증

| Case | 내용 | 결과 |
|---|---|---|
| **A** | 묘지 · 제외 존만 있다 | `DESIGNED_OUT` 만, **partial = False**, 점수 기존과 동일 |
| **B** | 상대 뒷면의 공격력을 모른다 | `WITHHELD`, partial = False, 정체가 점수에 새지 않음 |
| **C** | 내 앞면 몬스터의 공격력 | 정상 평가 (+2400), `excluded` **비어 있음** |
| **D** | EMZONE 몬스터 | `+2400` — MZONE 과 동일. STRUCTURAL-132 **유지**, 로직 재설계 없음 |

---

## 9. §10 — 통계 (3-E-7 과 같은 결정적 말뭉치)

### 무작위 선택 seed 1–6 (3-E-7 의 3031회와 **같은 말뭉치**)

| 항목 | 3-E-7 | 3-E-8 |
|---|---|---|
| 평가 횟수 | 3031 | 3031 |
| 점수/항 차이 | — | **0** |
| **partial** | **3020 (99.6371%)** | **0 (0.0000%)** |
| `DESIGNED_OUT` 기록 | (범주 없음) | 4902 (평가당 1.62건) |
| `UNKNOWN` 기록 | (범주 없음) | **0** |
| `WITHHELD` 기록 | (범주 없음) | 5017 (평가당 1.66건) |

### 다른 두 말뭉치

| 말뭉치 | 평가 | 점수 차이 | partial 전 | partial 후 | D/U/W |
|---|---|---|---|---|---|
| `allowed[0]` seed 1,2 | 443 | 0 | 99.3228% | **0%** | 455 / 0 / 440 |
| ATK `?` 덱 무작위 seed 1–4 | 975 | 0 | 99.8974% | **0%** | 1637 / 0 / 1708 |

### 변화의 원인은 **범주 분리 하나다**

§10 이 요구한 구분에 답한다.

- **점수 계산 변경 때문이 아니다** — 네 말뭉치 전부 차이 0 (§5)
- **기록이 줄어서가 아니다** — 제외 기록은 평가당 3.3건으로 **오히려 늘었다**
  (문구 #2 가 둘로 갈렸으므로)
- `partial` 만 떨어졌다. 떨어진 이유는 예전에 깃발을 세우던 것들이 전부
  `DESIGNED_OUT`(묘지 등)과 `WITHHELD`(상대 패 · 상대 뒷면)였기 때문이다

### 그리고 **지금 `partial` 은 언제나 거짓이다** — 숨기지 않고 적는다

세 말뭉치 모두 `UNKNOWN` 이 **0** 이다. 공격력 `?` 카드가 필드에 도달하지
않기 때문이다 — 저주받은 하인 킹은 효과 몬스터라서 엔진이 소환 후보로 내놓지
않는다 (`tests/agent/test_search_ai.py` 가 이미 그 사실을 적고 있다).

그러므로 **이 Phase 가 만든 것은 "쓸 수 있는 신호" 가 아니라 "옳은 신호" 다.**

| | 3-E-7 | 3-E-8 |
|---|---|---|
| `partial` 의 실제 의미 | "이 판에 묘지가 있다" | "공격력 `?` 카드가 필드에 있다" |
| 실측 | 99.6% 참 | 0% 참 |
| 틀렸는가 | **그렇다** — 묻지 않은 것을 못 푼 것으로 보고했다 | 아니다 |

늘 거짓인 깃발도 아직 신호는 아니다. 다만 **거짓을 말하지 않는다**, 그리고
`?` 공격력 카드가 필드에 서는 날 **정확히 그때** 참이 된다. 이것을
STRUCTURAL-133 으로 기록한다 (§11).

---

## 10. §11 — Search 영향

정책을 바꾸지 않았다. `partial` 은 `ordering_key()` 에 들어가지 않으므로
(§1-1) 순위가 바뀔 수 없다.

| 조합 | 완주 | 거부 | 에러 | 한도 | 시뮬 | 결정 |
|---|---|---|---|---|---|---|
| search vs search | 8/8 | 0 | 0 | 0 | 1834 | 818 |
| search vs rule | 8/8 | 0 | 0 | 0 | 802 | 768 |
| rule vs search | 8/8 | 0 | 0 | 0 | 801 | 709 |
| rule vs rule | 8/8 | 0 | 0 | 0 | 0 | 716 |

시뮬레이션 수 · 결정 수 · 행동 분포가 3-E-7 과 **숫자까지 동일**하다.

---

## 11. 의도적 위반 주입 (6건 · 전부 잡힘)

| # | 주입 | 잡은 테스트 |
|---|---|---|
| 1 | `partial` 을 `bool(excluded)` 로 되돌린다 | 13개 (`test_12_partial_is_now_rare…` 등) |
| 2 | 내 뒷면 몬스터를 `WITHHELD` 로 잘못 분류 | 8개 (`test_02_designed_out_alone…` 등) |
| 3 | 가려진 것을 `UNKNOWN` 으로 합친다 | 4개 (`test_06_…stays_withheld` 등) |
| 4 | 판정 순서를 뒤집어 `?` 뒷면을 `DESIGNED_OUT` 으로 | `test_07b_unreadable_beats_face_down…` |
| 5 | 가려진 `card_id` 를 점수에 흘린다 | `test_02_the_evaluator_reads_no_hidden_channel` |
| 6 | 뒷면 공격력을 다시 센다 (점수 변경) | 5개 (`test_03_the_score_did_not_move` 등) |

---

## 12. 기존 테스트 수정 (삭제 0 · skip 0 · 완화 0)

### API 이행뿐 (판정은 한 글자도 바뀌지 않았다) — 11곳

`for note in X.excluded` → `for note in X.notes`
(`test_set_action_space.py` 3곳, `test_evaluation_alignment_audit.py` 7곳,
`test_search_ai.py` 1곳)

`_zone_attack` 의 반환이 4-튜플 dataclass 가 되었으므로
`test_search_ai.py::test_12` 가 위치 분해 대신 이름으로 읽는다. **주장이
강해졌다** — 예전엔 "unknown 1" 이었던 것을 이제 "정의는 읽히는데 숫자가
없다(`indeterminate`) 1, 가려짐 0" 으로 못 박는다.

### 전제가 틀려서 뒤집은 것 — 5개 (각각 이유를 적는다)

1. **`test_12_partial_is_true_on_almost_every_real_board`**
   → `test_12_partial_is_now_rare_because_the_reasons_are_separated`
   99.6% 를 **결함으로 고정**하고 있었다. 틀린 것은 시험이 아니라 코드였고,
   이 Phase 가 그 코드를 고쳤다. 뒤집으면서 **"기록은 그대로 많다"** 를 함께
   주장하게 만들었다 — 줄어든 것이 범주 분리 때문인지 숨김 때문인지 이
   시험이 가른다.

2. **`test_12c_every_real_evaluation_is_partial_and_says_why`**
   → `…records_the_opponent_hand_as_withheld`
   "상대 패를 모르므로 모든 평가가 부분 평가다" 가 전제였다. 상대 패의 내용은
   **관측 경계 밖**이고, 그것을 모르는 것은 평가가 못 푼 것이 아니다. 기록을
   본다는 주장은 그대로 두고 `partial` 주장만 뒤집었다.

3. **`test_01_partial_is_exactly_one_bit_over_the_excluded_list`**
   → `test_01_partial_is_no_longer_one_bit_over_the_whole_excluded_list`
   `partial` 이 한 비트임을 **결함으로 고정**하고 있었다. 뒤집어, 다시 한
   비트로 돌아가면 깨지게 했다.

4. **`test_06_an_opponent_face_down_card_stays_unknown`**
   → `…stays_withheld`
   3-E-7 은 문구("모른다")로 분류해서 `UNKNOWN` 이라고 적었다. 그런데 3-E-7
   Audit **자신의 분류표에는 Category B(관측 불가)** 로 적혀 있었다 — 문구와
   분류가 어긋나 있었고, 범주를 담을 자리가 없어 문구가 이겼다. 그 어긋남이
   STRUCTURAL-130 이다.

5. **`test_04` · `test_05` · `test_07b` (`test_evaluation_excluded_audit.py`)**
   `DESIGNED_OUT` 만 있을 때 `partial` 이 참이 되는 것을 성과로 적고 있었다.
   보이는데 세지 않기로 한 것은 평가의 미해결이 아니므로 뒤집었다. **기록이
   남는다는 주장은 그대로다** — 뒤집은 것은 깃발뿐이다.

---

## 13. 테스트

```
3392 passed · 0 failed · 4 skipped
```

기준(`e014451`) 3378 passed → **+14**

- 신규 `tests/agent/test_exclusion_categories.py` — **14개**
  (진리표 8 + `DESIGNED_OUT` 전수 1 + 점수 불변 1 + EMZ 유지 1 +
  은닉 유지 1 + 범주 보존 1 + 끝난 판 1)
- `tests/agent/test_evaluation_excluded_audit.py` 는 13개 그대로 (내용 갱신)
- Regression **0** · 삭제 0 · skip 0 · assertion 완화 0

---

## 14. TODO

- **STRUCTURAL-130 → RESOLVED**
- **STRUCTURAL-132 → 유지(해결 상태)** — 로직을 다시 설계하지 않았고,
  `test_04_the_extra_monster_zone_fix_still_holds` 가 지킨다
- **STRUCTURAL-133 (신규)** — `partial` 이 이제 **옳지만 언제나 거짓**이다.
  `UNKNOWN` 의 유일한 원천인 공격력 `?` 카드가 현재 행동 공간에서 필드에
  도달하지 않는다 (효과 몬스터는 소환 후보에 오르지 않는다). 🟢 관찰
- 102 · 107 · 109 · 110 · 116 · 118 · 120 · 122 · 123 · 128 · 129 · 131
  **전부 유지**, 손대지 않았다

---

## 15. 다음 Phase 후보 — 하나만

**STRUCTURAL-128 — side-to-move 를 평가가 읽지 않는다.**

근거가 가장 명확하다:

1. **관측에 이미 있다** — `GameStateView.turn_player` · `is_my_turn`.
   3-E-5 Audit 이 "있는데도 읽지 않는다" 로 측정해 두었다
2. **이번 Phase 가 길을 치웠다** — 지금 평가는 "무엇을 세지 않는지" 를 범주로
   말할 수 있다. side-to-move 를 세지 않기로 하든 세기로 하든, 그 결정을
   `DESIGNED_OUT` 으로 **적을 수 있다**
3. **그런데 가중치 설계가 들어간다** — "내 차례인 것의 값이 LP 몇인가" 는
   새 가중치이고, 그것이 3-E-6 · 3-E-7 · 3-E-8 이 일관되게 금지해 온 일이다

그래서 다음 Phase 는 **Audit 으로 시작해야 한다**: side-to-move 가 지금 어떤
판단을 망치고 있는지 실측으로 고정하고, 가중치가 **필요한지부터** 판정한다.
필요 없다면 `DESIGNED_OUT` 으로 적고 끝낸다 — 그것도 해결이다.

STRUCTURAL-129(`hand` 만 차분이 아니다)는 영합 설계와, 131 은 표시 형식 변경
(STRUCTURAL-108 의 나머지 절반)과 묶여 있어 지금 할 수 없다.
