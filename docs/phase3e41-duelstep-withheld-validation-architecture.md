# Phase 3-E-41 — `DuelStep` / `WithheldAction` validation information 경계 감사

> **AUDIT-ONLY.** production 을 한 줄도 고치지 않았다 (§19 에서 `git diff` 로 확인).
> 목적은 "`DuelStep` 에 `ValidationCode` 를 추가하는 것" 이 아니라, 그 경계에서
> **무엇이 사라지며 그것이 결함인지 의도된 경계인지 확정하는 것** 이었다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-E-41 — DuelStep / WithheldAction validation information architecture |
| 성격 | **AUDIT-ONLY** (production diff = 0) |
| Base | Phase 3-E-40 (`5b9f15b`) |
| 작업 시작 시 실제 HEAD | `69ad7ff` — "Phase 3-E-40 보고서: commit SHA · push 결과 기록" |
| HEAD 가 3-E-40 을 포함하는가 | ○ `git merge-base --is-ancestor 5b9f15b HEAD` = yes |
| `docs/phase3e40-validation-code-unknown-policy.md` | ○ 존재 (42,348 bytes) |
| `tests/test_validation_code_unknown_policy.py` | ○ 존재 (33 tests) |
| working tree | clean (reset · checkout 하지 않았다) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 결과 commit | `<<SHA1>>` — `Phase 3-E-41: audit DuelStep and WithheldAction validation architecture` |
| push | <<PUSH>> |

---

## 2. BLOCKER

**없음.** 그리고 프롬프트가 든 전제 둘을 **측정으로 바로잡는다.**

### 바로잡는 것 ① — `DuelStep` 은 `code` 를 **보존한다**

> "하지만 DuelStep에는 validation 정보가 충분히 전달되지 않는다."

절반만 맞다. `DuelStep` 의 필드는 **다섯**이고 그중 하나가 `code: ValidationCode`
이며 **선택이 아니다** (기본값이 없다). 걸음을 만드는 production 자리 **17곳
전부**가 코드를 넘긴다 (`test_05`). 잃는 것은 `validity` · `missing_rule` ·
`notes` 셋이다.

### 바로잡는 것 ② — `DuelStep` 에 없는 칸들

§5 는 `status` · `viewer` · `validation` · `state_hash` · `future` 를 확인하라고
했다. **다섯 모두 없다.** `ValidationResult` 에도 `status` 는 없다 (상태는 계층마다
따로 산다: `ActivationStatus` · `ResolutionStatus` · `PaymentStatus` …).
`test_01` · `test_03` 이 이것을 고정한다.

---

## 3. Phase 3-E-40 요약 (이 Phase 가 받은 것)

3-E-40 의 결론은 **뒤집지 않는다.** 그리고 이 Phase 의 답은 그 Phase 의 결과에
**직접 의존한다.**

| 3-E-40 이 만든 것 | 이 Phase 에서의 의미 |
| --- | --- |
| `engine.validation.CODE_VALIDITY` — 48개 전수 분류 | **`DuelStep.code` 에서 `validity` 를 되찾는 함수가 되었다** |
| 47개는 `ActionValidity` 확정, 1개는 `None` | 복원 가능 47 / 불가 1 (`CHAIN_DEFINITION_UNAVAILABLE`) |
| `_UNKNOWN_CODES` 사본 제거 | 같은 사실의 사본을 늘리지 않는 것이 이 저장소의 방향임이 확정됐다 |
| 새 enum 0 · behavior 변화 0 | 이 Phase 도 같은 기준을 적용한다 |

**이것이 이 Phase 의 결론을 거의 혼자 정한다** — §8 · §11 을 보라.

---

## 4. `DuelStep` 구조

```python
@dataclass(frozen=True, slots=True)
class DuelStep:
    """행위 하나를 적용한 결과. **불변**이다."""
    action: PlayerAction
    accepted: bool
    code: ValidationCode
    reason: str
    result: "DuelResult | None" = None
```

| Field | Type | 생성 위치 | 입력 source | 의미 | Validation 정보? |
| --- | --- | --- | --- | --- | --- |
| `action` | `PlayerAction` | `engine/duel.py` ×17 | 호출자가 준 수 | 무엇을 하려 했나 | ✕ |
| `accepted` | `bool` | 〃 | 분기마다 리터럴 | 일어났나 | **△ validity 를 2값으로 압축** |
| `code` | `ValidationCode` | 〃 | 리터럴 5 + 동적 5 (§7) | **왜** | **○ 보존** |
| `reason` | `str` | 〃 | 리터럴 또는 `verdict.reason` | 사람이 읽을 설명 | ○ 보존 (문자열) |
| `result` | `DuelResult \| None` | 〃 | `self._check_end()` | 이 걸음으로 끝났나 | ✕ (승패) |

**생성 자리가 전부 `engine/duel.py` 안이다** — 다른 모듈은 걸음을 만들지 않는다
(`test_05`). 즉 이 경계의 계약을 지키는 책임이 **한 파일에 모여 있다.**

---

## 5. `WithheldAction` 구조

```python
@dataclass(frozen=True, slots=True)
class WithheldAction:
    kind: PlayerActionKind
    reason: str
    missing: str | None = None
```

