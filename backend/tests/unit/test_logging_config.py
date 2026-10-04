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
