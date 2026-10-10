# Phase 3-F-35 — Effect 블록 목록 길이 계약 감사

**최종 판정: `MIXED_FINDINGS`**

세 사실이 동시에 성립하고, 하나로 뭉갤 수 없다.

| 갈래 | 판정 | 조치 |
|---|---|---|
| 🔴 **출하된 CLI 경로에서 실제 결함이 재현된다** | 확인 | **최소 수정함** (`core/card_repository.py` 1파일) |
| 🔴 **길이 계약은 필요하지만 충분하지 않다** | `CONTRACT_INSUFFICIENT_IDENTITY_REQUIRED` | **고치지 않고 기록** — 식별자가 필요하고 그것은 §5 금지 |
| 🟢 **정상 corpus 산출물은 변화 0** | `NO_OUTPUT_CHANGE` | §6 의 11개 항목 전부 동일 |

`CONTRACT_ENFORCEABLE_NO_OUTPUT_CHANGE` 를 고르지 않은 이유: 계약이
**강제되지 않았다.** 순서 불일치는 길이 검사를 통과하면서 여전히 조용히
잘못 붙는다. `NO_CURRENT_MISALIGNMENT_FOUND` 도 아니다 — 실제 불일치를
CLI 에서 재현했다.

---

## 1. 기준 HEAD 및 테스트 결과

`git log` · `git show` · `git status` · `git rev-parse` 로 직접 확인했다.
**지시서 기준과 전부 일치한다.**

| 항목 | 지시서 | 실측 | 결과 |
|---|---|---|---|
| 기준 HEAD | `e3b4f82…` | `e3b4f823a1c6acb2416544a020ed0cf4c4e9eebf` | 일치 |
| 3-F-34 작업 commit | — | `dac1c8d` (1 file, +35/−2) | — |
| 3-F-34 테스트 commit | — | `b959dda` (2 files, +1212/−18) | — |
| 3-F-34 보고서 commit | — | `e3b4f82` (501줄) | — |
| 기준 보고서 | `phase3f34-…-audit.md` | 501줄, 존재 | 일치 |
| 브랜치 | `claude/pensive-goodall-te1egy` | 같음 | 일치 |
| `origin/claude/…` | — | `e3b4f82` — **HEAD 와 동일** | — |
| worktree | — | **clean** | — |
| 기준 전체 테스트 | 5,045 / 4 skipped / 0 failed | 같음 | 일치 |

### 1.1 기준 corpus 통계 재측정 (§1.4)

수정 **전** 상태에서 다시 산출해 3-F-34 보고값과 맞췄다.

| 항목 | 3-F-34 보고 | 재측정 | 결과 |
|---|---:|---:|---|
| 스크립트 / 파서 블록 | 12,702 / 34,684 | **같음** | 일치 |
| 붙은 카드 / 블록 | 12,687 / 34,635 | **같음** | 일치 |
| 등록 / 해결 Effect | 26,352 / 8,283 | **같음** | 일치 |
| 조건 / 비용 / 대상 | 12,438 / 5,007 / 5,516 | **같음** | 일치 |
| 액션 / 카테고리 | 18,280 / 20,484 | **같음** | 일치 |
| `EffectRef` 연결 불일치 | 0 | **0** | 일치 |
| 검색 카테고리 / 위치 | 31 / 31 | **같음** | 일치 |

기존 commit 은 rewrite/amend 하지 않았다.

---

## 2. 실제 parser → analyzer 연결 경로

§2 지시대로 **실제 HEAD 에서** 확인했다 (보고서 설명을 그대로 믿지 않았다).

```
                    c*.lua  (디스크)
                        │
      ┌─────────────────┴──────────────────┐
      ▼ ① 리포지토리 빌드 시점              ▼ ② 분석 시점
 LuaScriptSource.load_cached()        EffectAnalyzer._read_source()
   (data/cache/lua_scripts.json       (self.script_dir / file_name)
    에서 올 수도 있다)                        │
      │                                       ▼
 parse_lua_source()                   _collect_handlers()
      │                                       │
 LuaScriptInfo.effects                      entries
 = list[EffectSpec]                   = list[{handlers, function}]
      │                                       │
      └──────── _analyze_card ────────────────┘
                     │
   entries[position] if position < len(entries) else {}
                     │
             EffectAnalysis
             (is_registered = entry["function"] == "initial_effect")
```

