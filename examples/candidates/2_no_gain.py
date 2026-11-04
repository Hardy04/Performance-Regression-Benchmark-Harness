"""Candidate 2 — correct but no faster (cosmetic rewrite). Should be rejected: no significant gain."""
import time


def sum_of_squares(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i
    return total


if __name__ == "__main__":
    time.sleep(0.08)
    print(sum_of_squares(500_000))
