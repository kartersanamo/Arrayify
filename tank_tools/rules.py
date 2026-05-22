from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TankRules:
    register_name_re: re.Pattern[str] = field(default=re.compile(r"^R(\d+)$"), init=False)
    tank_description_re: re.Pattern[str] = field(default=re.compile(r"^(.*) @ (\d+)$"), init=False)
    register_array_name_re: re.Pattern[str] = field(default=re.compile(r"^R(\d+)\[(\d+)\]$"), init=False)
    table_title_re: re.Pattern[str] = field(default=re.compile(r"^Tank Soundings for (.+?) containing "), init=False)
    tag_prefix_overrides: dict[str, str | None] = field(
        default_factory=lambda: {
            "Fuel Oil OverFlow Tank Volume": "FO_OVFL",
            "Fuel Oil SDT Day Tank Volume": "FO_SDT",
            "Ballast Anti Roll #1 Tank Volume": "BS_AR1",
            "Ballast Anti Roll #2 Tank Volume": "BS_AR2",
            "Ballast #7-C Tank Volume": "BS_7C",
            "Fuel Oil #6-P Tank Volume": "FO_6P",
            "Fuel Oil #6-S Tank Volume": "FO_6S",
            "Ballast AftPeak-P Tank Volume": "BS_APP",
            "Ballast AftPeak-S Tank Volume": "BS_APS",
            "Ballast ForePeak Tank Volume": "BS_FP",
            "Methanol Pump Void #1-S Volume": "ME_1S",
            "Methanol Pump Void #1-P Volume": "ME_1P",
            "Methanol Pump Void #2-S Volume": "ME_2S",
            "Methanol Pump Void #2-P Volume": "ME_2P",
            "WashWater Tank Volume": "WW",
            "Ballast AftPeak Void-P Tank Volume": "BS_APPV",
            "Ballast AftPeak Void-S Tank Volume": "BS_APSV",
        },
        init=False,
    )

    @staticmethod
    def round_up_to_25(value: int) -> int:
        return ((value + 24) // 25) * 25

    def is_register_name(self, value: str) -> bool:
        return bool(self.register_name_re.match(value or ""))

    @staticmethod
    def default_initial_value(data_type: str) -> str:
        if data_type.upper() == "REAL":
            return "0.0"
        return "0"

    @staticmethod
    def canonicalize_tank_description(description: str) -> str:
        canonical_description = description.strip()
        canonical_description = canonical_description.replace("Fuel Oil", "FO")
        canonical_description = canonical_description.replace("Liquid Mud", "LM")
        canonical_description = canonical_description.replace("Methanol", "METH")
        canonical_description = canonical_description.replace("Potable Water", "POTWATER")
        return canonical_description

    @staticmethod
    def format_custom_tag_name(custom_tag: str) -> str | None:
        normalized_custom_tag = re.sub(r"[\s-]+", "_", custom_tag.strip())
        if not normalized_custom_tag:
            return None

        if normalized_custom_tag.endswith("_TANK_TABLE"):
            return normalized_custom_tag

        if normalized_custom_tag.endswith("_TABLE"):
            normalized_custom_tag = normalized_custom_tag[: -len("_TABLE")]

        if normalized_custom_tag.endswith("_TANK"):
            return f"{normalized_custom_tag}_TABLE"

        return f"{normalized_custom_tag}_TANK_TABLE"

    def load_tag_prefix_map(self, rows: list[list[str]]) -> dict[str, str]:
        prefix_map: dict[str, str] = {}
        for row in rows[1:]:
            if len(row) <= 2:
                continue

            name = row[0].strip()
            description = row[2].strip()
            if not name or not description or not name.endswith("_LEVEL"):
                continue

            prefix_map.setdefault(self.canonicalize_tank_description(description), name[: -len("_LEVEL")])

        return prefix_map

    def extract_base_description(self, description: str) -> str:
        description_match = self.tank_description_re.match(description)
        return description_match.group(1).strip() if description_match else description.strip()

    def normalize_tag_name(
        self,
        row: list[str],
        prefix_map: dict[str, str],
        custom_tag_map: dict[str, str] | None = None,
    ) -> str | None:
        if len(row) <= 2:
            return None

        description = row[2].strip()
        if not description:
            return None

        base_description = self.extract_base_description(description)
        if custom_tag_map is not None and base_description in custom_tag_map:
            base_name = custom_tag_map[base_description]
            register_match = self.register_array_name_re.match(row[0])
            if register_match:
                return f"{base_name}[{register_match.group(2)}]"

            if self.is_register_name(row[0]):
                return base_name

            return None

        override_prefix = self.tag_prefix_overrides.get(base_description)
        if override_prefix is not None:
            prefix = override_prefix
        else:
            if base_description in self.tag_prefix_overrides and self.tag_prefix_overrides[base_description] is None:
                return None
            prefix = prefix_map.get(self.canonicalize_tank_description(base_description))

        if prefix is None:
            return None

        normalized_prefix = prefix if prefix.endswith("_TANK") else f"{prefix}_TANK"
        base_name = f"{normalized_prefix}_TABLE"
        register_match = self.register_array_name_re.match(row[0])
        if register_match:
            return f"{base_name}[{register_match.group(2)}]"

        if self.is_register_name(row[0]):
            return base_name

        return None

    def extract_table_key(self, table_title: str) -> str | None:
        match = self.table_title_re.match(table_title.strip())
        if not match:
            return None

        return match.group(1).strip()

    def table_key_to_description(self, table_key: str) -> str | None:
        fuel_match = re.match(r"^FUEL(\d)\.(P|S|C)$", table_key)
        if fuel_match:
            number = fuel_match.group(1)
            side = fuel_match.group(2)
            return f"Fuel Oil #{number}-{side} Tank Volume"

        if table_key == "FO_DAY.S":
            return "Fuel Oil Day-S Tank Volume"
        if table_key == "FO_DAY.P":
            return "Fuel Oil Day-P Tank Volume"
        if table_key == "FO_OVER.S":
            return "Fuel Oil OverFlow Tank Volume"

        lm_match = re.match(r"^LM(\d)\.(P|S)$", table_key)
        if lm_match:
            number = lm_match.group(1)
            side = lm_match.group(2)
            return f"Liquid Mud #{number}-{side} Tank Volume"

        meth_match = re.match(r"^METH(\d)\.(P|S)$", table_key)
        if meth_match:
            number = meth_match.group(1)
            side = meth_match.group(2)
            return f"Methanol #{number}-{side} Tank Volume"

        pot_match = re.match(r"^POTWATER\.(P|S)$", table_key)
        if pot_match:
            side = pot_match.group(1)
            return f"Potable Water-{side} Tank Volume"

        if table_key == "SEWAGE.S":
            return "Sewage Tank Volume"
        if table_key == "WASHWATER.P":
            return "WashWater Tank Volume"
        if table_key == "FOREPEAK.C":
            return "Ballast ForePeak Tank Volume"

        ballast_match = re.match(r"^BALLAST(\d+)([CW])\.(P|S|C)$", table_key)
        if ballast_match:
            number = ballast_match.group(1)
            location = ballast_match.group(2)
            side = ballast_match.group(3)
            if location == "W":
                return f"Ballast #{number}{side}-W Tank Volume"
            return f"Ballast #{number}{side}-C Tank Volume"

        if table_key == "ANTIROLL1.C":
            return "Ballast Anti Roll #1 Tank Volume"
        if table_key == "ANTIROLL2.C":
            return "Ballast Anti Roll #2 Tank Volume"
        if table_key == "BALLAST1.P":
            return None
        if table_key == "BALLAST1.S":
            return "Ballast #1-S Tank Volume"
        if table_key == "BALLAST7.C":
            return "Ballast #7-C Tank Volume"
        if table_key == "AFTPEAK1.P":
            return "Ballast AftPeak-P Tank Volume"
        if table_key == "AFTPEAK1.S":
            return "Ballast AftPeak-S Tank Volume"

        return None

    @staticmethod
    def read_sounding_volumes(table) -> list[str]:
        volumes: list[str] = []
        for row in table.rows[2:]:
            if len(row.cells) < 2:
                continue

            volume_text = row.cells[1].text.strip()
            if not volume_text:
                continue

            volumes.append(volume_text)

        return volumes

    def find_base_row_index(self, rows: list[list[str]], description: str) -> int | None:
        for row_index, row in enumerate(rows[1:], start=1):
            if len(row) <= 12:
                continue

            if row[2] != description:
                continue

            if not self.is_register_name(row[0]) or "[" in row[0]:
                continue

            return row_index

        return None
