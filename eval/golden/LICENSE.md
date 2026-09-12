# 골든셋 라이선스 고지

| 항목 | 내용 |
|---|---|
| 출처 | **ELLIPSE Corpus** (English Language Learner Insight, Proficiency and Skills Evaluation) |
| 취득 경로 | Kaggle 대회 `feedback-prize-english-language-learning` (train.csv) |
| 원본 저장소 | https://github.com/scrosseye/ELLIPSE-Corpus |
| 라이선스 | **CC BY-NC-SA 4.0** (Attribution–NonCommercial–ShareAlike) |
| 상업적 사용 | **금지** |
| 재배포 | 가능하나 **동일 라이선스 유지(ShareAlike) 필수** |
| 이 저장소 커밋 여부 | **커밋하지 않음** (아래 근거) |

## 인용 (Attribution 의무)

> Crossley, S. A., Tian, Y., Baffour, P., Franklin, A., Kim, Y., Morris, W., Benner, B.,
> Picou, A., & Boser, U. (2023). *Measuring second language proficiency using the English
> Language Learner Insight, Proficiency and Skills Evaluation (ELLIPSE) Corpus.*
> International Journal of Learner Corpus Research, 9(2), 248–269.

프리프린트(무료): https://zenodo.org/records/11217937

## 왜 골든셋을 커밋하지 않는가

골든셋(`eval/golden/*.jsonl`)은 ELLIPSE 에세이 **원문 전문**을 담는다.
이 저장소는 라이선스를 지정하지 않은 public 저장소이므로, 원문을 그대로 올리면
**ShareAlike 조항을 충족하지 못한다.** 따라서 `.gitignore` 대상으로 둔다.

**재현 방법**은 코드로 보장한다:

```bash
uv run kaggle competitions download -c feedback-prize-english-language-learning \
    -p eval/golden/raw
unzip -o eval/golden/raw/*.zip -d eval/golden/raw/
uv run python scripts/build_golden_set.py --n 50
```

시드가 고정돼 있어 **같은 50건이 재현된다** (`--seed 20260912`).
원본만 확보하면 누구나 동일한 골든셋을 만들 수 있으므로 데이터를 올릴 필요가 없다.

## 커밋되는 것 / 안 되는 것

| | 커밋 |
|---|---|
| 추출 스크립트 (`scripts/build_golden_set.py`) | ⭕ 내 코드 |
| 파생 지표 (QWK, 정확도, latency, 비용) | ⭕ 사실 데이터 |
| 점수 분포 통계 | ⭕ |
| 에세이 원문 | ❌ |
| 원본 점수 라벨 (에세이와 짝지어진 상태) | ❌ |
| 공식 루브릭 서술어 원문 | ❌ (아래 참조) |

## 루브릭 서술어 처리

공식 루브릭(`ELL_Rubrics.docx`)도 같은 CC BY-NC-SA 라이선스 아래 있다.
따라서 `docs/01-루브릭.md`와 채점 프롬프트에 **원문 서술어를 그대로 옮기지 않는다.**

대신 **기준(무엇을 보고 무엇으로 점수를 가르는가)은 원본에 정확히 맞추고,
문장은 직접 쓴다.** 대조 결과와 수정 내역은 `docs/01-루브릭.md`
「원본 대조 기록」에 남긴다.

> 이 판단은 법률 자문이 아니다. 배포 범위를 넓힐 계획이 생기면 재검토할 것.

## 비상업 조건이 이 프로젝트에 갖는 의미

개인 학습·포트폴리오 용도는 비상업에 해당한다고 보고 진행한다.
**이 파이프라인을 상업적으로 쓰려면 골든셋을 다른 데이터로 교체해야 한다.**
`eval/harness.py`의 `load_golden_set`은 데이터 출처에 무관하게 동작하므로
교체 지점은 jsonl 파일 하나다.