| Field | Type | 생성 위치 | 입력 source | 의미 | Validation 정보? |
| --- | --- | --- | --- | --- | --- |
| `kind` | `PlayerActionKind` | `duel.py:620,633,654` | 리터럴 | 어떤 **종류**가 막혔나 | ✕ |
| `reason` | `str` | 〃 | 손글씨 / `plan.verdict.reason` / `verdict.reason` | 사람이 읽을 설명 | ○ (문자열) |
| `missing` | `str \| None` | 〃 | 손글씨 / `plan.unresolved_rules` / `verdict.missing_rule` | 무엇이 없어서 | △ (자리마다 출처가 다르다) |

**3-E-40 의 "code 가 없다" 를 실제 HEAD 에서 다시 확인했다** — 없다. 그리고
**`action` 자체도 없다**: 들고 있는 것은 수가 아니라 **종류**다 (`test_02`).
이것이 §13 의 숨은 정보 invariant 를 자료형이 **구조적으로** 지키는 방식이다 —
어느 카드인지 적을 칸이 애초에 없다 (`test_26`).

### F-3 — 세 자리가 `missing` 을 서로 다른 출처에서 채운다

| 자리 | 행위 | `ValidationResult` 가 있는가 | `missing` 의 출처 |
| --- | --- | --- | --- |
| `duel.py:620` | `PASS` | **없다** (흐름 계층의 사실) | 손으로 쓴 문자열 |
| `duel.py:633` | `END_PHASE` | 있다 (`plan.verdict`) | **`plan.unresolved_rules`** — verdict 의 것이 아니다 |
| `duel.py:654` | `ACTIVATE_CARD` | 있다 (`validator.validate`) | `verdict.missing_rule` |

고치지 않고 적어 둔다 (`test_09`). 같은 칸에 자리마다 다른 종류의 값이 들어간다는
사실 자체가 이 경계의 계약이 느슨하다는 증거다.

---

## 6. `ValidationResult` 구조 (비교의 기준점)

```
validity: ActionValidity        VALID | INVALID | UNKNOWN
code: ValidationCode            48개 중 하나 (3-E-40 이 전수 분류)
reason: str                     사람이 읽을 설명
missing_rule: str | None        UNKNOWN 일 때 무엇이 없어서
notes: tuple[str, ...]          부수 관찰 — 판정을 바꾸지 않는다
```

`status` 는 **없다** (`test_03`).

---

## 7. 정보 흐름

```
PlayerAction
   │
   ├─ 흐름 행위(PASS · END_PHASE)   → TurnProgressor / PriorityState 가 판정
   └─ 판 행위 · 발동               → ActionValidator / _activation_gate 가 판정
   │
   ▼
ValidationResult(validity, code, reason, missing_rule, notes)
   │
   ├────────────── 허가 안 됨 ──────────────┐
   │                                        │
   ▼ 허가됨                                  ▼
LegalActions.allowed                   LegalActions.withheld
   │                                        │  **종류별 1건** · code 없음
   ▼                                        └──→ **production 소비자 0곳**
Duel.apply
   │  ★ 여기서 validity → accepted(bool) 로 압축, missing_rule·notes 탈락
   ▼
DuelStep(action, accepted, code, reason, result)
   │
   ├──→ agent/simulation.py   step.code in _UNKNOWN_CODES  ← **유일한 code 소비자**
   └──→ agent/runner.py       TranscriptEntry(… accepted, reason …)  ← code 탈락
                                   │
                                   ▼
                        Transcript.canonical_state()
                        = 받아들여진 걸음의 (자리, 행위) + 결과
                          **이유도 코드도 보지 않는다**
```

`DuelStep.code` 의 출처는 **열 자리**다 (거절 분기, 3-E-39 가 측정하고 이번에
재확인). 리터럴 다섯 + 동적 다섯(`last.code` · `progressed.verdict.code` ·
`executed.code` · `gate.code` · `activated.code`).

---

## 8. `ValidationResult` → `DuelStep`

### 필수 표 1 (전반)

분류: **PRESERVED** 그대로 / **TRANSFORMED** 모양이 바뀜 / **DROPPED** 사라짐 /
**DERIVED** 저장되지 않지만 되찾을 수 있음.

| ValidationResult 정보 | DuelStep | 분류 | 실제 변환 |
| --- | --- | --- | --- |
| `validity` | 필드 없음 | **DERIVED** | `accepted`(2값)로 압축되지만 **`CODE_VALIDITY[step.code]` 로 복원된다** (48개 중 47개) |
| `status` | 애초에 없음 | — | `ValidationResult` 에 `status` 가 없다 |
| `code` | `code` | **PRESERVED** (+ 한 자리 **TRANSFORMED**) | 17개 생성 자리 전부가 넘긴다. 단 `duel.py:683` 은 **갈아 끼운다** → F-1 |
| `missing_rule` | 필드 없음 | **DROPPED** | 사람이 읽는 로드맵 문자열. 기계 소비자 0 |
| `notes` | 필드 없음 | **DROPPED** | 같음 |
| `reason` | `reason` | PRESERVED / 때때로 TRANSFORMED | 동적 자리는 `verdict.reason` 그대로, 리터럴 자리는 새로 쓴다 |

### 이 Phase 의 핵심 — `validity` 는 **이미 복원된다**

3-E-39 는 "`DuelStep` 이 `validity` 를 버린다" 를 **뿌리 원인**으로 지목했다.
그런데 Phase 3-E-40 이 `CODE_VALIDITY` 를 만든 뒤로는 **코드에서 판정을 되찾을 수
있다.**

