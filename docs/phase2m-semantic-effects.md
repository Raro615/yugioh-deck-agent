# Phase 2-M — Semantic Effect Layer

기준 커밋: `176e3a5` (Phase 2-L)

```
DESTROY        파괴한다          ─┐
SEND_TO_GRAVE  묘지로 보낸다      ├─ 전부 묘지로 간다
DISCARD        버린다            ─┘
MOVE           그냥 옮긴다 (2-L, 의미 없음)
        ↓  EffectExecutor
GameState 변경  +  ZoneMoved(movement=…, reason_names=…)
        ↓
EffectResult.unchecked_rules   ← 무엇을 **보지 않았는가**
```

---

## 1. 작업 전 검수 — 의미와 이동은 이미 나뉘어 있었다

| 이미 있던 것 | 상태 |
|---|---|
| `OperationKind` 의 의미 어휘 (`DESTROY` · `SEND_TO_GRAVE` · `DISCARD` · `RELEASE` · `BANISH` · `RETURN_*`) | **완성** |
| `REASON_NAMES` — 의미마다 다른 `REASON_*` | **완성** |
| `ZoneMoved.movement` · `AppliedOperation.kind` | **완성** — Delta 가 이미 의미를 들고 다닌다 |
| `SEND_TO_GRAVE` · `DISCARD` 실행 | **완성** (Phase 2-D-2) |
| `DISCARD` 의 "패에서만" 확인 | 실행기 안에 박혀 있었다 |
| `DESTROY` 실행 | **없었다** — `SUPPORTED` 에서 빠져 있었다 |
| "보지 않은 규칙" 을 말하는 자리 | **없었다** |

즉 ADR-002 의 구분은 데이터 모델에 **이미** 있었다. 없던 것은 둘이다.

1. 파괴가 아예 실행되지 않았다.
2. 의미를 수행하면서 **그 의미의 규칙을 얼마나 보았는지** 말할 곳이 없었다.

이번 단계는 그 둘만 채웠다. 새 Operation 어휘도, 새 Delta 도, 새 reason
체계도 만들지 않았다.

---

## 2. 새 파일 하나 — `engine/effect/semantics.py`

판을 바꾸지 않는다. `GameState` 를 가져오지도 않는다. 실행기가 참고하는
**표**다.

| | 무엇을 말하는가 |
|---|---|
| `SEMANTIC_KINDS` | 어떤 일이 **의미를 주장하는가** (셋) |
| `ORIGIN_RULES` | 그 의미가 **어디서 출발할 수 있는가** |
| `UNCHECKED_SEMANTIC_RULES` | 그 의미의 규칙 중 **아직 보지 않은 것** |

`RELEASE` · `BANISH` · `RETURN_*` 은 표에 **넣지 않았다.** 넣으면 "그 규칙을
봤다" 는 뜻이 되고, 이번 단계의 범위가 아니다.

---

## 3. DESTROY — 판정을 받아야만 실행된다

> **정정 (blocker fix, 커밋 `7cfd17f` 이후).**
> 처음 쓴 2-M 은 "파괴를 실행하되 보지 않은 규칙을 적어 둔다" 였다. 그것이
> STRUCTURAL-47 이었고, **적어 두는 것은 막는 것이 아니다** — 내성을
> 판정할 수 없는데 파괴하면 내성을 가진 카드가 실제로 파괴된다. 아래가
> 고친 뒤의 사실이다.

파괴는 **판정을 받아야만** 수행된다 (`RULE_GATED`). 판정기는
`DestructionRuling` 이고, 기본값은 아무것도 판정하지 못하는
`UnknownDestructionRuling` 이다.

| 판정 | 결과 |
|---|---|
| `UNKNOWN` (기본값) | `UNCHECKED_RULES` — **판이 그대로다.** `unchecked_rules` 는 결과에 그대로 남는다 |
| `FALSE` | `INVALID_TARGET` + `CANDIDATE_NOT_ELIGIBLE` — 판정했고 안 된다 |
| `TRUE` | 수행한다. 기록은 끝까지 **파괴**이고, `unchecked_rules` 는 여전히 실린다 |

```python
# 판정기를 받았을 때만
result.applied[0].kind        # OperationKind.DESTROY
result.deltas[0].reason_names # ("DESTROY", "EFFECT")
result.unchecked_rules        # 다섯 줄 — 성공해도 규칙 전체를 본 것은 아니다
```

**출발 자리**: 파괴는 필드에서만 다룬다. 필드 밖의 카드를 파괴하라고 하면
`UNSUPPORTED_OPERATION` + `missing="off-field destruction"` 이다 —
"안 된다" 가 아니라 **"이 엔진이 모른다"** 이다.

