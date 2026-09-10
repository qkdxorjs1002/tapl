<p align="center">
  <img src="assets/readme/tapl-logo.png" alt="TAPL 로고" width="120" />
</p>
<h1 align="center">tapl</h1>
<p align="center"><strong>코딩 에이전트에게 기억을.</strong></p>
<p align="center">요청부터 계획, 발견 사항, 완료 기록까지 코드 옆에 남겨 다음 세션에서도 이어갑니다.</p>

<p align="center">
  <a href="README.md">English</a> · <strong>한국어</strong>
</p>
<p align="center">
  <a href="https://github.com/qkdxorjs1002/tapl/releases"><img src="https://img.shields.io/github/v/release/qkdxorjs1002/tapl" alt="GitHub 안정 릴리즈" /></a>
  <a href="docs/guide.ko.md#requirements"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&amp;logoColor=white" alt="Python 3.11 이상" /></a>
  <a href="LICENSE.md"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT 라이선스" /></a>
</p>
<p align="center">
  <a href="#quick-start">빠른 시작</a> · <a href="#workflow">진행 예시</a> · <a href="docs/guide.ko.md">설치·운영 가이드</a>
</p>

## 왜 TAPL인가요?

대화가 길어지거나 세션이 바뀌어도, 작업의 맥락은 저장소에 남아 있어야 합니다.
TAPL은 Codex의 요청, 계획, 승인, 작업, 발견 사항과 이력을 로컬 SQLite 데이터베이스에 보관합니다.

- **중단한 곳에서 이어갑니다.** 완료한 일과 남은 일을 다시 설명할 필요가 줄어듭니다.
- **코드 옆에 기록합니다.** 저장소의 `.tapl/tapl.db`에 작업 상태와 근거가 함께 남습니다.
- **이전 결정을 찾습니다.** 전문 검색을 기본 제공하며, 시맨틱 검색을 선택할 수 있습니다.
- **진행 상황을 확인합니다.** 대화의 단계별 안내와 로컬 viewer로 계획과 작업 상태를 살펴봅니다.
- **병렬 작업의 경계를 정합니다.** 작업 의존성과 파일 소유 범위를 확인해 위임을 조율합니다.

<a id="workflow"></a>

## 작업 흐름 보기

Codex에게 평소처럼 요청하세요.

> 권한 검사 누락의 원인을 조사하고 근거를 정리해줘.

<p align="center">
  <img src="assets/readme/workflow-ko.gif" alt="권한 검사 누락 조사 요청이 RUN 분류, HISTORY 검색, PLAN 수립, TASK 조사, FINDING 근거 기록, ARCHIVE 보관으로 진행되는 예시" width="100%" />
</p>

[정적인 전체 예시 보기](assets/readme/workflow-ko.png)

위 화면은 **공개 진행 메시지를 재구성한 예시**이며 실제 세션 캡처가 아닙니다.
에이전트가 알리는 단계와 기록하는 근거, 작업 상태를 순서대로 보여 줍니다.

| 단계 | 이 예시에서 하는 일 |
| --- | --- |
| `RUN` | 요청을 `Investigation · Strict · Planned`로 분류합니다. |
| `HISTORY` | 관련된 이전 작업과 결정을 찾습니다. |
| `PLAN` | 권한 검사 호출 경로와 확인할 근거를 조사 계획에 정리합니다. |
| `TASK` | 계획에 따라 권한 검사 경로를 조사합니다. |
| `FINDING` | 확인한 원인과 근거를 기록합니다. |
| `ARCHIVE` | 결과를 보관해 다음 세션에서 찾을 수 있게 합니다. |

`RUN → HISTORY → PLAN → TASK → FINDING → ARCHIVE`는 이 조사 예시의 순서입니다.
권한과 관련된 조사이므로 `Strict`, 계획과 작업 기록을 사용하는 흐름이므로 `Planned`입니다.
모든 요청이 이 단계를 거치는 것은 아닙니다. 간단한 읽기 전용 요청은 더 적은 단계로 끝날 수 있습니다.
수정·테스트·구현·검증을 직접 요청하는 것도 실행 승인에 해당합니다.

<a id="quick-start"></a>

## 빠른 시작

