# Phase 3-E-42 — `SimulationResult` → `SearchCandidate` 정보 보존 감사

> **AUDIT-ONLY.** production 을 한 줄도 고치지 않았다 (§19 에서 `git diff` 로 확인).
> 목적은 "`SimulationResult` 에 `SearchCandidate` 필드를 넣는 것" 이 아니라,
> **두 객체 사이의 정보 변환이 실제 architecture contract 와 일치하는지 증명하는 것**
> 이었다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-E-42 — SimulationResult → SearchCandidate information preservation |
| 성격 | **AUDIT-ONLY** (production diff = 0) |
| Base | Phase 3-E-41 (`0d0ab3c`) |
| 작업 시작 시 실제 HEAD | `1184764` — "Phase 3-E-41 보고서: commit SHA · push 결과 기록" |
| HEAD 가 3-E-41 을 포함하는가 | ○ `git merge-base --is-ancestor 0d0ab3c HEAD` = yes |
| `docs/phase3e41-...-architecture.md` | ○ 존재 (35,820 bytes) |
| `tests/test_duelstep_withheld_validation_audit.py` | ○ 존재 (32 tests) |
| working tree | clean (reset · checkout 하지 않았다) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 결과 commit | `dfd08a6` — `Phase 3-E-42: audit SimulationResult to SearchCandidate information boundary` |
| push | 완료 — `origin/claude/pensive-goodall-te1egy` (`1184764..dfd08a6`) |

---

## 2. BLOCKER

**없음.** 그리고 프롬프트의 전제 둘을 **측정으로 바로잡는다.**

### 바로잡는 것 ① — `ordering_key` 는 **필드가 아니라 메서드**다

> "반면 SearchCandidate는: value / ordering_key / state_hash 등 탐색/랭킹용 정보를 가진다."

`SearchCandidate` 의 필드는 **넷**이다: `action` · `status` · `value` · `reason`.
`ordering_key` 는 `value` 와 `action` 으로 **계산하는 메서드**이고 저장되지 않는다.
`comparable` 도 property 다 (`test_02`).

### 바로잡는 것 ② — `state_hash` 는 **후보의 칸이 아니다**

§5 · §10 은 `SearchCandidate.state_hash` 의 provenance 를 조사하라고 했다.
**후보에는 그 칸이 없다.** `state_hash` 는 `SearchDecision` 의 칸이고 (`test_03`),
값은 **결정 지점의 진짜 판** 해시다 — 시뮬레이션된 미래의 해시가 아니다
(`test_18`).

### 함께 바로잡는 것 — "score" 라는 칸은 어디에도 없다

점수를 담는 자료형은 `StateValue` 이고 (`terminal` · `heuristic` · `terms` ·
`excluded`), `score` 라는 이름의 필드는 `SimulationResult` · `SearchCandidate` ·
`SearchDecision` **어디에도 없다** (`test_04`). `agent/arena.py` 의
`DecisionRecord.score` 는 `(등급, 휴리스틱)` 로 요약한 **보고용 투영**이다.

---

## 3. Phase 3-E-41 요약 (이 Phase 가 받은 것)

3-E-41 의 결론은 뒤집지 않는다. 그리고 그 Phase 가 **넘긴 질문**이 이것이었다.

| 3-E-41 이 말한 것 | 이 Phase 가 받은 과제 |
| --- | --- |
| 엔진 쪽 경계는 **ENGINE V1 FREEZE 의 공개 계약** | 에이전트 쪽 경계는 freeze **밖**이다 |
| 잃는 `validity` 는 `code` 에서 **복원된다** | 여기서 잃는 `code` 는 **복원 불가**다 |
| 읽는 쪽이 0곳 / 1곳 | **흔적을 읽는 사람**이라는 소비자를 세지 않았다 |
| 숨은 정보 위험 있음 (식별자) | 여기서는 코드만이라 위험이 낮다 |
| provenance 가 의도를 증언 | 여기도 증언하는가? → **그렇다** (§17) |

---

## 4. `SimulationResult` 구조

```python
@dataclass(frozen=True, slots=True)
class SimulationResult:
    action: PlayerAction
    status: SimulationStatus
    viewer: int
    reason: str = ""
    code: "ValidationCode | None" = None
    future: "GameStateView | None" = None
```

| Field | Type | 생성 위치 | 생산 의미 | 소비 위치 | 후보로 전달 |
| --- | --- | --- | --- | --- | :--: |
| `action` | `PlayerAction` | `simulation.py` ×4 | 해 본 수 | 후보 생성 | **○** |
| `status` | `SimulationStatus` | 〃 | 어떻게 끝났나 | `search.py:311` 분기 · 후보 | **○** |
| `viewer` | `int` | 〃 | **누구의 눈**으로 본 미래인가 | **없다 — 읽는 자리 0곳** | ✕ |
| `reason` | `str` | 〃 | 사람이 읽을 설명 | 후보 | **○** |
| `code` | `ValidationCode \| None` | 〃 (2곳만 채운다) | 엔진이 말한 이유 | `simulation.py` 분류기 **하나** | ✕ |
| `future` | `GameStateView \| None` | SUPPORTED 한 자리만 | 그 수를 둔 뒤의 **관측** | 평가자 (`search.py:325`) | △ **소비됨** |

**없는 칸**: `score` · `value` · `notes` · `ordering_key` · `state_hash` — 다섯 모두
없다 (`test_01`).

