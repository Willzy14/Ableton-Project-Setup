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


def test_environment_controls_kick_detector_defaults():
    old_enable = os.environ.get("ENABLE_KICK_DETECTOR")
    old_model = os.environ.get("KICK_DETECTOR_MODEL_PATH")
    old_source = os.environ.get("KICK_DETECTOR_SOURCE_DIR")
    old_threshold = os.environ.get("KICK_DETECTOR_THRESHOLD")
    old_device = os.environ.get("KICK_DETECTOR_DEVICE")
    old_python = os.environ.get("KICK_DETECTOR_PYTHON_EXE")
    old_timeout = os.environ.get("KICK_DETECTOR_TIMEOUT_SEC")
    try:
        os.environ["ENABLE_KICK_DETECTOR"] = "true"
        os.environ["KICK_DETECTOR_MODEL_PATH"] = r"C:\Models\kick_crnn_V3.pt"
        os.environ["KICK_DETECTOR_SOURCE_DIR"] = r"C:\Repos\Kick Detector\Source"
        os.environ["KICK_DETECTOR_THRESHOLD"] = "0.3"
        os.environ["KICK_DETECTOR_DEVICE"] = "cpu"
        os.environ["KICK_DETECTOR_PYTHON_EXE"] = "py -3.14"
        os.environ["KICK_DETECTOR_TIMEOUT_SEC"] = "180"

        assert project_builder.get_enable_kick_detector() is True
        assert project_builder.get_kick_detector_model_path() == Path(r"C:\Models\kick_crnn_V3.pt")
        assert project_builder.get_kick_detector_source_dir() == Path(r"C:\Repos\Kick Detector\Source")
        assert project_builder.get_kick_detector_threshold() == 0.3
        assert project_builder.get_kick_detector_device() == "cpu"
        assert project_builder.get_kick_detector_python_exe() == "py -3.14"
        assert project_builder.get_kick_detector_timeout_sec() == 180
    finally:
        for key, value in {
            "ENABLE_KICK_DETECTOR": old_enable,
            "KICK_DETECTOR_MODEL_PATH": old_model,
            "KICK_DETECTOR_SOURCE_DIR": old_source,
            "KICK_DETECTOR_THRESHOLD": old_threshold,
            "KICK_DETECTOR_DEVICE": old_device,
            "KICK_DETECTOR_PYTHON_EXE": old_python,
            "KICK_DETECTOR_TIMEOUT_SEC": old_timeout,
        }.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_environment_overrides_project_paths()
    test_environment_controls_ml_defaults()
    test_environment_controls_kick_detector_defaults()
    print("project config tests passed")
