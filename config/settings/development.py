import os

from .base import *

DEBUG = True

# Vite dev server (HMR)
VITE_DEV_MODE = os.environ.get("VITE_DEV_MODE", "False").lower() in ("true", "1", "yes")
VITE_DEV_URL = os.environ.get("VITE_DEV_URL", "http://localhost:5847")
