# 기여와 검증

[문서 홈](../README.ko.md) · [English](contributing.md)

소스 체크아웃 환경을 준비하고 변경 경계에 맞는 검증을 선택하며 공개 문서를 유지하는 안내입니다. 구현 구조는 [아키텍처](architecture.ko.md), 로컬 개발과 구분되는 게시 절차는 [릴리스](releases.ko.md)를 참고하세요.

## 개발 환경

Python 패키지는 **Python 3.11+**가 필요하며 런타임 의존성은 `mcp==2.0.0`으로 고정되어 있습니다. `test` extra는 pytest·PyYAML·wheel, `semantic` extra는 NumPy·sentence-transformers·sqlite-vec를 선언합니다. 패키지의 해석된 환경은 `uv.lock`을 사용합니다.

저장소 루트에서 실행합니다.

```sh
uv --directory tapl sync --extra test
uv --directory tapl run --extra test python -m unittest discover -s tests
uv --directory tapl run --extra test python -m pytest -q tests
uv --directory tapl build
```

저장소에는 unittest와 pytest 함수 방식의 테스트가 함께 있습니다. Unittest discovery만으로 모든 pytest 함수를 실행하지 못합니다. 의미 검색 작업에는 선택 환경을 포함합니다.

```sh
uv --directory tapl sync --extra test --extra semantic
```

확장은 TypeScript·React·Vite·MCP TypeScript SDK를 사용하며 릴리스 CI는 **Node.js 22**를 사용합니다. 저장소 루트에서 준비·검증합니다.

```sh
npm --prefix vscode-extension install --package-lock=false
npm --prefix vscode-extension run test:host
npm --prefix vscode-extension run compile
```

`test:host`는 TypeScript 컴파일 후 Node 테스트 러너로 `tests/*.cjs`를 실행합니다. `compile`은 확장 번들·webview를 빌드하고 Python 브라우저 자산을 동기화합니다. 공유 Viewer 변경 후 실행하며 수정의 원본으로 컴파일된 `_viewer/assets`를 직접 편집하지 않습니다. `vscode-extension`에서 사용하는 패키징 명령은 `npm run package`, `npm run package:pre-release`이며 로컬 패키지 생성이지 게시 명령이 아닙니다.

## 의미 있는 검사 선택

| 변경 경계 | 관련 검사 |
| --- | --- |
| 애플리케이션·MCP·세션 라우팅 | `test_application.py`, `test_mcp_native.py`, `test_session_mcp.py`, `test_cli_boundary.py` |
| 정책 진입·축약 응답·지침 | `test_context_optimization.py`, `test_compact_item.py`, authoring-detail·기록 작성 테스트 |
| 계획·작업·의존성·배치 실행 | `test_tapl.py`, 애플리케이션·세션 테스트, `test_execution_timing.py` |
| 브라우저·공유 Viewer·폐기 | `test_viewer.py`, `test_viewer_native.py`, `test_viewer_discard.py`, `test_run_discard.py`, 확장 `test:host`·`compile` |
| 메모리·검색 | `test_recall*.py`, `test_memory_review.py`, `test_search.py`, 메모리 확장 테스트 |
| 설치·릴리스 | 설치·업데이트·제거 테스트, `test_release_version.py`, `test_release_packaging.py`, Homebrew·macOS 서명 테스트 |
| Windows 런타임 | `test_windows_runtime.py`, Windows 설치기·bootstrap 테스트, Windows 수명주기 workflow |

예를 들어 세션 변경은 다음처럼 검증합니다.

```sh
uv --directory tapl run --extra test python -m pytest -q tests/test_session_mcp.py tests/test_session_runs.py
```

동작을 수정할 때는 대상 테스트를, 완료 보고 전에는 관련 전체 테스트를 실행합니다. 프로젝트 지침에 따라 격리 환경에서 실제 Codex 대화 테스트가 필요하면 **morae-mcp**을 사용해야 합니다. 로컬 단위 테스트는 실제 호스트 대화 성공의 근거가 아닙니다. 비공개 실험 대화나 도구를 공개 검증 자료로 게시하지 마세요.

플랫폼 검증 범위는 다릅니다. Windows CI는 PowerShell 5.1로 설치기 구문을 검사하고 Python 3.11/3.12, 실제 wheel, 설치·업데이트·재설치·제거와 CLI·MCP 런타임을 검증합니다. macOS 서명 보존은 전용 Homebrew workflow가 필요하며 Linux 단위 테스트로 설치 후 Developer ID 서명 보존을 입증할 수 없습니다. [릴리스](releases.ko.md)를 보세요.

## 영문·국문 문서 유지

루트 README는 프로젝트 목적·핵심 기능·빠른 시작·링크를 간결하게 유지합니다. 상세 동작·설정·예제·제약·검증은 `docs/` 주제 페이지에 둡니다. 공개 주제 목록은 [영문 홈](../README.md)과 [국문 홈](../README.ko.md)이 기준입니다.

동작 변경 시 영향받는 사용자 행동, CLI·MCP 인자, 설정·기본값, 설치·업데이트, Viewer, 제약·문제 해결을 같은 변경에서 검토합니다. 불필요해진 우회 방법은 제거합니다. 문서 변경이 필요 없으면 변경 검토에 짧게 이유를 남깁니다.

대응하는 `.md`·`.ko.md`는 동작·명령 예제·설정값을 일치시킵니다. 다른 페이지에서는 설명을 복사하지 말고 해당 주제의 기준 설명에 링크합니다. 각 주제 페이지에 문서 홈과 언어 전환 링크를 둡니다. 주제 추가·이동 시 양쪽 홈과 관련 링크를 갱신하고 공개 경로·앵커는 호환 목차나 앵커로 유지합니다.

현재 구현·테스트·명령 도움말을 근거로 설명합니다. 소스의 정적 패키지 버전은 최신 배포 버전의 근거가 아닙니다. 공개 검증에는 승인된 집계값·발췌, 측정 조건과 해석 한계만 넣습니다. 보고 수치를 바꾸면 기준 대비 증감률도 재계산합니다. 비공개 실험 원문·개별 기록·대화·전용 도구는 공개 문서와 커밋에 넣지 않습니다.

문서 변경 완료 전에 실행합니다.

```sh
git diff --check
```

상대 링크·앵커, 실제 명령 옵션, 영문·국문 대응, Markdown 렌더링 구조도 확인합니다. 문서 검사 과정에서 상태를 바꾸는 수명주기 예제를 실행하지 마세요. 설명용 호출은 [MCP 참조](../reference/mcp.ko.md), 공개 측정 범위는 [기준 벤치마크](../reference/benchmarks.ko.md)를 보세요.

## 검토와 커밋

적용되는 프로젝트 지침을 따르고 적절하다면 유사 작업의 최신 브랜치를 사용하며 승인된 워크스페이스 변경을 커밋합니다. 다른 기여자의 편집을 보존하고 워크플로 DB·비공개 실험 자료는 커밋에서 제외합니다. 검토에는 구체적 동작 변경, 검증 근거, 남은 주요 한계를 작성합니다. 설치·릴리스 게시·외부 서비스 변경은 별도 범위가 필요하며 로컬 빌드 성공만으로 게시되지는 않습니다.
