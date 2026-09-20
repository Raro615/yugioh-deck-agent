# Phase 2-N — Target Selection Core

기준 커밋: `c646067` (Phase 2-M blocker fix)

```
TargetSpec (규칙)
    ↓  TargetResolver.candidates()    지금 고를 수 있는 것들
CandidateSet  (eligible · undecided · unchecked)
    ↓  TargetResolver.validate()      고른 것이 적법한가
TargetValidation  (LEGAL · ILLEGAL · UNKNOWN)
    ↓  EffectExecutor._check_target() 계획 단계에서
GameState 변경 (LEGAL 일 때만)
```

---

## 1. 작업 전 검수 — 절반은 이미 있었다

| 이미 있던 것 | 상태 |
|---|---|
| `TargetSpec` · `TargetRequirement` · `TargetRef` · `TargetBinding` · `TargetSelection` | **완성** (Phase 2-D-1). 대상 지정 ≠ 고르기 구분까지 |
| `CandidateSource` (자리 · 주인 · 조건) · `ChoiceSpec` (최소 · 최대 · 고르는 사람) | **완성** (Phase 2-C) |
| `CandidateSet` — `eligible` / `undecided` / `reasons` | **완성**. 세 갈래가 이미 있었다 |
| `CandidateResolver` — 관측에서 후보 찾기, 결정론적 정렬 | **완성** |
| `SelectionValidator` | 비용 쪽 선택 검사 (Phase 2-C) |
| **고른 대상이 규칙에 맞는지 실행기가 보는가** | **없었다** |

마지막 줄이 이번 단계의 이유다. 실행기는 `context.selection_for(ref)` 를
읽어 **그 카드가 판에 있는지만** 확인하고 그대로 실행했다. 자리도 주인도
조건도 보지 않았으므로, "자신 필드의 몬스터 1장" 이라고 적어 둔 효과가
상대의 묘지 카드를 제외할 수 있었다.

---

## 2. 새 파일 하나 — `engine/effect/targeting.py`

두 질문을 **나눈다** (§7).

| | 답하는 질문 |
|---|---|
| `TargetResolver.candidates` | **무엇을 고를 수 있는가** |
| `TargetResolver.availability` | **고를 것이 충분히 있는가** |
| `TargetResolver.validate` | **고른 것이 적법한가** |

고르는 일은 여기서 하지 않는다. AI 가 무엇을 **선호하는가**는 이 계층의
질문이 아니다 — 테스트가 `def choose` · `score` · `policy` · `random` 이
없음을 확인한다.

후보 찾기는 `CandidateResolver` 를 **그대로 쓴다.** 후보를 세는 코드를 두
벌 만들지 않는다 (테스트가 AST 로 확인한다).

---

## 3. 세 갈래

```python
class TargetLegality(str, Enum):
    LEGAL / ILLEGAL / UNKNOWN
    permits_selection  # LEGAL 일 때만 참
```

| 상황 | 판정 |
|---|---|
| 후보에 들어 있다 | `LEGAL` |
| 자리 · 주인 · 조건이 맞지 않는다 | `ILLEGAL` (`CANDIDATE_NOT_ELIGIBLE`) |
| 조건이 카드 정의를 요구하는데 **뒷면**이다 | `UNKNOWN` (`INFORMATION_UNAVAILABLE`) |
| 관측에 **아예 없다** | `UNKNOWN` (`HIDDEN_CARD`) |

여럿을 합칠 때 **`ILLEGAL` 이 `UNKNOWN` 을 이긴다** — 확실한 위반이 하나라도
있으면 나머지를 몰라도 위반이다 (검증 계층이 `FALSE` 를 먼저 보는 것과 같은
규율).

`permits_selection` 은 `LEGAL` 일 때만 참이고, `TargetVerdict` 와
`TargetValidation` 의 `__bool__` 은 예외를 던진다.

---

## 4. 없는 카드는 `ILLEGAL` 이 아니다

관측에 없는 카드를 고르면 **`UNKNOWN`** 이다. "이 듀얼에 없다" 고 단정하는
것 자체가 정보이기 때문이다 — 검증을 반복하는 것만으로 상대의 패를 탐지할
수 있으면 안 된다 (`ActionValidator` 가 처음부터 지켜 온 규칙).

그래서 실행기에 `ResolutionStatus.UNCHECKED_TARGET` 이 생겼다.
`INVALID_TARGET`(**확실히 틀린** 대상)과 합치지 않는다.

---

## 5. STRUCTURAL-15 — 절반 해결

`CandidateResolver` 는 가려진 존을 **조용히 건너뛰었다.** 상대의 패를
후보원으로 삼으면 후보 0장이 나오고, 그것이 "후보가 없다" 로 읽혔다.

`CandidateSet.unchecked` 를 더했다 — 못 들여다본 자리를 **장수만** 적는다
(가려진 존의 카드는 지목할 수조차 없으므로 `InstanceId` 로 적을 수 없다).
`fully_checked` 가 거짓이면 "후보가 없다" 고 말할 수 없다.

- `TargetResolver.availability` 가 이것을 **읽는다**: 확실한 후보가 모자라도
  못 본 곳이 있으면 `UNKNOWN` 이다.
- 비용 쪽(`CostValidator._judge_candidates`)은 **아직 읽지 않는다.** 데이터는
  더 이상 사라지지 않지만 그쪽의 판정은 그대로다 → STRUCTURAL-15 는
  **절반만** 닫혔다. 비용은 이번 단계의 주제가 아니다.

---

## 6. 장수 (§8)

`ChoiceSpec` 의 `minimum` / `maximum` 을 그대로 쓴다. 새 개념을 만들지
않았다.

