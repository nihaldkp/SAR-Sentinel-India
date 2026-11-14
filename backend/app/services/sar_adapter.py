
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import rasterio

from app.schemas.integration import (
    OutputAssetRegistration,
    OutputRegistrationRequest,
    ProcessingAdapterInput,
)
from app.services.nisar_gcov import (
    PROCESSOR_VERSION,
    process_gcov_product,
)


class NisarGcovAdapter:
    """Adapter connecting the NISAR GCOV processor to integration jobs."""

    def process(
        self, request: ProcessingAdapterInput
    ) -> OutputRegistrationRequest:
        job_directory = Path(request.output_directory).resolve()
        output_directory = job_directory / "nisar-gcov"

        source_path = Path(request.local_file_path).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(
                "The verified NISAR acquisition file is unavailable."
            )

        # The integration service creates job_directory before calling
        # this adapter. The processor requires a new output directory.
        result = process_gcov_product(
            hdf5_path=source_path,
            product_id=request.acquisition.product_id,
            river_id=request.acquisition.river_id,
            output_directory=output_directory,
        )

        outputs: list[OutputAssetRegistration] = []

        metadata_path = output_directory / "processing-metadata.json"
        if not metadata_path.is_file():
            raise RuntimeError(
                "The SAR processor did not create processing metadata."
            )

        mask_path = output_directory / "candidate-water-mask.tif"
        if mask_path.is_file():
            outputs.append(
                self._raster_asset(
                    request.job_id,
                    job_directory,
                    mask_path,
                    role="candidate_water_mask",
                    units="class_code",
                )
            )

        measurements_path = output_directory / "gcov-measurements.tif"
        if measurements_path.is_file():
            outputs.append(
                self._raster_asset(
                    request.job_id,
                    job_directory,
                    measurements_path,
                    role="gcov_measurements",
                    units="dimensionless_gamma0_linear_power",
                )
            )

        vector_path = output_directory / "candidate-water.geojson"
        if vector_path.is_file():
            outputs.append(
                self._vector_asset(
                    request.job_id,
                    job_directory,
                    vector_path,
                )
            )

        outputs.append(
            OutputAssetRegistration(
                role="processing_metadata",
                storage_key=self._storage_key(
                    request.job_id,
                    job_directory,
                    metadata_path,
                ),
                output_type="metadata",
                media_type="application/json",
                metadata={
                    "format": "NISAR GCOV processing metadata",
                    "scientific_validation_status": "not_performed",
                    "processor_version": PROCESSOR_VERSION,
                },
            )
        )

        metrics = {
            key: value
            for key, value in result.items()
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
        }

        return OutputRegistrationRequest(
            outputs=outputs,
            result_metadata={
                "processor": "NISAR GCOV candidate open-water classification",
                "processor_version": PROCESSOR_VERSION,
                "requested_processing_version": request.processing_version,
                "status": result.get("status"),
                "scientific_validation_status": "not_performed",
                "processing_result": result,
            },
            metrics=metrics,
        )

    @staticmethod
    def _storage_key(
        job_id: str,
        job_directory: Path,
        file_path: Path,
    ) -> str:
        relative_path = file_path.resolve().relative_to(
            job_directory.resolve()
        )
        return f"{job_id}/{relative_path.as_posix()}"

    @classmethod
    def _raster_asset(
        cls,
        job_id: str,
        job_directory: Path,
        path: Path,
        *,
        role: str,
        units: str,
    ) -> OutputAssetRegistration:
        with rasterio.open(path) as dataset:
            if dataset.crs is None:
                raise ValueError(
                    f"Raster output has no CRS: {path.name}"
                )

            metadata: dict[str, Any] = {
                "crs": dataset.crs.to_string(),
                "width": dataset.width,
                "height": dataset.height,
                "transform": list(tuple(dataset.transform)[:6]),
                "units": units,
                "nodata": dataset.nodata,
                "band_count": dataset.count,
                "dtype": dataset.dtypes[0],
            }

        return OutputAssetRegistration(
            role=role,
            storage_key=cls._storage_key(
                job_id,
                job_directory,
                path,
            ),
            output_type="raster",
            media_type="image/tiff",
            metadata=metadata,
        )

    @classmethod
    def _vector_asset(
        cls,
        job_id: str,
        job_directory: Path,
        path: Path,
    ) -> OutputAssetRegistration:
        document = json.loads(
            path.read_text(encoding="utf-8")
        )

        geometry_types = {
            feature.get("geometry", {}).get("type")
            for feature in document.get("features", [])
            if feature.get("geometry")
        }

        geometry_type = (
            next(iter(geometry_types))
            if len(geometry_types) == 1
            else "GeometryCollection"
        )

        return OutputAssetRegistration(
            role="candidate_water_polygons",
            storage_key=cls._storage_key(
                job_id,
                job_directory,
                path,
            ),
            output_type="vector",
            media_type="application/geo+json",
            metadata={
                "crs": "EPSG:4326",
                "geometry_type": geometry_type,
                "display_only": True,
            },
        )
