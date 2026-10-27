from domain.recovery_catalog import RecoveryCatalog


class RecoveryPlanner:
    def __init__(self, catalog: RecoveryCatalog, supported_extensions):
        self.catalog = catalog
        self.supported_extensions = frozenset(extension.casefold() for extension in supported_extensions)
        self.extensions = set(self.supported_extensions)
        self.minimum_size_bytes = 0

    def set_filters(self, extensions=None, minimum_size_kb=0):
        self.extensions = self.supported_extensions if extensions is None else {
            extension.casefold() for extension in extensions
        }
        self.minimum_size_bytes = max(0, int(minimum_size_kb)) * 1024

    def is_eligible(self, node):
        return self.catalog.is_eligible(
            node,
            self.supported_extensions.intersection(self.extensions),
            self.minimum_size_bytes,
        )

    def candidates(self):
        return self.catalog.eligible_files(
            self.supported_extensions,
            self.extensions,
            self.minimum_size_bytes,
        )

    def plan(self, selected_nodes, excluded_nodes=()):
        eligible = self.candidates()
        selected = self.catalog.plan_selection(selected_nodes, eligible)
        if not excluded_nodes:
            return selected
        excluded_keys = {
            self.catalog.node_key(node)
            for node in self.catalog.plan_selection(excluded_nodes, eligible)
        }
        return [node for node in selected if self.catalog.node_key(node) not in excluded_keys]
