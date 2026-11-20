"""Optional Azure Blob Storage Bronze backend using the official Azure SDK."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from pipeline.storage.base import BronzeStorageBackend, StoredObject


class AzureBlobBronzeStorage(BronzeStorageBackend):
    """
    Uploads raw CSV snapshots and metadata.json to Azure Blob Storage.
    Credentials are read exclusively from environment configuration; never hardcoded.
    """

    backend_name = "azure"

    def __init__(
        self,
        container_name: str,
        connection_string: Optional[str] = None,
        account_url: Optional[str] = None,
    ) -> None:
        if not container_name:
            raise ValueError("AZURE_STORAGE_CONTAINER must be set for Azure storage backend.")
        if not connection_string and not account_url:
            raise ValueError(
                "Either AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL must be configured."
            )
        self.container_name = container_name
        self.connection_string = connection_string
        self.account_url = account_url

    def _get_blob_service_client(self):
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "azure-storage-blob is not installed. Run `pip install azure-storage-blob` "
                "to enable the Azure Bronze storage backend."
            ) from exc

        if self.connection_string:
            return BlobServiceClient.from_connection_string(self.connection_string)

        try:
            from azure.identity import DefaultAzureCredential  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "azure-identity is required when authenticating via AZURE_STORAGE_ACCOUNT_URL."
            ) from exc

        return BlobServiceClient(account_url=self.account_url, credential=DefaultAzureCredential())

    def store_batch(
        self,
        source_file: Path,
        source_name: str,
        batch_id: str,
        ingestion_date: str,
        metadata: Dict[str, Any],
    ) -> StoredObject:
        year, month, day = ingestion_date.split("-")
        prefix = f"bronze/{source_name}/{year}/{month}/{day}/batch_{batch_id}"
        data_blob_path = f"{prefix}/{source_file.name}"
        meta_blob_path = f"{prefix}/metadata.json"

        service_client = self._get_blob_service_client()
        container_client = service_client.get_container_client(self.container_name)
        if not container_client.exists():
            container_client.create_container()

        data_blob = container_client.get_blob_client(data_blob_path)
        with source_file.open("rb") as stream:
            data_blob.upload_blob(stream, overwrite=False)

        enriched_meta = dict(metadata)
        enriched_meta["bronze_blob_path"] = data_blob_path
        enriched_meta["storage_backend"] = self.backend_name

        meta_blob = container_client.get_blob_client(meta_blob_path)
        meta_blob.upload_blob(
            json.dumps(enriched_meta, indent=2).encode("utf-8"),
            overwrite=False,
        )

        return StoredObject(
            backend=self.backend_name,
            uri=f"az://{self.container_name}/{data_blob_path}",
            metadata_uri=f"az://{self.container_name}/{meta_blob_path}",
            checksum_sha256=metadata["source_file_hash"],
            size_bytes=metadata["source_file_size"],
        )
