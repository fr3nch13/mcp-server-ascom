"""Patch alpaca/alpyca imports for testing."""
import sys
from unittest.mock import MagicMock

# Mock alpaca modules to prevent import errors in test suite
alpaca_mock = MagicMock()
sys.modules["alpaca"] = alpaca_mock
sys.modules["alpaca.camera"] = MagicMock()
sys.modules["alpaca.filterwheel"] = MagicMock()
sys.modules["alpaca.focuser"] = MagicMock()
sys.modules["alpaca.telescope"] = MagicMock()
sys.modules["alpaca.discovery"] = MagicMock()
sys.modules["alpyca"] = alpaca_mock