### 2.1 🔴 두 목록은 **같은 파싱의 두 뷰가 아니다**

`analysis/effect_analyzer.py` 282-287행 (실제 HEAD):

```python
entries = self._collect_handlers(source, spans)

for position, spec in enumerate(card.script.effects):
    entry = entries[position] if position < len(entries) else {}
    effect = self._analyze_effect(spec, entry.get("handlers", {}), functions, analysis)
    effect.is_registered = entry.get("function") == "initial_effect"
```

* `card.script.effects` — 리포지토리를 **지을 때** 파싱한 결과. 디스크 캐시
  (`data/cache/lua_scripts.json`)에서 올 수 있다.
* `entries` — `_read_source` 로 `self.script_dir / file_name` 을 **그때 다시
  읽어** 만든다.

두 텍스트가 어긋나면 길이도 순서도 어긋난다. **결합은 위치(`position`)
하나로만 이루어지고, 블록 고유 식별자는 쓰이지 않는다** (`test_01` 이 AST 로
확인 — `entries[...]` 첨자가 `enumerate` 의 위치 변수이고, 그 함수에
`EffectRef` 도 `spec.index` 도 없다).

### 2.2 계약의 소유자

`EffectAnalyzer.__init__` 은 **이미** 리포지토리에게 디렉터리를 묻고 있었다.

```python
self.script_dir = Path(
    script_dir
    or getattr(repository, "script_dir", None)   # ← 이미 묻고 있다
    or Path(__file__).resolve().parent.parent    # ← fallback: 저장소 루트
)
```

🔴 그런데 `CardRepository` 에 그 속성이 **없었다.** `__init__` 시그니처는
`(self, cards, constants=None)` 이고 `script_dir` 을 어디에도 저장하지
않았다. 그래서 `getattr` 은 **언제나 `None`** 이고 fallback 이 쓰였다.

---

## 3. 길이 및 순서 불일치 재현 결과

§4 의 모든 사례를 **실제 production 경로**(`EffectAnalyzer.analyze`)로 돌렸다.
두 목록을 독립적으로 만드는 방법은 "`card.script` 은 텍스트 A 를 파싱한
결과로 두고 디스크에는 텍스트 B 를 둔다" 다 — 인공적인 상황이 아니라
캐시가 낡거나 `script_dir` 이 어긋나면 **정확히 그 상태**가 된다.

### 3.1 길이 조합

입력 A = 블록 1개(`e1` 조건) · 입력 B = 블록 2개(`e1` 조건 · `e2` 비용)

| # | blocks | entries | 기존 결과 | 올바른 결과 | 안전한가 |
|---|---:|---:|---|---|---|
| 1 | 0 | 0 | 등록 0 · 해결 0 | 같음 | 🟢 |
| 2 | 1 | 1 | `e1` 등록 · 조건 O | 같음 | 🟢 |
| **3** | **2** | **1** | 🔴 `e1` 등록 · **`e2` 해결로 밀림** | 둘 다 등록, `e2` 비용 O | 🔴 **아니다** |
| **4** | **1** | **2** | 🔴 `e1` 등록 · **두 번째 entry 소멸** | 블록이 1개면 그 entry 는 쓸 곳이 없다 — 그러나 그 사실이 **보고되지 않는다** | 🔴 **아니다** |
| **5** | **3** | **1** | 🔴 `e2`·`e3` **둘 다** 해결로 밀림 | 셋 다 등록 | 🔴 **아니다** |

🔴 **§3.2 의 답**: 길이가 달라도 **예외가 나지 않고 경고도 없다.**
짧으면 뒤쪽 블록이 `{}` 를 받아 `is_registered=False` 가 되고
(`{}.get("function")` 은 `None`), **"해결 중 생성되는 효과" 로
오분류**된다. 길면 남는 entry 가 **조용히 버려진다.** (`test_08`~`test_11`)

