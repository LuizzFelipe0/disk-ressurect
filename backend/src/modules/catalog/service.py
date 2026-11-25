"""Pure catalog queries and supported file types."""

import heapq

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
        total_matches = 0

        def matching_nodes():
            nonlocal total_matches
            for node in snapshot.catalog.nodes.values():
                if (normalized in node.name.casefold()
                        or normalized in node.full_path.casefold()):
                    total_matches += 1
                    yield node

        sort_key = lambda node: (node.full_path.casefold(), node.full_path)
        if limit < 0:
            matches = list(matching_nodes())
            matches.sort(key=sort_key)
            return tuple(matches[:limit]), total_matches

        # Keep only the requested prefix in memory while still counting every hit.
        matches = heapq.nsmallest(max(1, limit), matching_nodes(), key=sort_key)
        return tuple(matches[:limit]), total_matches