| | |
|---|---|
| 정확히 1장 | `minimum == maximum == 1` |
| 최대 N장 | `minimum=1, maximum=N` |
| 고르지 않아도 됨 | `minimum=0` (`is_optional`) |
| 같은 카드 두 번 | `allow_duplicates` 가 거짓이면 `DUPLICATE_SELECTION` |

**장수는 가려진 정보와 무관하다.** 몇 장을 골랐는가는 고른 쪽이 아는
사실이므로, 모자라거나 넘치면 `UNKNOWN` 이 아니라 확실한 위반이다.

`None`(아직 고르지 않음)과 빈 선택은 다른 사실이지만, 대상을 요구하는
규칙에서는 둘 다 최소 장수를 못 채운다.

---

## 7. 실행 연결 (§10)

`EffectExecutor._plan_card_operation` 안, **선택을 읽은 직후**다.

```
선택 읽기 → _check_target() → 출발 자리(2-M) → 파괴 관문(2-M) → 적용
```

`ILLEGAL` → `INVALID_TARGET`, `UNKNOWN` → `UNCHECKED_TARGET`. 둘 다 계획
단계라 **판에 손대기 전**이고, 하나라도 걸리면 효과 전체가 멈춘다 (앞의
드로우도 일어나지 않는다).

---

## 8. 의미 계층과의 독립 (§14)

`targeting.py` 에 `DESTROY` 도 `SEND_TO_GRAVE` 도 `DISCARD` 도
`OperationKind` 도 **쓰이지 않는다** (테스트가 AST 로 확인한다). 같은 대상
규칙이 파괴에도 보내기에도 쓰인다 — 테스트가 그 둘을 같은 `TargetSpec` 으로
실행해 보인다.

`chain.py` 와 `trigger.py` 는 `engine.effect.targeting` 을 가져오지 않는다.
체인은 무엇을 언제만 정하고, 대상 선택은 실행기가 쓴다.

---

## 9. 관측 경계 (§6)

`TargetResolver` 는 `GameStateView` 만 받는다 — `GameState` 를 넘기면
거부한다. 상대의 패는 관측에 실리지 않아 후보가 될 수 없고, 대신
`unchecked` 에 장수만 남는다. 판정 결과(`to_dict()`)에 상대의 가려진
`card_id` 가 새지 않음을 테스트가 확인한다.

**정체는 가려도 자리는 보인다** — 상대의 세트 카드는 지목할 수 있고, 조건이
정체를 묻지 않으면 `LEGAL` 이다. 그래야 공격도 파괴도 표현된다.

---

## 10. 결정론 (§13)

`CandidateResolver` 의 정렬 `(컨트롤러, 존 순서, sequence, instance_id)` 을
그대로 쓴다. 같은 규칙을 다섯 번 물어도 같은 답이고, 복제본도 같다.
무작위 선택은 만들지 않았다.

---

## 11. 구현하지 않은 것

§17 이 금지한 것 전부. 특히:

- AI 의 대상 선호 · 탐색
- 전체 OCG 대상 규칙 (대상 내성 · 대상 변경 · 동시 대상 지정)
- 모든 카드 속성 필터
- 무작위 선택 · 대상 대체
- 연속 효과 · 대체 효과 · 전투 대상 · 데미지 스텝

---

## 12. 기존 테스트 8건 수정 (§18 의 정직성 요구)

전부 **대상 검증이 없어서 통과하던 것**이다.

| 수 | 무엇 | 왜 |
|---|---|---|
| 2 | 후보 명세가 "1장" 인데 2~3장을 골라 옮기던 헬퍼 | 명세를 실제와 맞췄다 (`maximum` 명시). 정의가 말하지 않은 장수를 실행하던 쪽이 틀렸다 |
| 1 | 상대 몬스터를 `owner=CONTROLLER` 규칙으로 파괴하던 fixture | `owner=None` 으로 고쳤다. 테스트가 확인하던 "주인의 묘지로 간다" 는 그대로다 |
| 5 | 없는 카드를 고르면 `INVALID_TARGET`/`CANDIDATE_NOT_FOUND` 를 기대 | `UNCHECKED_TARGET`/`HIDDEN_CARD` 로 고쳤다. **판이 안 바뀐다는 단언은 그대로이고 오히려 늘었다** (`applied == ()`, `deltas == ()`) |

삭제한 테스트는 없다. 약화한 단언도 없다.

---

## 13. 새로 발견된 것

- **🟠 STRUCTURAL-50** — 대상 하나가 걸리면 효과 **전체**가 멈춘다. 실제
  규칙에서는 "대상 중 적법한 것만 처리" 하는 경우가 있지만, 그 부분 적용
  규칙을 아직 옮기지 못했으므로 안전한 쪽으로 통째로 멈춘다
  (STRUCTURAL-49 와 같은 뿌리).
- **🟠 STRUCTURAL-51** — 대상 지정(`TARGETING`)과 단순 고르기(`CHOOSING`)를
  `TargetSpec` 이 구분하지만, 검증은 **둘을 같게 다룬다.** 대상 지정만
  받는 무효화·회피 규칙이 생기면 그때 갈라져야 한다.
- **STRUCTURAL-15 절반 해결** (위 §5).

---

## 14. 앞으로 만들면 좋은 것

1. **비용 쪽이 `unchecked` 를 읽게 하기** — STRUCTURAL-15 의 남은 절반.
2. **부분 적용** — 적법한 대상만 처리하는 규칙 (STRUCTURAL-49 · -50).
3. **대상 지정과 고르기의 규칙 차이** (STRUCTURAL-51).
4. 카드 속성 필터를 조건 계층에서 늘리기 — 대상 규칙은 그것을 그대로 쓴다.