```
48개 중 복원 가능 47  ·  불가 1 (CHAIN_DEFINITION_UNAVAILABLE — 3-E-40 이 일부러 None)
```

그리고 **실제 듀얼에서 `accepted` 와 policy 가 어긋난 걸음이 0건**이다 —
32판 · 11,609 걸음에서 `accepted=True` 는 **전부** `OK`(= `VALID`)였고
`accepted=False` 가 `VALID` 인 경우는 없었다 (`test_11`).

즉 **3-E-39 가 찾은 손실은 앞 Phase 가 `DuelStep` 을 건드리지 않고 이미 닫았다.**
여기에 `validity` 필드를 더하면 "어느 코드가 어느 판정인가" 를 적는 자리가 **둘**이
되고, 그 둘이 어긋날 수 있다 — **어긋나는 것이 3-E-39 가 찾은 문제였다**
(`test_32`).

### F-1 — 한 자리는 코드를 **갈아 끼운다** (실행으로 확인)

```
가려진 카드를 가리키는 normal_summon 을 apply 에 직접 주면

  ActionValidator → UNKNOWN · HIDDEN_CARD
                    "#9999 가 관측에 보이지 않습니다. 이 듀얼에 없는지
                     가려진 존에 있는지 구분할 수 없습니다."
  DuelStep        → accepted=False · RULE_NOT_IMPLEMENTED
                    "normal_summon 는 지금 허가된 행위가 아닙니다."
```

**이유가 바뀌었다** (`duel.py:683`, `test_12`). 두 코드가 모두 policy 상
`UNKNOWN` 이므로 **판정은 살아남지만** "가려져서 모른다" 가 "엔진이 못 한다" 로
읽힌다.

이것이 결함인가 — **진단으로서는 충분하고, 그 자리는 production 경로에서 닿지
않는다.** `Simulator.simulate` 와 `DuelRunner._judge` 가 후보 여부를 **먼저**
보므로, 이 분기는 **부르는 쪽의 잘못**을 알리는 자리다. 그래서 §21 의 변경 조건을
만족하지 않는다. **기록만 한다.**

---

## 9. `ValidationResult` → `WithheldAction`

### 필수 표 1 (후반)

| ValidationResult 정보 | WithheldAction | 분류 | 실제 변환 |
| --- | --- | --- | --- |
| `validity` | 필드 없음 | **DROPPED** | 복원 불가 — 코드가 없으므로 policy 를 쓸 수 없다 |
| `status` | 애초에 없음 | — | — |
| `code` | **필드 없음** | **DROPPED** | 복원 불가. 단 **읽는 쪽이 0곳** (§14) |
| `missing_rule` | `missing` | PRESERVED / TRANSFORMED | 자리마다 출처가 다르다 (F-3) |
| `notes` | 필드 없음 | DROPPED | — |
| `reason` | `reason` | PRESERVED | 그대로 복사 (`test_14` 가 동일성을 확인) |
| (행위 자체) | `kind` 만 | **TRANSFORMED** | 수 → 종류. **의도된 압축** (§15) |

### 계약을 읽는다 — `withheld` 는 **로드맵 채널**이다

`LegalActions` 의 설명이 직접 적는다.

> ``allowed`` 만 보고 고르면 된다. ``withheld`` 는 읽는 쪽이 **"엔진이 무엇을
> 아직 못 하는가"** 를 알아야 할 때 본다.

그리고 `WithheldAction` 의 설명도:

> 빈 목록은 "할 것이 없다" 로 읽힌다. 적어 두면 **"아직"** 으로 읽힌다.

**확실한 거부는 "아직" 이 아니다.** 조건이 거짓인 카드는 "엔진이 못 하는 것" 이
아니라 **규칙이 안 된다고 한 것**이고, 그것은 합법 행위 목록에 없는 것으로 이미
충분히 표현된다 (소환할 수 없는 몬스터가 목록에 없는 것과 같다). 즉
`CANDIDATE_NOT_ELIGIBLE` 을 `withheld` 에 적지 않는 것은 **계약 위반이 아니라
계약 그대로**다.

### F-2 — 그런데 **잘못 읽힐 수 있다** (실행으로 확인)

덱을 1장으로 만들어 욕망의 항아리의 조건("자신 DECK 에 2장 이상")을 확실히 거짓으로
만들면:

| 무엇 | 값 |
| --- | --- |
| `_activation_gate` 판정 | `INVALID` · **`CANDIDATE_NOT_ELIGIBLE`** · "발동 조건이 거짓입니다: 자신 DECK 에 2장 이상" |
| `legal_actions().allowed` 의 발동 후보 | **0건** |
| `legal_actions().withheld` | `ACTIVATE_CARD` **한 건**, 이유는 "…판정할 규칙 계층이 **아직 없습니다**", `missing='activation-timing (Phase 2-C/2-F)'` |

소비자가 보는 유일한 기록이 **다른 행위 종류(`ACTIVATE_CARD` vs
`ACTIVATE_EFFECT`)의 다른 이유**다. 게이트의 판정은 `WithheldAction` 으로도
`DuelStep` 으로도 **남지 않는다** — `_activation_actions` 가 `continue` 로
넘어간다 (`test_15`).

그리고 `_withheld_board_actions` 는 패의 **첫 장에서 `break`** 한다 — 주석이
"같은 이유가 패의 카드마다 반복되므로" 라고 적지만 그 전제가 늘 참은 아니다
(`test_16`). 측정한 판에서는 다섯 장이 전부 같은 판정이었으므로 이 판에서는
전제가 지켜졌다.

