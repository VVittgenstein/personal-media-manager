from __future__ import annotations

import signal
import sys

from .server import main


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, OSError):
        pass
    raise SystemExit(main(sys.argv[1:]))

