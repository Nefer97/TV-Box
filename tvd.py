#!/usr/bin/env python3
"""tvd — demone "Smart TV" per Mac mini + Apple Remote (avvio).

Il codice è nel pacchetto tvbox/ accanto a questo file (vedi tvbox/__init__.py).
Questo file resta in /opt/tvbox/tvd.py: lo avvia la sessione X (system/xinitrc).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tvbox.main import main  # noqa: E402

if __name__ == "__main__":
    main()