### 3.2 🔴 순서 — 길이가 같은데도 잘못 붙는다

입력: 파싱된 쪽은 `e1`(조건) → `e2`(비용), 디스크 쪽은 **순서만** 뒤바뀐
같은 두 블록.

| | `e1` | `e2` |
|---|---|---|
| 올바른 결과 | 조건 **True** · 비용 False | 조건 False · 비용 **True** |
| 🔴 실제 결과 | 조건 **False** · 비용 **True** | 조건 **True** · 비용 False |

**정확히 뒤바뀐다.** 길이는 둘 다 2 이므로 **어떤 길이 검사도 통과한다.**
(`test_12` · `test_13` 이 올바른 결과와 나란히 고정한다)

🔴 **§3.3 의 답: 그렇다.** 길이가 같아도 순서가 다르면 잘못 연결된다.

### 3.3 🔴 출하된 CLI 에서 재현된다 — 이것이 이 Phase 의 핵심 발견

`app/main.py:578` 이 `--scripts` 를 노출한다 ("c*.lua 디렉터리 (기본: 저장소
루트)"). `DeckAgent.build(script_dir=args.scripts)` → `CardRepository.build(...)`.
그런데 `cmd_analyze`(419행)와 `cmd_relations`(497행)는
`EffectAnalyzer(agent.repository)` 로 **`script_dir` 없이** 만든다.

```console
$ python -m app.main analyze 55144522 --scripts <대체 디렉터리>
```

실측 (수정 전):

```
CLI 가 넘긴 --scripts     : <대체 디렉터리>
repository 가 읽은 블록 수 : 2   [('e1','EVENT_FREE_CHAIN'), ('e2','EVENT_TO_HAND')]
🔴 analyzer.script_dir    : /home/user/yugioh-deck-agent   ← fallback
analyzer 가 읽은 entries  : 1   [(('Operation','Target'), 'initial_effect')]

🔴 길이 불일치: blocks 2 vs entries 1
   → 등록 1 · 해결 1
      R e1  trigger=EVENT_FREE_CHAIN  cond=False cost=False actions=1
      X e2  trigger=EVENT_TO_HAND     cond=False cost=False actions=0
```

대체 디렉터리의 Lua 가 말하는 것과 대조하면:

* `e1` 은 `SetCondition(s.con)` 을 갖는데 **`cond=False`** 다 — 저장소
  루트의 `Operation`/`Target` 을 받았고 자기 조건을 잃었다.
* `actions=1` 은 저장소 루트의 `s.activate` 에서 왔다. 그 함수는 **대체
  디렉터리에 존재하지 않는다.**
* `e2` 는 대체 디렉터리에서 `initial_effect` 에 등록되는데 **"해결 중
  생성" 으로 오분류**됐다.
* 🔴 **예외도 경고도 없다.** CLI 는 두 스크립트를 섞은 분석을 그대로
  출력했다.

### 3.4 수정 후 같은 명령

```
🔴 analyzer.script_dir    : <대체 디렉터리>      ← 같은 자리를 읽는다
analyzer 가 읽은 entries  : 2   [(('Condition',),'initial_effect'),
                                 (('Cost',),'initial_effect')]
   → 등록 2 · 해결 0
      R e1  trigger=EVENT_FREE_CHAIN  cond=True  cost=False
      R e2  trigger=EVENT_TO_HAND     cond=False cost=True
```

**대체 디렉터리의 Lua 가 말하는 그대로다.**

---

## 4. 목록 간 대응 관계가 보장되는 근거

정상 입력에서 두 목록이 대응하는 것은 **우연이 아니다.** 근거는 셋이다.

1. **같은 탐지 규칙** — `_collect_handlers` 는 `_RE_CREATE_EFFECT` ·
   `_RE_CLONE_EFFECT` · `_clone_source` · `_is_card_effect` 를 로더에서
   **import 해서** 쓴다 (3-F-28 이 통일, 3-F-32 가 `_clone_source` 추가).
   `test_19` 가 **같은 객체(`is`)** 임을 확인한다.