**이것이 §20 의 다섯 기준을 통과하는가** — §11 에서 답한다.

---

## 10. M1 / M2 / M3

### 필수 표 2

| Case | ValidationResult | DuelStep | WithheldAction | 정보 손실 |
| --- | --- | --- | --- | --- |
| **M1** 조건 거짓 | `INVALID` · `CANDIDATE_NOT_ELIGIBLE` · "발동 조건이 거짓입니다…" (실측) | **도달 0** — 후보가 아니므로 `apply` 가 불리지 않는다 | **기록 없음** — `continue` 로 넘어간다 | code · validity 가 **어디에도** 남지 않는다. 대신 `ACTIVATE_CARD` 의 "아직" 기록이 보인다 |
| **M2** 출처 금지 | `_fail` 쪽에서 `EXECUTION_FORBIDDEN` | **도달 0** | **기록 없음** | `activatable_effects` 가 후보 생성 **전에** 걸러서 경계에 오지도 않는다 (`test_17`) |
| **M3** 사건 무반응 | `INVALID` · `RULE_NOT_IMPLEMENTED` (dormant) | **도달 0** | **도달 0** | 파이프라인 자체가 dormant (`test_18`) |

세 경우 모두 **경계에서 잃는 것이 아니라 경계에 도달하지 않는다.** 이것이
"information loss" 와 "unreachable" 의 차이이고, 섞으면 잘못된 수정을 하게 된다.

---

## 11. 정보 손실 분류 (§20 의 다섯 기준)

각 손실을 다섯 기준으로 채점했다.

| 손실 | ① 소비자가 필요? | ② 재구성 불가? | ③ 다른 칸으로 복원? | ④ 누출 위험? | ⑤ 계약이 요구? | 판정 |
| --- | :--: | :--: | :--: | :--: | :--: | --- |
| `DuelStep` 의 `validity` | ✕ (읽는 쪽 없음) | ✕ | **○ `CODE_VALIDITY`** | ✕ | ✕ | **손실 아님 (DERIVED)** |
| `DuelStep` 의 `missing_rule` | ✕ | ✕ (검증기 재질의) | △ | ✕ | ✕ | 손실이나 **문제 아님** |
| `DuelStep` 의 `notes` | ✕ | ✕ | △ | ✕ | ✕ | 같음 |
| `WithheldAction` 의 `code` | **✕ (소비자 0곳)** | ○ | ✕ | **○** | **✕ (계약이 "아직" 채널로 정의)** | **의도된 경계** |
| M1·M2 게이트 판정 미기록 | ✕ | ✕ (게이트 재질의) | ○ | ○ | ✕ | **의도된 경계** + 읽기 혼동(F-2) |
| 코드 갈아 끼우기 (F-1) | ✕ | — | — | ✕ | ✕ | **정밀도 결함** — 기록만 |

**①이 전부 ✕ 인 것이 결론을 정한다.** 측정 결과:

- `LegalActions.withheld` 를 읽는 production 자리 = **0곳** (`test_20`)
- `DuelStep.code` 를 읽는 production 자리 = **`agent/simulation.py` 하나** (`test_21`)
- `DuelStep` / `WithheldAction` 을 import 하는 정책 = **없다** (`test_25`)

②에 대해: 게이트와 검증기는 **판만 읽는 순수 함수**이고, `legal_actions` 와
`apply` 가 **같은 함수로 같은 판**을 본다 (STRUCTURAL-134). 그래서 같은
`GameState` 에서 **다시 물으면 같은 판정이 나온다** — 재구성이 가능하다.

---

## 12. public / internal boundary

| 정보 | 어디에 속하나 | 근거 |
| --- | --- | --- |
| `action` · `accepted` · `result` | **public game history** | `TranscriptEntry` 가 보존하고 `canonical_state()` 가 읽는다 |
| `reason` | public **설명** (판정이 아니다) | 사람이 읽는 문자열. 기계 분기에 쓰이지 않는다 |
| `code` | **internal diagnostic** | 읽는 자리 하나뿐이고 그마저 "모름인가" 한 비트만 쓴다 |
| `missing_rule` · `notes` | **roadmap / debug** | "무엇이 아직 없는가" 추적용 |
| `withheld` 전체 | **roadmap 채널** | 계약이 "엔진이 무엇을 **아직** 못 하는가" 로 정의 |

**거절은 역사가 아니다.** `DuelRunner.run` 은 거절이 나오면 **멈추고**,
`Transcript.refusals` 의 설명이 그것을 "듀얼의 사실이 아니라 **정책의 결함**"
이라고 적는다 (`test_23`). 그래서 정상적인 기록에는 거절된 걸음이 **없고**
(코퍼스 32판에서 0건), 거절 코드를 역사에 보존해야 한다는 요구가 **계약에서
나오지 않는다.**

---

## 13. replay / serialization

