# Phase 2-Z — Deterministic Randomness & Random Selection Core

기준 커밋: `26f85ff` (Phase 2-Y) · 2465 passed / 4 skipped

```
seed
  → RandomSource        꺼낸 횟수를 센다. **카드를 보지 않는다**
  → RandomOutcome       정체가 붙는다. **엔진 내부 기록이다**
  → ShuffleOperation    기존 표에 한 줄
  → plan (여기서 결정)  →  apply (난수를 꺼내지 않는다)
  → ZoneShuffled        **결과 순서를 적지 않는다**
  → EventReader → ObservedEvent → EventJournal   (기존 통로 그대로)
```

두 원칙이 이 단계의 전부다.

> **랜덤이어도 재현 가능해야 한다.**
> **게임 규칙의 랜덤과 AI 의 랜덤은 서로 다른 계층이다.**

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/randomness.py` | **신규** — `RandomPurpose` · `RandomOutcome` · `RandomSource` · `RandomError` |
| `engine/state/game_state.py` | `_rng` → `_random: RandomSource` · `randomness` 속성 · `clone` · `create` |
| `engine/state/zones.py` | `ZoneContainer.reorder` · `ZoneReorderError` |
| `engine/effect/operation.py` | `OperationKind.SHUFFLE` · `ShuffleOperation` · `SHUFFLEABLE_ZONES` |
| `engine/effect/delta.py` | `ZoneShuffled` |
| `engine/effect/executor.py` | `_plan_shuffle` / `_apply_shuffle` + 표 한 줄 · `_Step.outcome` |
| `tests/engine/test_randomness.py` | **신규** — 42개 |
| `tests/engine/test_operation_integration.py` | 단언 2건 갱신 (§11) |
| `docs/phase2z-deterministic-randomness.md` · `engine/__init__.py` | 문서 |

**새 RandomBus · RandomEngine · EventBus · ReplayEngine · EffectEngine
0개.** 테스트가 `engine/` 전체를 훑어 그것을 확인한다.

---

## 2. 기존 구조 조사 결과 (§1)

먼저 세어 보니 **§2 가 요구한 것의 절반이 이미 있었다** (STRUCTURAL-53).

| 이미 있던 것 | 상태 |
|---|---|
| `GameState._seed` · `_rng` (주입된 `random.Random`) | 있었다 |
| 전역 `random` 미사용 | 지켜지고 있었다 |
| `clone()` 이 `getstate()`/`setstate()` 로 난수원 복제 | 있었다 |
| `create(seed=..., shuffle=True)` · seed 없는 셔플 거부 | 있었다 |
| `canonical_state`/`state_hash` 가 난수원을 **제외** | 있었다 (의도적) |

없던 것은 넷이다.

1. **꺼낸 횟수(재현 좌표)** — 실패한 시나리오를 되짚을 번호가 없었다.
2. **결과를 기록할 값** — 무엇 중에서 무엇이 골라졌는지 남지 않았다.
3. **규칙이 쓸 API** — `state.rng.choice(...)` 를 직접 부르는 수밖에 없었고,
   그것은 §2 가 금지한 모양이다.
4. **게임 RNG 와 AI RNG 의 경계** — 값으로 구분된 것이 없었다.

---

## 3. 새 abstraction과 그 이유 (§15-3)

새로 만든 것은 **세 개**이고 전부 한 파일에 있다.

### `RandomSource` — 왜 `random.Random` 으로 부족한가

세 가지가 더 필요했다.

- **꺼낸 횟수를 센다.** `random.Random` 은 "몇 번째" 를 말해 주지 않는다.
  그 번호가 없으면 "seed 3 의 7번째 무작위에서 갈렸다" 를 적을 수 없다.
- **카드를 보지 않는다.** 원시 연산이 돌려주는 것은 자리 번호와 순열뿐이고,
  정체를 카드에 대응시키는 일은 부르는 쪽이 한다. **난수원을 통해 숨은
  정보가 샐 수 없다 — 애초에 정체를 쥐지 않기 때문이다.**
- **값으로 비교된다.** `canonical_state()` 가 `getstate()` 의 내용에서
  나온다. 객체 주소도 `repr` 도 쓰지 않는다 (§9).

### `RandomOutcome` — 왜 카드를 그냥 돌려주면 안 되는가

§4 가 요구한 그대로다. 카드 하나만 돌려주면 **무엇 중에서 골랐는지**와
**몇 번째 무작위였는지**가 사라져 재현도 기록도 못 한다.

그리고 이 값은 **엔진 내부 기록이지 관측이 아니다.** 그래서 문이 둘이다.

| | 담는 것 | 누구에게 |
|---|---|---|
| `to_dict()` | 후보 · 선택 · 좌표 (`InstanceId`) | **엔진 내부** |
| `public_summary()` | 목적 · 후보 수 · 선택 수 | 누구에게 보여도 된다 |

### `RandomPurpose` — 왜 열거형이 필요한가

§8 의 경계를 **값으로** 들고 있기 위해서다. `AI_*` 목적이 여기 없다는
사실 자체가 경계이고, 테스트가 그것을 고정한다 (`{deck_shuffle,
random_selection}` 정확히 둘).

### 만들지 **않은** 것

동전(실제 카드 30장) · 주사위(57장) · `randint`. 코퍼스에 있는 줄 알면서
만들지 않았다 — 만들면 결과 범위 · 재굴림 · "동전을 던졌을 때" 트리거까지
규칙이 따라오는데 그 계층이 없다 (§3 "과도하게 확장하지 않는다").
테스트가 `RandomSource` 의 공개 이름이 정확히 아홉 개임을 고정한다.

---

## 4. RNG deterministic 보장 방식 (§15-4)

| 보장 | 어떻게 |
|---|---|
| 전역 상태 없음 | `RandomSource` 가 `random` **모듈**을 받으면 `TypeError` |
| 엔진이 전역을 안 씀 | AST — `engine/**/*.py` 중 난수원을 만드는 두 파일 외에는 `import random` 도 `random.*` 호출도 **0건** |
| 실행기가 판의 난수원만 씀 | AST — `executor.py` 의 `.randomness` 접근이 전부 `state.randomness` |
| 같은 seed → 같은 결과 | `choose` 10회 · `shuffle` 연속 호출 비교 |
| 좌표로 되짚기 | `draw` 번호까지 진행한 뒤 같은 답이 나온다 |
| 후보 순서가 결정론의 일부 | `CandidateResolver` 가 이미 `(컨트롤러, 존 순서, sequence, instance_id)` 로 정렬해 준다 — 새로 만들지 않았다 |

**빈 후보는 거절한다.** 그리고 거절했을 때 좌표가 움직이지 않는다 —
실패가 난수원만 소비하면 재현이 깨진다.

---

## 5. clone independence (§15-5)

| 보는 것 | 확인 |
|---|---|
| 사본이 같은 위치에서 출발 | `draws` · `canonical_state()` 동일 |
| 원본을 50번 소비 | 사본의 다음 다섯 결과 **불변** |
| 판을 복제 | 난수원도 **꺼낸 횟수까지** 복제 |
| 사본에서 셔플 | 원본의 덱 순서 · `state_hash` · 난수원 위치 전부 그대로 |

---

## 6. state_hash / canonical_state 영향 (§9 · §15-6)

**난수원은 `GameState.canonical_state()` 에 들어가지 않는다. 넣지
않기로 한 것이 이번 단계의 판단이다.**

이유는 이 프로젝트가 `chain` · `journal` · 우선권을 해시에서 뺀 것과 같다.
난수원의 위치는 **판의 모양이 아니라 흐름의 위치**다. 넣으면 판이
똑같은데 몇 번 뽑았느냐로 해시가 달라지고, 그러면 그것은 판의 해시가
아니다. 테스트가 그 성질을 직접 고정한다 — 한쪽만 난수를 열 번 꺼내도
두 판의 `state_hash()` 와 `canonical_state()` 가 같다.

**해시에 넣지 않는다고 값으로 비교할 수 없는 것은 아니다.**
`RandomSource.canonical_state()` 가 따로 있고, `getstate()` 의 내용을
결정론적으로 직렬화해 요약한다 — 객체 주소도 `repr` 도 들어가지 않는다
(테스트가 `"0x"` 와 `"object at"` 가 없음을 확인한다).

셔플이 판을 바꾸므로 **`state_hash` 는 달라진다.** 그것은 덱의 순서가
판의 모양이기 때문이고, 난수원의 위치와는 다른 이야기다.

---

## 7. hidden information 안전성 (§7 · §15-7)

세 겹으로 막는다.

1. **난수원이 정체를 쥐지 않는다.** 원시 연산은 자리 번호만 다룬다.
2. **변화가 결과 순서를 적지 않는다.** `ZoneShuffled` 는 `(player, zone,
   size, draw)` 뿐이다 — 섞은 뒤의 덱 순서는 아무도 모르는 것이 규칙이고,
   적어 두면 읽는 쪽이 알게 된다. 테스트가 네 장의 `card_id` 가 변화의
   어디에도 없음을 확인한다.
3. **결과 기록의 문이 둘이다.** `public_summary()` 는 "4장 중 1장" 만
   말한다.

§7 의 시나리오도 그대로 본다. 상대 패 `[A,B,C,D]` 에서 무작위로 1장 —
엔진은 어느 `InstanceId` 인지 알고, **관측은 여전히 상대 패를 보지
못한다**. 무작위였다는 사실이 정체를 공개하는 근거가 되지 않는다.

Phase 2-Y 의 관측 경계를 **우회하지 않았다.** `looked_at` 도 건드리지
않았고, 난수는 관측 밖에서 일어난다.

---

## 8. EventJournal / StateDelta 연결 (§5 · §15-8)

새 통로를 만들지 않았다. 표에 **한 줄**이 늘었을 뿐이다.

```
ShuffleOperation
  → _plan_shuffle    난수를 **여기서** 꺼낸다 → _Step.outcome
  → _apply_shuffle   계획이 정한 순서를 그대로 적용. 난수를 꺼내지 않는다
  → ZoneShuffled
  → EventReader → ObservedEvent → EventJournal (1건)
