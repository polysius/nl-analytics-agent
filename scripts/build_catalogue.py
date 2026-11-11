"""Embed every column of the F1 database into catalog.columns. Run once after loading the data."""

from nlagent.catalogue import build_catalogue
from nlagent.retrieval import embed_texts

if __name__ == "__main__":
    count = build_catalogue(embed_texts)
    print(f"Indexed {count} columns into catalog.columns")
