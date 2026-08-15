# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
from typing import Any, Callable


def ask_local_consent(subject: str, tool: str, arguments: dict[str, Any], input_fn: Callable[[str], str] = input) -> bool:
    print("\nR740 chiede di usare uno strumento su questo computer")
    print(f"Account: {subject}")
    print(f"Strumento: {tool} (sola lettura)")
    print("Argomenti:")
    print(json.dumps(arguments, ensure_ascii=False, indent=2))
    answer = input_fn("Consenti una volta? Scrivi SI: ").strip().casefold()
    return answer == "si"
