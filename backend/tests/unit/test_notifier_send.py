from kerotrack.notifier.send import send


class _Fake:
    def __init__(self):
        self.calls = []

    def notify(self, **kw):
        self.calls.append(kw)
        return True


async def test_send_no_urls_is_false():
    assert await send([], "t", "b") is False


async def test_send_uses_factory():
    fake = _Fake()
    assert await send(["json://example.net"], "T", "B", apprise_factory=lambda urls: fake) is True
    assert fake.calls[0]["title"] == "T"
