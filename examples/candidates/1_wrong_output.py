"""Candidate 1 — looks clever but is off by one. Should be rejected by the correctness gate."""
import time


def sum_of_squares(n: int) -> int:
    return n * (n + 1) * (2 * n + 1) // 6


if __name__ == "__main__":
    time.sleep(0.08)
    print(sum_of_squares(500_000))
