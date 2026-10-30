# 빠른 시작

[문서 홈](../README.ko.md) · [English](quickstart.md)

TAPL을 설치하고 Codex에 연결한 뒤 평소처럼 작업을 요청하세요. Codex가 워크플로 기록을 관리하므로 PLAN이나 TASK를 직접 작성할 필요가 없습니다.

## 1. TAPL 설치

macOS의 Homebrew에서는 다음과 같이 설치합니다.

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl
```

Linux·Windows·시맨틱 검색·프리릴리즈는 [설치 안내](installation.ko.md)를 따르세요. 설치를 맡기려면 [Agent 설치 프롬프트](integrations.ko.md#agent에게-tapl-설치-맡기기)를 복사합니다.

## 2. 연결 범위 하나 선택

| 범위 | 선택할 때 | 명령 |
| --- | --- | --- |
| User | Codex 프로젝트 전반에서 TAPL을 사용할 때 | `taplctl install user` |
| Repository | 대상 저장소에서만 TAPL을 사용할 때 | `taplctl install repo` |

`repo`는 대상 저장소에서 실행하거나 `--repo /path/to/repository`를 추가하세요. 독립 설치는 [실제 실행 파일 경로](integrations.ko.md#독립-설치의-실행-파일-경로)가 필요할 수 있습니다.

Codex를 재시작하고 요청이 나타나면 설치된 hook을 신뢰하세요. 원하는 작업 폴더를 엽니다. TAPL은 그 정확한 폴더의 `.tapl/tapl.db`를 사용하며 하위 폴더의 이력은 별개입니다.

## 3. 설치 확인

의도한 작업 폴더에서 실행합니다.

```sh
taplctl --version
taplctl doctor
```

출력된 버전, DB 경로, SQLite 기능과 의존성을 확인하세요. 시맨틱 의존성은 선택 사항입니다. `doctor`는 작업 공간 상태를 초기화하거나 기존 연결을 갱신할 수 있습니다.

## 4. 원하는 결과 요청

예를 들어 다음과 같이 요청합니다.

> 테스트 명령이 실패하는 이유를 조사하고 원인을 수정한 뒤 관련 검사를 실행해 줘.

Codex는 현재 TAPL 정책과 세션 상태를 읽고 요청을 분류하며 관련 이력을 확인하고 필요한 작업을 계획합니다. 수정·테스트를 명시적으로 요청하면 그 범위의 실행 승인으로 취급합니다. 중요한 범위나 선택지가 미정이면 추가 확인이 필요할 수 있습니다.

**Implementation · Standard · Planned** 같은 RUN 분류와 간결한 계획·실행·검증 안내가 표시됩니다. 실제 분류는 작업에 따라 달라집니다. 보안·권한 변경에는 Strict 엄격도가 필요하고 Fast의 비영구 답변에는 PLAN·TASK가 필요 없을 수 있습니다.

계획형 작업에서는 Agent가 계획과 Task를 기록하고 승인된 작업을 실행·검증하며 의사결정에 영향을 주는 발견 사항을 남깁니다. 완료 시 유용한 기억 후보를 검토하고 결과를 기록한 뒤 남은 작업과 기억 오류를 해결하고 아카이브합니다. 계획만 요청한 경우 실행이나 종료를 선택할 때까지 활성 상태를 유지합니다.

## 5. 결과 확인

같은 폴더에서 Viewer를 시작합니다.

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000
```

브라우저에서 <http://127.0.0.1:8000>을 열어 선택한 RUN, 계획, Task, 발견 사항, 아카이브와 기억을 확인합니다. 브라우저는 자동으로 열리지 않으며 `Ctrl+C`로 서버를 종료합니다. 8000번 포트가 사용 중이면 `taplctl viewer --port 9000`을 사용하세요.

다음 작업에서는 Codex에 관련 이전 작업을 찾거나 현재 세션의 작업을 이어 달라고 요청할 수 있습니다. 같은 폴더에서도 세션 소유 RUN은 격리되지만 작업 파일은 공유합니다. [워크플로 경계](../concepts/workflow.ko.md#작업-공간과-세션-경계)를 참고하세요.

## 다음 단계와 제약

- [워크플로](../concepts/workflow.ko.md): 모드·승인·검증·종료.
- [기록 구조와 메타데이터](../concepts/records.ko.md): 저장 항목과 읽는 방법.
- [설정](../guides/configuration.ko.md): 사용자·작업 공간 설정과 기본값.
- [Viewer](../guides/viewer.ko.md)와 [VS Code](../guides/vscode.ko.md): 두 인터페이스에서 작업 확인.
- [문제 해결](../guides/troubleshooting.ko.md): 도구 누락·hook 신뢰·경로·런타임 문제.

TAPL 업데이트 뒤 기존 연결 범위는 자동 갱신되므로 보통 재연결이 필요 없습니다. 호스트 설정을 다시 읽어야 할 때 Codex를 재시작하세요. TAPL의 워크플로 기록은 동시 파일 편집을 격리하거나 버전 관리 절차를 대신하지 않습니다.
