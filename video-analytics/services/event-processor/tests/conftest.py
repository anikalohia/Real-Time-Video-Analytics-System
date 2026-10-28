import os
import sys

_SVC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _SVC not in sys.path:
    sys.path.insert(0, _SVC)