구조적 보장 하나: `__post_init__` 이 **`SUPPORTED` ↔ `future` 유무**를 묶는다.
`SUPPORTED` 인데 관측이 없으면, 아닌데 관측이 있으면 **생성 자체가 실패한다**
(`test_30`). 즉 `future` 의 책임은 시뮬레이션 계층에 있다.

---

## 5. `SearchCandidate` 구조

```python
@dataclass(frozen=True, slots=True)
class SearchCandidate:
    action: PlayerAction
    status: "SimulationStatus | None"
    value: "StateValue | None" = None
    reason: str = ""

    @property
    def comparable(self) -> bool: ...
    def ordering_key(self) -> tuple: ...
```

| Field | Type | 생성 위치 | 의미 | `SimulationResult` source |
| --- | --- | --- | --- | --- |
| `action` | `PlayerAction` | `search.py` ×3 | 비교 중인 수 | **루프 변수** (`result.action` 이 아니다) |
| `status` | `SimulationStatus \| None` | 〃 | 어떻게 끝났나 · `None` = 해 보지 못함 | `result.status` 또는 `None` |
| `value` | `StateValue \| None` | 〃 | **점수**. 없으면 견줄 수 없다 | **평가자**가 `result.future` 를 읽어 만든다 |
| `reason` | `str` | 〃 | 설명 | `result.reason` 또는 `SKIPPED_BY_BUDGET` |

**없는 칸**: `code` · `viewer` · `future` · `score` · `state_hash` · `notes` ·
`ordering_key`(메서드다) (`test_02`).

---

## 6. `SearchDecision` 구조

```
seat · state_hash · turn_number · phase · candidates · chosen · reason
     · simulations = 0 · skipped = 0
```

후보와 **다른 것**을 표현한다 — 하나는 "비교 중인 수", 하나는 "한 결정 지점의
흔적" 이다. `state_hash` 가 여기 사는 까닭은 §11 에 있다.

---

## 7. 실제 call path

```
SearchPolicy.decide(view, legal)
   │  legal.allowed 를 canonical_state 로 정렬 (목록 순서에 기대지 않는다)
   ▼
_look_ahead
   │
   ├─(A) 예산 초과 ─────────→ SearchCandidate(action, status=None,
   │                                          reason=SKIPPED_BY_BUDGET)
   │                          ★ SimulationResult 가 **없다**
   │
   └─(B) simulate(action, viewer=legal.seat)
          │
          ▼  Simulator: _fork() → clone() → 진짜 Duel.apply → fork.view(viewer)
       SimulationResult(action, status, viewer, reason, code, future)
          │
          ├─(B1) status is not SUPPORTED ─→ SearchCandidate(action,
          │                                 status=result.status,
          │                                 reason=result.reason)
          │                                 ★ code · viewer · future 가 안 간다
          │
          └─(B2) SUPPORTED ──────────────→ SearchCandidate(action,
                                            status=result.status,
                                            value=evaluator.evaluate(result.future),
                                            reason=result.reason)
                                            ★ future 를 **소비**해 value 를 만든다
   ▼
min(candidates, key=ordering_key)
   │  키: value 유무 → 등급 → 휴리스틱 → canonical_state
   ▼
SearchDecision(seat, state_hash=simulator.state_hash(), …, candidates, chosen)
   │  ★ state_hash 는 **결정 전 진짜 판**의 해시다
   ▼
PlayerAction
```

**변환 자리는 셋**이고 전부 `_look_ahead` 안이며, 넘기는 인자가 서로 다르다
(`test_05`). (A) 가 가장 중요하다 — **시뮬레이션 결과 없이 만들어지는 후보**가
있다는 것이 "후보는 wrapper 가 아니다" 의 증거다.

---

## 8. field mapping

### 필수 표 1 — 전체 mapping

| SimulationResult 정보 | SearchCandidate | 분류 | 이유 | 보존 필요 |
| --- | --- | --- | --- | --- |
| `action` | `action` | **PRESERVED** | 같은 수. 다만 **루프 변수**를 넣는다 (요청한 수) | ○ (이미 됨) |
| `status` | `status` | **PRESERVED** | 그대로 복사. 단 후보는 `None` 도 가질 수 있다 (예산) | ○ (이미 됨) |
| `viewer` | 없음 | **DROPPED** | production 에서 **읽는 자리가 0곳** (`test_11`) | ✕ |
| `reason` | `reason` | **PRESERVED** | 그대로 복사 (`test_19` 가 동일성 확인) | ○ (이미 됨) |
| `code` | 없음 | **DROPPED** | 탐색 경로에서 읽는 자리가 **없다** (`test_10`) | ✕ (§13 · §21) |
| `future` | `value` 로 | **TRANSFORMED** | 평가자가 **읽고** 점수를 만든 뒤 사본과 함께 버린다 | ○ (이미 됨, 변환되어) |
| `score` | — | **NOT_APPLICABLE** | 그런 칸이 **없다** — 점수는 `StateValue` 다 | — |
| `value` | `value` | **DERIVED** | `SimulationResult` 에 없다. `Evaluator` 가 만든다 | — |
| `notes` | — | **NOT_APPLICABLE** | `StateValue.notes` 는 property 이고 `excluded` 에서 나온다 | — |
| `ordering_key` | 메서드 | **DERIVED** | `value` + `action` 으로 계산. 저장하지 않는다 | — |
| `state_hash` | 없음 (`SearchDecision` 에) | **NOT_APPLICABLE** | 결정 지점의 성질이다 (§11) | — |

