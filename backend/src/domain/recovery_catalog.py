"""Framework-independent recovery catalog and hierarchical selection rules."""

import os


class RecoveryCatalog:
    def __init__(self, nodes, root_nodes=None):
        self.nodes = nodes
        self.root_nodes = list(root_nodes or ())
        if not self.root_nodes:
            self.root_nodes = [node for node in nodes.values() if getattr(node, "parent", None) is None]
        self.file_nodes = []
        self._files_by_extension = {}
        for node in nodes.values():
            if node.record.is_dir:
                continue
            extension = os.path.splitext(node.record.name)[1].casefold()
            self.file_nodes.append(node)
            self._files_by_extension.setdefault(extension, []).append(node)

    @staticmethod
    def node_key(node):
        """Return a stable key for selections across UI model refreshes."""
        record = node.record
        return (
            getattr(record, "index", None),
            getattr(record, "sequence_number", None),
            os.path.normcase(getattr(node, "full_path", "")),
        )

    def available_extensions(self, supported_extensions):
        supported = {extension.casefold() for extension in supported_extensions}
        return sorted(extension for extension in self._files_by_extension if extension in supported)

    def eligible_files(self, supported_extensions, extensions=None, min_file_size=0):
        supported = {extension.casefold() for extension in supported_extensions}
        selected = supported if extensions is None else {extension.casefold() for extension in extensions}
        threshold = max(0, int(min_file_size))
        eligible_keys = {
            self.node_key(node)
            for extension in supported.intersection(selected)
            for node in self._files_by_extension.get(extension, ())
            if int(node.record.file_size) >= threshold
        }
        return [
            node for node in self.file_nodes
            if self.node_key(node) in eligible_keys
        ]

    @staticmethod
    def is_eligible(node, allowed_extensions, min_file_size=0):
        if node.record.is_dir:
            return False
        extension = os.path.splitext(node.record.name)[1].casefold()
        return extension in allowed_extensions and int(node.record.file_size) >= min_file_size

    def plan_selection(self, selected_nodes, eligible_files):
        """Expand selected folders to eligible files and deduplicate nested checks."""
        eligible_by_key = {self.node_key(node): node for node in eligible_files}
        selected_keys = set()
        visited = set()
        pending = list(reversed(tuple(selected_nodes)))
        while pending:
            node = pending.pop()
            key = self.node_key(node)
            if key in visited:
                continue
            visited.add(key)
            if key in eligible_by_key:
                selected_keys.add(key)
            pending.extend(reversed(tuple(getattr(node, "children", ()))))
        return [node for key, node in eligible_by_key.items() if key in selected_keys]

    def files_in(self, directory, eligible_keys):
        children = self.root_nodes if directory is None else directory.children
        return [
            node for node in children
            if not node.record.is_dir and self.node_key(node) in eligible_keys
        ]
