"""Tests for annotation snapshot model."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

import pytest

from app.models.annotation_snapshot import AnnotationSnapshot


class TestAnnotationSnapshotModel:
    """Test AnnotationSnapshot model fields."""

    def test_model_fields(self):
        """Test model has expected fields."""
        snap = AnnotationSnapshot()
        assert hasattr(snap, "id")
        assert hasattr(snap, "image_id")
        assert hasattr(snap, "filename")
        assert hasattr(snap, "version")
        assert hasattr(snap, "box_data")
        assert hasattr(snap, "box_count")
        assert hasattr(snap, "snapshot_type")
        assert hasattr(snap, "create_by")
        assert hasattr(snap, "create_time")

    def test_model_creation(self):
        """Test creating an AnnotationSnapshot instance."""
        snap = AnnotationSnapshot(
            image_id=42,
            filename="test.jpg",
            version=1,
            box_data="0 0.5 0.5 0.1 0.1\n1 0.3 0.3 0.2 0.2",
            box_count=2,
            snapshot_type="auto",
            create_by="admin",
        )
        assert snap.image_id == 42
        assert snap.filename == "test.jpg"
        assert snap.version == 1
        assert snap.box_count == 2
        assert snap.snapshot_type == "auto"

    def test_model_defaults(self):
        """Test model can be created with minimal fields."""
        snap = AnnotationSnapshot(image_id=1, filename="a.jpg", version=1, box_data="")
        assert snap.image_id == 1

    def test_table_name(self):
        """Test table name is correct."""
        assert AnnotationSnapshot.__tablename__ == "annotation_snapshot"