**분류의 요지**: 진짜 DROPPED 는 **`code` 와 `viewer` 둘**이고, 나머지는 보존 ·
변환 · 파생 · 해당없음이다. 그리고 그 둘은 **production 에서 읽히지 않는다.**

---

## 9. score / value (§8 의 일곱 질문)

| # | 질문 | 답 |
| --- | --- | --- |
| 1 | `SimulationResult` 가 score 를 표현하는가 | **아니다.** 그런 칸이 없고, 모듈에 `evaluate` · `heuristic` 이라는 이름조차 없다 (`test_09`) |
| 2 | `SearchCandidate.value` 는 어디서 오는가 | `self.evaluator.evaluate(result.future)` — **평가자**다 |
| 3 | Evaluation 이 계산하는가 | **그렇다.** `StateEvaluator` 가 관측 하나를 LP 단위 값으로 바꾼다 |
| 4 | `SimulationResult` 가 계산하는가 | **아니다.** 시뮬레이터는 평가자를 **알지 못한다** |
| 5 | `SearchCandidate` 가 따로 계산하는가 | **아니다.** 받아서 들고만 있다 |
| 6 | score 와 value 가 같은 개념인가 | **아니다.** `value` 는 `(등급, 휴리스틱)` 를 가진 **구조**이고, "score" 는 `arena` 가 보고용으로 꺼낸 `(등급.value, 휴리스틱)` **튜플**이다 |
| 7 | 둘을 혼동할 가능성이 있는가 | **낮다.** `score` 라는 이름이 `DecisionRecord` 에만 있고, 그 docstring 이 "고른 후보의 `(등급, 휴리스틱)`" 이라고 적는다 |

**이름이 비슷하다는 이유로 같다고 판단하지 않았다** — 세 계층에서 각각 다른
자료형이고, `StateValue` 만이 비교 가능한 값이다.

---

## 10. `ordering_key`

```python
def ordering_key(self) -> tuple:
    if self.value is None:
        return (1, 0, 0, self.action.canonical_state())
    terminal, heuristic = self.value.ordering_key()
    return (0, -terminal, -heuristic, self.action.canonical_state())
```

| 조사 항목 | 결과 |
| --- | --- |
| 어디서 생성되는가 | `SearchCandidate` 의 **메서드**. 저장되지 않는다 |
| 무엇을 기준으로 정렬하나 | ① 점수 유무 ② 등급 ③ 휴리스틱 ④ `canonical_state` |
| `SimulationResult` 와 직접 연결되나 | **아니다** — `value` 와 `action` 만 읽는다 |
| `status` 를 포함하나 | **아니다** (`test_16` 이 식에 `status` 가 없음을 확인) |
| `UNKNOWN`/`REFUSED` 를 구별하나 | **아니다** — 둘 다 `value is None` 이므로 같은 키다 |
| `value=None` 처리 | 첫 칸이 `1` 이 되어 **점수 있는 후보 뒤로** 간다 |
| canonical tie-break | **있다** — 넷째 칸 (`test_26` 이 실제 동점에서 확인) |

**실측 랭킹** (MAIN1, seed 11, 후보 11개, 전부 SUPPORTED):

```
 0 -1 -3200  normal_summon #3    ← 고른 수
 0 -1 -3000  normal_summon #0    ┐ 동점 — canonical_state 로 깬다
 0 -1 -3000  normal_summon #2    ┘
 0 -1 -2500  normal_summon #4
 0 -1 -1300  set_monster #0 / #2 / #3 / #4   ← 넷 동점
 0 -1 -1100  set_spell_trap #1
 0 -1 -1000  end_phase
 0 -1  -600  activate_effect #1 55144522:e[0]
```

§9 가 요구한 재검증: **3-E-39 의 "UNKNOWN 과 REFUSED 가 같은 키" 는 사실이다**
(`test_15`). 그런데 그것이 bug 인지는 §13 에서 답한다.

---

## 11. `state_hash`

### 필수 표 3 — provenance

| Field | 최초 생성 계층 | 현재 생성 위치 | 원본 | 책임 계층 |
| --- | --- | --- | --- | --- |
| `value` | Evaluation | `search.py` 가 `evaluator.evaluate(result.future)` 호출 | 시뮬레이션된 **미래 관측** | Evaluation |
| `ordering_key` | Search | `SearchCandidate` 의 메서드 (계산) | `value` + `action` | Search |
| `state_hash` | Search | `SearchDecision(state_hash=self.simulator.state_hash())` | **결정 전 진짜 판** | Search (결정 단위) |
| `status` | Simulation | `Simulator.simulate` | `DuelStep.accepted` + `code` | Simulation |
| `code` | Engine | `DuelStep.code` | `ValidationResult` / 리터럴 | Engine |
| `future` | Simulation | `fork.view(viewer)` | **사본**의 관측 | Simulation |

§10 의 일곱 질문:

| # | 질문 | 답 |
| --- | --- | --- |
| 1 | `SimulationResult` 가 `state_hash` 를 갖는가 | **아니다** |
| 2 | 아니라면 어디서 생성되나 | `SearchDecision` 생성 시 `Simulator.state_hash()` |
| 3 | 시뮬레이션 **종료 후** 상태에서 생성되나 | **아니다** |
| 4 | **원본** `GameState` 의 해시인가 | **그렇다** — `self.duel.state.state_hash()` |
| 5 | **시뮬레이션된** 상태의 해시인가 | **아니다** (`test_18` 이 결정 전 해시와 같음을 확인) |
| 6 | 랭킹에서 쓰이나 | **아니다** — `ordering_key` 에 없다 |
| 7 | diagnostic 인가 | **그렇다** — "개발자가 AI 가 무엇을 내다봤는지 읽는 자리" |

