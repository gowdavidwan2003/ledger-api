"""Request body size limit, as raw ASGI middleware.

Without a limit, a client can send an arbitrarily large body and the server
buffers all of it before validation ever runs. Requests that declare a size over
the limit are refused before reading; chunked bodies (no Content-Length) are
counted as they stream in and cut off once they cross it.
"""

import contextlib

from app.api.errors import error_response


class _BodyTooLarge(Exception):
    pass


class BodySizeLimit:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    def _too_large(self):
        return error_response(413, "PAYLOAD_TOO_LARGE", f"Request body exceeds {self.max_bytes} bytes")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            return await self._too_large()(scope, receive, send)

        seen = 0
        exceeded = False

        async def counted_receive():
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    exceeded = True
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message):
            # Once the limit is crossed, whatever the app answers (FastAPI turns the
            # aborted read into a generic 400) is replaced by the 413 below.
            if not exceeded:
                await send(message)

        with contextlib.suppress(_BodyTooLarge):
            await self.app(scope, counted_receive, guarded_send)
        if exceeded:
            await self._too_large()(scope, receive, send)