---

## 4. SEND_TO_GRAVE — 파괴와 끝까지 다르다

같은 칸에서 같은 묘지로 가도 같은 사건이 아니다.

| | `kind` | `reason_names` | `unchecked_rules` |
|---|---|---|---|
| 파괴 | `DESTROY` | `("DESTROY", "EFFECT")` | 5줄 |
| 묘지로 보내기 | `SEND_TO_GRAVE` | `("EFFECT",)` | 3줄 |
| 버리기 | `DISCARD` | `("DISCARD", "EFFECT")` | 4줄 |
| 그냥 이동 | `MOVE` | `()` | **없음** |

`MOVE` 의 빈 목록은 "전부 봤다" 가 아니다 — **주장한 의미가 없다**는 뜻이다.

**출발 자리를 적지 않았다.** 보내기는 패 · 덱 · 필드 어디서든 일어나고,
이 엔진은 막아야 할 자리를 모른다. 모르는 것을 빈 제약으로 적으면 "전부
허용" 이 규칙인 것처럼 보이므로 아예 적지 않았다 (`origin_rule(SEND) is None`).

---

## 5. DISCARD — "안 된다" 와 "모른다" 를 나눈다

버리기는 패에서만 일어난다. 이것은 **규칙을 아는 경우**다.

```python
ORIGIN_RULES[DISCARD] = OriginRule(zones={HAND}, known=True,  …)
ORIGIN_RULES[DESTROY] = OriginRule(zones=FIELD, known=False, missing=…)
```

`known` 이 갈림길이다.

- 참 → 어긋나면 `INVALID_TARGET` + `SOURCE_WRONG_ZONE`. **확실히 틀렸다.**
- 거짓 → 어긋나면 `UNSUPPORTED_OPERATION` + `missing`. **아직 안 옮겼다.**

둘을 합치면 "규칙상 불가능" 과 "미구현" 이 한 덩어리가 된다. `OriginRule`
은 `known=False` 인데 `missing` 이 없으면 **만들어지지 않는다.**

---

## 6. `MOVE` 와의 경계 (Phase 2-L 그대로)

| | |
|---|---|
| `MoveOperation` | 목적지만 말한다. `reason_names == ()` |
| `CardOperation` | 무슨 일인지 말한다. 목적지는 의미가 정한다 |

`LibraryEntry` 는 여전히 `executable=True` 인 정의에 `MOVE` 가 들어 있으면
**거부한다.** 파괴를 실행할 수 있게 되었다고 `MoveOperation(GRAVE, …)` 를
파괴라고 부를 수 있게 된 것이 아니다.

---

## 7. `ZoneMoved` 에 `reason` 필드를 더하지 않은 이유

§8 이 `ZoneMoved(movement=MOVE, reason=DESTROY)` 같은 구조를 제안했는데,
현재 모델은 이미 **한 필드로** 그것을 하고 있다:
`ZoneMoved(movement=DESTROY)` 이고 `reason_names` 는 그 `movement` 에서
파생된다.

두 번째 필드를 더하면 `movement` 와 `reason` 이 **서로 다른 말을 할 수
있게 된다** (`movement=SEND, reason=DESTROY`). 한 사실을 두 곳에 적으면
언젠가 둘이 갈린다. 그래서 Delta 는 손대지 않았다.

---

## 8. Event / Trigger 경계

2-J 의 통로를 그대로 쓴다. 새 `EventKind` 도 새 Delta 도 EventBus 도 만들지
않았다.

```python
TimingEvent.from_delta(result.deltas[0]).operation   # OperationKind.DESTROY
```

기존 `TriggerSpec(operations=frozenset({DESTROY}))` 가 **그대로** 파괴만
걸러 낸다 — 보내기에는 반응하지 않는다 (테스트로 확인). 자동 체인 삽입도
SEGOC 도 하지 않는다.

---

## 9. 실패 안전성

| 실패 | 결과 |
|---|---|
| 판에 없는 카드 | `INVALID_TARGET` + `CANDIDATE_NOT_FOUND` |
| 패 밖의 카드를 버리기 | `INVALID_TARGET` + `SOURCE_WRONG_ZONE` |
| 필드 밖의 카드를 파괴 | `UNSUPPORTED_OPERATION` + `missing` |
| 출처 금지 | `FORBIDDEN` |
| 구현 없음 | `NOT_IMPLEMENTED` |
| 뒤의 일이 실패 | 앞의 파괴도 **일어나지 않는다** |

전부 `state_hash()` 불변. `EffectResult` 는 **아무 일도 하지 않았는데
`unchecked_rules` 가 있으면 거부한다** — 무엇을 보지 않았는가는 무엇을
했는가에서 나온다.