2. **같은 전처리와 같은 순서** — 둘 다 `_RE_BLOCK_COMMENT` 로 블록 주석을
   지우고 byte offset 으로 정렬한다.
3. **같은 재바인딩 규칙** — 3-F-34 가 `_RE_REBIND` · `_EVENT_ORDER` 를
   공유하게 만들었다 (`test_29` · `test_30`).

🔴 **그러나 이 셋은 "같은 텍스트" 를 전제로 한다.** 텍스트가 다르면 세
근거가 모두 무력해진다 — 그것이 §3 의 재현이다.

### 4.1 전수 확인 (정상 corpus)

| 항목 | 결과 |
|---|---|
| 길이 불일치 스크립트 | **0** / 12,687 (블록 34,635 = entries 34,635) |
| 순서 불일치 스크립트 | **0** |

(`test_20` · `test_21`)

---

## 5. 길이 계약의 필요성과 충분성

### 5.1 필요하다

§3.1 의 사례 3·4·5 는 길이가 다를 때 **조용히 틀린 결과**를 만든다.
길이 검사가 있었다면 그 셋은 잡힌다.

### 5.2 🔴 그러나 충분하지 않다 — **§3.4 의 답**

§3.2 의 순서 사례는 **길이가 같다.** 어떤 길이 assertion 도 통과하고,
결과는 정확히 뒤바뀐다. 그래서 길이 계약만 넣고 "고쳤다" 고 하면 거짓이
된다. (`test_14` 가 이것을 명시적으로 못 박는다 — 길이는 같고 의미는
다르다는 것을 두 값으로 보인다.)

### 5.3 그럼 무엇이 필요한가 — 안정적인 식별자

블록과 entry 를 **위치가 아니라 정체로** 맞춰야 한다. 후보를 검토했다.

| 후보 | 가능한가 |
|---|---|
| `EffectSpec.index` (Lua 변수명) | 🔴 **불가능** — 유일하지 않다. `test_15` 가 코퍼스 2,000 스크립트에서 중복을 실측한다 (위험 E6, 3-F-28) |
| `EffectRef(card_id, ordinal)` | 🔴 `ordinal` 이 **곧 위치**다 — 순환이다 |
| byte offset | 가능해 보이지만 `entries` 에 offset 을 담아야 하고, 그것은 자료구조 변경이다 |
| 새 ID 체계 | 🔴 **§5 금지** |

결론: **충분한 계약을 넣으려면 설계를 바꿔야 하고, 그것은 이 Phase 가
금지된 범위다.** 그래서 기록하고 멈춘다.

### 5.4 🔴 §3.5 — 두 목록을 하나로 공유할 수 있는가

`LuaScriptInfo` 가 핸들러를 담고 있지 않다. 담게 하려면 `EffectSpec` 에
칸을 더하거나 `LuaScriptInfo` 에 병렬 목록을 더해야 하고, 전자는 §5 가
명시적으로 금지하며 후자는 "같은 길이의 두 목록" 문제를 **한 자료구조
안으로 옮기는 것**일 뿐 없애지 못한다. 진짜 공유는 블록과 핸들러를 **한
객체**에 담을 때 성립하고, 그것이 설계 변경이다.

---

## 6. corpus 산출물 및 검색 결과 비교

수정 **전/후**를 같은 측정 스크립트로 돌려 맞댔다. §6 의 "단순히 테스트가
통과했다는 이유로 동일하다고 선언하지 않는다" 를 지켰다.

| 항목 | 수정 전 | 수정 후 | 결과 |
|---|---|---|---|
| 스크립트 수 | 12,702 | 12,702 | 🟢 |
| 파서 블록 수 | 34,684 | 34,684 | 🟢 |
| **`EffectSpec` 전수 지문** | `b2623fe93aa0…` | `b2623fe93aa0…` | 🟢 **동일** |
| 붙은 카드 / 블록 | 12,687 / 34,635 | 같음 | 🟢 |
| **`CardAnalysis` 전수 지문** | `602328c9c029…` | `602328c9c029…` | 🟢 **동일** |
| 등록 / 해결 Effect | 26,352 / 8,283 | 같음 | 🟢 |
| 조건 / 비용 / 대상 | 12,438 / 5,007 / 5,516 | 같음 | 🟢 |
| 액션 / 카테고리 | 18,280 / 20,484 | 같음 | 🟢 |
| `EffectRef` 연결 (34,635, 불일치) | 0 | 0 | 🟢 |
| **검색 카테고리 결과·순위 지문** | `d57c6ae18b70…` | 같음 | 🟢 **동일** |
| **검색 위치 결과·순위 지문** | `a822e7604cab…` | 같음 | 🟢 **동일** |
| 3-F-32 대표 3사례 + 반례 2사례 | — | 같음 | 🟢 |

