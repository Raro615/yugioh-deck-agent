# Phase 2-Y — Observation Boundary & Movement Gate Resolution

기준 커밋: `2956546` (Phase 2-X) · 실제 Phase 2-W baseline `60ecef6`

```
A. 엔진이 아는 것            GameState          — 언제나 전부 안다
B. 그 사람이 보는 것          GameStateView      — 자리마다 다르다
C. 규칙 판정에 필요한 것      효과의 후보 규칙    — 효과가 이름으로 말한다
        ↓
Observation  →  Rule Gate  →  Validation  →  Operation
```

**이번 단계는 카드를 늘리는 단계가 아니다.** 관측 때문에 잘못 막히던 것을
풀고, 그 위에서 관문이 제대로 평가되게 한다. 그리고 **두 UNKNOWN 을 서로
다른 답으로** 갈라 놓는다.

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/game_state_view.py` | `from_state(..., looked_at=)` · `_player_view`/`_zone_view` 로 전달 · `owner == viewer` 방어 한 줄 |
| `engine/cost/choice.py` | `CandidateSource.looked_at_zones()` · `ChoiceSpec.looked_at_zones()` |
| `engine/effect/target.py` | `TargetSpec.looked_at_zones()` |
| `engine/effect/executor.py` | `_check_target` 가 규칙이 말한 자리만 열고 판정 |
| `engine/activation.py` | 대상 검증을 **규칙마다** 따로 관측해서 한다 |
| `tests/engine/test_observation_boundary.py` | 신규 — 29개 |
| `tests/engine/test_rule_gate_grave_discard.py` | 실제 카드 테스트 1건 갱신 + 3건 추가 (§17) |
| `docs/phase2y-observation-boundary.md` · `engine/__init__.py` | 문서 |

**새 abstraction 0개.** 새 EventBus · EffectEngine · TargetSystem ·
ChainSystem · OperationSystem · RuleEngine · AI policy **0개**. 새
ValidationCode **0개**. 새 클래스 **0개** — 인자 하나와 메서드 셋이
전부다.

---

## 2. STRUCTURAL-69 의 정확한 원인 (§17-4)

먼저 현재 정책을 **코드로 재현**했다 (§2). 자리마다 실제로 무엇이
보이는가:

| | DECK | HAND | EXTRA | MZONE | SZONE | GRAVE | REMOVED |
|---|---|---|---|---|---|---|---|
| **자기** | **가려짐** | 보임 | 보임 | 보임 | 보임 | 보임 | 보임 |
| **상대** | 가려짐 | 가려짐 | 가려짐 | 보임 | 자리만 | 보임 | 보임 |

**정책은 거의 다 맞았다.** "자기 카드니까 보인다" 는 일반화가 틀린 것도
확인했다 — 상대의 뒷면 세트 카드는 존이 공개인데도 `card_id` 가 없고,
자기 것은 보인다. 카드 단위 판정이 따로 있다.

문제는 **한 칸**이었다. `_zone_view` 가 이렇게 되어 있었다:

```python
if visibility is ZoneVisibility.HIDDEN:
    return ZoneView(**base, cards=(), concealed=True)
```

자리 이름만 보고 정하고, **"이 효과는 자기 덱을 들여다본다" 를 말할
자리가 없었다.** 그것이 STRUCTURAL-69 다.

기본값이 틀린 것이 아니다. 룰북이 예외를 명시한다:

> "If a card effect requires you to reveal cards from your Deck, **or look
> through it**, shuffle it and put it back in this space afterwards."
> — `sd-rulebook-en-v10`, Deck

즉 **덱이 가려진 것은 기본값이지 불변이 아니다.** "덱에서 고른다" 는
효과는 그 순간 자기 덱을 본다. 그 경우를 담을 표현력이 없었다.

---

## 3. observation policy 변경 내용 (§17-5)

`GameStateView.from_state(state, viewer, looked_at=None)` 한 인자다.

```python
looking = container.owner == viewer and zone in looked_at

if visibility is ZoneVisibility.HIDDEN and not looking:
    return ZoneView(**base, cards=(), concealed=True)
```

세 가지가 중요하다.

1. **기본값은 비어 있고, 비면 예전과 한 글자도 다르지 않다.**
   테스트가 `canonical_state()` 와 `to_dict()` 로 그것을 고정한다.
2. **`owner == viewer` 가 같은 줄에 있다.** 어떤 값을 넘겨도 남의 자리는
   열리지 않는다. 방어를 **한 곳에만** 두어야 부르는 쪽이 늘어도 새지
   않는다.
3. **자리 이름은 효과가 말한다.** 엔진이 "덱에서 고르니까 덱을 보겠지"
   하고 넓히는 것이 아니라, `CandidateSource.zones` 를 읽는다.

### 누가 무엇을 들여다보는가

```python
# CandidateSource
def looked_at_zones(self) -> frozenset[Zone]:
    if self.owner is PlayerRef.OPPONENT:
        return frozenset()      # 남의 자리에서 고르라고 볼 권리까지 주지 않는다
    return self.zones

