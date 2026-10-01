"""Request-size gating on the HTTP edge.

Starlette buffers JSON request bodies fully in memory before pydantic
validation runs, so without a Content-Length gate an unauthenticated attacker
could exhaust server memory by POSTing a huge body to a public endpoint such
as /api/v1/auth/login.
"""

import unittest

import httpx

from app.config import settings

try:
    from app.main import app
except ModuleNotFoundError:
    app = None


@unittest.skipIf(app is None, "FastAPI dependencies are not installed")
class RequestSizeLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_login_rejects_declared_oversized_body(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            # Declare a huge Content-Length while sending a tiny body: the
            # middleware must reject on the declared size without buffering.
            response = await client.post(
                "/api/v1/auth/login",
                content=b"{}",
                headers={"Content-Length": str(settings.MAX_REQUEST_BYTES + 1)},
            )
            self.assertEqual(response.status_code, 413)

    async def test_authenticated_route_rejects_declared_oversized_body(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.post(
                "/api/v1/chat/send",
                content=b"{}",
                headers={"Content-Length": str(settings.MAX_REQUEST_BYTES + 1)},
            )
            # 413 (too large) must win over 401 (unauthenticated): the gate
            # runs before authentication.
            self.assertEqual(response.status_code, 413)

    async def test_normal_sized_body_passes_the_gate(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"token": "wrong-token"},
            )
            # Not 413: the request reaches authentication and fails there.
            self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
