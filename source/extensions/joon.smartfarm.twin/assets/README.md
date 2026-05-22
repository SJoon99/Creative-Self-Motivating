# Smart Farm Twin Assets

외부 3D 모델을 이 폴더에 넣으면 `Create Twin Scene` 실행 시 reference로 배치한다.

## 현재 지원 파일명

```text
assets/
├─ greenhouse.usd          또는 greenhouse.usda / greenhouse.usdc
└─ strawberry_plant.usd    또는 strawberry_plant.usda / strawberry_plant.usdc
```

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

## 라이선스 메모

모델 파일을 커밋하기 전 출처와 라이선스를 이 문서 또는 별도 `ASSET_LICENSES.md`에 기록한다.