# ChoiceSpec
def looked_at_zones(self) -> frozenset[Zone]:
    if self.chooser is not PlayerRef.CONTROLLER:
        return frozenset()      # 보는 사람과 고르는 사람이 다르다
    return self.source.looked_at_zones()
```

Lua 가 그대로 여기 와 있다.
`Duel.SelectMatchingCard(tp, filter, tp, LOCATION_DECK, 0, 1, 1, nil)` 의
"고르는 사람 `tp`" 가 `chooser`, "`tp` 의 덱" 이 `zones`/`owner` 다.

발동과 해결의 **두 대상 검증**이 이것을 쓴다. 발동 쪽은 규칙마다 따로
관측을 만든다 — 하나로 합치면 덱을 보는 규칙이 같은 효과의 다른 규칙에도
덱을 열어 준다.

**발동 조건(`activation`) 은 넓히지 않았다.** 어리석은 매장의 조건 중
옮긴 것은 덱 *장수* 뿐이고 장수는 원래 공개다. 안 쓰는 곳을 넓히지
않는다.

---

## 4. 자기 정보와 상대 정보의 구분 (§17-6)

§3 의 A · B · C 를 하나의 boolean 으로 합치지 않았다.

| | 무엇 | 어디 | 이번에 |
|---|---|---|---|
| A | 엔진이 아는 실제 상태 | `GameState` | **건드리지 않았다** |
| B | 그 사람이 보는 것 | `GameStateView` | 인자 하나로 **넓힐 수 있게** 했다 |
| C | 규칙 판정에 필요한 것 | 효과의 후보 규칙 | B 를 넓히는 **유일한 근거** |

테스트가 A ≠ B 를 직접 보인다: 엔진은 자기 덱의 `card_id` 를 알고
(`state.find_instance(...)`), 기본 관측은 모른다
(`view.player(MINE).zone(DECK).concealed is True`).

---

## 5. HIDDEN_CARD 처리 결과 (§17-7)

**상대의 비공개 정보는 하나도 열리지 않았다.** 최악의 경우까지 본다 —
부르는 쪽이 **모든 자리**를 `looked_at` 으로 넘겨도:

| | 결과 |
|---|---|
| 상대 덱 | `concealed=True` |
| 상대 패 | `concealed=True` |
| 상대 엑스트라 덱 | `concealed=True` |
| 상대 뒷면 세트 카드 | `card_id is None` |

거절 결과에 상대 카드의 `card_id` 도 `instance_id` 도 실리지 않는다.

**자기 쪽은** 효과가 이름으로 말한 자리만 열린다. 열린 뒤에도 그 관측은
그 판정 한 번을 위해 만들어지고 버려진다 — 일반 관측이 넓어지는 것이
아니다.

---

## 6. IsAbleToGrave 평가 결과 (§17-8)

**한 글자도 추측하지 않았다.** `UnknownMovementRuling` 은 여전히 모든
카드에 `UNKNOWN` 이고, 목록에도 아무 재정을 적지 않았다.

달라진 것은 **어디서 막히는가**다.

| | Phase 2-X | Phase 2-Y |
|---|---|---|
| 어리석은 매장 발동 | `UNCHECKED_TARGET` / `HIDDEN_CARD` | **`ACTIVATED`** |
| 어리석은 매장 해결 | (닿지 못함) | **`UNCHECKED_RULES` / `RULE_NOT_IMPLEMENTED`** |
| `missing` | (관측) | `send-to-grave-legality (Card.IsAbleToGrave 판정)` |

즉 **관문에 도달했고, 관문이 정직하게 모른다고 답한다.** "관측 때문에
막힌 것" 과 "관문이 미구현인 것" 이 이제 다른 답이다 — 그것이 §5 가
요구한 분리다.

---

## 7. 네 상태 (§8 · §17-11 · §17-12)

실제 카드(어리석은 매장)와 synthetic 양쪽에서 확인한다.

| | 상황 | status | code |
|---|---|---|---|
| CASE 1 | 관측 가능 + 관문 TRUE | `RESOLVED` | `OK` |
| CASE 2 | 관측 가능 + 규칙상 후보 아님 | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| CASE 3 | 관측 불가 (상대 덱 · 상대 패) | `UNCHECKED_TARGET` | `HIDDEN_CARD` |
| CASE 4 | 관측 가능 + 관문 근거 없음 | `UNCHECKED_RULES` | `RULE_NOT_IMPLEMENTED` |

**네 답이 서로 다르다는 것을 단언한다** (`len(set(pairs.values())) == 4`).

CASE 2 는 이번 단계가 **새로 가능해진 것**이다. 덱이 보이니까 "고른 것이
몬스터가 아니다" 를 말할 수 있다 — 예전에는 전부 `HIDDEN_CARD` 로
뭉개졌다.

### 성공 경로 (CASE 1, 실제 카드)

```
어리석은 매장 (81439173)
  → EffectActivator                     ACTIVATED
  → TargetResolver (looked_at={DECK})   LEGAL
  → MovementRuling (테스트가 답을 준다)  TRUE
  → GameState.move                      DECK → GRAVE
  → ZoneMoved(movement=SEND_TO_GRAVE)   파괴가 아니다
  → TimingPoint.CARD_MOVED · journal 1건
