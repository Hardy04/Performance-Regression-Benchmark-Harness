def find_duplicates(items: list[int]) -> list[int]:
    seen: set[int] = set()
    dupes: dict[int, None] = {}
    for x in items:
        if x in seen:
            dupes[x] = None
        seen.add(x)
    return list(dupes)


if __name__ == "__main__":
    data = [(i * 7919) % 6000 for i in range(8000)]
    print(len(find_duplicates(data)), sum(find_duplicates(data)))