**그러므로 "`state_hash` 가 `SimulationResult` 에 없다" 는 결함이 아니다.** 그것은
**결정 지점**을 가리키는 좌표이고, 한 결정의 열한 후보가 **같은 값을 공유**한다 —
후보마다 들면 같은 값이 열한 번 적힌다 (`test_12`).

그리고 안전하다: 64자 SHA-256 digest 이고, 그 docstring 이 "되돌려 읽을 수 없는
요약이므로 남겨도 가려진 정보가 새지 않는다" 고 적는다.

---

## 12. `SimulationStatus`

### 필수 표 2 — status 비교

| SimulationStatus | SimulationResult | SearchCandidate | ordering | ranking 영향 | 실제 의미 |
| --- | --- | --- | --- | --- | --- |
| `SUPPORTED` | `future` **필수** | `value` 가 붙는다 | `(0, -등급, -휴리스틱, …)` | **있다** (유일하게 평가된다) | 엔진이 적용했다 |
| `NOT_A_CANDIDATE` | `code=None` | 그대로 | `(1,0,0,…)` | 없음 | 지금 허가된 후보가 아니다 |
| `UNKNOWN` | `code ∈ unknown_codes()` | 그대로 | `(1,0,0,…)` | 없음 | 규칙이 아직 없다 |
| `REFUSED` | `code ∉ unknown_codes()` | 그대로 | `(1,0,0,…)` | 없음 | 규칙에 따라 거절했다 |
| `ERROR` | `code=None` | 그대로 | `(1,0,0,…)` | 없음 | 예외가 났다 |
| (`None`) | — | 예산 초과 | `(1,0,0,…)` | 없음 | **해 보지 못했다** |

`status` 는 후보로 **PRESERVED** 되지만, **읽는 자리가 표시용 하나다** —
`describe_ko` 뿐이고 `decide` 도 랭킹도 읽지 않는다 (`test_17`).

**Q20 의 답: Search ranking 은 `SimulationStatus` 에 의존하지 않는다.** 의존하는
것은 `value` 의 유무다.

---

## 13. UNKNOWN / REFUSED

**재측정 결과: UNREACHABLE IN CURRENT PRODUCTION.** 실제 듀얼에서 모든 후보를
시뮬레이션하면 `SUPPORTED` 만 나온다 (`test_14`) — 3-E-39 가 32판 · 5,316 호출로
측정한 것과 같다. **fake executor 를 만들지 않았다** (§23).

그래서 §12 의 비교는 **손으로 만든 후보**로만 했고, 그 사실을 테스트 docstring 에
명시했다 (`test_15`).

### 같은 키가 bug 가 아닌 까닭 — 태어날 때의 설계가 그렇게 적혀 있다

Phase 3-C 커밋이 직접 적는다.

> 모르는 것을 0 으로 바꾸지 않았다. … **UNKNOWN 으로 끝난 시뮬레이션의 후보는
> 점수가 아예 없다 — 0 점도 최저 점수도 아니고 견줄 수 없는 것이다.**

즉 "같은 키" 는 두 상태를 **혼동한 결과가 아니라**, "점수가 없다" 는 **하나의
사실**을 표현한 것이다. 순위 계층이 아는 것은 "견줄 수 있는가" 이고, **왜** 견줄
수 없는지는 `status` 에 그대로 남아 있다 (후보가 보존한다).

§21 의 다섯 기준으로 채점하면:

| 기준 | 답 |
| --- | --- |
| 1 후보 consumer 가 구분을 필요로 하나 | **아니다** — 랭킹이 `status` 를 읽지 않는다 |
| 2 `SearchDecision` 이 필요로 하나 | **아니다** — `arena` 는 `value` 만 읽는다 (`test_27`) |
| 3 replay/debug 가 필요로 하나 | **구분은 이미 보존되어 있다** — `status` 가 후보에 그대로 있고 `describe_ko` 가 그것을 찍는다 |
| 4 다른 칸으로 복원 가능한가 | `status` 자체가 보존되므로 복원이 아니라 **직접 읽으면 된다** |
| 5 AI 결정을 바꾸는가 | **아니다** |

---

## 14. hidden information

**§16 의 요구를 실측으로 확인했다** (`test_20` · `test_21`).

| 측정 | 결과 |
| --- | --- |
| 후보 객체 그래프의 타입 전수 | `PlayerAction` · `PlayerActionKind` · `InstanceId` · `EffectRef` · `SimulationStatus` · `StateValue` · `Terminal` · `Exclusion` · `ExclusionCategory` · `int` · `str` · `tuple` |
| `GameState` · `GameStateView` · `CardInstance` · `ZoneContainer` · `PlayerState` · `Duel` · `Simulator` · `Randomness` 포함 여부 | **하나도 없다** |
| 상대의 패 · 덱 · 묘지 instance 식별자 (20개) 가 후보 기록에 있는가 | **0개** |
| 내 패 instance 식별자가 있는가 | **있다** (`#0`~`#4`) — **내가 고려하는 내 수**가 가리킨다. 내 정보다 |
| 상대 패 **장수**가 적히는가 | 적힌다 (`"상대 패 5장의 값을 모른다"`) — **장수는 공개 정보**다 (`ZoneView.size` 는 "언제나 정확하다") |