**왜 0 인가**: 저장소 루트로 지은 리포지토리에서는 새 `script_dir` 값이
기존 fallback(`Path(effect_analyzer.__file__).parent.parent`)과 **같은
디렉터리**다. 그래서 analyzer 가 읽는 파일이 글자 그대로 동일하다.
`test_24` 가 그 등식(`repo.script_dir == fallback == PROJECT_ROOT`)을 못
박고, `script_dir` 을 주지 않은 리포지토리가 여전히 `None` 을 돌려주는 것도
확인한다 — **기존 fallback 경로가 그대로 남아 있다.**

---

## 7. 수정 여부와 그 근거

### 7.1 수정했다 — §5 의 네 조건을 전부 충족한다

| 조건 | 충족 | 근거 |
|---|---|---|
| ① 실제 오류가 최소 재현으로 입증됨 | ✅ | §3.3 — **출하된 CLI 명령 한 줄**로 재현. 두 스크립트가 섞인 분석이 출력됐다 |
| ② 수정 위치와 계약의 소유자가 명확함 | ✅ | analyzer 가 **이미** `getattr(repository, "script_dir")` 로 묻고 있었다. 답하지 않은 쪽이 `CardRepository` 다 |
| ③ 정상 corpus 산출물에 미치는 영향이 측정됨 | ✅ | §6 — 11개 항목 **전부 동일** |
| ④ 최소 수정으로 잘못된 연결을 방지 | ✅ | 속성 하나 + `build` 에서 전달. 기본값 `None` 이라 기존 fallback 유지 |

`core/card_repository.py` **1파일** (+22/−2, 주석 포함).

```diff
-    def __init__(self, cards: dict[int, Card], constants=None):
+    def __init__(self, cards: dict[int, Card], constants=None, script_dir=None):
         ...
+        self.script_dir = script_dir
```

```diff
         cls._record_provenance(cards)
-        return cls(cards, constants=constants)
+        return cls(cards, constants=constants, script_dir=lua.script_dir)
```

### 7.2 🔴 고치지 **않은** 것과 그 이유

| 안 고친 것 | 이유 |
|---|---|
| 길이 assertion 추가 | 🔴 **순서 사례를 잡지 못한다** (§5.2). 넣으면 잡히지 않는 실패를 가린 채 "계약을 강제했다" 고 주장하게 된다. `test_38` 이 결합 자리에 길이 assertion 이 **없다**는 것을 의도적으로 고정한다 |
| 길이 불일치 시 예외 | 호출자 동작을 바꾼다. 그리고 §5.2 와 같은 이유로 **부분적 방어**다 |
| 블록·entry 식별자 도입 | 🔴 **§5 금지** — 새 ID 체계, `EffectSpec`/`EffectRef` 설계 변경 |
| 두 함수 합치기 | 🔴 **§5 금지** |

§5 는 *"수정하지 않더라도 문제가 해결되는 것은 아니다. 위험이 확인되면
재현 코드, 영향 범위, 후속 수정 조건을 보고서에 남긴다"* 고 했다. §9 에
그대로 남긴다.

---

## 8. 신규 · 기존 테스트 결과

### 8.1 신규

`tests/test_effect_block_alignment_audit.py` — **38개** (지시서 최소 25개).
🔴 **문자열 존재 검사로 개수를 채우지 않았다** — 핵심은 `_analyze_with` 로,
두 목록을 독립적으로 만들어 `EffectAnalyzer.analyze` 를 **실제로 돌린다.**

