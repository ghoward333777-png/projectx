import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
APPS = os.path.join(os.path.dirname(ROOT), "apps")