**`future` 가 후보에 들어가지 않는 것이 이 보장의 핵심이다.** 평가자가 읽고 나면
사본과 함께 버려진다. Phase 3-C 가 태어날 때 적은 그대로다.

> 시뮬레이터가 돌려주는 SimulationResult 에는 **판을 담는 칸이 아예 없다.** 그래서
> 정책은 판을 바꿀 수단도 가려진 정보를 읽을 수단도 **구조적으로** 갖지 못한다.

처음 측정에서 카드 **번호**(`55144522`)로 찾았다가 "상대 식별자가 들어 있다" 고
잘못 읽었다 — 그것은 **내 욕망의 항아리**의 번호였고 내 수가 그것을 가리킨다.
instance 식별자로 다시 세어 고쳤다.

---

## 15. clone / RNG

| 불변식 (§17 · §18 · §19) | 측정 |
| --- | --- |
| 후보가 가변 `GameState` 를 참조하나 | **아니다** — 객체 그래프에 없다 (`test_20`) |
| 결정 **뒤에** 판을 바꾸면 이미 만든 후보가 움직이나 | **아니다** — 순위 키가 그대로다 (`test_22`) |
| 두 자료형이 frozen 인가 | `SearchCandidate` · `SearchDecision` 둘 다 `frozen=True` |
| 탐색이 원본 `state_hash` 를 바꾸나 | **아니다** |
| 탐색이 Game RNG 를 소비하나 | **아니다** — `draws` 가 전후 같다 (`test_23`) |
| 후보 생성이 RNG 를 쓰나 | **아니다** — `search.py` 에 `randomness` 라는 이름이 없다 (`test_29`) |
| 같은 seed · 같은 판에서 같은 결정인가 | **그렇다** — 고른 수 · 해시 · 순위 키 · 점수 전부 동일 (`test_24`) |

그리고 `agent/search.py` · `agent/evaluation.py` 에 `clone(` · `project(` ·
`randomness` · `set_result` 가 없고, **`.state` 접근이 하나도 없다** (구문으로
확인 — 문자열로 세면 `state_hash` 가 걸린다; 처음에 그렇게 세어 틀렸다).

---

## 16. consumer

### 필수 표 4 — Consumer 영향

| Consumer | `SimulationResult` 직접 사용 | `SearchCandidate` 사용 | 실제 의존 field | 영향 |
| --- | :--: | :--: | --- | --- |
| `SearchPolicy._look_ahead` | **○** | 생성 | `result.status` · `result.reason` · `result.future` | — |
| `SearchPolicy.decide` (ranking) | ✕ | **○** | `candidate.ordering_key()` · `best.comparable` · `best.value` · `best.action` | — |
| Tie-break | ✕ | ○ | `action.canonical_state()` (키의 넷째 칸) | — |
| `SearchDecision` | ✕ | 담는다 | `candidates` · `comparable_count` | — |
| `arena._records` | ✕ | **○ (이름 없이)** | `decision.candidates` · `.simulations` · `.reason` · `chosen.value.terminal/heuristic` | — |
| `Evaluation` | △ `future` 만 받는다 | ✕ | 관측 하나 | — |
| `Simulation` | 생성 | ✕ | — | — |
| Logging (`describe_ko`) | ✕ | ○ | `status.value` · `reason` · `value.describe_ko()` | — |
| `RuleBasedPolicy` · `RandomPolicy` · `FirstLegalPolicy` | ✕ | ✕ | 없음 | — |

**이름으로** `SearchCandidate`/`SearchDecision` 을 쓰는 production 파일은
`agent/search.py`(정의)와 `agent/__init__.py`(재수출) **둘뿐**이다. `arena` 는
`policy.decisions` 를 그대로 받아 **이름 없이** 읽는다 (`test_28`). 처음에 arena 를
이름 사용처로 세어 틀렸고 소스를 읽어 고쳤다.

---

## 17. provenance

**§22 가 묻던 것을 찾았다 — `provenance available` 이다** (3-E-41 과 같은 결과).

| 대상 | 최초 commit | 날짜 |
| --- | --- | --- |
| `SimulationResult` | **`40ea6c8` "Phase 3-C: 미래를 보고 고르는 AI — 그리고 아직 아무것도 더 알려주지 않는다"** | 2026-10-01 |
| `SearchCandidate` | 같은 commit | 2026-10-01 |
| `ordering_key` | 같은 commit | 2026-10-01 |
| `SearchDecision.state_hash` | 같은 commit (이후 `490ddcd` "Phase 3-D: AI vs AI Search Validation" 이 손댐) | 2026-10-01 |

그 커밋 메시지가 **두 객체를 분리한 이유를 직접 적는다.**

> 구조는 셋이다.
>
> ```
> agent/simulation.py  사본에 진짜 Duel.apply 를 적용하고 관측만 준다
> agent/evaluation.py  미래 관측 하나를 LP 단위의 값으로 바꾼다
> agent/search.py      후보마다 해 보고 가장 좋은 미래를 고른다
> ```

세 줄이 곧 이 Phase 가 조사한 경계의 **계약**이다. 그리고 세 가지를 더 적는다.

1. **판을 담지 않는 이유** — "정책은 판을 바꿀 수단도 가려진 정보를 읽을 수단도
   **구조적으로** 갖지 못한다."
2. **점수가 없는 후보의 뜻** — "0 점도 최저 점수도 아니고 **견줄 수 없는 것**이다."
3. **키의 모양** — "Terminal 을 등급으로 두고 비교를 (등급, 휴리스틱) 으로 했다 —
   등급이 다르면 휴리스틱을 아예 보지 않으므로 추월이 불가능하다."

