from fastapi import APIRouter, BackgroundTasks, Request

from app.collect.verify import verify_tick
from app.run_log import logged_run

router = APIRouter(prefix="/api", tags=["verify"])


async def _logged_verify(pool, http, activity) -> None:
    # 요청 스코프 conn은 응답과 함께 반납되므로 백그라운드에서 쓸 수 없다 — 풀에서 직접 얻는다.
    # 틱이 행마다 UPDATE를 하므로 러너처럼 커넥션을 놓았다 잡을 수 없다(스케줄 잡과 동일 방식).
    async with pool.acquire() as conn:
        await logged_run(
            conn, pipeline="verify", trigger="manual",
            clear=lambda: activity.clear("verify"),
            run=lambda: verify_tick(conn, http=http,
                                    on_stage=lambda st, d, p: activity.set_stage("verify", st, d, str(p))),
        )


@router.post("/verify/run", status_code=202)
async def run_verify(request: Request, bg: BackgroundTasks):
    # 수동 실행은 settings.enabled와 무관 — 배포 직후 첫 검사를 자정까지
    # 기다리지 않고 검증하기 위한 명시적 행동이다(수집기·알림기와 동일 규칙).
    # 전수검사는 공고 수만큼 상세 API를 순회해 분 단위로 걸린다. 응답을 붙들면
    # 클라이언트가 타임아웃해 성공한 실행도 실패로 보인다 — 접수만 알리고 뒤에서 돈다.
    # 진행 상황은 activity(Ops 라이브 상태), 결과는 run_log로 관측한다.
    bg.add_task(_logged_verify, request.app.state.db, request.app.state.http,
                request.app.state.activity)
    return {"status": "running"}
