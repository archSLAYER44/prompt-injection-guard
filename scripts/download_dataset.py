"""Download the public datasets and convert them to the project's CSV format.

Every source keeps its own official train/test split; nothing is re-split at random.

    mirzaakhi/prompt-injection-detection-dataset   GitHub, CC BY 4.0     main train + official test
    deepset/prompt-injections                      Hugging Face, Apache 2.0   English + German
    jackhhao/jailbreak-classification              Hugging Face, Apache 2.0   jailbreak vs benign prompts
    Lakera/gandalf_ignore_instructions             Hugging Face, MIT     real injection attempts only

Run from the project root:
    python scripts/download_dataset.py
"""
from pathlib import Path
from urllib.request import urlretrieve

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"

HF = "https://huggingface.co/datasets/{repo}/resolve/main/{path}"
PRIMARY_URL = (
    "https://raw.githubusercontent.com/mirzaakhi/"
    "prompt-injection-detection-dataset/main/prompt_injection_dataset.csv"
)
SOURCES = {
    "deepset": ("deepset/prompt-injections", {
        "train": ["data/train-00000-of-00001-9564e8b05b4757ab.parquet"],
        "test": ["data/test-00000-of-00001-701d16158af87368.parquet"],
    }),
    "jackhhao": ("jackhhao/jailbreak-classification", {
        "train": ["default/jailbreak_dataset_train.csv"],
        "test": ["default/jailbreak_dataset_test.csv"],
    }),
    "gandalf": ("Lakera/gandalf_ignore_instructions", {
        "train": ["data/train-00000-of-00001-ded53be747ff55cd.parquet",
                  "data/validation-00000-of-00001-94481a2a09ff2fff.parquet"],
        "test": ["data/test-00000-of-00001-bc92128b9288a6d1.parquet"],
    }),
}

COLUMNS = ["text", "label", "category", "technique", "language", "source"]


def fetch(url, dest):
    if dest.exists():
        return dest
    print(f"  downloading {dest.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, dest)
    return dest


def read(path):
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def to_labels(source, frame):
    """Map each source's own label scheme to 1 = injection, 0 = benign."""
    if source == "jackhhao":
        frame = frame.rename(columns={"prompt": "text"})
        frame["label"] = (frame["type"] == "jailbreak").astype(int)
    elif source == "gandalf":
        frame["label"] = 1   # the dataset contains injection attempts only
    frame["label"] = frame["label"].astype(int)
    frame["category"] = source
    frame["technique"] = ""
    frame["language"] = ""
    frame["source"] = source
    return frame[COLUMNS]


def build_primary():
    raw = read(fetch(PRIMARY_URL, RAW / "mirzaakhi.csv"))
    unknown = set(raw["label"].unique()) - {"malicious", "benign"}
    if unknown:
        raise ValueError(f"unexpected label values in primary dataset: {unknown}")

    df = raw.rename(columns={"prompt": "text"})
    df["label"] = (df["label"] == "malicious").astype(int)
    df["source"] = "mirzaakhi"

    # Keep the dataset's own split: its test set holds out whole attack types.
    for split, name in [("train", "injection_train.csv"), ("test", "injection_test.csv")]:
        part = df.loc[df["split"] == split, COLUMNS].reset_index(drop=True)
        part.to_csv(DATA / name, index=False)
        print(f"  wrote {name}: {len(part)} rows")


def build_extra():
    parts = {"train": [], "test": []}
    for source, (repo, splits) in SOURCES.items():
        for split, paths in splits.items():
            for path in paths:
                local = RAW / f"{source}_{split}_{Path(path).name}"
                frame = read(fetch(HF.format(repo=repo, path=path), local))
                parts[split].append(to_labels(source, frame))

    for split, name in [("train", "extra_train.csv"), ("test", "extra_test.csv")]:
        frame = pd.concat(parts[split], ignore_index=True)
        frame.to_csv(DATA / name, index=False)
        counts = frame.groupby("source")["label"].agg(["size", "sum"])
        print(f"  wrote {name}: {len(frame)} rows")
        print(counts.rename(columns={"size": "rows", "sum": "injections"}).to_string())


def main():
    DATA.mkdir(exist_ok=True)
    print("Primary dataset (mirzaakhi):")
    build_primary()
    print("Extra sources (deepset, jackhhao, gandalf):")
    build_extra()


if __name__ == "__main__":
    main()