구조 확인에 AST 를 쓴 테스트(`test_01`·`test_02`·`test_38`)는 "결합이
위치만으로 이루어진다" 와 "길이 assertion 이 없다" 를 **의도적으로**
고정하는 것이고, 그 사실 자체가 이 감사의 결론이다.

삭제 0 · skip 추가 0 · assertion 약화 0.
(`test_36`·`test_37` 은 이 Phase 의 commit 이 없을 때만 건너뛰는 guard 다.)

### 8.2 기존 테스트

**하나도 수정하지 않았다.** 수정이 산출물을 바꾸지 않았으므로 기존 어서션이
전부 그대로 성립한다 — 그것 자체가 §6 의 회귀 검증이다.

### 8.3 회귀 결과

| 실행 | 결과 |
|---|---|
| 기준 (3-F-34 끝, `e3b4f82`) | 5,045 passed / 4 skipped / 0 failed |
| 신규 파일 단독 | 36 passed / 2 skipped (commit 전 guard) |
| **최종 전체 (commit 된 상태)** | 🟢 **5,083 passed / 4 skipped / 0 failed** |

### 8.4 최종 전체 회귀

```
5083 passed, 4 skipped in 2457.21s (0:40:57)
```

🔴 **계정이 맞는다**: 5,045 → 5,083 은 **+38** 이고 신규 테스트 수와 정확히
같다. skip 은 **4 → 4** 로 유지됐다 (§6 의 조건) — 신규 파일의 두 guard 는
commit 후 실행되어 통과한다.

### 8.5 commit 셋

| commit | 내용 |
|---|---|
| `5b9c0fb` | *make the repository report the script directory it read* — `core/card_repository.py` (+22/−2) |
| `98aa9cc` | *test effect block list length contract* — 신규 38개 |
| (아래) | *document effect block alignment audit* — 이 보고서 |

---

## 9. 남은 구조적 위험

### 9.1 이 Phase 가 해소한 것

| # | 위험 | 상태 |
|---|---|---|
| **N17** | 🔴 `CardRepository` 가 `script_dir` 을 노출하지 않아 analyzer 가 **다른 디렉터리**를 읽는다 — 출하된 CLI 에서 재현 | 🟢 **해소** |

### 9.2 남은 것 — 후속 수정 조건까지 적는다

| # | 위험 | severity | 재현 | 현재 영향 | 후속 수정 조건 |
|---|---|---|---|---|---|
| **N18** | 🔴 **길이가 같고 순서가 다르면 조용히 잘못 붙는다** | 🟠 중 | `test_12`·`test_14` | 정상 corpus **0건** (순서 불일치 0) | 블록↔entry **식별자**가 필요하다. `EffectSpec.index` 는 유일하지 않아 쓸 수 없고(`test_15`), `ordinal` 은 곧 위치여서 순환이다. byte offset 을 `entries` 에 담는 것이 유일하게 설계를 덜 흔드는 길인데 그것도 자료구조 변경이므로 **별 Phase 의 명시적 허가**가 필요하다 |
| **N19** | 🟠 **길이 불일치가 조용히 넘어간다** — 예외도 경고도 없다 | 🟠 중 | `test_08`~`test_11` | 정상 corpus **0건** | N18 과 함께 다뤄야 한다. 길이만 막으면 N18 을 가린다. 막을 때는 "부분 zip 금지 · 남은 항목 조용히 버리기 금지"(§5)를 함께 지켜야 하고, 그러면 **"분석 불가" 를 표현할 채널**이 필요하다 — `CardAnalysis` 에 그런 칸이 **없다**(실측). `core/provenance.py` 의 `AnalysisStatus` 는 다른 용도다 |
| **N20** | 🟡 **두 목록이 서로 다른 시점의 파싱에서 온다** — 캐시 vs 즉시 읽기 | 🟡 하 | §2.1 | 측정 0건 | 캐시 서명이 `v9:{count}:{newest:.0f}` 로 **초 단위**다. 같은 초 안의 편집이나 파일 추가·삭제가 맞물리면 낡은 캐시가 통과할 수 있다 (위험 E4 의 구체적 결과) |
| N14 | 두 경로의 "같은 블록 수" 가 암묵적 계약 | 3-F-34 | `test_20`·`test_21` | 0건 | 🔴 **이 Phase 가 조사해 N18·N19 로 쪼갰다** — 길이만으로는 강제할 수 없다는 것이 답이다 |
| N13 · N15 · N16 | `_EVENT_ORDER` 미발동 · 파일 세는 테스트 함정 · 테스트 쪽 "수정 전" 복사본 | 3-F-33·34 | — | **유지** |
| N2~N10 · E1~E8 | 주석 처리된 설정자 · 보조 함수 UNKNOWN · `index` 비유일 · 캐시 서명에 파서 버전 없음 등 | 3-F-28~32 | — | **유지** |

