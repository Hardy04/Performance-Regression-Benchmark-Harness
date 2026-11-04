"""Example target — slow version (simulates a naive algorithm)."""

import time


def sum_of_squares(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i
    return total


if __name__ == "__main__":
    time.sleep(0.08)          # simulate extra overhead
    result = sum_of_squares(500_000)
    print(result)