| 질문 (§17) | 답 |
| --- | --- |
| 1. 필드 추가가 backward compatibility 에 영향을 주는가 | **대상이 없다.** `DuelStep` · `WithheldAction` · `LegalActions` · `TranscriptEntry` · `DecisionRecord` 에 `to_dict` · `from_dict` · `to_json` 이 **하나도 없다** (`test_24`) |
| 2. `None`/기본값으로 안전하게 추가할 수 있는가 | 기술적으로는 가능하다 (frozen dataclass + 기본값). 그러나 1번이 비어 있으므로 "추가해도 안전하다" 가 추가할 **이유**가 되지 않는다 |
| 3. 기존 replay 를 읽을 수 있는가 | **저장된 replay 가 없다.** 재현은 **같은 seed 로 다시 돌리는 것**이다 |
| 4. validation 정보가 replay 에 필요한가 | **아니다.** `Transcript.canonical_state()` 가 재현 동일성의 정의이고, 그것은 **받아들여진 걸음의 (자리, 행위) + 결과**만 본다 — 이유도 코드도 보지 않는다 (`test_22`) |
| 5. validation 정보가 replay 의 authoritative game state 가 되는가 | **아니다.** `state_hash` 는 `GameState.canonical_state()` 에서만 나오고 `DuelStep` 은 `GameState` 밖에 있다 |

`app/` 전체에서 `json.dumps` 는 **한 자리**이고 그것은 카드 검색 결과다 — 듀얼
기록이 아니다.

---

## 14. AI / Search 영향

### 필수 표 3 — Consumer 영향

| Consumer | `DuelStep` 사용 | `WithheldAction` 사용 | validation field 의존 | 변경 영향 |
| --- | :--: | :--: | --- | --- |
| Duel history (`TranscriptEntry`) | ○ (`accepted` · `reason`) | ✕ | **code 안 읽음** | 없음 |
| Replay (`canonical_state`) | △ (`accepted` 만) | ✕ | 없음 | 없음 |
| `Simulator` | ○ | ✕ | **`code` → `_UNKNOWN_CODES` (한 비트)** | 없음 |
| `SearchPolicy` | ✕ (import 조차 안 한다) | ✕ | 없음 | 없음 |
| `Evaluation` | ✕ | ✕ | 없음 | 없음 |
| `RuleBasedPolicy` | ✕ | ✕ | 없음 | 없음 |
| `RandomPolicy` · `FirstLegalPolicy` | ✕ | ✕ | 없음 | 없음 |
| `Arena` (`DecisionRecord`) | △ (`accepted` 경유) | ✕ | 없음 | 없음 |

AI 경계는 건드리지 않았다 — `GameStateView` · `legal_actions()` 의 의미 ·
`Policy` · `SearchPolicy` · `Evaluation` · `Simulation` · `clone` · RNG 격리 모두
diff 0 이다.

---

## 15. hidden information 영향

**§13 의 invariant: "Validation information preservation must not become a
hidden-information leak."** 이것이 보존 쪽에 **반대로 작용하는** 유일한 기준이고,
결론에 실제로 영향을 줬다.

- `WithheldAction` 은 **`kind` 만** 적는다 — `source` · `action` · `instance_id`
  칸이 **없다** (`test_26`). 후보별로 코드를 남기려면 **어느 카드인지**를 가리켜야
  하고, 그러면 `HIDDEN_CARD` 처럼 **가려진 것을 가리키는** 판정에서 식별자가 함께
  새어 나갈 길이 열린다.
- 실측: `ActionValidator` 가 `HIDDEN_CARD` 를 낸 자리의 설명이
  "#9999 가 관측에 보이지 않습니다 — **이 듀얼에 없는지 가려진 존에 있는지 구분할
  수 없습니다**" 다. 즉 그 코드는 **"모른다" 를 말하기 위한** 코드이고, 그것에
  식별자를 붙여 공개 목록에 싣는 것은 경계를 넓히는 일이다.
- `_withheld_board_actions` 는 `state.player(seat).hand` 만 돈다 — 상대 패를 보지
  않는다 (`test_27`).

**그래서 "보존" 의 방향은 공짜가 아니다.** 안전한 경계가 보존보다 우선이라는
원칙에 따라, 후보별 코드 기록은 **설계 문제로 남긴다.**

---

## 16. state_hash / RNG 영향

| 측정 | 결과 |
| --- | --- |
| `legal_actions()` 를 양쪽 자리에서 읽은 뒤 `state_hash` | **불변** (`test_28`) |
| 같은 뒤 RNG `draws` | **불변** |
| 거절된 `apply` 뒤 `state_hash` · RNG | **불변** (`test_13`) |
| `clone()` 한 사본을 바꾼 뒤 원본 | **불변** (`test_28`) |
| `DuelStep` 이 `state_hash` 에 들어가는가 | **아니다** — 해시는 `GameState.canonical_state()` 만 본다 |

validation metadata 는 game state 가 아니다. 이 Phase 는 그것을 바꾸지 않았고,
설령 보존을 늘린다 해도 **해시에 들어가게 하면 즉시 구조적 문제**다.

---

## 17. provenance

**§18 이 묻던 것을 찾았다 — 그리고 이번에는 `provenance available` 이다.**

| 대상 | 최초 commit | 날짜 | 태어난 모양 |
| --- | --- | --- | --- |
| `DuelStep` | **`0088cc6` "Phase 2-AO: 듀얼 한 판 — ENGINE V1 FREEZE"** | 2026-09-30 | **지금과 똑같은 다섯 칸** (`code` 포함) |
| `WithheldAction` | 같은 commit | 2026-09-30 | **지금과 똑같은 세 칸** |
| `LegalActions.withheld` | 같은 commit | 2026-09-30 | 같음 |

즉 두 자료형은 **ENGINE V1 FREEZE 그 자체에서 태어났고 그 뒤로 모양이 바뀌지
않았다.** 그리고 그 커밋의 메시지가 **의도를 직접 적는다.**

