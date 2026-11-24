"""Pure catalog queries and supported file types."""

from modules.catalog.entities import RecoveryCatalogSnapshot
from modules.catalog.entities import SUPPORTED_CATALOG_EXTENSIONS


class CatalogService:
    @staticmethod
    def supported_extensions():
        return SUPPORTED_CATALOG_EXTENSIONS

    @staticmethod
    def search(snapshot: RecoveryCatalogSnapshot, query, limit=500):
        normalized = query.casefold()
        if not normalized:
            return (), 0
        matches = [
            node for node in snapshot.catalog.nodes.values()
            if normalized in node.name.casefold()
            or normalized in node.full_path.casefold()
        ]
        matches.sort(key=lambda node: (node.full_path.casefold(), node.full_path))
        return tuple(matches[:limit]), len(matches)
