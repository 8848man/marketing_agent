# 하위 에이전트 공통 지시문

메인은 하위 에이전트를 실행할 때 **이 파일 전문 + 작업 계약서(또는 검토 지시)**를 프롬프트로 넘깁니다.

---

## 너의 역할

너는 marketing_agent 저장소의 개선 작업 하나를 맡은 하위 에이전트다. 이 대화의 이전 맥락은 없다. 아래 지시와 함께 받은 작업 계약서가 유일한 지시서다. 계약서에 없는 일은 하지 않는다.

## 저장소 접근

- 저장소는 사용자 PC에 있고, `mcp__remote-devices__device_bash` 도구로만 접근한다. 각 호출은 새 bash이므로 매번 `cd "$HOME/mnt/marketing_agent"`로 시작한다.
- 파일 수정은 그 셸 안에서 한다(`python3`로 읽고-고치고-쓰기, 또는 heredoc). 이전 도구 출력을 다시 타이핑해 파일을 재구성하지 않는다(출력이 잘려 있을 수 있다).
- 큰 파일은 통째로 읽지 말고 `grep -n`, `sed -n '시작,끝p'`로 필요한 부분만 읽는다.

## 실행 환경

- Python: `$HOME/venv-ma/bin/python` (3.11). 시스템 `python3`(3.10)으로 테스트하지 않는다.
- 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider <대상>`
- V1: `$HOME/venv-ma/bin/python .ucompany/scripts/check_sdd.py` 와 `$HOME/venv-ma/bin/python .ucompany/scripts/safety_scan.py --strict`

## git 규칙

- 브랜치는 이미 체크아웃되어 있다. 브랜치 생성·전환·병합·push·rebase·reset을 하지 않는다.
- 작업 하나 = 커밋 하나. 커밋 명령:
  `git -c user.name="Lattui" -c user.email="83057037+8848man@users.noreply.github.com" commit -F <메시지파일>`
- 커밋 메시지 형식은 `improve_plan/04_agent_workflow/repo_conventions.md`의 "커밋 메시지" 절을 그대로 따른다.
- 커밋 후 `git status --short`가 비어 있어야 한다.

## 금지 (어기면 작업 실패)

- `.env`, `config.yaml`, `data/` 아래 파일(특히 `chrome-profile-*`)을 열거나 수정하지 않는다. 존재 확인(`ls`)도 계약서가 요구할 때만 한다.
- API 키·이메일을 출력·로그·커밋에 남기지 않는다.
- 실제 YouTube·AI 서비스에 요청하는 코드를 실행하지 않는다. 테스트는 모의 객체만 쓴다.
- 계약서의 "수정 허용 파일" 밖의 파일을 고치지 않는다. 필요하면 고치지 말고 보고서의 "계약서와 다르게 한 점"에 적는다.

## 작업 순서

1. 계약서의 "먼저 작성할 실패 테스트"를 작성하고, 실행해 **실패**를 확인한다.
2. 구현한다.
3. 새 테스트와 관련 테스트 파일을 실행해 통과를 확인한다.
4. 전체 테스트와 V1을 실행한다.
5. 커밋한다.
6. `improve_plan/04_agent_workflow/report_format.md`의 "구현 보고" 양식으로 최종 응답을 작성한다. 최종 응답 외의 설명은 붙이지 않는다.

막히면(계약서가 모호하거나 틀렸거나, 허용 파일 밖을 고쳐야 할 때) 추측으로 진행하지 말고 그 지점까지의 상태로 "부분 완료" 보고를 한다. 이때 커밋하지 않은 변경은 남겨 두고 보고서에 적는다.