안전 넷도 그때 전부 확인했다고 적혀 있다: 원본 불변 · 사본 독립 · 난수 격리 ·
가려진 정보 보호. **이 Phase 의 측정이 그 네 가지를 오늘도 재확인했다.**

---

## 18. BEFORE / AFTER

AUDIT-ONLY 이므로 **BEFORE = AFTER** 가 기대값이고, 그대로였다.

| 항목 | BEFORE | AFTER | 변화 |
| --- | --- | --- | --- |
| `SimulationResult` 필드 | 6 | 6 | — |
| `SearchCandidate` 필드 | 4 | 4 | — |
| `SearchDecision` 필드 | 9 | 9 | — |
| `StateValue` 필드 | 4 | 4 | — |
| 변환 자리 | 3 | 3 | — |
| `SimulationStatus` / `Terminal` | 5 / 4 | 5 / 4 | — |
| `ValidationCode` / `ActionValidity` / `unknown_codes()` | 48 / 3 / 7 | 같음 | — |
| MAIN1 결정 (seed 11) | 후보 11 · 고른 수 `normal_summon P0 #3` | 같음 | — |
| 결정의 `state_hash` | 결정 전 판의 해시 | 같음 | — |
| RNG `draws` | 2 → 2 | 같음 | — |
| 네 정책 전체 듀얼 (seed 1~4 × 4조합) | 16판 전부 `completed` · refusal 0 | 같음 | — |
| production diff | — | **0** | — |
| 테스트 수 | 3972 | **4008** | +36 (새 파일) |

---

## 19. 테스트

### 새 파일

`tests/test_simulation_result_search_candidate_audit.py` — **36개**
(요구 최소 30개). §29 의 1~32 항목을 덮는다.

| §29 항목 | 테스트 |
| --- | --- |
| 1 · 2 · 3 인벤토리 | `test_01` · `test_02` · `test_03` |
| (score 의 집) | `test_04` |
| 4 field mapping | `test_05` |
| 5 PRESERVED | `test_06` |
| 9 NOT_APPLICABLE / wrapper 아님 | `test_07` · `test_12` |
| 6 TRANSFORMED | `test_08` |
| 7 DERIVED | `test_09` |
| 8 DROPPED | `test_10` (code) · `test_11` (viewer) |
| 10 SUPPORTED 전달 | `test_13` |
| 11 · 12 UNKNOWN · REFUSED | `test_14` (도달 불가) · `test_15` (손으로 만든 비교) |
| 13 ordering_key | `test_16` · `test_26` |
| 16 status | `test_17` |
| 15 state_hash | `test_18` |
| 17 reason | `test_19` |
| 19 future | `test_20` · `test_30` |
| 20 hidden information | `test_21` |
| 21 · 22 clone 독립 · 원본 불변 | `test_22` · `test_23` |
| 23 RNG 격리 | `test_23` |
| 24 결정론적 반복 | `test_24` |
| 25 ranking 안정성 | `test_25` |
| 26 tie-breaking | `test_26` |
| 27 SearchDecision | `test_27` · `test_28` |
| 28 full duel | `test_31` |
| (계층 분리) | `test_29` · `test_32` |
| 29~32 기존 Phase 회귀 | `test_33` · `test_34` + 전체 suite |
| (AUDIT-ONLY · 새 추상 금지) | `test_35` · `test_36` |

### 기존 테스트 수정

**0건.** 삭제 0 · skip 추가 0 · assertion 약화 0 · 기존 파일 한 줄도 건드리지
않았다 (production diff 가 0 이므로 기존 사실이 하나도 바뀌지 않았다).

### 이 파일을 쓰며 고친 내 오류 셋

전부 **측정 방법**이 틀렸고 production 은 멀쩡했다.

1. `.state` 를 **문자열**로 찾아 `state_hash` 가 걸렸다 → AST 의 attribute 이름으로
   센다.
2. `viewer` 를 production 전체에서 찾아 `GameStateView` · `engine/observation.py` ·
   `engine/timing.py` 의 **다른 자료형의 같은 이름** 25건을 잘못 셌다 → `agent/`
   로 좁히고 관측의 칸을 제외한다.
3. `arena.py` 를 `SearchCandidate` **이름** 사용처로 셌다 → 실제로는 이름 없이
   읽는다. 두 사실을 갈라 적었다.

### Full regression

```
$ python -m pytest -q -p no:randomly
4008 passed, 4 skipped in 467.06s (0:07:47)
```

| 항목 | Phase 3-E-41 종료 시 | 이번 Phase 종료 시 |
| --- | --- | --- |
| passed | 3972 | **4008** (+36) |
| failed | 0 | **0** |
| skipped | 4 | **4** |
| production diff | — | **0** |

---

## 20. 82 최종 질문

**Q1. `SimulationResult` 의 실제 책임은?**
"이 수를 사본에 **진짜 엔진으로** 적용하면 어떻게 끝나고, 그 뒤의 **관측**은
무엇인가." 점수도 순위도 해시도 그 책임이 아니다.

**Q2. `SearchCandidate` 의 실제 책임은?**
"탐색에서 **비교할 수 있는 형태**로 줄여 놓은 후보 하나." 판도 관측도 들지 않는다.

**Q3. 둘은 같은 정보를 표현하나?** **아니다.** 공유하는 칸은 `action` · `status` ·
`reason` 셋이고, 후보는 **시뮬레이션 없이도 존재할 수 있다** (예산 초과).

