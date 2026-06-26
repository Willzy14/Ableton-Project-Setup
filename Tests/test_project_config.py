"""Regression tests for project builder configuration."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import project_builder  # noqa: E402


def test_environment_overrides_project_paths():
    old_template = os.environ.get("ABLETON_TEMPLATE_PATH")
    old_output = os.environ.get("ABLETON_OUTPUT_BASE")
    try:
        os.environ["ABLETON_TEMPLATE_PATH"] = r"C:\Temp\Template.als"
        os.environ["ABLETON_OUTPUT_BASE"] = r"D:\Output"

        assert project_builder.get_template_path() == Path(r"C:\Temp\Template.als")
        assert project_builder.get_output_base() == Path(r"D:\Output")
    finally:
        if old_template is None:
            os.environ.pop("ABLETON_TEMPLATE_PATH", None)
        else:
            os.environ["ABLETON_TEMPLATE_PATH"] = old_template
        if old_output is None:
            os.environ.pop("ABLETON_OUTPUT_BASE", None)
        else:
            os.environ["ABLETON_OUTPUT_BASE"] = old_output


def test_environment_controls_ml_defaults():
    old_enable = os.environ.get("ENABLE_ML_CLASSIFIER")
    old_python = os.environ.get("PYTHON_ML_EXE")
    try:
        os.environ["ENABLE_ML_CLASSIFIER"] = "false"
        os.environ["PYTHON_ML_EXE"] = r"C:\Python313\python.exe"

        assert project_builder.get_enable_ml_classifier() is False
        assert project_builder.get_ml_python_exe() == r"C:\Python313\python.exe"
    finally:
        if old_enable is None:
            os.environ.pop("ENABLE_ML_CLASSIFIER", None)
        else:
            os.environ["ENABLE_ML_CLASSIFIER"] = old_enable
        if old_python is None:
            os.environ.pop("PYTHON_ML_EXE", None)
        else:
            os.environ["PYTHON_ML_EXE"] = old_python


if __name__ == "__main__":
    test_environment_overrides_project_paths()
    test_environment_controls_ml_defaults()
    print("project config tests passed")
