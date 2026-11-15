from pathlib import PurePosixPath


def portable_catalog_path(value: str) -> PurePosixPath:
    return PurePosixPath(value.replace("\\", "/"))
