"""Test the full project build pipeline with Ak1ra stems."""
import sys
sys.path.insert(0, "Source")
from project_builder import build_project
from pathlib import Path

stem_folder = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes\2. Ongoing Stem Mixes\Ak1ra - The Way [Ramzi Karam] Project\Audio\STEMS - AK1RA - THE WAY - 122 bpm")
output_base = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\0.1---GIT HUB---\Ableton Project Setup\Test Output")

output_base.mkdir(exist_ok=True)

build_project(
    stem_folder=stem_folder,
    artist="TEST Ak1ra",
    title="The Way",
    label="Test Run",
    bpm=122,
    output_base=output_base,
)
