"""Run every deploy/tests/test_*.py in order; non-zero exit if any fails."""

import glob
import os
import subprocess
import sys

failed = []
for path in sorted(glob.glob("/tests/test_*.py")):
    name = os.path.basename(path)
    print(f"### {name}")
    if subprocess.run([sys.executable, path]).returncode != 0:
        failed.append(name)
    print()

if failed:
    print(f"FAILED: {', '.join(failed)}")
    sys.exit(1)
print("ALL INTEGRATION TESTS PASSED")
