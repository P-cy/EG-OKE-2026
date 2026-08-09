"""WebSocket server — แยกโปรเซสจาก REST API

เหตุผลที่แยก: WS ถือ connection ยาว
ถ้าอยู่โปรเซสเดียวกับ REST แล้ว deploy/restart → จอทุกตัวหลุดพร้อมกัน
"""
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from app.core import redis_client
from app.core.config import settings
from app.core.observability import log, setup_logging
from app.core.redis_client import K, get_redis
from app.realtime.manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await manager.start()
    log.info("ws_server_started")
    yield
    await manager.stop()
    await redis_client.close_redis()
    log.info("ws_server_stopped")


app = FastAPI(title="EG'OKE 2026 Realtime", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/healthz")
async def healthz():
    return {"status": "alive", "connections": manager.count}


@app.websocket("/v1/live/ws")
async def live_ws(ws: WebSocket, token: str = Query(default="")):
    """จอแสดงผลหน้างานเท่านั้น — ต้องมี display token

    ⚠️ ห้ามให้มือถือผู้เข้าร่วมต่อ WS: 2,000 connection บน WiFi งานอีเวนต์
       = reconnect storm ตอน AP สั่น = ระบบตายรอบสอง
    """
    if not settings.DISPLAY_TOKEN or token != settings.DISPLAY_TOKEN:
        await ws.close(code=4401, reason="unauthorized")
        return

    conn = await manager.connect(ws)
    sender = asyncio.create_task(manager.sender(conn))

    try:
        # ส่ง snapshot ล่าสุดทันทีที่ต่อ — จอจะได้ไม่ว่างเปล่าระหว่างรอ tick ถัดไป
        seq = int(await get_redis().get(K.SEQ) or 0)
        await ws.send_text(json.dumps({
            "type": "hello",
            "seq": seq,
            "heartbeat_interval": settings.WS_HEARTBEAT_SECONDS,
        }))
        if snap := await get_redis().get(K.SNAPSHOT):
            await ws.send_text(json.dumps({"type": "snapshot", "data": json.loads(snap)}))

        while conn.alive:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")
            if mtype == "subscribe":
                conn.channels = set(msg.get("channels", []))
            elif mtype == "resume":
                # client กลับมาหลังหลุด → ส่ง state ล่าสุดให้ (ไม่ replay event ทีละตัว
                # เพราะ vote.tick เป็น state ไม่ใช่ event — ค่าล่าสุดคือทั้งหมดที่ต้องรู้)
                if snap := await get_redis().get(K.SNAPSHOT):
                    await ws.send_text(json.dumps({"type": "snapshot", "data": json.loads(snap)}))
            # "pong" → ไม่ต้องทำอะไร แค่รู้ว่ายังมีชีวิต

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("ws_error", error=str(e))
    finally:
        manager.disconnect(conn)
        sender.cancel()
