import json
import threading
from pathlib import Path

class ProdIDManager:
    """
    Thread-safe manager for leasing sequential production IDs (prod_ids).
    Enforces lowercase prefix and 6-digit minimum numeral range.
    """
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.lock = threading.Lock()
        self._validate_config_exists()

    def _validate_config_exists(self) -> None:
        """Create a default config if it does not exist."""
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            default_config = {
                "prefix": "db",
                "range_start": 100000,
                "range_end": 999999,
                "next_value": 100000
            }
            self.config_path.write_text(json.dumps(default_config, indent=2))

    def _load_and_validate(self) -> dict:
        """Load, validate constraints (lowercase prefix, >=6-digit range), and return config."""
        try:
            config = json.loads(self.config_path.read_text())
        except Exception as e:
            raise RuntimeError(f"Failed to read production config: {e}")

        # Enforce lowercase prefix
        config["prefix"] = str(config.get("prefix", "db")).lower()

        # Enforce 6-digit numeral validation
        start = int(config.get("range_start", 100000))
        end = int(config.get("range_end", 999999))
        next_val = int(config.get("next_value", 100000))

        if start < 100000 or end < 100000:
            raise ValueError(f"Production range values must be at least 6 digits long. Got start={start}, end={end}")

        if next_val < start or next_val > end:
            raise ValueError(f"Next value {next_val} is out of bounds [{start}, {end}]")

        config["range_start"] = start
        config["range_end"] = end
        config["next_value"] = next_val

        return config

    def lease_id(self) -> str:
        """
        Thread-safely lease the next sequential production ID.
        Returns prefix + numerals combined (e.g. 'db100000').
        """
        with self.lock:
            config = self._load_and_validate()
            current_val = config["next_value"]
            prefix = config["prefix"]

            # Format is combined prefix + numeral
            prod_id = f"{prefix}{current_val}"

            # Increment and save
            next_val = current_val + 1
            if next_val > config["range_end"]:
                raise ValueError(f"Leased ID range exhausted! Reached maximum value: {config['range_end']}")

            config["next_value"] = next_val
            self.config_path.write_text(json.dumps(config, indent=2))

            return prod_id
