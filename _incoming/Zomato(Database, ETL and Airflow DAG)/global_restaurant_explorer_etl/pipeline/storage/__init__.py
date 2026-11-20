"""Storage backends for Bronze raw data preservation (Local & Azure Blob Storage)."""

from pipeline.storage.base import BronzeStorageBackend, StoredObject
from pipeline.storage.local_storage import LocalBronzeStorage
from pipeline.storage.azure_blob_storage import AzureBlobBronzeStorage

__all__ = [
    "BronzeStorageBackend",
    "StoredObject",
    "LocalBronzeStorage",
    "AzureBlobBronzeStorage",
]