> 허가가 나지 않은 것은 내놓지 않는다
>
> `legal_actions()` 는 VALID 만 담는다. UNKNOWN 은 허가가 아니므로 후보가
> 아니다. 그래서 고를 수 있는 것은 일반 소환과 페이즈 넘기기뿐이고, 마법
> 발동은 **이유와 함께** withheld 에 남는다 (activation-timing, 100회 관측).

**"이유와 함께"** — 처음부터 `withheld` 는 **이유(문자열) 채널**로 설계되었다.
코드를 넣지 않은 것은 빠뜨린 것이 아니라 **그 자리의 설계**다. 3-E-39 · 3-E-40 이
`provenance unavailable` 로 남긴 것과 **반대 결과**다.

---

## 18. BEFORE / AFTER

AUDIT-ONLY 이므로 **BEFORE = AFTER** 가 기대값이고, 그대로였다.

| 항목 | BEFORE | AFTER | 변화 |
| --- | --- | --- | --- |
| `DuelStep` 필드 | 5 | 5 | — |
| `WithheldAction` 필드 | 3 | 3 | — |
| `LegalActions` 필드 | 3 | 3 | — |
| `ValidationResult` 필드 | 5 | 5 | — |
| `ValidationCode` / `ActionValidity` / `SimulationStatus` | 48 / 3 / 5 | 48 / 3 / 5 | — |
| `unknown_codes()` | 7 | 7 | — |
| 코퍼스 32판 결과 | `completed` ×32 · refusal 0 | 같음 | — |
| 코퍼스 `DuelStep` 쌍 | `{True\|OK: 11609}` | 같음 | — |
| `accepted` ↔ policy 어긋남 | **0** | **0** | — |
| `state_hash` · RNG | 불변 | 불변 | — |
| production diff | — | **0** | — |
| 테스트 수 | 3940 | **3972** | +32 (새 파일) |

---

## 19. 테스트

### 새 파일

`tests/test_duelstep_withheld_validation_audit.py` — **32개** (요구 최소 25개).
§24 의 1~28 항목을 덮는다.

| §24 항목 | 테스트 |
| --- | --- |
| 1 `DuelStep` 인벤토리 | `test_01` |
| 2 `WithheldAction` 인벤토리 | `test_02` |
| 3 `ValidationResult` 인벤토리 | `test_03` |
| (`LegalActions`) | `test_04` |
| 17 `code` 보존 | `test_05` |
| (핵심) `validity` 가 DERIVED | **`test_06`** |
| 18 · 19 `missing_rule` · `notes` | `test_07` |
| 15 `accepted` 의미 | `test_08` |
| (F-3) 세 자리의 `missing` | `test_09` |
| 4 VALID 전달 | `test_10` · `test_11` |
| 5 INVALID 전달 · 10 `HIDDEN_CARD` | **`test_12`** (F-1) |
| 24 `state_hash` 불변 (거절) | `test_13` |
| 6 UNKNOWN 전달 | `test_14` |
| 7 `CANDIDATE_NOT_ELIGIBLE` · 12 M1 trace | **`test_15`** (F-2) |
| (F-2 후반) | `test_16` |
| 8 `EXECUTION_FORBIDDEN` · 13 M2 trace | `test_17` |
| 14 M3 trace | `test_18` |
| 11 `PRIORITY_STATE_STALE` | `test_19` |
| 22 AI consumer · (withheld 소비자) | `test_20` · `test_21` · `test_25` |
| 20 replay 영향 | `test_22` · `test_23` |
| 21 serialization 영향 | `test_24` |
| 23 hidden info 경계 | `test_26` · `test_27` |
| 24 · 25 · 26 `state_hash` · RNG · clone | `test_28` |
| 16 status 의미 · (어휘 불변) | `test_29` · `test_30` |
| (AUDIT-ONLY 확인) | `test_31` |
| (Q1 · Q16 의 근거) | `test_32` |
| 28 기존 regression | 아래 |

### 기존 테스트 수정

**0건.** 삭제 0 · skip 추가 0 · assertion 약화 0 · 기존 파일 한 줄도 건드리지
않았다. (production diff 가 0 이므로 기존 사실이 하나도 바뀌지 않았다.)

### Full regression

```
$ python -m pytest -q -p no:randomly
3972 passed, 4 skipped in 467.07s (0:07:47)
```

| 항목 | Phase 3-E-40 종료 시 | 이번 Phase 종료 시 |
| --- | --- | --- |
| passed | 3940 | **3972** (+32) |
| failed | 0 | **0** |
| skipped | 4 | **4** |
| production diff | — | **0** |

---

## 20. 82 최종 질문

**Q1. `DuelStep` 은 `validity` 를 보존해야 하는가?**
**아니다.** `CODE_VALIDITY[step.code]` 로 **이미 복원된다** (48개 중 47개). 필드를
더하면 같은 사실의 둘째 사본이 생기고, 그것이 3-E-39 가 찾은 문제의 모양이다.

**Q2. `DuelStep` 은 `ValidationCode` 를 보존해야 하는가?**
**이미 보존한다.** 필수 필드이고 17개 생성 자리 전부가 넘긴다.

**Q3. `missing_rule` 을 보존해야 하는가?** **아니다.** 기계 소비자 0, 같은 판에서
검증기에 다시 물으면 나온다.

