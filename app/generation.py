from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx

from app.files import encode_image_base64, extract_text, is_image, is_pdf
from app.ollama import OllamaClient
from app.storage import Storage

_MULTIMODAL_ERROR = (
    "This model doesn't support image attachments. "
    "Try a multimodal model like llava or moondream."
)


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
        model: str | None = None,
        attachment_ids: list[int] | None = None,
    ) -> None:
        task = self._tasks.get(request_id)
        if task is not None and not task.done():
            return

        next_task = asyncio.create_task(
            self._run_generation(
                request_id=request_id,
                assistant_message_id=assistant_message_id,
                model_messages=list(model_messages),
                model=model,
                attachment_ids=attachment_ids or [],
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
        model: str | None = None,
        attachment_ids: list[int],
    ) -> None:
        self.storage.update_generation_job(request_id, status="streaming")
        self.storage.update_message(assistant_message_id, status="streaming")

        images: list[str] = []
        text_context_parts: list[str] = []

        for aid in attachment_ids:
            attachment = self.storage.get_attachment(aid)
            if attachment is None:
                continue
            ct = attachment["content_type"]
            fp = attachment["file_path"]
            fname = attachment["filename"]
            if is_image(ct):
                images.append(encode_image_base64(fp))
            else:
                text = extract_text(ct, fp)
                if text:
                    label = "PDF" if is_pdf(ct) else "file"
                    text_context_parts.append(
                        f'[Attached {label}: {fname}]\n```\n{text}\n```'
                    )

        # Prepend any extracted text to the last user message
        if text_context_parts and model_messages:
            last = model_messages[-1]
            if last.get("role") == "user":
                prefix = "\n\n".join(text_context_parts) + "\n\n"
                model_messages[-1] = {**last, "content": prefix + last["content"]}

        try:
            async for chunk in self.ollama.stream_chat(
                model_messages, model=model, images=images or None
            ):
                self.storage.append_message_chunk(assistant_message_id, chunk)
        except httpx.HTTPStatusError as exc:
            # Ollama returns 4xx/5xx when the model doesn't support images
            if images:
                error = _MULTIMODAL_ERROR
            else:
                error = f"Ollama request failed: {exc.response.status_code}"
            self.storage.update_message(assistant_message_id, status="failed", error=error)
            self.storage.update_generation_job(request_id, status="failed", error=error)
            return
        except (httpx.HTTPError, OSError, ValueError) as exc:
            error = f"Ollama request failed: {exc.__class__.__name__}"
            self.storage.update_message(assistant_message_id, status="failed", error=error)
            self.storage.update_generation_job(request_id, status="failed", error=error)
            return

        self.storage.update_message(assistant_message_id, status="completed")
        self.storage.update_generation_job(request_id, status="completed")
