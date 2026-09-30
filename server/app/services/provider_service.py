import json
import asyncio
import re
import httpx
from typing import AsyncGenerator, Dict, Any, List
from app.config import settings
from app.services.storage_service import storage_service

class ModelProviderService:
    def __init__(self):
        pass

    async def stream_chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        system_prompt: str = ""
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Submit chat requests to the configured inference endpoint.
        Uses exact user-selected model slug without any model remapping or fallback.
        """
        app_settings = storage_service.get_settings()
        api_key = app_settings.get("model_api_key") or settings.MODEL_API_KEY
        base_url = (app_settings.get("model_api_base_url") or settings.MODEL_API_BASE_URL).rstrip("/")

        if not api_key:
            yield {
                "type": "content.delta",
                "delta": "An inference API key is missing. Add one in App Settings → Model provider."
            }
            yield {"type": "turn.completed", "ok": False}
            return

        if not base_url:
            yield {
                "type": "content.delta",
                "delta": "An inference API base URL is missing. Add it in App Settings → Model provider."
            }
            yield {"type": "turn.completed", "ok": False}
            return

        # When the operator configured an explicit model list, the requested model
        # must be on it, regardless of wire protocol.
        configured_model_ids = app_settings.get("model_ids") or []
        if configured_model_ids and (model or "").strip() not in configured_model_ids:
            yield {
                "type": "content.delta",
                "delta": "The selected model is not in the configured model list."
            }
            yield {"type": "turn.completed", "ok": False}
            return

        if app_settings.get("model_api_wire_api") == "responses":
            async for event in self._stream_responses(
                base_url, api_key, model, messages, system_prompt,
                app_settings.get("model_api_headers") or {},
            ):
                yield event
            return

        # Target EXACT model slug passed by user without any alias remapping or fallback
        target_endpoint = (model or "gpt-5-mini").strip()

        # The slug is interpolated directly into the upstream request URL, so
        # reject anything that could alter the path or query string (e.g. `/`,
        # `?`, `#`, `..`).
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", target_endpoint) or ".." in target_endpoint:
            yield {"type": "content.delta", "delta": "The selected model name contains unsupported characters."}
            yield {"type": "turn.completed", "ok": False}
            return

        # Extract latest user prompt and image_url
        user_prompt = ""
        image_url = None
        for m in reversed(messages):
            if m.get("role") == "user":
                if not user_prompt:
                    user_prompt = m.get("content", "")
                if not image_url and m.get("image_url"):
                    image_url = m.get("image_url")
                break

        # Include recent conversation context in the system prompt for stateless inference endpoints.
        previous_messages = messages[:-1] if len(messages) > 1 else []
        last_10_messages = previous_messages[-10:] if len(previous_messages) > 10 else previous_messages

        history_blocks = []
        for m in last_10_messages:
            role_name = "User" if m.get("role") == "user" else "Assistant"
            content = m.get("content", "").strip()
            msg_img = m.get("image_url")
            if msg_img:
                content = f"{content} [Attached Image: {msg_img}]".strip()
            if content:
                history_blocks.append(f"{role_name}: {content}")

        formatted_history = "\n".join(history_blocks)

        full_system_prompt = system_prompt.strip() if system_prompt else ""
        if formatted_history:
            context_prefix = f"### Recent Conversation History (Last {len(last_10_messages)} Messages):\n{formatted_history}\n\n### Instructions:\nRespond to the latest user prompt keeping the conversation context above in mind."
            if full_system_prompt:
                full_system_prompt = f"{full_system_prompt}\n\n{context_prefix}"
            else:
                full_system_prompt = context_prefix

        # Headers expected by the configured inference endpoint.
        headers = {
            **(app_settings.get("model_api_headers") or {}),
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }

        # Request body expected by the configured inference endpoint.
        input_body = {
            "prompt": user_prompt,
            "image_url": image_url if image_url else None,
            "system_prompt": full_system_prompt if full_system_prompt else None,
            "reasoning_effort": "low",
            "web_search": False
        }

        # Direct model endpoint submission URL (POST {base_url}/{target_endpoint})
        request_attempts = [
            (f"{base_url}/{target_endpoint}", input_body)
        ]




        last_error = ""

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                for endpoint_url, body_data in request_attempts:
                    try:
                        response = await client.post(endpoint_url, json=body_data, headers=headers)

                        if response.status_code == 200:
                            res_data = response.json()

                            # Check for Task Prediction Submission (returns request_id)
                            request_id = res_data.get("request_id") or res_data.get("id")
                            if request_id:
                                # Async Polling Loop for predictions result (GET /predictions/{request_id}/result)
                                poll_url = f"{base_url}/predictions/{request_id}/result"
                                poll_deadline = asyncio.get_event_loop().time() + 180

                                while asyncio.get_event_loop().time() < poll_deadline:
                                    try:
                                        poll_res = await client.get(poll_url, headers=headers)
                                        if poll_res.status_code == 200:
                                            poll_data = poll_res.json()
                                            status = poll_data.get("status")
                                            error_text = poll_data.get("error")

                                            if status == "completed":
                                                # Safely parse outputs array (handles strings like ["Hi there! 😊"] or objects)
                                                output_text = ""
                                                outputs = poll_data.get("outputs", [])
                                                if isinstance(outputs, list) and len(outputs) > 0:
                                                    first_out = outputs[0]
                                                    if isinstance(first_out, str):
                                                        output_text = first_out
                                                    elif isinstance(first_out, dict):
                                                        output_text = first_out.get("text") or first_out.get("url") or str(first_out)
                                                
                                                if not output_text:
                                                    output_text = poll_data.get("result") or poll_data.get("output") or "Task completed."

                                                # Stream the real response text back to the frontend UI
                                                words = str(output_text).split(" ")
                                                for i, w in enumerate(words):
                                                    yield {"type": "content.delta", "delta": w + (" " if i < len(words) - 1 else "")}
                                                    await asyncio.sleep(0.02)
                                                yield {"type": "turn.completed", "ok": True}
                                                return

                                            elif status in ["failed", "cancelled", "error"] or error_text:
                                                err_msg = error_text or f"Task ended with status: {status}"
                                                yield {"type": "content.delta", "delta": f"Error: {err_msg}"}
                                                yield {"type": "turn.completed", "ok": False}
                                                return
                                        else:
                                            # Catch non-200 polling HTTP errors immediately (e.g. 404, 401, 500)
                                            poll_err = f"Error polling prediction result ({poll_url}) - HTTP {poll_res.status_code}: {poll_res.text}"
                                            yield {"type": "content.delta", "delta": f"Error: {poll_err}"}
                                            yield {"type": "turn.completed", "ok": False}
                                            return

                                    except Exception as poll_exc:
                                        yield {"type": "content.delta", "delta": f"Error during polling: {str(poll_exc)}"}
                                        yield {"type": "turn.completed", "ok": False}
                                        return

                                    await asyncio.sleep(0.5)


                            # Direct output in initial POST response
                            direct_output = ""
                            outputs = res_data.get("outputs", [])
                            if isinstance(outputs, list) and len(outputs) > 0:
                                first_out = outputs[0]
                                if isinstance(first_out, str):
                                    direct_output = first_out
                                elif isinstance(first_out, dict):
                                    direct_output = first_out.get("text") or first_out.get("url") or str(first_out)

                            if not direct_output:
                                direct_output = res_data.get("result") or res_data.get("output") or res_data.get("choices", [{}])[0].get("message", {}).get("content", "")

                            if direct_output:
                                words = str(direct_output).split(" ")
                                for i, w in enumerate(words):
                                    yield {"type": "content.delta", "delta": w + (" " if i < len(words) - 1 else "")}
                                    await asyncio.sleep(0.02)
                                yield {"type": "turn.completed", "ok": True}
                                return

                        else:
                            last_error = f"Inference endpoint ({endpoint_url}) returned HTTP {response.status_code}: {response.text}"
                    except Exception as exc:
                        last_error = f"Connection error on ({endpoint_url}): {str(exc)}"

        except Exception as exc:
            last_error = f"Inference request failed: {str(exc)}"

        # Output exact backend error message to frontend UI without any fallback mockup
        error_display = last_error if last_error else "Unable to connect to the inference endpoint."
        yield {"type": "content.delta", "delta": error_display}
        yield {"type": "turn.completed", "ok": False}

    async def _stream_responses(self, base_url, api_key, model, messages, system_prompt, extra_headers):
        inputs = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "user" and message.get("image_url"):
                content = [
                    {"type": "input_text", "text": content},
                    {"type": "input_image", "image_url": message["image_url"]},
                ]
            inputs.append({"role": role, "content": content})

        headers = {**extra_headers, "Authorization": f"Bearer {api_key}",
                   "Content-Type": "application/json", "Accept": "text/event-stream"}
        body = {"model": model, "input": inputs, "instructions": system_prompt,
                "stream": True, "store": False}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", f"{base_url}/responses", json=body, headers=headers) as response:
                    if not response.is_success:
                        raise RuntimeError(f"Responses API returned HTTP {response.status_code}.")
                    data_lines = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                        elif not line and data_lines:
                            payload = "\n".join(data_lines)
                            data_lines = []
                            if payload == "[DONE]":
                                break
                            event = json.loads(payload)
                            event_type = event.get("type")
                            if event_type == "response.output_text.delta":
                                yield {"type": "content.delta", "delta": event.get("delta", "")}
                            elif event_type == "response.refusal.delta":
                                yield {"type": "content.delta", "delta": event.get("delta", "")}
                            elif event_type == "response.completed":
                                yield {"type": "turn.completed", "ok": True}
                                return
                            elif event_type in {"response.failed", "response.incomplete", "error"}:
                                raise RuntimeError(f"Responses API ended with {event_type}.")
                    raise RuntimeError("Responses stream ended before completion.")
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            # Do not expose upstream bodies, request headers, or credentials.
            detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            yield {"type": "content.delta", "delta": f"Inference request failed: {detail}"}
            yield {"type": "turn.completed", "ok": False}


provider_service = ModelProviderService()
