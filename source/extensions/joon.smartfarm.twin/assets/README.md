# Smart Farm Twin Assets

외부 3D 모델을 이 폴더에 넣으면 `Create Twin Scene` 실행 시 reference로 배치한다.

## 현재 지원 파일명

```text
assets/
├─ local/                  로컬 전용 선택 자산, git 제외
│  ├─ greenhouse.usd       또는 greenhouse.usda / greenhouse.usdc
│  └─ strawberry_plant.usd 또는 strawberry_plant.usda / strawberry_plant.usdc
├─ official/               공식 asset pack 압축 해제 위치, git 제외
├─ greenhouse.usd          공유 가능한 작은 자산일 때만 사용
└─ strawberry_plant.usd    공유 가능한 작은 자산일 때만 사용
```

`Create Twin Scene` 실행 시 `assets/local/`을 먼저 찾고, 없으면 `assets/` 루트를 찾는다.

## 권장 작업 흐름

```text
GLB / glTF / FBX / OBJ 다운로드
  -> Omniverse Asset Importer로 USD 변환
  -> 위 파일명으로 assets/에 배치
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

현재 임시 연결:

```text
assets/local/strawberry_plant.usd
  -> assets/official/tower_demo/.../Assets/ArchVis/Residential/Plants/Plant_Succulent_01.usd
```

이 파일은 딸기 전용 모델이 아니라 외부 USD 참조 테스트용 식물 모델이다.

## Omniverse에서 확인하는 순서

```text
1. 앱 실행
2. Smart Farm Twin 창에서 Create Twin Scene
3. /World/SmartFarm/Plants 아래 Plant_* 확인
4. 식물 모델이 마음에 안 들면 assets/local/strawberry_plant.usd 링크 교체
5. 다시 Create Twin Scene
```

## 후보 탐색 명령

```bash
find source/extensions/joon.smartfarm.twin/assets/official -type f \( -name '*.usd' -o -name '*.usda' -o -name '*.usdc' \)
find source/extensions/joon.smartfarm.twin/assets/official -type f \( -name '*.usd' -o -name '*.usda' -o -name '*.usdc' \) | rg -i 'plant|grass|tree|garden|site|light|glass|planter'
```

## 라이선스 메모

모델 파일을 커밋하기 전 출처와 라이선스를 이 문서 또는 별도 `ASSET_LICENSES.md`에 기록한다.
