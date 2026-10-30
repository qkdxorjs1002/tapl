# 문제 해결

[문서 홈](../README.ko.md) · [English](troubleshooting.md)

Codex가 TAPL을 사용하는 작업 폴더에서 시작하세요. 워크스페이스는 해당 폴더의 `.tapl/tapl.db`를 사용하며 부모 DB를 검색하지 않습니다. 기록이 없어 보인다면 설치 범위, 설정 범위, 활성 세션 식별자도 확인해야 합니다.

## 런타임과 설정 확인

```sh
taplctl --version
taplctl doctor --json
taplctl config get
```

`doctor`는 DB 경로, SQLite·런타임 정보, 적용 설정을 보고합니다. DB를 여는 명령은 누락된 DB를 초기화할 수 있으므로 의도한 워크스페이스에서 실행하세요. 다른 폴더에서 진단한 결과가 원래 워크스페이스를 나타낸다고 가정하지 마세요.

| 증상 | 확인과 해결 |
| --- | --- |
| Codex에 TAPL 도구가 보이지 않음 | `taplctl doctor`를 실행하고 [에이전트 연결](../getting-started/integrations.ko.md)에서 설치 방식·선택 범위에 맞는 연결 명령을 다시 실행한 뒤 Codex를 재시작합니다. |
| 독립 설치 후 `taplctl`을 찾지 못함 | 설치기가 출력한 `PATH` export를 적용하고 셸 프로필에 저장한 뒤 터미널을 다시 엽니다. Windows도 PATH 갱신 후 셸을 다시 엽니다. |
| 설치 버전이나 채널이 예상과 다름 | `taplctl --version`을 설치 채널·메타데이터와 비교합니다. Homebrew 설치는 Homebrew로, 설치기 관리 설치는 `taplctl update`로 갱신합니다. [설치](../getting-started/installation.ko.md)를 참고하세요. |
| Homebrew formula 충돌 | 기존 TAPL formula를 제거한 뒤 `taplctl`, `taplctl-semantic`, `taplctl-pre` 중 하나를 고릅니다. 같은 명령을 제공합니다. |
| 설정 변경이 적용되지 않음 | `taplctl config get`의 적용 값과 경로를 확인합니다. 명시적 설정이나 저장소 설정이 사용자 설정과 다른 파일을 선택할 수 있습니다. [설정](configuration.ko.md)을 보세요. |

## Viewer와 VS Code

| 증상 | 확인과 해결 |
| --- | --- |
| Viewer에서 워크스페이스를 요청함 | `.tapl/tapl.db`가 있는 폴더를 선택하거나 `taplctl init --workspace-root /path/to/workspace`로 의도한 폴더를 초기화합니다. 로그인 서비스는 저장소 밖에서 시작할 수 있습니다. |
| 8000 포트 사용 중 | 해당 Homebrew 서비스를 멈추거나 `taplctl viewer --port 9000`을 실행합니다. 여러 formula 서비스가 같은 기본 포트를 사용합니다. |
| 프록시·터널에서 `Origin is not allowed.` 표시 | 공개 HTTP(S) origin을 `--allowed-origin` 또는 `viewer.allowed_origins`로 정확히 허용하고 서비스를 재시작합니다. origin에는 경로가 없습니다. [Viewer](viewer.ko.md#역방향-프록시와-터널)를 보세요. |
| RUN 폐기 확인 버튼이 비활성 | 표시된 전체 RUN ID를 대소문자·공백까지 정확히 입력하거나 붙여 넣습니다. 취소하면 모든 기록이 유지됩니다. |
| VS Code가 MCP를 실행하지 못함 | `tapl-mcp`를 실행할 수 있는지 확인합니다. 필요하면 `taplWorkflow.taplMcpPath`를 실행 파일 경로로 설정합니다. 확장은 서버를 직접 실행하며 브라우저 서비스에 연결하지 않습니다. |
| VS Code에 다른 폴더나 RUN이 표시됨 | 대시보드에서 의도한 열린 워크스페이스와 RUN을 선택합니다. 폴더마다 연결·DB·선택 세션을 따로 관리합니다. |
| 메모리 또는 RUN 폐기 UI가 없음 | 확장에서 실행하는 `tapl-mcp`를 업데이트합니다. 해당 화면·동작은 서버 기능 지원에 따라 제공하며 구버전에서도 다른 화면은 유지합니다. |
| VS Code 화면이 갱신되지 않음 | **Developer: Show Running Extensions**로 활성 상태를 확인한 뒤 **TAPL Workflow: Refresh Workflow Views**를 실행합니다. 실행 파일 문제를 고친 뒤 VS Code를 재시작합니다. |

## 검색과 수명주기 확인

| 증상 | 확인과 해결 |
| --- | --- |
| 의미 검색이 BM25로 대체됨 | 적용 검색 설정과 선택적 의미 검색 의존성을 확인합니다. 인덱싱·provider 확인은 [검색](search.ko.md)을 보세요. 전문 검색에는 semantic extra가 필요하지 않습니다. |
| Windows에서 `searchd`를 쓸 수 없음 | 선택 의존성을 갖춘 로컬 의미 검색 provider나 BM25를 사용합니다. 데몬은 Unix 소켓이 필요합니다. |
| MCP에서 현재 작업이 보이지 않음 | 모든 호출에 같은 hook `session_id`를 전달합니다. 생략하면 격리된 legacy 범위를 선택합니다. MCP 전송 연결 자체는 대화 식별자가 아닙니다. |
| 작업 시작·dispatch가 거부됨 | `tapl_get_next` 권고와 `tapl_validate_state` 오류를 확인합니다. 계획, 실행 승인, 완료된 의존 작업, 병렬 작업의 겹치지 않는 소유 경로를 확인합니다. |
| 병렬 작업 완료에서 실행이 거부됨 | 활성 dispatch manifest가 반환한 정확한 `execution_id`를 사용합니다. 중단 후에는 원래 배치를 복구하거나 취소한 뒤 재시도합니다. |
| 종료 시 `review_required` 반환 | 활성 RUN의 메모리 검토를 완료한 뒤 별도로 아카이브합니다. 메모리 인자와 함께 `expected_run_id`를 사용합니다. [연상 메모리](memory.ko.md)를 보세요. |
| 메모리 수정에서 revision 충돌 | 현재 메모리를 읽고 바뀐 내용을 검토한 뒤 명시적 사용자 요청 범위에서 현재 `expected_revision`을 사용합니다. |

수명주기 오류를 DB 삭제나 다른 세션 식별자 사용으로 우회하지 마세요. 작업에 구체적 차단 사유와 다음 행동을 유지합니다. 유효한 전이는 [워크플로](../concepts/workflow.ko.md)와 [MCP 참조](../reference/mcp.ko.md)를 참고하세요.

## 해결되지 않은 문제 보고

[GitHub Issues](https://github.com/qkdxorjs1002/tapl/issues)에 OS, 관련 TAPL·VS Code·확장 버전, 설치 방식, 실행 파일 경로, 정확한 재현 절차, 필요한 범위의 `doctor`·오류 출력을 첨부합니다. 비밀과 비공개 워크스페이스 내용은 제거하세요. 보안 취약점은 [비공개 취약점 보고](https://github.com/qkdxorjs1002/tapl/security/advisories/new)를 사용합니다.

이 해결 방법은 CLI·Viewer·확장 지원 계약과 세션·런타임 회귀 테스트를 근거로 합니다. 로컬 검증 명령은 [기여와 검증](../development/contributing.ko.md), 서명·게시 실패는 [릴리스](../development/releases.ko.md)를 보세요.
