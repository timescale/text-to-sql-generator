def split_number(n: int) -> tuple[int, int, int]:
    base = n // 3
    remainder = n % 3

    # Initialize the parts with base values
    part1 = base
    part2 = base
    part3 = base

    # Distribute the remainder
    if remainder > 0:
        part1 += 1
    if remainder > 1:
        part2 += 1

    return part1, part2, part3
