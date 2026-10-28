import os
import sys

# Keep the endpoint suite independent of the developer's shell. Auth is enabled
# by default in production; these tests exercise the open local-dev mode.
os.environ.setdefault('AUTH_ENABLED', '0')

_SVC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _SVC not in sys.path:
    sys.path.insert(0, _SVC)
