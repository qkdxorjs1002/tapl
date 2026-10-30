# Viewer와 서비스

[문서 홈](../README.ko.md) · [English](viewer.md)

브라우저 Viewer는 로컬 TAPL 워크스페이스의 활성 RUN, 계획, 작업, 승인, 발견 사항, 아카이브, 이력 검색, 연상 메모리를 보여 줍니다. 메모리 목록·검색·상세·원본 확인은 읽기 전용입니다. 메모리 수정이나 삭제는 에이전트에게 명시적으로 요청하세요.

## 워크스페이스 열기

초기화한 작업 폴더에서 실행합니다.

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000

# 필요하면 다른 포트 사용:
taplctl viewer --port 9000
```

출력된 URL을 직접 여세요. 명령은 브라우저를 자동 실행하지 않으며 `Ctrl+C`로 종료합니다. CLI는 `127.0.0.1`에만 바인딩합니다. 시작 폴더의 `.tapl/tapl.db`를 선택하며 부모 폴더를 검색하지 않습니다. 하위 폴더를 별도로 초기화하면 별도 워크스페이스입니다.

시작 폴더에 DB가 없으면 페이지에서 `.tapl/tapl.db`가 있는 폴더를 선택합니다. 브라우저는 마지막으로 성공한 선택을 기억합니다. 로그인 서비스가 저장소 밖에서 시작될 때 유용합니다. 폴더 선택은 초기화 작업이 아니므로 먼저 `taplctl init --workspace-root /path/to/workspace`를 실행하세요. Viewer에는 `--workspace` 옵션이 없습니다.

RUN 탭에서 살펴볼 세션을 선택합니다. 아카이브와 이력 검색으로 이전 작업을 찾고, 메모리 화면에서 재사용 단서의 원본 근거로 이동할 수 있습니다. RUN을 선택해도 소유권은 바뀌지 않습니다.

## RUN 폐기

RUN 탭의 **×**를 누르고 대화상자에 표시된 **전체 RUN ID**를 그대로 입력하거나 붙여 넣습니다. `PLAN-001`, 세션 ID, 축약 해시가 아닌 RUN 식별자입니다. 대소문자와 공백까지 일치해야 확인 버튼이 활성화됩니다. 취소하거나 Escape를 누르면 아무것도 바뀌지 않습니다.

확인 후 동작은 다음과 같습니다.

- 선택한 RUN과 같은 소유자·split group의 모든 대기 RUN을 의존성 연결 여부와 무관하게 함께 처리합니다.
- 각 RUN은 보존할 기록이 있으면 계획·작업·발견 사항과 함께 강제 아카이브하고, 정말 비어 있으면 아카이브 없이 삭제합니다. 결과, 실행 이력, 메모리, 보존 참조도 남겨야 할 기록으로 취급합니다.
- 활성 DB 실행과 배치를 취소하고 작업 타이머를 멈춥니다. 대기 RUN은 자동 시작하지 않습니다.
- 다른 세션과 무관한 요청은 유지합니다. 외부 에이전트 프로세스는 계속 실행됩니다. 폐기는 TAPL 상태만 바꿉니다.

브라우저 요청에는 허용된 `Origin`이 있어야 합니다. 서버는 선택한 워크스페이스, 소유 세션, 정확한 RUN ID, 명시적 확인도 검증합니다. 대응 도구 계약은 [MCP 참조](../reference/mcp.ko.md#confirmed-discard)를 보세요.

## Homebrew 서비스로 실행

설치한 formula를 시작합니다. 세 formula 모두 8000 포트를 사용하므로 해당 포트에서는 Viewer 서비스를 하나만 실행하세요.

```sh
brew services start taplctl
# 다른 선택: taplctl-semantic 또는 taplctl-pre
brew services restart taplctl
brew services stop taplctl
```

업그레이드·재설치는 실행 중인 Viewer 서비스의 재시작을 시도합니다. semantic formula는 검색 데몬을 미리 올리지 않습니다. Unix에서 필요할 때 따로 시작하세요.

```sh
taplctl searchd start
taplctl searchd status
```

`searchd`는 Unix 소켓을 사용하므로 Windows에서 지원하지 않습니다. Windows는 선택 의존성을 설치하면 데몬 없이 로컬 의미 검색을 사용할 수 있으며 BM25/전문 검색도 유지됩니다. [검색](search.ko.md)을 참고하세요.

## 역방향 프록시와 터널

신뢰할 수 있는 프록시나 터널로 다른 브라우저 origin에서 Viewer를 제공하면 정확한 origin을 허용합니다.

```sh
taplctl viewer --allowed-origin https://tapl.example.com
```

지속 실행하는 Homebrew 서비스는 적용되는 설정에 다음을 넣고 해당 formula를 재시작합니다.

```toml
[viewer]
allowed_origins = [
  "https://tapl.example.com",
  "https://tapl.internal.example",
]
```

```sh
brew services restart taplctl
```

origin에는 HTTP(S) 스킴, 호스트, 선택적 포트만 넣습니다. 경로·사용자 정보·쿼리·프래그먼트·와일드카드는 허용하지 않습니다. 여러 값은 `--allowed-origin`을 반복합니다. CLI와 설정의 origin은 로컬 origin과 합쳐집니다. 이 설정은 해당 브라우저 origin의 요청을 허용하며 일반 CORS를 켜거나 loopback 바인딩을 바꾸지 않습니다. 로컬 워크플로 데이터에 외부 접근을 제공하기 전에 프록시에서 인증과 TLS를 처리해야 합니다.

## 검증과 관련 문서

브라우저와 VS Code는 같은 React 화면과 프로토콜 타입을 사용합니다. 브라우저 HTTP origin·워크스페이스 검사는 `tapl/tests/test_viewer.py`, `test_viewer_discard.py`, 폐기 수명주기는 `test_run_discard.py`에서 검증합니다. 공유 UI의 확인·라우팅 검사는 `vscode-extension/tests`에 있습니다.

- [VS Code 확장](vscode.ko.md): 에디터 워크스페이스 라우팅과 요구 사항.
- [설정](configuration.ko.md): 설정 범위와 적용 값.
- [문제 해결](troubleshooting.ko.md): 워크스페이스·포트·origin 오류.