**Q4. `notes` 를 보존해야 하는가?** **아니다.** 같은 이유. 그리고 `notes` 는
"판정을 바꾸지 않는 부수 관찰" 로 정의되어 있다.

**Q5. `WithheldAction` 은 `ValidationCode` 를 보존해야 하는가?**
**지금은 아니다.** 읽는 쪽이 **0곳**이고, 그 자료형의 계약이 "엔진이 무엇을
**아직** 못 하는가" 이며, 코드를 후보별로 남기려면 **식별자**가 따라붙어 숨은
정보 경계를 건드린다 (§15).

**Q6. `accepted=False` 만으로 rejection semantic 을 복원할 수 있는가?**
**아니다 — 그리고 그래서 `code` 가 함께 있다.** `accepted` 는 2값이고
`ActionValidity` 는 3값이므로 압축이 일어난다. 그러나 `DuelStep` 은 코드를 함께
들고 있으므로 **그 둘을 같이 보면** 복원된다. `WithheldAction` 쪽은 복원되지 않는다.

**Q7. M1 은 `DuelStep` 에서 구분 가능한가?** **그 경계에 도달하지 않는다.**
후보가 아니므로 `apply` 가 불리지 않는다.

**Q8. M2 는?** 같다 — `activatable_effects` 가 후보 생성 **전에** 걸러낸다.

**Q9. M3 는 production 에서 reachable 한가?** **아니다** (dormant, `test_18`).

**Q10. Validation 정보가 public history 에 필요한가?**
**아니다.** 거절은 역사가 아니라 **정책의 결함**으로 다뤄지고 판을 멈춘다.
재현 동일성은 **받아들여진 행위**만 본다.

**Q11. validation metadata 가 hidden information 을 누출할 수 있는가?**
**그렇다 — 후보별로 남기려 하면.** `HIDDEN_CARD` 는 "가려져서 모른다" 를 말하는
코드이고, 그것을 후보별 기록으로 남기려면 가려진 대상의 식별자를 가리켜야 한다.
현재 자료형은 `kind` 만 적어 **구조적으로** 막고 있다.

**Q12. replay 가 validation code 를 필요로 하는가?** **아니다.** 저장되는 replay
형식이 **없고**, 재현 동일성 함수가 코드를 보지 않는다.

**Q13. AI/Search 가 validation code 를 필요로 하는가?**
**한 비트만.** `Simulator` 가 "모름인가" 를 묻고, 그 답은 3-E-40 의 policy 에서
온다. 정책들은 `DuelStep` 을 import 조차 하지 않는다.

**Q14. 현재 정보 손실은 실제 architecture bug 인가?**
**아니다.** §11 의 다섯 기준에서 ①(소비자 필요)이 전부 ✕ 이고, ②(재구성 불가)도
✕ 다. 대신 **정밀도 결함 둘**(F-1 · F-2)과 **계약 느슨함 하나**(F-3)를 찾았고 전부
기록했다.

**Q15. 현재 구조 유지가 가능한가?** **그렇다.**

**Q16. production 변경이 필요하다면 최소 변경은 무엇인가?**
지금은 필요하지 않다. 만약 **후보별 거절 이유를 노출해야 하는 소비자**가 생긴다면
최소 변경은 "`WithheldAction` 에 `code` 추가" 가 아니라 다음 순서다.
① 그 소비자의 요구를 적는다 → ② 식별자를 싣지 않고 코드만 실을 수 있는지 본다 →
③ `_activation_actions` 가 **종류별 1건** 규칙을 유지하면서 발동 거절을 적을 수
있는지 본다. **§22 의 다음 Phase 로 넘긴다.**

**Q17. 공통 `ValidationDiagnostic` 객체가 필요한가?**
**아니다.** §23 의 조건을 만족하지 못한다 — `ValidationResult` 와 의미가 겹치고,
두 자료형이 **같은 의미를 공유하지 않는다** (`DuelStep` 은 "일어난 일",
`WithheldAction` 은 "아직 못 하는 일"). 단순 wrapper 가 된다.

**Q18. 새 enum 이 필요한가?** **아니다.**

**Q19. `state_hash` 에 영향을 주는가?** **아니다** (diff 0, 실측 불변).

**Q20. RNG 에 영향을 주는가?** **아니다.**

**Q21. Engine V1 freeze 를 깨는가?** **아니다 — 그리고 이것이 핵심이다.** 두
자료형은 **freeze 커밋에서 태어났고** 그 모양이 곧 V1 의 공개 경계다 (§17).
여기에 필드를 더하는 것은 freeze 를 여는 일이다.

**Q22. 별도 architecture phase 가 필요한가?**
**지금은 아니다.** 필요해지는 조건을 Q16 에 적었다. 그 조건이 생기기 전에 구조를
열면, 아무도 읽지 않는 정보를 위해 V1 경계를 넓히는 일이 된다.

---

## 21. Final Decision

**A. AUDIT_ONLY_SUFFICIENT**

현재 `DuelStep` / `WithheldAction` 구조는 **의도된 정보 경계**이며 production
변경이 필요하지 않다.

근거 넷:

1. **`DuelStep` 은 이미 충분하다.** `code` 를 보존하고, `validity` 는 Phase 3-E-40
   의 policy 로 **복원된다** (47/48). 실제 듀얼 11,609 걸음에서 `accepted` 와
   policy 가 어긋난 적이 **0건**이다.