macOS에서는 Homebrew로 안정판을 설치하고 Codex에 연결합니다.

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl
taplctl install user
```

1. TAPL MCP 서버와 hook을 읽도록 **Codex를 재시작**합니다.
2. Codex가 처음 확인을 요청하면 **설치된 hook을 신뢰**합니다.
3. 저장소에서 **평소처럼 작업을 요청**합니다.

TAPL이 작업 공간에 `.tapl/tapl.db`를 만들고, Codex가 MCP를 통해 기록을 관리합니다.
작업을 기록하기 위한 CLI 명령을 따로 익힐 필요는 없습니다.

[Linux 설치](docs/guide.ko.md#linux)와 [Windows 설치](docs/guide.ko.md#windows)는 가이드를 참고하세요.
설치 후 [운영체제별 Codex 연결 명령](docs/guide.ko.md#connect)을 실행합니다.

## 설치

| 플랫폼·채널 | 설치 방법 | 안내 |
| --- | --- | --- |
| macOS · 안정판 | Homebrew `taplctl` | [전문 검색 포함](docs/guide.ko.md#homebrew) |
| macOS · 안정판 + 시맨틱 검색 | Homebrew `taplctl-semantic` | [선택 의존성 포함](docs/guide.ko.md#homebrew) |
| macOS · 프리릴리즈 포함 최신 채널 | Homebrew `taplctl-pre` | [채널 선택](docs/guide.ko.md#homebrew) |
| Linux · 안정판 기본 | 독립형 셸 설치 스크립트 | [설치 및 경로 설정](docs/guide.ko.md#linux) |
| Windows 10/11 · 안정판 기본 | 독립형 PowerShell 설치 스크립트 | [설치 및 경로 설정](docs/guide.ko.md#windows) |

Python 3.11 이상이 필요합니다. Homebrew의 세 formula는 서로 충돌하므로 하나만 설치하세요.
자세한 의존성, 업데이트, 설정은 [설치·운영 가이드](docs/guide.ko.md)에서 확인할 수 있습니다.

## Viewer 열기

초기화된 저장소에서 실행하세요.

```sh
taplctl viewer
# http://127.0.0.1:8000
```

브라우저에서 [127.0.0.1:8000](http://127.0.0.1:8000)을 직접 열면 계획, 작업, 발견 사항과 이력을 볼 수 있습니다.
브라우저는 자동으로 열리지 않으며, `Ctrl+C`로 viewer를 종료합니다.

8000 포트가 사용 중이면 `taplctl viewer --port 9000`을 사용하세요.
작업 공간 없이 시작하면 viewer에서 초기화된 저장소 폴더를 선택할 수 있습니다.
서비스 자동 시작과 리버스 프록시는 [Viewer 운영 안내](docs/guide.ko.md#viewer)를 참고하세요.

VS Code에서도 [선택 확장 기능](vscode-extension/README.md)으로 작업 기록을 볼 수 있습니다.

## 동작 방식

```mermaid
flowchart LR
    A[Codex] --> B[tapl-mcp]
    A --> C[tapl-hook]
    B <--> D[(.tapl/tapl.db)]
    C <--> D
    D --> E[로컬 Viewer]
```

- **`tapl-mcp`**가 워크플로 기록 생성, 조회, 검색과 작업 상태 관리를 수행합니다.
- **`tapl-hook`**이 Codex의 수명 주기 지점에 현재 상태를 전달하고 실행 승인 경계를 확인합니다.
- **`taplctl`**은 설치, 진단, 업데이트, 설정과 viewer 등 관리 작업을 담당합니다.

SQLite 데이터베이스가 이 구성 요소들이 공유하는 작업 기록의 기준입니다.
SubAgent의 생성과 관리는 Codex 런타임이 담당하고, TAPL은 의존성과 실행 범위를 조율합니다.
[위임 설정과 프로필](docs/guide.ko.md#subagents)에서 동작을 조정할 수 있습니다.

## 문서

- [설치·운영 가이드](docs/guide.ko.md) — 플랫폼별 설치, 업데이트, 설정, 문제 해결
- [VS Code 확장 기능](vscode-extension/README.md) — 편집기에서 작업 기록 보기
- [GitHub Issues](https://github.com/qkdxorjs1002/tapl/issues) — 버그 신고와 기능 제안

## 개발

저장소 루트에서 실행합니다.

```sh
uv --directory tapl sync --extra test
uv --directory tapl run --extra test python -m unittest discover -s tests
uv --directory tapl build
npm --prefix vscode-extension run compile
git diff --check
```

시맨틱 검색을 개발할 때는 `uv --directory tapl sync --extra semantic`을 사용하세요.

## 라이선스

[MIT](LICENSE.md)