---

## 10. 실제 카드가 아니라 synthetic 인 이유 (§13)

파괴 · 보내기 · 버리기는 **전부 대상 선택이 필요하다.** 그 계층이 아직
없으므로 실제 카드로는 이 경로를 시험할 수 없다. 그래서 이번 단계의
테스트는 `provenance=hand_written` 인 **synthetic 정의**를 쓴다.

효과 목록(`library.py`)은 **늘리지 않았다.** 실제 카드를 억지로 넣으려면
대상 규칙을 추측해야 하고, 그것이 이 프로젝트가 처음부터 하지 않기로 한
일이다. 블랙홀은 여전히 실행 불가로 남아 있다 — 파괴가 실행 가능해졌지만
"필드의 몬스터 **전부**" 를 `TargetSpec` 이 담지 못한다 (STRUCTURAL-10).

---

## 11. 기존 테스트 8개를 고쳤다 (§22)

파괴를 실행할 수 있게 만든 것의 직접적인 결과다.

| 무엇 | 왜 |
|---|---|
| 6개 — "지원하지 않는 일" 의 **표본**이 `CardOperation.destroy` 였다 | 표본을 `UnimplementedOperation("특수 소환")` 으로 바꿨다. 그 테스트들이 지키는 사실("실행기가 못 하는 일은 조용히 성공하지 않는다")은 **그대로**이고, 같은 파일이 이미 쓰던 표본이다 |
| `test_destroy_is_unsupported_not_silently_a_trip_to_the_graveyard` | 이름과 내용을 새 사실로 다시 고정했다. 단언이 **늘었다** — 실행되고, 파괴로 기록되고, 보내기가 아니고, 미확인 규칙을 들고 나온다 |
| `test_destroy_is_still_not_executable` (2-L) | 같은 이유. "묘지로 가는 `MOVE` 는 여전히 파괴가 아니다" 로 다시 고정했다 |

**약화한 단언은 없다.** 삭제한 테스트도 없다.

---

## 12. 구현하지 않은 것

§14 가 금지한 것 전부. 특히:

- 파괴 내성 · 대체 효과 · "파괴되었을 때" 유발 · 동시 파괴
- 보내기 · 버리기를 막는 효과, 그 유발
- 무작위 버리기 · 손패 전체 선택
- `RELEASE` · `BANISH` · `RETURN_*` 의 의미 규칙
- 대상 선택 계층 · 전역 Event ID · 롤백 · 자동 체인 · SEGOC

---

## 13. 새로 발견된 것

- **🟠 STRUCTURAL-46** — `unchecked_rules` 는 **결과에만** 실린다.
  `EventJournal` 에 적히는 사건에는 들어가지 않아서, 나중에 기록만 보고
  "이 파괴가 규칙을 얼마나 본 것인가" 를 되짚을 수 없다. 기록 구조를
  넓히는 것은 이번 단계의 범위가 아니라 남긴다.
- **🔴 STRUCTURAL-47 → BLOCKER, 수정됨** — 파괴가 내성 판정 없이 실행되던
  문제. 판정을 받아야만 실행되도록 고쳤다 (위 §3). 남은 것은
  STRUCTURAL-48 · -49 다.
- **🟠 STRUCTURAL-48** — `SEND_TO_GRAVE` 와 `DISCARD` 는 아직 관문이 없다.
  둘도 판정되지 않은 규칙을 안고 실행된다 (Phase 2-D-2 부터의 상태).
  **알면서 남겨 둔 것이지 괜찮다고 판단한 것이 아니다.**
- **🟠 STRUCTURAL-49** — 한 장이라도 판정받지 못하면 효과 **전체**가
  멈춘다. 실제 규칙에서는 내성을 가진 한 장만 남고 나머지는 파괴되지만,
  그 부분 적용 규칙을 아직 옮기지 못했으므로 안전한 쪽으로 통째로 멈춘다.
- Phase 2-L 의 STRUCTURAL-45(`MOVE` 사건에 아무도 반응할 수 없다) 그대로.

---

## 14. 앞으로 만들면 좋은 것

1. **파괴 내성 · 대체 효과** — `DestructionRuling` 의 실제 구현.
   그것이 생기기 전까지 파괴는 손으로 선언한 판정으로만 일어난다.
2. **대상 선택 계층** — 실제 카드로 이 경로를 시험할 수 있게 된다.
3. `unchecked_rules` 를 `EventJournal` 까지 (STRUCTURAL-46).
4. `RELEASE` · `BANISH` · `RETURN_*` 의 의미 표 — 같은 모양으로 늘린다.