**Q4. 실제 DROPPED 정보는?** **`code` 와 `viewer` 둘.**

**Q5. 그 정보가 Search 에 필요한가?** **아니다.** `code` 를 읽는 자리는 `agent/`
전체에서 `simulation.py` 의 분류기 하나이고, `viewer` 는 **읽는 자리가 0곳**이다.

**Q6. score 와 value 는 같은 의미인가?** **아니다** (§9).

**Q7. value 는 어디서 계산되나?** **`Evaluator`** — `evaluator.evaluate(result.future)`.

**Q8. ordering_key 는 어디서 생성되나?** `SearchCandidate` 의 **메서드**. 저장되지
않는다.

**Q9. ordering_key 가 status 를 구분해야 하나?**
**아니다.** 순위가 아는 것은 "견줄 수 있는가" 이고, **왜** 견줄 수 없는지는
`status` 가 그대로 들고 있다. 키에 넣으면 같은 사실이 두 곳에 적힌다.

**Q10. 랭킹에서 UNKNOWN 과 REFUSED 를 구분해야 하나?**
**아니다** (§13). 둘 다 점수가 없고, 구분은 보존되어 있으며, 그것이 Phase 3-C 가
적어 둔 설계다.

**Q11. state_hash 는 simulated state 의 해시인가?** **아니다 — 결정 전 진짜 판의
해시다** (`test_18`).

**Q12. 왜 `SearchCandidate` 가 아니라 `SearchDecision` 에 있나?**
결정 지점의 좌표이고 한 결정의 모든 후보가 **공유**하기 때문이다.

**Q13. `SimulationResult` 에 state_hash 가 없어도 되나?** **된다.** 시뮬레이션의
책임은 "어떻게 끝났고 무엇이 보이나" 이고 좌표를 매기는 일이 아니다.

**Q14. `SimulationResult.code` 가 후보에 없어도 되나?** **된다.** 읽는 쪽이 없고,
`status` 가 이미 "어떻게 끝났나" 를 전한다.

**Q15. `reason` 이 후보에 없어도 되나?** 그 질문은 성립하지 않는다 — **있다**.
그대로 복사된다 (`test_19`).

**Q16. future 는 누구의 책임인가?** **Simulation.** `__post_init__` 이
`SUPPORTED` ↔ `future` 유무를 **구조로** 묶는다 (`test_30`). 평가자가 읽고 나면
사본과 함께 버려진다.

**Q17. 후보가 hidden information 을 포함하나?** **아니다** (§14, 실측).

**Q18. 후보가 mutable `GameState` 를 참조하나?** **아니다** (`test_20` · `test_22`).

**Q19. 후보 생성이 RNG 를 소비하나?** **아니다** (`test_23`).

**Q20. Search ranking 이 `SimulationStatus` 에 의존하나?** **아니다** (`test_17`).

**Q21. 현재 정보 손실은 architecture bug 인가?**
**아니다.** DROPPED 는 둘이고 둘 다 읽는 쪽이 없다. 나머지는 보존 · 변환 · 파생 ·
해당없음이다.

**Q22. 현재 구조는 의도된 projection 인가?**
**그렇다.** 세 계층의 역할이 **태어난 커밋에 적혀 있고**(§17), 측정이 그 세 줄과
정확히 일치한다.

**Q23. production 변경이 필요한가?** **아니다.** §26 의 아홉 조건 중 **첫 세
개**(실제 손실 · consumer 의 필요 · 복원 불가)가 충족되지 않는다.

**Q24. 필요하다면 가장 작은 변경은?**
지금은 필요하지 않다. 만약 "후보의 거절 이유를 기계가 읽어야 하는" 소비자가
생긴다면, 최소 변경은 `SimulationResult` 에 필드를 더하는 것이 **아니라**
`SearchCandidate` 에 `code` 를 더하는 것이다 — 그 정보가 **탐색 계층의
semantic 에 속하게 되는 순간**에만. 다만 `status` 가 이미 그 구분을 들고 있으므로
그 소비자는 먼저 `status` 로 충분한지 보아야 한다.

**Q25. 새 abstraction 이 필요한가?** **아니다** (§28, `test_36`).

**Q26. 새 enum 이 필요한가?** **아니다.**

**Q27. state_hash 가 변할 가능성?** **없다** — 이 Phase 는 아무것도 바꾸지 않았고
측정값이 불변이다.

**Q28. RNG 가 변할 가능성?** **없다.**

**Q29. Engine V1 freeze 를 깨는가?** **아니다.** `engine/` diff 0. 이 경계는
애초에 `agent/` 안이라 freeze 밖이지만, 그래도 **열지 않았다.**

**Q30. 다음 Phase 에서 무엇을 해야 하나?** §22 에 하나만 적는다.

---

## 21. Final Decision

**A. AUDIT_ONLY_SUFFICIENT**

`SimulationResult` → `SearchCandidate` 는 **의도된 projection** 이며 production
변경이 필요하지 않다.

근거 넷:

1. **후보는 wrapper 가 아니다.** 예산에 걸린 후보는 `SimulationResult` **없이**
   만들어진다. 즉 `SearchCandidate` 는 시뮬레이션 결과의 포장이 아니라 **탐색
   계층의 독립된 기록**이다 (§13 의 B/C).
2. **진짜 사라지는 것은 둘(`code` · `viewer`)이고 둘 다 읽는 쪽이 없다.**
   `future` 는 버려지는 것이 아니라 **평가자가 소비해 `value` 를 만든다** — 그것이
   Simulation / Evaluation 분리다.
