"""Живая синхронизация экранов через WebSocket. У каждого магазина своя «комната»:
телефон и ноутбук одного магазина видят изменения сразу, чужие магазины — нет."""
from fastapi import WebSocket


class Hub:
    def __init__(self):
        self.rooms: dict[int, set[WebSocket]] = {}

    async def join(self, ws: WebSocket, shop_id: int):
        await ws.accept()
        self.rooms.setdefault(shop_id, set()).add(ws)

    def leave(self, ws: WebSocket, shop_id: int):
        self.rooms.get(shop_id, set()).discard(ws)

    async def broadcast(self, shop_id: int, message: dict):
        for ws in list(self.rooms.get(shop_id, ())):
            try:
                await ws.send_json(message)
            except Exception:
                self.leave(ws, shop_id)


hub = Hub()