---

## 10. 최종 판정 및 다음 Phase 후보

## **`MIXED_FINDINGS`**

1. 🔴 **실제 결함을 찾아 고쳤다** — `CardRepository` 가 `script_dir` 을
   노출하지 않아, 출하된 CLI 의 `--scripts` 경로에서 두 목록이 **서로
   다른 디렉터리**에서 왔다. 분석이 두 스크립트를 섞었고 효과 하나가
   오분류됐으며 **예외도 경고도 없었다.** §5 의 네 조건을 전부 충족해
   최소 수정했다 (1파일, +22/−2).
2. 🔴 **길이 계약은 충분하지 않다** (`CONTRACT_INSUFFICIENT_IDENTITY_REQUIRED`)
   — 길이가 같고 순서만 다르면 결과가 **정확히 뒤바뀌는데** 어떤 길이
   검사도 통과한다. 막으려면 식별자가 필요하고 그것은 §5 가 금지한 설계
   변경이다. 그래서 **고치지 않고 재현 코드·영향 범위·후속 조건을
   기록했다.**
3. 🟢 **정상 corpus 산출물은 변화 0** — §6 의 11개 항목 전부 동일.

🔴 **"길이가 같다" 가 "의미가 대응한다" 를 보장하지 않는다** — §3 이
명시적으로 금지한 결론을 내리지 않았다. 지금 대응을 보장하는 것은 두
경로가 **같은 텍스트**를 **같은 규칙**으로 읽는다는 사실이고, 이 Phase 가
고친 것이 바로 그 "같은 텍스트" 전제였다.

### 10.1 다음 Phase 후보 1개

**Phase 3-F-36 — 블록↔핸들러 대응의 식별자 도입 가능성 조사 (N18 + N19)**

이 Phase 가 "길이로는 안 된다" 를 확정했으므로, 다음은 **무엇으로 되는가**를
재는 단계다. 조사 우선이어야 한다 — 설계를 건드리기 때문이다.

* 🔴 **먼저 재야 할 것**: `_collect_handlers` 가 각 entry 에 **생성 위치
  (byte offset)** 를 함께 담고, `_analyze_card` 가 위치가 아니라 그 offset
  으로 맞추는 방안. `EffectSpec` 에는 offset 이 없으므로 loader 쪽도 담아야
  하는지, 아니면 `_analyze_card` 가 블록 offset 을 **그 자리에서 다시
  계산**할 수 있는지(그러면 자료구조 변경이 없다)를 측정해야 한다.
* 함께 결정할 것: 불일치가 확인되면 **무엇을 출력할 것인가.** 조용히
  부분 zip 하는 것은 §5 가 금지했고, 예외는 호출자를 깨뜨리며,
  `CardAnalysis` 에는 "분석 불가" 를 담을 칸이 **없다**. 칸을 하나 더하는
  것이 정당한지가 그 Phase 의 핵심 판단이다.
* 성공 기준은 이 Phase 와 같다 — **산출물 무변화**. 기준값(블록 34,684 ·
  `EffectSpec` 지문 · `CardAnalysis` 지문 · 검색 두 지문 · digest 핀 7개)을
  이 Phase 가 측정해 두었다.
* 🔴 산출물이 바뀌면 그때는 리팩터가 아니라 **또 다른 버그 수정**이므로,
  3-F-32 처럼 `ordinal` 영향부터 재야 한다.
