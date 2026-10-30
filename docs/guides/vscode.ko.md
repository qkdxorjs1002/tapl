# VS Code 확장

[문서 홈](../README.ko.md) · [English](vscode.md)

TAPL Workflow Viewer는 VS Code에 활성 작업·아카이브 트리, 이력 검색, 대시보드를 추가합니다. 지속 연결하는 `tapl-mcp` stdio 클라이언트로 워크스페이스를 읽으며 브라우저 Viewer 서비스는 필요하지 않습니다.

## 설치와 열기

VS Code **1.90+**, `.tapl/tapl.db`가 있는 초기화된 워크스페이스, 실행 가능한 `tapl-mcp`가 필요합니다. 먼저 [설치](../getting-started/installation.ko.md)와 [에이전트 연결](../getting-started/integrations.ko.md)을 완료하세요.

Marketplace에서 `paragonnov.tapl-workflow-viewer`를 설치하거나 [GitHub Releases](https://github.com/qkdxorjs1002/tapl/releases)에서 `.vsix`를 받아 **Extensions: Install from VSIX…**를 실행합니다. 초기화한 폴더를 열고 활동 표시줄에서 **TAPL**을 선택한 뒤 **TAPL Workflow: Open TAPL Dashboard**를 실행하세요.

기본 검색 경로는 `PATH`, `/opt/homebrew/bin/tapl-mcp`, `/usr/local/bin/tapl-mcp`이며 Windows에서는 `tapl-mcp.exe`를 사용합니다. 필요하면 다음처럼 지정합니다.

```json
{
  "taplWorkflow.taplMcpPath": "/opt/homebrew/bin/tapl-mcp",
  "taplWorkflow.layout": "auto",
  "taplWorkflow.language": "auto"
}
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
| `taplWorkflow.taplMcpPath` | 명령 이름 또는 실행 파일 경로 | 빈 문자열: 자동 검색 |
| `taplWorkflow.layout` | `auto`, `small`, `medium`, `large` | `auto` |
| `taplWorkflow.language` | `auto`, `ko`, `en` | `auto`: VS Code 표시 언어 사용 |

## 워크스페이스와 세션 라우팅

처음에는 VS Code의 첫 번째 워크스페이스 폴더를 사용합니다. 여러 루트가 열린 창에서는 대시보드의 워크스페이스 선택기로 다른 열린 폴더를 고릅니다. 해당 폴더를 작업 디렉터리로 MCP 프로세스를 실행하며 실행 파일 설정도 그 폴더의 값을 적용합니다. DB를 찾기 위해 부모 폴더를 검색하지 않습니다.

연결은 워크스페이스별로 관리합니다. DB·WAL·SHM 파일(`.tapl/tapl.db`, `-wal`, `-shm`) 변경은 짧게 모아서 새로 고침합니다. 실행 파일 설정이 바뀌면 연결을 무효화하고, 워크스페이스가 바뀌면 대시보드 경로를 초기화합니다. RUN 선택은 워크스페이스별로 기억하며 선택한 소유자의 세션을 읽습니다. 늦게 도착한 읽기 결과는 더 최근의 화면 이동이나 워크스페이스 선택을 덮어쓰지 못합니다.

## 공유 Viewer와 기능 조건

브라우저와 확장은 React 화면, CSS, `src/viewer/types.ts`를 공유합니다. VS Code는 워크스페이스·MCP 어댑터를, 브라우저는 HTTP와 로컬 폴더 선택을 제공합니다. 둘 다 메모리 목록·검색·상세·원본 이동을 지원합니다. 메모리 수정과 삭제는 에이전트에게 명시적으로 요청해야 합니다.

지원 기능은 서버가 알려 줍니다. 메모리를 지원하지 않는 구버전 서버에서도 다른 화면은 사용할 수 있습니다. RUN **×** 폐기는 최신 서버가 기능 지원을 알릴 때만 제공하며 그 외에는 읽기 전용입니다. 대화상자에서 전체 RUN ID를 정확히 입력하고 명시적으로 확인해야 합니다. 보존할 기록은 아카이브하며 정말 빈 RUN은 삭제합니다. 외부 에이전트는 계속 실행됩니다. 정확한 영향은 [Viewer](viewer.ko.md#run-폐기)를 보세요.

## 검증과 진단

**Developer: Show Running Extensions**로 활성 상태를 확인합니다. 실행 파일 경로를 확인하고 필요하면 VS Code를 다시 시작한 뒤 **Refresh Workflow Views**를 실행하세요. 소스 변경 시 `vscode-extension`에서 실행합니다.

```sh
npm run test:host
npm run compile
```

호스트 테스트는 워크스페이스 라우팅, 새로 고침·화면 이동, 세션·메모리 화면, 실행 시간, 확인된 폐기를 다룹니다. 컴파일은 확장과 공유 webview를 번들링하고 브라우저 자산을 동기화합니다. 의존성 준비는 [기여와 검증](../development/contributing.ko.md), 문제 보고는 [문제 해결](troubleshooting.ko.md)을 참고하세요.
