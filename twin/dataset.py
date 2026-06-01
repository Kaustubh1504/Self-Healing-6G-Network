"""Real 5G telemetry traces from the TelecomTS dataset (arXiv:2510.06063).

The radio-access edges of the twin replay real per-UE KPI time series: a `normal`
trace in steady state, swapped for a labelled `anomalous` trace when a fault fires.

Raw TelecomTS metrics are downloaded once and preprocessed into compact local CSVs
under data/telecomts/ (only the columns we use, downsampled). At runtime only those
local CSVs are read, so the app needs no network access and no `huggingface_hub`.

To (re)build the local traces:  python -m twin.dataset
"""

from pathlib import Path

import pandas as pd

_LOCAL_DIR = Path(__file__).resolve().parent.parent / "data" / "telecomts"

# Compact trace schema: the KPIs we map from the raw metrics.
RADIO_COLUMNS = ["throughput_mbps", "packet_loss_pct", "utilization_pct", "snr_db", "rsrp_dbm"]

# Each radio edge of the twin and the real traces it can play (normal + anomalies).
# Keyed by sorted node-pair tuple to match twin.faults.edge_id.
RADIO_TRACES = {
    ("BS1", "UE1"): {"normal": "ZoneA_YouTube_normal", "jammer": "ZoneA_YouTube_jammer"},
    ("BS2", "UE2"): {"normal": "ZoneB_Twitch_normal", "congestion": "ZoneB_Twitch_congestion"},
    ("BS3", "UE3"): {"normal": "ZoneC_File_normal"},
}


def load_trace(key: str) -> pd.DataFrame:
    """Load a preprocessed local trace by key (e.g. 'ZoneA_YouTube_normal')."""
    return pd.read_csv(_LOCAL_DIR / f"{key}.csv")


# --------------------------------------------------------------------------- #
# One-time preprocessing (requires huggingface_hub; not needed to run the app).
# --------------------------------------------------------------------------- #

_REPO = "AliMaatouk/TelecomTS"
_TARGET_ROWS = 2000  # downsampled length per trace — plenty for a long live demo

# Local trace key -> raw metrics.csv path in the TelecomTS repo.
_SPECS = {
    "ZoneA_YouTube_normal": "normal/stationary/Zone_A/no_congestion/YouTube/raw/metrics.csv",
    "ZoneA_YouTube_jammer": "anomalous/jammer/YouTube/raw/metrics.csv",
    "ZoneB_Twitch_normal": "normal/stationary/Zone_B/no_congestion/Twitch/raw/metrics.csv",
    "ZoneB_Twitch_congestion": "normal/stationary/Zone_B/congestion/Twitch/raw/metrics.csv",
    "ZoneC_File_normal": "normal/stationary/Zone_C/no_congestion/File/raw/metrics.csv",
}


def _map_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map raw TelecomTS metrics to our compact KPI schema."""
    out = pd.DataFrame()
    # Bytes per 100 ms sample -> Mbps:  bytes * 8 bits / 1e6 / 0.1 s == bytes * 8 / 1e5.
    out["throughput_mbps"] = (df["TX_Bytes"] + df["RX_Bytes"]) * 8 / 1e5
    out["packet_loss_pct"] = (df["DL_BLER"] * 100).clip(0, 100)  # block error rate
    out["utilization_pct"] = df["PRB_Utilization_DL"].clip(0, 100)
    out["snr_db"] = df["UL_SNR"]
    out["rsrp_dbm"] = df["RSRP"]
    return out


def build_local_traces() -> None:
    """Download raw TelecomTS metrics and write compact, downsampled local CSVs."""
    from huggingface_hub import hf_hub_download

    _LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    for key, path in _SPECS.items():
        raw = pd.read_csv(hf_hub_download(repo_id=_REPO, filename=path, repo_type="dataset"))
        compact = _map_columns(raw)
        stride = max(1, len(compact) // _TARGET_ROWS)
        compact = compact.iloc[::stride].head(_TARGET_ROWS).reset_index(drop=True)
        compact.round(4).to_csv(_LOCAL_DIR / f"{key}.csv", index=False)
        print(f"  wrote {key}.csv  ({len(compact)} rows)")


if __name__ == "__main__":
    print(f"Building local TelecomTS traces in {_LOCAL_DIR} …")
    build_local_traces()
    print("Done.")