2. **`WithheldAction` 의 `code` 를 필요로 하는 쪽이 없다.** `withheld` 를 읽는
   production 자리가 **0곳**이고, 계약이 그것을 "엔진이 **아직** 못 하는 것" 의
   채널로 정의한다 — 확실한 거부는 거기 속하지 않는다.
3. **provenance 가 의도를 증언한다.** 두 자료형은 **ENGINE V1 FREEZE 커밋**에서
   지금 모양으로 태어났고, 그 커밋이 "마법 발동은 **이유와 함께** withheld 에
   남는다" 고 적는다. 빠뜨린 것이 아니라 설계다.
4. **보존 쪽에 역방향 비용이 있다.** 후보별 코드를 남기려면 식별자를 실어야 하고,
   그것은 `HIDDEN_CARD` 가 다루는 바로 그 경계를 건드린다. 안전한 경계가 보존보다
   우선이다.

§21 의 변경 허용 조건 일곱 중 **첫 두 개가 충족되지 않는다** (실제 손실 ·
소비자/계약의 요구). 그래서 AUDIT-ONLY 로 끝낸다.

### 기록한 결함 셋 (고치지 않았다)

| ID | 내용 | 성격 | 지금 해가 있는가 |
| --- | --- | --- | --- |
| **F-1** | `duel.py:683` 이 코드를 갈아 끼운다 (`HIDDEN_CARD` → `RULE_NOT_IMPLEMENTED`) | 정밀도 | 없다 — production 경로가 닿지 않고, 두 코드가 같은 판정이다 |
| **F-2** | 발동 후보별 게이트 판정이 어디에도 기록되지 않고, 보류 훑기가 첫 장에서 멈춘다 | 읽기 혼동 | 없다 — 읽는 쪽이 0곳 |
| **F-3** | 세 `WithheldAction` 자리가 `missing` 을 다른 출처에서 채운다 | 계약 느슨함 | 없다 |

### 다른 판정을 고르지 않은 까닭

- **B (MINIMAL_VALIDATION_PROPAGATION)** — "실제 정보 손실이 존재" 해야 한다.
  `validity` 는 복원되고, `code` 는 이미 있고, 나머지는 읽는 쪽이 없다.
- **C (VALIDATION_DIAGNOSTIC_OBJECT)** — 두 자료형이 **같은 의미를 공유하지
  않는다**. 공통 객체는 §23 의 조건을 못 넘고 wrapper 가 된다.
- **D (PUBLIC_BOUNDARY_GAP)** — 공개 경계가 "지나치게" 압축한다고 하려면 압축된
  정보를 공개 쪽이 필요로 해야 한다. 역사는 **받아들여진 일**만 적고, 거절은
  정책 결함으로 판을 멈춘다 — 설계가 일관된다.
- **E (HIDDEN_INFORMATION_RISK)** — 누출 위험은 **실재하고 §15 에 적었다.**
  그러나 E 는 "정보를 보존하려면 위험하다 → 별도 설계로 넘긴다" 는 판정이고,
  그 전제는 "보존해야 한다" 다. 이 Phase 의 측정은 **보존할 이유가 아직
  없다**는 쪽이므로 A 가 더 정확하다. 위험은 Q16 의 조건부 설계 지침으로 남겼다.
- **F (BLOCKER)** — 막힌 것이 없다. 자료형 · 생성 자리 · 소비자 · 역사 ·
  직렬화 · provenance · 코퍼스까지 전부 repository 안에서 측정했다.

---

## 22. 다음 Phase

**하나만 제안한다.**

> **Phase 3-E-42 — `SimulationResult` → `SearchCandidate` 정보 보존**
> (§35 의 후보 3번)

까닭 — §15 가 "이번 Phase 에서 `SimulationResult` 를 섞지 말라" 고 했고 섞지
않았다. 그런데 **그 경계는 이 Phase 가 조사한 경계와 성질이 다르다.**

| | `ValidationResult → DuelStep` (이 Phase) | `SimulationResult → SearchCandidate` |
| --- | --- | --- |
| 경계의 성격 | **ENGINE V1 FREEZE 의 공개 경계** | `agent/` 내부 — freeze 밖 |
| provenance | 의도가 커밋에 적혀 있다 | 3-E-39 가 조사하지 않았다 |
| 잃는 것 | `validity`(복원됨) · roadmap 문자열 | **`code` 자체** (복원 불가) |
| 읽는 쪽 | 0곳 / 1곳 | 흔적을 읽는 **사람** (오래 사는 `SearchDecision`) |
| 숨은 정보 위험 | 있다 (식별자) | 낮다 (코드만) |

즉 "같은 종류의 손실" 로 보였던 둘이 **다른 경계**다. 엔진 쪽은 freeze 가
지키는 공개 계약이고, 에이전트 쪽은 **열려 있고** 그 흔적을 사람이 읽는다.
3-E-39 §11 이 "`code` 가 `SearchCandidate` 에서 사라진다" 를 측정했고 "읽는
consumer 가 0곳" 이라고 적었지만, **흔적을 읽는 사람**이라는 소비자는 세지
않았다. 그 경계를 같은 다섯 기준(§20)으로 재는 것이 다음 일이다.

**이번 Phase 에서 그것을 하지 않았다.** 그리고 F-1 · F-2 · F-3 을 근거로 다른
구조를 연쇄 수정하지 않았다 (§35 의 마지막 금지). 다음 Phase 의 범위와 금지
사항은 사용자가 정한다.
