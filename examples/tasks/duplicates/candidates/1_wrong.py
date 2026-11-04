def find_duplicates(items: list[int]) -> list[int]:
    return sorted(set(items))


if __name__ == "__main__":
    data = [(i * 7919) % 6000 for i in range(8000)]
    print(len(find_duplicates(data)), sum(find_duplicates(data)))
