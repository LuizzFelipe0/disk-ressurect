"""Fast hierarchical selection state shared by desktop catalog views."""


class RecoverySelection:
    UNCHECKED = 0
    PARTIALLY_CHECKED = 1
    CHECKED = 2

    def __init__(self, catalog, supported_extensions, extensions=None, min_file_size_kb=0):
        self.catalog = catalog
        self.supported_extensions = tuple(supported_extensions)
        initial_extensions = (
            catalog.available_extensions(self.supported_extensions)
            if extensions is None else extensions
        )
        self.extensions = {extension.casefold() for extension in initial_extensions}
        self.min_file_size_kb = max(0, int(min_file_size_kb))
        self.eligible_nodes = []
        self._eligible_keys = set()
        self._selected_keys = set()
        self._eligible_counts = {}
        self._selected_counts = {}
        self._listeners = []
        self.set_filters(self.extensions, self.min_file_size_kb, notify=False)

    def add_listener(self, listener):
        self._listeners.append(listener)

    def set_filters(self, extensions, min_file_size_kb=0, notify=True):
        self.extensions = {extension.casefold() for extension in extensions}
        self.min_file_size_kb = max(0, int(min_file_size_kb))
        self.eligible_nodes = self.catalog.eligible_files(
            self.supported_extensions,
            self.extensions,
            self.min_file_size_kb * 1024,
        )
        self._eligible_keys = {self.catalog.node_key(node) for node in self.eligible_nodes}
        self._selected_keys.intersection_update(self._eligible_keys)
        self._rebuild_counts()
        if notify:
            self._notify(None)

    def set_checked(self, node, checked):
        # Checkbox changes should visit only the selected subtree, not rebuild
        # a lookup over every eligible file on each click.
        targets = []
        pending = [node]
        visited = set()
        while pending:
            current = pending.pop()
            key = self.catalog.node_key(current)
            if key in visited:
                continue
            visited.add(key)
            if key in self._eligible_keys:
                targets.append(current)
            pending.extend(reversed(tuple(getattr(current, "children", ()))))
        changed = []
        delta = 1 if checked else -1
        for file_node in targets:
            key = self.catalog.node_key(file_node)
            if checked and key in self._selected_keys:
                continue
            if not checked and key not in self._selected_keys:
                continue
            if checked:
                self._selected_keys.add(key)
            else:
                self._selected_keys.remove(key)
            current = file_node
            while current is not None:
                current_key = self.catalog.node_key(current)
                self._selected_counts[current_key] = self._selected_counts.get(current_key, 0) + delta
                changed.append(current)
                current = getattr(current, "parent", None)
        if changed:
            self._notify(self._unique_nodes(changed))
        return bool(changed)

    def select_all(self):
        if self._selected_keys == self._eligible_keys:
            return False
        self._selected_keys = set(self._eligible_keys)
        self._selected_counts = dict(self._eligible_counts)
        self._notify(None)
        return True

    def clear(self):
        if not self._selected_keys:
            return False
        self._selected_keys.clear()
        self._selected_counts.clear()
        self._notify(None)
        return True

    def check_state(self, node):
        key = self.catalog.node_key(node)
        eligible = self._eligible_counts.get(key, 0)
        if not eligible:
            return None
        selected = self._selected_counts.get(key, 0)
        if not selected:
            return self.UNCHECKED
        if selected == eligible:
            return self.CHECKED
        return self.PARTIALLY_CHECKED

    def is_eligible(self, node):
        return self.catalog.node_key(node) in self._eligible_keys

    def eligible_count_for(self, node):
        return self._eligible_counts.get(self.catalog.node_key(node), 0)

    def files_in(self, directory):
        return self.catalog.files_in(directory, self._eligible_keys)

    def selected_nodes(self):
        return [
            node for node in self.eligible_nodes
            if self.catalog.node_key(node) in self._selected_keys
        ]

    @property
    def selected_count(self):
        return len(self._selected_keys)

    @property
    def eligible_count(self):
        return len(self.eligible_nodes)

    def _rebuild_counts(self):
        eligible_counts = {}
        selected_counts = {}
        for file_node in self.eligible_nodes:
            is_selected = self.catalog.node_key(file_node) in self._selected_keys
            current = file_node
            while current is not None:
                key = self.catalog.node_key(current)
                eligible_counts[key] = eligible_counts.get(key, 0) + 1
                if is_selected:
                    selected_counts[key] = selected_counts.get(key, 0) + 1
                current = getattr(current, "parent", None)
        self._eligible_counts = eligible_counts
        self._selected_counts = selected_counts

    def _notify(self, nodes):
        for listener in tuple(self._listeners):
            listener(nodes)

    def _unique_nodes(self, nodes):
        unique = {}
        for node in nodes:
            unique[self.catalog.node_key(node)] = node
        return tuple(unique.values())
