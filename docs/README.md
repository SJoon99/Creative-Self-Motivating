# Creative-Self-Motivating Docs

Omniverse Kit App Template 이해용 문서.

짧은 설명, 구조 그림, 실행 흐름 중심.

## 문서 지도

```mermaid
flowchart LR
    A[처음 보는 사람] --> B[01 디렉토리 지도]
    B --> C[02 빌드와 실행 흐름]
    C --> D[03 Kit 앱과 Extension]
    D --> E[04 Git 작업 흐름]
```

| 문서 | 내용 | 먼저 볼 때 |
|---|---|---|
| [01-directory-map.md](./01-directory-map.md) | 폴더별 역할 | "뭐가 어디 있지?" |
| [02-build-and-launch-flow.md](./02-build-and-launch-flow.md) | `repo.sh` 기준 동작 흐름 | "빌드/실행 때 무슨 일이?" |
| [03-kit-app-and-extension.md](./03-kit-app-and-extension.md) | `.kit`, 앱, Extension 관계 | "Kit 구조 감 잡기" |
| [04-git-workflow.md](./04-git-workflow.md) | 이 저장소 Git 관리 방식 | "GitHub에 어떻게 올리지?" |

## 현재 프로젝트 핵심

```text
Creative-Self-Motivating
├─ source/apps/joon.my_editor.kit     실제 생성된 앱 정의
├─ source/extensions/joon.smartfarm.twin/
│                                      Python UI Extension 템플릿 결과
├─ premake5.lua                       빌드 대상 앱 등록
├─ repo.toml                          repo tool 전체 설정
├─ templates/                         새 앱/Extension 생성용 원본
├─ tools/                             repo/packman 도구
└─ docs/                              한국어 이해 문서
```

## 제일 중요한 3개 파일

| 파일 | 의미 |
|---|---|
| `source/apps/joon.my_editor.kit` | 앱의 메뉴, 창 제목, 의존 Extension, 렌더러 설정 |
| `source/extensions/joon.smartfarm.twin/config/extension.toml` | Extension 이름, 버전, Python 모듈 설정 |
| `premake5.lua` | `define_app("joon.my_editor.kit")`로 빌드 대상 지정 |
| `repo.toml` | SDK, 빌드, 패키징, precache, registry 설정 |

## 빠른 명령

```bash
./repo.sh template new   # 새 앱/Extension 생성
./repo.sh build          # 빌드
./repo.sh launch         # 실행
./repo.sh test           # 테스트
./repo.sh package        # 패키징
```
