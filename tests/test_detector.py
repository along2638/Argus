"""Tests for YOLO detector module."""

from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from app.core.detector import MultiModelDetector, ModelSession


@pytest.fixture
def mock_frame():
    """Create a mock frame."""
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def detector():
    """Create a MultiModelDetector with mocked model paths."""
    with patch("app.core.detector.settings") as mock_settings:
        mock_settings.YOLO_ONNX_PATH = "models/mock_general.onnx"
        mock_settings.FIRE_SMOKE_MODEL_PATH = "models/mock_fire.onnx"
        mock_settings.HELMET_MODEL_PATH = "models/mock_helmet.onnx"
        mock_settings.CLASS_MAPPING = {
            "0": "person", "14": "bird", "15": "cat", "16": "dog",
            "17": "horse", "18": "sheep", "19": "cow", "20": "elephant",
            "21": "bear", "22": "zebra", "23": "giraffe",
        }
        mock_settings.FIRE_SMOKE_CLASS_MAPPING = {"0": "fire", "1": "smoke"}
        mock_settings.HELMET_CLASS_MAPPING = {"0": "helmet", "1": "no-helmet", "2": "person"}
        mock_settings.ALARM_CLASSES = ["person", "fire", "smoke", "no-helmet"]
        mock_settings.CONFIDENCE_THRESHOLD = 0.7
        det = MultiModelDetector()
        yield det


class TestModelSession:
    """Test ModelSession class."""

    def test_init(self):
        """Test ModelSession initialization."""
        session = ModelSession("models/test.onnx", "test_model")
        assert session.model_path == "models/test.onnx"
        assert session.model_name == "test_model"
        assert session.session is None
        assert session.input_shape == (640, 640)

    def test_close(self):
        """Test ModelSession close."""
        session = ModelSession("models/test.onnx", "test_model")
        session.session = MagicMock()
        session.close()
        assert session.session is None

    def test_close_when_none(self):
        """Test close when session is already None."""
        session = ModelSession("models/test.onnx", "test_model")
        session.close()  # Should not raise
        assert session.session is None


class TestMultiModelDetector:
    """Test MultiModelDetector class."""

    def test_init_models(self, detector):
        """Test that all three models are registered."""
        assert "general" in detector._models
        assert "fire_smoke" in detector._models
        assert "helmet" in detector._models

    def test_class_mappings(self, detector):
        """Test class mappings are loaded."""
        assert "general" in detector._class_mapping
        assert "fire_smoke" in detector._class_mapping
        assert "helmet" in detector._class_mapping

    def test_preprocess(self, detector, mock_frame):
        """Test frame preprocessing."""
        input_shape = (640, 640)
        blob, scale = detector._preprocess(mock_frame, input_shape)

        assert blob.shape == (1, 3, 640, 640)
        assert blob.dtype == np.float32
        assert scale[0] == pytest.approx(640 / 640, rel=0.1)
        assert scale[1] == pytest.approx(480 / 640, rel=0.1)

    def test_preprocess_different_input_shape(self, detector, mock_frame):
        """Test preprocessing with non-square input shape."""
        input_shape = (320, 320)
        blob, scale = detector._preprocess(mock_frame, input_shape)

        assert blob.shape == (1, 3, 320, 320)
        assert blob.dtype == np.float32

    def test_postprocess_empty(self, detector):
        """Test postprocessing with no detections."""
        output = np.array([[[100, 100, 200, 200, 0.1, 0]]])
        scale = (1.0, 1.0)

        detections = detector._postprocess(output, scale, confidence_threshold=0.5)
        assert len(detections) == 0

    def test_postprocess_with_detections(self, detector):
        """Test postprocessing with valid detections."""
        output = np.array([[
            [100, 100, 200, 200, 0.85, 1],  # class 1, conf 0.85
            [50, 50, 150, 150, 0.92, 3],     # class 3, conf 0.92
            [200, 200, 300, 300, 0.3, 0],    # class 0, conf 0.3 (below threshold)
        ]])
        scale = (1.0, 1.0)

        detections = detector._postprocess(output, scale, confidence_threshold=0.5)
        assert len(detections) == 2
        assert detections.class_id[0] == 1
        assert detections.class_id[1] == 3

    def test_postprocess_scaling(self, detector):
        """Test that boxes are properly scaled."""
        output = np.array([[
            [100, 100, 200, 200, 0.85, 0],
        ]])
        scale = (2.0, 2.0)

        detections = detector._postprocess(output, scale, confidence_threshold=0.5)
        assert len(detections) == 1
        assert detections.xyxy[0][0] == 200  # x1 * 2
        assert detections.xyxy[0][1] == 200  # y1 * 2

    def test_get_class_name_general(self, detector):
        """Test class name mapping for general model."""
        assert detector.get_class_name("general", 0) == "person"
        assert detector.get_class_name("general", 14) == "bird"
        assert detector.get_class_name("general", 15) == "cat"

    def test_get_class_name_helmet(self, detector):
        """Test class name mapping for helmet model."""
        assert detector.get_class_name("helmet", 0) == "helmet"
        assert detector.get_class_name("helmet", 1) == "no-helmet"
        assert detector.get_class_name("helmet", 2) == "person"

    def test_get_class_name_fire_smoke(self, detector):
        """Test class name mapping for fire_smoke model."""
        assert detector.get_class_name("fire_smoke", 0) == "fire"
        assert detector.get_class_name("fire_smoke", 1) == "smoke"

    def test_get_class_name_unknown(self, detector):
        """Test class name mapping for unknown class ID."""
        assert detector.get_class_name("general", 99) == "unknown_99"

    def test_get_class_name_unknown_model(self, detector):
        """Test class name mapping for unknown model."""
        assert detector.get_class_name("nonexistent", 0) == "unknown_0"

    def test_is_alarm_class(self, detector):
        """Test alarm class check."""
        assert detector.is_alarm_class("no-helmet") is True
        assert detector.is_alarm_class("person") is True
        assert detector.is_alarm_class("fire") is True
        assert detector.is_alarm_class("smoke") is True
        assert detector.is_alarm_class("helmet") is False
        assert detector.is_alarm_class("bird") is False
        assert detector.is_alarm_class("unknown") is False

    def test_close(self, detector):
        """Test detector close releases all sessions."""
        # Set mock sessions
        for model in detector._models.values():
            model.session = MagicMock()

        detector.close()

        for model in detector._models.values():
            assert model.session is None

    @pytest.mark.asyncio
    async def test_detect_with_model(self, detector, mock_frame):
        """Test detection with a specific model."""
        mock_session = MagicMock()
        mock_session.get_inputs.return_value = [MagicMock(shape=[1, 3, 640, 640])]
        mock_session.get_inputs.return_value[0].name = "images"
        mock_session.run.return_value = [np.zeros((1, 0, 6))]

        # Patch the model's get_session to return our mock
        detector._models["general"].session = mock_session
        detector._models["general"].input_shape = (640, 640)

        detections, inference_time = await detector.detect_with_model(mock_frame, "general")
        assert inference_time >= 0
        mock_session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_detect_with_model_unknown(self, detector, mock_frame):
        """Test detection with unknown model raises ValueError."""
        with pytest.raises(ValueError, match="Unknown model"):
            await detector.detect_with_model(mock_frame, "nonexistent")
