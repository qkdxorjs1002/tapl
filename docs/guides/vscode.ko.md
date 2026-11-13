# VS Code 확장

[문서 홈](../README.ko.md) · [English](vscode.md)

TAPL Workflow Viewer는 VS Code에 활성 작업·아카이브 트리, 이력 검색, 대시보드를 추가합니다. 지속 연결하는 `tapl-mcp` stdio 클라이언트로 워크스페이스를 읽으며 브라우저 Viewer 서비스는 필요하지 않습니다.

공유 DB의 검색 결과·상세·RUN 선택은 원본을 유지합니다. 다른 환경 RUN의 닫기 동작은 제공하지 않습니다. [로컬 식별자와 공유 이력](storage.ko.md)을 참고하세요.

## 설치와 열기

VS Code **1.90+**, `.tapl/tapl-{UUID}.db`가 있는 초기화된 워크스페이스, 실행 가능한 `tapl-mcp`가 필요합니다. 먼저 [설치](../getting-started/installation.ko.md)와 [에이전트 연결](../getting-started/integrations.ko.md)을 완료하세요.

Marketplace에서 `paragonnov.tapl-workflow-viewer`를 설치하거나 [GitHub Releases](https://github.com/qkdxorjs1002/tapl/releases)에서 `.vsix`를 받아 **Extensions: Install from VSIX…**를 실행합니다. 초기화한 폴더를 열고 활동 표시줄에서 **TAPL**을 선택한 뒤 **TAPL Workflow: Open TAPL Dashboard**를 실행하세요.

대시보드는 VS Code에서 연 워크스페이스를 사용하며 워크스페이스 변경 버튼이나 폴더 선택 모달을 표시하지 않습니다. Viewer 내부의 폴더 선택은 [웹 Viewer](viewer.ko.md#viewer-탐색)에서만 제공합니다.

기본 검색 경로는 `PATH`, `/opt/homebrew/bin/tapl-mcp`, `/usr/local/bin/tapl-mcp`이며 Windows에서는 `tapl-mcp.exe`를 사용합니다. 필요하면 다음처럼 지정합니다.

```toml
# .tapl/config.toml (or ~/.tapl/config.toml)
[viewer]
mcp_path = "/opt/homebrew/bin/tapl-mcp"
layout = "auto"
language = "auto"
```

## 명령과 설정

| 명령 ID | 명령 팔레트 영문 이름 | 용도 |
| --- | --- | --- |
| `taplWorkflow.refresh` | Refresh Workflow Views | 트리와 열린 대시보드 새로 고침. |
| `taplWorkflow.openOverview` | Open TAPL Dashboard | 워크스페이스 대시보드 열기. |
| `taplWorkflow.openArchive` | Open TAPL Archive | 아카이브 트리에서 선택한 항목 열기. |
| `taplWorkflow.search` | Search TAPL Workflow | 워크스페이스의 이전 기록 검색. |

위 이름은 **TAPL Workflow** 범주의 영문 표기이며 UI는 한국어도 지원합니다.

| 설정 | 허용 값 | 기본값 |
| --- | --- | --- |
| `viewer.mcp_path` | 명령 이름 또는 실행 파일 경로 | 빈 문자열: 자동 검색 |
| `viewer.layout` | `auto`, `small`, `medium`, `large` | `auto` |
| `viewer.language` | `auto`, `ko`, `en` | `auto`: VS Code 표시 언어 사용 |

이 값은 VS Code 설정 대신 [TAPL 설정 파일](configuration.ko.md#작업-공간과-파일-선택)에서 관리합니다. MCP 실행 전 TOML을 직접 읽으므로 커스텀 경로로도 초기 연결할 수 있습니다. 설정 페이지에서 저장하면 언어·레이아웃이 적용되고 파일을 외부에서 바꿔도 갱신됩니다. 워크스페이스에 정의한 실행 파일이나 작업공간 기준 상대 실행 파일은 Workspace Trust를 따라야 합니다. 잘못된 MCP 경로로 연결하지 못하면 파일을 직접 고치거나 `taplctl config unset viewer.mcp_path`로 자동 검색을 복원하세요.

## 워크스페이스와 세션 라우팅

처음에는 VS Code의 첫 번째 워크스페이스 폴더를 사용합니다. 폴더는 VS Code에서 변경하며 Viewer 내부에서는 선택기를 표시하지 않습니다. 해당 폴더를 작업 디렉터리로 MCP 프로세스를 실행하며 실행 파일 설정도 그 폴더의 값을 적용합니다. DB를 찾기 위해 부모 폴더를 검색하지 않습니다.

연결은 워크스페이스별로 관리합니다. DB·WAL 이벤트를 2초 동안 모은 뒤 DB 또는 데이터 프레임이 있는 WAL의 변경을 확인합니다. SHM 관리 작업이나 빈 WAL 생성·삭제만으로는 화면을 다시 조회하지 않습니다. 겹치는 갱신 요청은 합치며 조회 도중 변경이 발생하면 후속 확인을 예약합니다. 숨겨지거나 포커스가 없는 Viewer 패널은 데이터 조회를 미루고, 다시 표시되고 포커스를 얻으면 최신 상태를 반영합니다. **Refresh Workflow Views**는 계속 강제 갱신합니다.

실행 파일 설정이 바뀌면 연결을 무효화하고, 워크스페이스가 바뀌면 대시보드 경로를 초기화합니다. RUN 선택은 워크스페이스별로 기억하며 선택한 소유자의 세션을 읽습니다. 늦게 도착한 읽기 결과는 더 최근의 화면 이동이나 워크스페이스 선택을 덮어쓰지 못합니다. webview는 작은 UI 선호·탐색 상태를 보존하며 다시 로드할 때 화면 데이터를 TAPL에서 조회합니다.

## 공유 Viewer와 기능 조건

브라우저와 확장은 React 화면, CSS, `src/viewer/types.ts`를 공유합니다. VS Code는 워크스페이스·MCP 어댑터를, 브라우저는 HTTP와 로컬 폴더 선택을 제공합니다. 둘 다 메모리 목록·검색·상세·원본 이동을 지원합니다. 메모리 수정과 삭제는 에이전트에게 명시적으로 요청해야 합니다.

지원 기능은 서버가 알려 줍니다. 메모리를 지원하지 않는 구버전 서버에서도 다른 화면은 사용할 수 있습니다. **관리 → RUN 삭제**는 최신 서버가 기능 지원을 알릴 때만 제공하며 그 외에는 RUN 기록이 읽기 전용입니다. 대화상자에서 전체 RUN ID를 정확히 입력하고 명시적으로 확인해야 합니다. 보존할 기록은 아카이브하며 정말 빈 RUN은 삭제합니다. 외부 에이전트는 계속 실행됩니다. 정확한 영향은 [Viewer](viewer.ko.md#run-폐기)를 보세요.

현재 RUN 및 워크스페이스 중심 기억 관계 마인드맵·고정 RUN 탭·축소 아이콘 탐색과 고정/호버 확장·탐색 확장 패널·RUN별 TASK 필터·기록 검색·돌아가기는 [공유 Viewer 탐색](viewer.ko.md#viewer-탐색)을 참고하세요. `small`은 탐색 서랍을 사용하며 다른 레이아웃은 너비가 충분하면 고정 구조를 유지합니다. 정확한 과거 RUN 페이지와 기록 목록은 워크스페이스 MCP 서버도 업데이트해야 합니다. 미지원 메모리는 기능 조건으로 구분합니다.

**관리 → 설정**에서 `taplctl config`의 모든 선호를 편집·저장·초기화하며 표시 언어도 선택합니다. MCP 서버가 설정 도구를 지원해야 하며 구버전은 업데이트 안내를 표시합니다. 파일 범위·revision 충돌·초기화는 [Viewer 설정](configuration.ko.md#viewer-설정)을 참고하세요.

## 검증과 진단

**Developer: Show Running Extensions**로 활성 상태를 확인합니다. 실행 파일 경로를 확인하고 필요하면 VS Code를 다시 시작한 뒤 **Refresh Workflow Views**를 실행하세요. 소스 변경 시 `vscode-extension`에서 실행합니다.

```sh
npm run test:host
npm run compile
```

호스트 테스트는 워크스페이스 라우팅, 새로 고침·화면 이동, 세션·메모리 화면, 실행 시간, 확인된 폐기를 다룹니다. 컴파일은 확장과 공유 webview를 번들링하고 브라우저 자산을 동기화합니다. 의존성 준비는 [기여와 검증](../development/contributing.ko.md), 문제 보고는 [문제 해결](troubleshooting.ko.md)을 참고하세요.
