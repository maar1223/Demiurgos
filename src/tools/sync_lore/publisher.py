"""Publisher stub — preview and publish entities for the wiki frontend."""

import logging

_logger = logging.getLogger(__name__)


def preview(entities: list[dict], mundo: str, mundos_path: str | None = None) -> dict:
    """Preview entity import without writing files.
    
    Returns a dict with preview information about what would be created/updated.
    """
    _logger.info("Publisher preview for mundo=%s (%d entities)", mundo, len(entities))
    return {
        "files": [],
        "total": len(entities),
        "created": 0,
        "updated": 0,
        "skipped": len(entities),
        "errors": [],
    }


def publish_entities(
    entities: list[dict],
    mundo: str,
    preview_only: bool = False,
    mundos_path: str | None = None,
) -> dict:
    """Publish entities to the atlas.
    
    Currently a stub — returns empty results.
    """
    _logger.info(
        "Publisher publish_entities for mundo=%s (%d entities, preview=%s)",
        mundo, len(entities), preview_only,
    )
    return {
        "files": [],
        "total": len(entities),
        "created": 0,
        "updated": 0,
        "skipped": len(entities),
        "errors": [],
    }
