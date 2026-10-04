import logging
from kerotrack.logging_config import configure_logging, _HANDLER_NAME

def test_configure_logging_sets_level_and_single_handler():
    configure_logging("DEBUG")
    configure_logging("INFO")  # idempotent
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, "name", None) == _HANDLER_NAME]
    assert len(ours) == 1
    assert root.level == logging.INFO
    assert logging.getLogger("kerotrack.scheduler.service").getEffectiveLevel() == logging.INFO

def test_configure_logging_bad_level_falls_back_to_info():
    configure_logging("NOPE")
    assert logging.getLogger().level == logging.INFO


def test_noisy_http_loggers_are_capped_at_warning():
    configure_logging("DEBUG")
    configure_logging("INFO")  # idempotent second call must keep the caps
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


async def test_quote_fetch_never_logs_the_postcode(caplog):
    import httpx
    import respx

    from kerotrack.quotes.homefuelsdirect import HomeFuelsDirect
    from kerotrack.quotes.models import QuoteRequest

    configure_logging("INFO")
    caplog.clear()
    with respx.mock:
        respx.get("https://homefuelsdirect.co.uk/index.php").respond(json={"prices": {}})
        async with httpx.AsyncClient() as c:
            await HomeFuelsDirect().fetch(c, QuoteRequest("ZZ99 9ZZ", 500, "standard"))
    texts = [r.getMessage() for r in caplog.records]
    assert not any("ZZ99" in t for t in texts), texts
