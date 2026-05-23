# Smart Farm Twin Assets

외부 3D 모델을 이 폴더에 넣으면 `Create Twin Scene` 실행 시 reference로 배치한다.

## 현재 지원 파일명

```text
assets/
├─ official/               공식 asset pack 압축 해제 위치, git 제외
├─ candidates/             외부 후보 모델 비교 위치, 모델 파일 git 제외
├─ greenhouse.usd          또는 greenhouse.usda / greenhouse.usdc
└─ strawberry_plant.usd    또는 strawberry_plant.usda / strawberry_plant.usdc
```

`Create Twin Scene` 실행 시 위 파일명 또는 `candidates/` 후보 USD가 있을 때 외부 USD를 참조한다.
위 파일명은 symlink로 쓸 수 있고 git에서 제외한다.

## Greenhouse 후보 비교

```text
candidates/
├─ greenhouse_low_poly_generic/
│  └─ greenhouse.usd
│
└─ greenhouse_hoop_house_20x60/
   └─ greenhouse.usd
```

Smart Farm Twin UI:

```text
Auto Asset   greenhouse.usd -> generic -> hoop 순서
Generic      greenhouse_low_poly_generic만 사용
Hoop         greenhouse_hoop_house_20x60만 사용
```

선택 후 `Create Twin Scene`을 다시 누른다.

## 권장 작업 흐름

```text
GLB / glTF / FBX / OBJ 다운로드
  -> Omniverse Asset Importer로 USD 변환
  -> 위 파일명으로 assets/ 또는 assets/candidates/<후보>/에 배치
  -> ./repo.sh build
  -> ./repo.sh launch
  -> Create Twin Scene
```

## fallback

파일이 없으면 extension.py가 primitive proxy 온실/딸기 식물을 생성한다.

## 공식 asset pack 로컬 배치

```text
assets/official/
├─ aec_demo/       AECDemo_NVD@10012.zip 압축 해제
└─ tower_demo/     AECO_TowerDemoPack_NVD@10012.zip 압축 해제
```

현재 자동 연결된 공식 asset pack USD는 없다.

## Omniverse에서 확인하는 순서

```text
1. 앱 실행
2. Content Browser 또는 File > Open으로 assets/official/ 아래 USD 직접 확인
3. 사용할 USD를 정하면 greenhouse.usd 또는 strawberry_plant.usd로 연결
4. Smart Farm Twin 창에서 Create Twin Scene
```

## 후보 탐색 명령

```bash
find source/extensions/joon.smartfarm.twin/assets/official -type f \( -name '*.usd' -o -name '*.usda' -o -name '*.usdc' \)
find source/extensions/joon.smartfarm.twin/assets/official -type f \( -name '*.usd' -o -name '*.usda' -o -name '*.usdc' \) | rg -i 'plant|grass|tree|garden|site|light|glass|planter'
```

## 라이선스 메모

모델 파일을 커밋하기 전 출처와 라이선스를 이 문서 또는 별도 `ASSET_LICENSES.md`에 기록한다.
