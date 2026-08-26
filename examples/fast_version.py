"""Example target — fast version (closed-form formula)."""


def sum_of_squares(n: int) -> int:
    return n * (n - 1) * (2 * n - 1) // 6


if __name__ == "__main__":
    result = sum_of_squares(500_000)
    print(result)
