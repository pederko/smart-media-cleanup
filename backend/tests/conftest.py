import os
import sys
import tempfile
from pathlib import Path

# Must be set before the app modules are imported
_DATA = tempfile.mkdtemp(prefix="smc-test-data-")
os.environ["SMC_DATA_DIR"] = _DATA
os.environ["SMC_TEST_APPARENT_SIZE"] = "1"
os.environ["SMC_DISABLE_SCHEDULER"] = "1"
os.environ["SMC_DB_TIMEOUT"] = "3"  # lock errors should show up quickly in the tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
