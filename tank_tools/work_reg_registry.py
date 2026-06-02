from __future__ import annotations

from tank_tools.rules import TankRules

WORK_REG_COUNT = 4


def scan_work_register_bindings(rows: list[list[str]], rules: TankRules) -> dict[str, list[str]]:
    """Map tank volume descriptions to the four work register names for each tank block."""
    bindings: dict[str, list[str]] = {}
    row_index = 1

    while row_index < len(rows):
        row = rows[row_index]
        if len(row) <= 2 or not rules.is_register_name(row[0]) or "[" in row[0]:
            row_index += 1
            continue

        volume_description = row[2].strip()
        if rules.is_tank_volume_description(volume_description):
            register_names = _find_work_registers_for_volume(rows, row_index, volume_description, rules)
            if register_names is not None:
                bindings[volume_description] = register_names
                row_index = _advance_past_tank_group(rows, row_index, volume_description, register_names, rules)
                continue

        description_match = rules.tank_description_re.match(row[2])
        if description_match and description_match.group(2) == "0":
            base_description = description_match.group(1)
            if base_description not in bindings:
                register_names = _find_work_registers_after_sounding_block(rows, row_index, base_description, rules)
                if register_names is not None:
                    bindings[base_description] = register_names
                    block_end = _find_sounding_block_end(rows, row_index, base_description, rules)
                    row_index = block_end + WORK_REG_COUNT if block_end is not None else row_index + 1
                    continue

        row_index += 1

    return bindings


def _find_work_registers_for_volume(
    rows: list[list[str]],
    volume_index: int,
    volume_description: str,
    rules: TankRules,
) -> list[str] | None:
    immediate = _collect_empty_work_register_names(rows, volume_index + 1, rules)
    if immediate is not None:
        return immediate

    block_start = volume_index + 1
    block_end = _find_sounding_block_end(rows, block_start, volume_description, rules)
    if block_end is None:
        return None

    return _collect_empty_work_register_names(rows, block_end, rules)


def _find_work_registers_after_sounding_block(
    rows: list[list[str]],
    block_start: int,
    base_description: str,
    rules: TankRules,
) -> list[str] | None:
    block_end = _find_sounding_block_end(rows, block_start, base_description, rules)
    if block_end is None:
        return None

    return _collect_empty_work_register_names(rows, block_end, rules)


def _find_sounding_block_end(
    rows: list[list[str]],
    start_index: int,
    base_description: str,
    rules: TankRules,
) -> int | None:
    if start_index >= len(rows):
        return None

    start_row = rows[start_index]
    if len(start_row) <= 2 or not rules.is_register_name(start_row[0]) or "[" in start_row[0]:
        return None

    description_match = rules.tank_description_re.match(start_row[2])
    if description_match is None or description_match.group(2) != "0":
        return None

    if description_match.group(1) != base_description:
        return None

    base_register = int(start_row[0][1:])
    scan_index = start_index
    expected_index = 0

    while scan_index < len(rows):
        current_row = rows[scan_index]
        if len(current_row) <= 2 or not rules.is_register_name(current_row[0]) or "[" in current_row[0]:
            break

        current_description_match = rules.tank_description_re.match(current_row[2])
        if current_description_match is None:
            break

        if (
            current_description_match.group(1) != base_description
            or int(current_description_match.group(2)) != expected_index
            or int(current_row[0][1:]) != base_register + expected_index
        ):
            break

        expected_index += 1
        scan_index += 1

    if expected_index <= 1:
        return None

    return scan_index


def _advance_past_tank_group(
    rows: list[list[str]],
    volume_index: int,
    volume_description: str,
    register_names: list[str],
    rules: TankRules,
) -> int:
    immediate_end = volume_index + 1 + len(register_names)
    immediate = _collect_empty_work_register_names(rows, volume_index + 1, rules)
    if immediate == register_names:
        block_start = immediate_end
    else:
        block_start = volume_index + 1

    block_end = _find_sounding_block_end(rows, block_start, volume_description, rules)
    if block_end is None:
        return immediate_end

    return block_end + len(register_names)


def _collect_empty_work_register_names(
    rows: list[list[str]],
    start_index: int,
    rules: TankRules,
) -> list[str] | None:
    register_names: list[str] = []
    scan_index = start_index

    while scan_index < len(rows) and len(register_names) < WORK_REG_COUNT:
        current_row = rows[scan_index]
        if len(current_row) <= 2 or not rules.is_register_name(current_row[0]) or "[" in current_row[0]:
            break

        if current_row[2].strip():
            break

        register_names.append(current_row[0].split("[", 1)[0])
        scan_index += 1

    if len(register_names) != WORK_REG_COUNT:
        return None

    return register_names
