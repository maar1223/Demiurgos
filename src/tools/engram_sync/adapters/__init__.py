"""Phase-1 adapters with conservative, explicitly authorized persistence."""

from ._common import BaseAdapter
from .arc_state import ArcStateAdapter
from .ideas import IdeasAdapter
from .lore_index import LoreIndexAdapter
from .templates import TemplatesAdapter

__all__ = ["ArcStateAdapter", "BaseAdapter", "IdeasAdapter", "LoreIndexAdapter",
           "TemplatesAdapter", "register_phase1"]


def register_phase1(registry, client, project, *, ideas_primary="mundos/Ideas",
                    ideas_secondary="mundos/vibrantes/ideas", estado=".demiurgos-estado.json",
                    lore_index="output/lore-index.json",
                    templates_catalog="plantillas/_catalog.json"):
    registry.register(IdeasAdapter(client, project, ideas_primary, ideas_secondary))
    registry.register(ArcStateAdapter(client, project, estado))
    registry.register(LoreIndexAdapter(client, project, lore_index))
    registry.register(TemplatesAdapter(client, project, catalog_path=templates_catalog))
    return registry
