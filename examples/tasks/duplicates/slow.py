"""Task: quadratic duplicate detection."""


def find_duplicates(items: list[int]) -> list[int]:
    dupes: list[int] = []
    for i, x in enumerate(items):
        if x in items[:i] and x not in dupes:
            dupes.append(x)
    return dupes


if __name__ == "__main__":
    data = [(i * 7919) % 6000 for i in range(8000)]
    print(len(find_duplicates(data)), sum(find_duplicates(data)))
