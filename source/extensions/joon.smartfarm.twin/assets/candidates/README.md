# Greenhouse Candidate Assets

Sketchfab 모델 파일과 변환된 USD는 외부 에셋이라 git에 넣지 않는다.

## 후보

```text
candidates/
├─ greenhouse_low_poly_generic/
│  └─ greenhouse.usd   변환 후 직접 배치, git 제외
│
└─ greenhouse_hoop_house_20x60/
   └─ greenhouse.usd   변환 후 직접 배치, git 제외
```

## Smart Farm Twin에서 선택

```text
Smart Farm Twin
├─ Auto Asset   greenhouse.usd -> generic -> hoop 순서로 자동 탐색
├─ Generic      low poly generic green house 후보만 사용
└─ Hoop         hoop house 20x60 후보만 사용
```

선택 후 `Create Twin Scene`을 다시 누르면 4개 동 모두 같은 후보 greenhouse asset을 reference한다.

## 변환 후 파일명

현재 두 후보는 Kit asset converter로 아래 파일명까지 변환 완료되어 있다.

```text
greenhouse.usd
```

`usda`, `usdc`도 코드에서 탐색하지만, 비교 편의를 위해 `greenhouse.usd`로 맞추는 것을 권장한다.

## 현재 로컬 상태

```text
greenhouse_low_poly_generic/greenhouse.usd
greenhouse_hoop_house_20x60/greenhouse.usd
```

USD Composer에서 `Generic` 또는 `Hoop`을 누른 뒤 `Create Twin Scene`을 다시 누르면 4개동에 같은 후보 모델이 들어간다.
