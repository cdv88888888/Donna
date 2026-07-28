#!/usr/bin/env python3
"""Train (or retrain) Donna's voice from your real messages.

Pulls your Gmail sent-mail and Telegram history, distills a style guide per
channel, and stores it. Run this after setup, and re-run any time you want her
to re-learn how you write.

    python scripts/train_voice.py            # both channels + merge
    python scripts/train_voice.py email      # just email
    python scripts/train_voice.py telegram   # just Telegram
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from donna.db import init_db  # noqa: E402
from donna import voice  # noqa: E402


def main() -> None:
    init_db()
    which = sys.argv[1] if len(sys.argv) > 1 else "all"

    if which in ("all", "email"):
        print(voice.train_email())
    if which in ("all", "telegram"):
        print(voice.train_telegram())
    if which == "all":
        print(voice.build_global_profile())
    print("\nDone. Donna will use this voice on every draft.")


if __name__ == "__main__":
    main()