```

**난수를 계획 단계에서 꺼내는 것이 핵심이다.** 적용 중에 꺼내면 "계획을
전부 확인한 뒤에 적용한다" 가 깨지고, 뒤의 일이 막혔을 때 난수원만
소비된 채로 남는다. 테스트가 셔플 한 번에 `draws` 가 정확히 1 늘어남을
확인한다.

계획과 적용 사이에 존의 내용이 달라지면 `EffectExecutionError` 다 —
재현이 깨지는 상황을 조용히 넘기지 않는다.

### 사건 계층은 정직하게 모른다고 말한다

"덱을 섞었을 때" 라는 `TimingPoint` 가 **없다.** 지어내지 않고
`UNIMPLEMENTED` 로 남긴다 — "사건이 없었다" 가 아니라 "옮길 이름이
없었다" 다 (`is_observable is False`, `note` 가 채워져 있다).

---

## 9. failure safety (§11 · §15-9)

seed 없는 판에서 섞으려 하면:

| | 결과 |
|---|---|
| `status` | `UNSUPPORTED_OPERATION` |
| `code` | `RULE_NOT_IMPLEMENTED` |
| `missing` | `seeded randomness (GameState.create(seed=...))` |
| `applied` · `deltas` | `()` · `()` |
| `state_hash` | **불변** |
| 덱 순서 | **불변** |
| journal | 0건 |
| 사건 | 0건 |

빈 후보에서 고르는 것도 거절하고 (`RandomError`), **좌표가 움직이지
않는다.**

카드를 잃거나 만드는 재배열은 존이 거부하고 (`ZoneReorderError`), 카드를
잃거나 만드는 결과는 `RandomOutcome` 이 생성 시점에 거부한다.

---

## 10. 테스트 결과 (§12 · §15-10)

`tests/engine/test_randomness.py` — **42개**, 전부 통과.

| 묶음 | 수 | §12 대응 | 보는 것 |
|---|---:|---|---|
| A. 난수원 | 6 | A · B · C | 같은 seed 같은 결과 · 다른 seed · 재현 좌표 · 전역 거부 · 빈 후보 거부 |
| B. 복제 독립 | 3 | D · E | 같은 위치 · 원본 소비해도 사본 불변 |
| C. 셔플 | 4 | F · G | 집합 보존 · 중복/누락 없음 · 원시는 카드를 안 본다 |
| D. 판과의 연결 | 6 | L · M | seed 없으면 거절 · **해시는 난수원을 안 담는다** · 난수원은 따로 정규형이 있다 · 판 복제 |
| E. Operation 통합 | 9 | H · I | 표 한 줄 · 이유 없음 · 섞을 수 있는 존 · 전체 pipeline · 같은/다른 seed · **변화가 순서를 안 적는다** · 사건은 이름이 없다 · 계획에서 꺼낸다 |
| F. 실패 안전성 | 2 | J | 판·기록·사건 불변 |
| G. 숨은 정보 | 3 | K | 엔진은 알고 관측은 모른다 · 요약은 아무것도 안 말한다 · 두 문이 따로다 |
| H. 경계 | 4 | — | AI 목적 없음 · **엔진이 전역 random 을 안 쓴다** · AI policy 없음 · 새 architecture 없음 |
| I. 결정론 전체 | 2 | L · M | 같은 실행 같은 결과 · 복제 독립 |
| J. 실제 Lua 조사 | 2 | — | 코퍼스에 무엇이 있는가 · 무엇을 일부러 안 만들었나 |

전체 회귀 (§12 N): **2507 passed, 4 skipped** (직전 2465 + 42).

### 실제 카드 (§13)

**실제 카드를 하나도 늘리지 않았다.** 대신 코퍼스를 세어 사실을 적었다.

| Lua 원시 | 카드 수 | 이번에 |
|---|---:|---|
| `SEQ_DECKSHUFFLE` | 514 | 기반을 만들었다 (덱 셔플) |
| `Duel.ShuffleHand` | 442 | 만들지 않았다 |
| `Duel.ShuffleDeck` | 243 | 기반을 만들었다 |
| `Group:RandomSelect` | 142 | `choose` 는 있으나 카드에 연결하지 않았다 |
| `Duel.TossDice` | 57 | 만들지 않았다 |
| `Duel.TossCoin` | 30 | 만들지 않았다 |
| `Duel.ShuffleExtra` | 28 | 존은 열어 두었다 (`SHUFFLEABLE_ZONES`) |

---

## 11. 기존 테스트 수정 / 삭제 (§15-11)

**삭제 0건. 수정 2건** — 둘 다 `test_operation_integration.py` 의 단언이고,
약화하지 않았다.

| 테스트 | 이전 전제 | 왜 바뀌어야 했는가 |
|---|---|---|
| `test_a_the_taxonomy_is_exactly_what_is_executable` | 실행 가능한 일이 11가지 | **그때의 사실**이었다. 목록이 늘면 깨지도록 되어 있고 그것이 그 테스트의 일이다. `"shuffle"` 한 줄을 더했다 |
| `test_k_the_executor_makes_no_choice_of_its_own` | 원문에 `"random"` 이라는 **낱말**이 없다 | **전제가 무뎠다.** 그 검사는 "무작위를 전혀 쓰지 않는다" 를 뜻했는데, 실행기는 이제 규칙이 요구하는 무작위(덱 셔플)를 쓴다. 규칙의 무작위와 임의의 선택은 다른 것이고 낱말 하나로는 구분되지 않는다. 낱말 대신 **셋을 코드로** 확인한다: 전역 `random` 을 import 하지 않는다 · `random.*` 를 부르지 않는다 · 무작위는 `state.randomness` 에서만 나온다. **예전 검사보다 강하다** |

엔진의 다른 테스트는 한 건도 고치지 않았다.

---

## 12. 새 TODO (§15-12)

- **STRUCTURAL-71 (기반 마련, 미완)** — Phase 2-Y 가 남긴 "덱을 들여다본
  뒤 섞지 않는다". 이제 **섞을 수 있는 조작이 생겼다.** 남은 것은 "효과가
  끝난 뒤 자동으로 부른다" 는 규칙이고, 그것은 효과 해결의 마무리 단계가
  필요하다. 이번에 자동으로 붙이지 않았다 — 언제 섞는가는 규칙이지
  구현자의 재량이 아니다.
- **STRUCTURAL-73 (신규 · 🟠)** — "무작위로 1장 고른다" 를 **효과가
  선언할 수 없다.** `RandomSource.choose` 는 있지만 그것을 쓰는
  `Operation` 이 없다 — 지금의 선택 계층(`ChoiceSpec`)은 "누가 고른다" 를
  전제하고, 무작위 선택은 고르는 사람이 없다. 실제 카드 142장이
  `Group:RandomSelect` 를 쓴다.
- **STRUCTURAL-74 (신규 · 🟡)** — "덱을 섞었을 때" 시점이 없어 셔플이
  `UNIMPLEMENTED` 사건으로 남는다. 유희왕에 그런 트리거가 실제로 있는지
  공식 자료에서 확인하지 못했으므로 **이름을 지어내지 않았다.**
- **STRUCTURAL-75 (신규 · 🟡)** — 패 셔플(`Duel.ShuffleHand`, 442장)을
  옮기지 않았다. 패는 칸 없는 존이라 `reorder` 는 되지만, "패를 섞는다" 가
  규칙상 무엇을 뜻하는지(상대에게 보이는 정보가 바뀌는가)를 확인하지
  못했다.
- STRUCTURAL-70 · 72 및 10 · 41 · 47 ~ 68 — **하나도 건드리지 않았다**
  (§14 "unrelated TODO 해결 금지").

---

## 13. BLOCKER / STRUCTURAL / DETAIL / COSMETIC

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 1 신규 | 73 (무작위 선택을 효과가 선언할 수 없다) |
| 🟡 DETAIL | 2 신규 | 74 (셔플 시점 이름 없음) · 75 (패 셔플 미구현) |
| 🟢 COSMETIC | 0 | |

---

## 14. 다음 Phase 진행 가능 여부 (§15-13)

가능하다. BLOCKER 가 없고 전체 회귀가 통과한다.

두 원칙이 지켜졌는지 다시 본다.

> **랜덤이어도 재현 가능해야 한다** — 같은 seed · 같은 입력이면 결과도
> 판도 기록도 사건 번호도 같다. 갈린 지점은 `draw` 번호로 지목된다.
>
> **게임의 랜덤과 AI 의 랜덤은 다른 계층이다** — `RandomPurpose` 에
> `AI_*` 가 없고, AI 는 이번에 한 줄도 만들지 않았다.