```

판정은 **테스트가 명시적으로 준다** (`DeclaredMovementRuling`). 저장소는
여전히 모르고, 목록에 적지 않았다 — 싸이크론의 파괴 판정과 같은 자리다
(Phase 2-O). `UNKNOWN` 을 `TRUE` 로 바꾼 것이 아니라 **밖에서 답을
받은** 것이다.

### 실패 행렬 (§9 · §17-12)

여섯 갈래 전부 `applied == ()` · `deltas == ()` · **`state_hash` 불변 ·
journal 0건 · 사건 0건**.

`HIDDEN_CARD` · `CANDIDATE_NOT_ELIGIBLE` · `UNCHECKED_RULES` ·
관문이 거절 · 안 고름 · 없는 `InstanceId`.

**두 UNKNOWN 의 `missing` 이 다르다** — 관측 실패와 관문 미구현이 서로
다른 계층을 지목한다.

---

## 8. 실제 카드 coverage 변화 (§15 · §17-9)

| | Phase 2-X | Phase 2-Y |
|---|---|---|
| 목록 전체 | 13장 | **13장** |
| `EXECUTABLE` | 9장 | **9장** |
| 관문을 선언한 카드 | 1장 | **1장** |
| **관측 때문에 막히는 카드** | **1장** (어리석은 매장) | **0장** |
| **관문이 UNKNOWN 이라 막히는 카드** | 1장 (싸이크론) | **2장** (싸이크론 · 어리석은 매장) |
| 해결까지 실행되는 카드 | 8장 | **8장** |

**실행되는 카드 수는 늘지 않았다. 그것이 옳다.**

늘리려면 `Card.IsAbleToGrave` 의 내용을 추측해야 하는데, 저장소에 그
근거가 없다. 룰북은 토큰을 한 번 언급하고 그것도 엑시즈 소재 이야기다.
추측해서 숫자를 늘리는 것이 §16 이 금지한 일이고 최종 판단 기준이
FAIL 이라고 못 박은 일이다.

바뀐 것은 **막히는 이유**다. 이제 관측이 아니라 관문이 막는다. 그것이
다음에 무엇을 해야 하는지를 정확히 가리킨다.

---

## 9. synthetic coverage 변화 (§17-10)

synthetic 쪽에서는 **CASE 1 이 새로 가능해졌다** — 가려진 자리에서
고르는 효과가 관문까지 가고, 판정을 받으면 실행된다. Phase 2-X 에서는
가려진 자리를 쓰는 synthetic 시험 자체를 만들 수 없었다.

`tests/engine/test_observation_boundary.py` 의 29개 중 25개가 synthetic,
4개가 실제 Lua 없이 정책만 보는 것이다.

---

## 10. hidden information · determinism · state_hash (§17-13 ~ 15)

| 보는 것 | 확인 |
|---|---|
| 상대 비공개 정보 | 모든 자리를 넘겨도 열리지 않는다 |
| 거절 결과 | 상대 카드의 `card_id` · `instance_id` 없음 |
| 기본값 불변 | `looked_at` 없음 == 빈 집합 (`canonical_state` 동일) |
| 같은 판 · 같은 들여다봄 | 같은 `canonical_state()` |
| 두 번 봐도 | 같은 답 |
| 관문 결과 | 두 판에서 같은 `canonical_state()` · 같은 `state_hash()` |
| **관측은 판을 바꾸지 않는다** | 모든 자리를 들여다봐도 `state_hash` 불변 |
| 복제 독립 | 복제본에서 실행해도 원본 `state_hash` 불변 |
| AI 없음 | AST — `game_state_view.py` 에 `choose`/`score`/`policy`/`best`/`prefer` 이름 없음 · `random` 없음 |

---

## 11. Event Pipeline 영향 (§17-16)

**없다.** 관측은 사건을 만들지 않는다. 관문을 통과한 이동은 기존
`StateDelta → EventReader → ObservedEvent → TimingEvent → EventJournal`
을 그대로 지나고, `ZoneMoved.movement` 가 `SEND_TO_GRAVE` 를 들고 간다.

실패하면 사건이 **하나도** 나오지 않는다 — 테스트가 `observed == ()` 로
확인한다.

---

## 12. 기존 테스트 수정 / 삭제 (§17-17)

**삭제 0건. 수정 1건 · 추가 3건.**

| 테스트 | 이전 전제 | 왜 바뀌어야 했는가 |
|---|---|---|
| `test_i_foolish_burial_activates_and_names_the_hidden_deck` → `test_i_foolish_burial_now_reaches_the_gate` | 발동이 `UNCHECKED_TARGET` / `HIDDEN_CARD` 로 멈춘다 | **그 테스트가 고정하고 있던 것이 STRUCTURAL-69 의 증상 자체였다.** 올바른 동작이 아니라 "지금 이렇게 막혀 있다" 는 기록이었고, 이번 단계가 바로 그것을 고쳤다. 단언을 약화한 것이 아니라 **더 멀리까지** 확인한다 — 발동 통과 · 관문 도달 · `missing` 일치 · 판 불변 · journal 0건 |

같은 카드에 대해 **세 개를 더 넣었다** — 상대 덱은 여전히 `HIDDEN_CARD`
(§4 의 방어선), 보이는 마법은 `CANDIDATE_NOT_ELIGIBLE` (CASE 2),
판정을 주면 끝까지 실행 (CASE 1). 하나를 고치면서 **경계를 더 촘촘하게**
만들었다.

엔진 테스트는 한 건도 고치지 않았다. `looked_at` 기본값이 비어 있어
기존 2,436개가 그대로 통과한다.

---

## 13. 새 TODO (§17-18)

- **STRUCTURAL-69 — 해결.** 효과가 자기 자리를 이름으로 말하면 그
  자리를 들여다본다. 기본 공개 범위는 그대로다.
- **STRUCTURAL-71 (신규 · 🟠)** — 덱을 들여다본 뒤 **섞지 않는다.**
  룰북은 "shuffle it and put it back in this space afterwards" 라고
  말하는데, 이 엔진에는 "효과가 끝난 뒤 덱을 섞는다" 는 단계가 없다.
  지금은 덱 순서가 관측에 노출되고 그대로 남는다. 결정론적 셔플은 이미
  있으므로(STRUCTURAL-53 해결) 부를 자리만 없다.
- **STRUCTURAL-72 (신규 · 🟡)** — 발동 조건(`activation`)은 들여다보지
  않는다. 어리석은 매장의 `IsExistingMatchingCard(..., LOCATION_DECK, ...)`
  중 덱 장수만 옮긴 상태 그대로다. 조건 계층까지 넓히려면 "조건이 어느
  자리를 보는가" 를 조건마다 말할 수 있어야 한다.
- **STRUCTURAL-70 (보류 그대로)** — `IsAbleTo*AsCost` 는 비용 계층의
  일이다. 이번에 건드리지 않았고 충돌도 없었다 (§12).
- STRUCTURAL-10 · 41 · 47 ~ 68 — 변동 없음. **하나도 건드리지
  않았다** (§13).

---

## 14. BLOCKER / STRUCTURAL / DETAIL / COSMETIC (§17-19)

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | 비용 계층과의 충돌도 없었다 (§12) |
| 🟠 STRUCTURAL | 1 신규 | 71 (들여다본 뒤 섞지 않는다) |
| 🟡 DETAIL | 1 신규 | 72 (발동 조건은 들여다보지 않는다) |
| 🟢 COSMETIC | 0 | |

---

## 15. 전체 테스트 (§17-20)

`tests/engine/test_observation_boundary.py` — **29개**, 전부 통과.

| 묶음 | 수 | 보는 것 |
|---|---:|---|
| A. 기본 관측 정책 | 4 | 자리 14칸을 한 표로 고정 · 뒷면 세트는 카드 단위 · 장수는 공개 |
| B. 엔진 ≠ 관측 | 5 | A/B 분리 · 자기 자리만 열린다 · **모든 자리를 넘겨도 남의 것은 안 열린다** · 기본값 불변 · 관측은 판을 안 바꾼다 |
| C. 규칙이 말한다 | 6 | 자기 덱은 본다 · 남의 자리는 못 본다 · 양쪽이면 자기 쪽만 · 상대가 고르면 안 넓힌다 |
| D. 네 상태 | 6 | CASE 1~4 · 네 답이 다르다 · 두 UNKNOWN 의 `missing` 이 다르다 |
| E. 실패 안전성 | 2 | 여섯 갈래 판·사건·기록 불변 · 정체 유출 없음 |
| F. 결정론 | 5 | 같은 답 · 복제 독립 · AI 없음 |

전체 회귀: **2465 passed, 4 skipped** (직전 2436 + 29).

```
pytest -m real_card         92 passed
pytest -m "not real_card"   2373 passed, 4 skipped
```
