def fib(n: int) -> int:
    a, b = 1, 1
    for _ in range(n - 2):
        a, b = b, a + b
    return a


if __name__ == "__main__":
    print(fib(30))