3. **provenance 가 의도를 증언한다.** Phase 3-C 커밋이 세 계층의 역할, 판을 담지
   않는 이유, 점수 없는 후보의 뜻, 키의 모양을 **모두 적어 두었고**, 이 Phase 의
   측정이 그것과 일치한다.
4. **안전 불변식이 전부 유지된다.** 후보의 객체 그래프에 판이 없고, 상대 식별자가
   0개이며, 원본 해시 · RNG 가 불변이고, 같은 seed 가 같은 결정을 낸다.

§26 의 아홉 조건 중 **1 · 2 · 3 이 충족되지 않는다.** 그래서 AUDIT-ONLY 로 끝낸다.

### 다른 판정을 고르지 않은 까닭

- **B (MINIMAL_INFORMATION_PROPAGATION)** — "실제 Search consumer 가 필요로 하는
  정보가 손실" 되어야 한다. 손실된 둘을 **아무 consumer 도 읽지 않는다.**
- **C (SEARCH_RESULT_CONTRACT_GAP)** — 책임 경계가 불명확하다고 하려면 경계가
  어디인지 적혀 있지 않아야 한다. **커밋에 세 줄로 적혀 있고** 코드가 그대로다
  (`test_29` 가 이름 수준에서 재확인).
- **D (HIDDEN_INFORMATION_RISK)** — 위험은 **이미 구조로 막혀 있다.** 후보가 판을
  들 수 없는 모양이라 "보존하면 새어 나간다" 는 긴장이 생기지 않는다. (3-E-41 의
  엔진 쪽 경계와 다른 점이 바로 이것이다.)
- **E (RANKING_SEMANTIC_GAP)** — `UNKNOWN`/`REFUSED`/`SUPPORTED` 가 순위 semantic
  과 충돌한다는 판정이다. 충돌이 아니라 **설계**다 — 순위는 "견줄 수 있는가" 만
  묻고, 구분은 `status` 에 보존된다. 그리고 두 상태는 **production 에서 생산되지도
  않는다.**
- **F (BLOCKER)** — 막힌 것이 없다. 네 자료형 · 세 변환 자리 · 전 소비자 · 객체
  그래프 · provenance · 실제 랭킹 · 16판 듀얼까지 전부 repository 안에서 측정했다.

### 기록만 하는 관찰 둘 (고치지 않았다)

| ID | 내용 | 성격 |
| --- | --- | --- |
| **O-1** | `SimulationResult.viewer` 는 **production 에서 읽는 자리가 0곳**이다 — "누구의 눈으로 본 미래인가" 를 적어 두는 기록용 칸이다. 지우자는 뜻이 아니다 (그 사실을 적어 두는 것이 이 저장소의 방식이다) | 관찰 |
| **O-2** | 후보의 `action` 은 `result.action` 이 아니라 **루프 변수**다. 지금은 같은 값이지만(같은 수로 `simulate` 를 불렀으므로) 두 출처가 갈라질 길이 구조적으로 열려 있다 | 관찰 |

---

## 22. 다음 Phase

**하나만 제안한다.**

> **Phase 3-E-43 — Trigger pipeline dormant 구조 감사** (§40 의 후보 5번)

까닭 — **validation / 정보 경계 계열의 질문이 닫혔다.**

| Phase | 경계 | 판정 |
| --- | --- | --- |
| 3-E-39 | `SimulationStatus` / `_UNKNOWN_CODES` | C → 3-E-40 이 해결 |
| 3-E-40 | `ValidationCode` UNKNOWN policy | **A** (정식화 완료) |
| 3-E-41 | `ValidationResult` → `DuelStep` / `WithheldAction` | **A** (의도된 경계) |
| 3-E-42 | `SimulationResult` → `SearchCandidate` | **A** (의도된 projection) |

세 경계가 모두 "의도된 설계" 로 확정되었고, 더 이상 같은 계열에서 물을 것이
남아 있지 않다. 반면 **dormant 구조**는 3-E-33 부터 이번까지 **열 Phase 연속**
측정에서 계속 같은 사실로 나타난다.

- `TriggerSpec` · `TriggerRegistry` production 생성 **0곳**
- `engine/duel.py` 가 "trigger" 를 **한 번도** 쓰지 않는다
- M3 (`_event_relation`) 가 `INVALID` 에 `RULE_NOT_IMPLEMENTED` 를 붙인 채 남아 있다
  (3-E-38 이 일부러 남겼다)
- `CHAIN_DEFINITION_UNAVAILABLE` 이 policy 에서 `None` 인 까닭도 **트리거 쪽 carrier
  와 체인 쪽 carrier 가 다른 말을 하기** 때문이다 (3-E-40 §10)
- 3-E-39 가 "`judge_all` 은 그 분기에 닿지 않는다" 를 측정했다

즉 **지금 남아 있는 가장 큰 미지의 구조**가 트리거 파이프라인이고, 그것이 깨어나는
순간 앞선 네 Phase 가 확정한 경계들이 **처음으로 실제 부하를 받는다.** 깨우기
전에 그 구조가 무엇을 전제하고 무엇이 비어 있는지 재는 것이 다음 일이다.

**이번 Phase 에서 그것을 하지 않았다.** 그리고 O-1 · O-2 를 근거로 다른 구조를
연쇄 수정하지 않았다 (§40 의 마지막 금지). 다음 Phase 의 범위와 금지 사항은
사용자가 정한다.
