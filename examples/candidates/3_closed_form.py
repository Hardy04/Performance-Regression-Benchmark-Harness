"""Candidate 3 — closed-form formula, no overhead. Should be accepted."""


def sum_of_squares(n: int) -> int:
    return n * (n - 1) * (2 * n - 1) // 6


if __name__ == "__main__":
    print(sum_of_squares(500_000))
