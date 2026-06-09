from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx

from app.ollama import OllamaClient
from app.storage import Storage


class GenerationManager:
    def __init__(self, storage: Storage, ollama: OllamaClient) -> None:
        self.storage = storage
        self.ollama = ollama
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(
        self,
        request_id: str,
        assistant_message_id: int,
        model_messages: Sequence[dict[str, str]],
    ) -> None:
        task = self._tasks.get(request_id)
        if task is not None and not task.done():
            return

        next_task = asyncio.create_task(
            self._run_generation(
                request_id=request_id,
                assistant_message_id=assistant_message_id,
                model_messages=list(model_messages),
            )
        )
        next_task.add_done_callback(lambda _: self._tasks.pop(request_id, None))
        self._tasks[request_id] = next_task

    async def _run_generation(
        self,
        *,
        request_id: str,
        assistant_message_id: int,
        model_messages: list[dict[str, str]],
    ) -> None:
        self.storage.update_generation_job(request_id, status="streaming")
        self.storage.update_message(assistant_message_id, status="streaming")

        try:
            async for chunk in self.ollama.stream_chat(model_messages):
                self.storage.append_message_chunk(assistant_message_id, chunk)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            error = f"Ollama request failed: {exc.__class__.__name__}"
            self.storage.update_message(
                assistant_message_id,
                status="failed",
                error=error,
            )
            self.storage.update_generation_job(
                request_id,
                status="failed",
                error=error,
            )
            return

        self.storage.update_message(assistant_message_id, status="completed")
        self.storage.update_generation_job(request_id, status="completed")
