import os
import subprocess
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from domain.recovery_catalog import RecoveryCatalog
from domain.recovery_selection import RecoverySelection

try:
    from gui.catalog_browser import CatalogBrowser, CHECKED, PARTIAL
    from gui.widgets import configure_theme
except (ModuleNotFoundError, tk.TclError):
    GUI_AVAILABLE = False
else:
    GUI_AVAILABLE = True


def make_node(index, name, size, is_dir=False, path=""):
    return SimpleNamespace(
        record=SimpleNamespace(index=index, sequence_number=1, name=name, file_size=size, is_dir=is_dir),
        full_path=path or name,
        parent=None,
        children=[],
    )


@unittest.skipUnless(GUI_AVAILABLE, "Tkinter is required to test the browser widgets")
class CatalogBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        configure_theme(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.root_node = make_node(5, "root", 0, is_dir=True)
        self.folder = make_node(10, "folder", 0, is_dir=True, path="root/folder")
        self.nested = make_node(13, "nested", 0, is_dir=True, path="root/folder/nested")
        self.photo = make_node(11, "photo.jpg", 4096, path="root/folder/photo.jpg")
        self.pdf = make_node(12, "report.pdf", 2048, path="root/folder/nested/report.pdf")
        self.root_file = make_node(14, "loose.pdf", 1024, path="root/loose.pdf")
        for parent, child in ((self.root_node, self.folder), (self.folder, self.nested),
                              (self.folder, self.photo), (self.nested, self.pdf),
                              (self.root_node, self.root_file)):
            parent.children.append(child)
            child.parent = parent
        nodes = {node.record.index: node for node in (self.root_node, self.folder, self.nested,
                                                       self.photo, self.pdf, self.root_file)}
        self.catalog = RecoveryCatalog(nodes, [self.root_node])
        self.selection = RecoverySelection(self.catalog, {".jpg", ".pdf"})
        self.browser = CatalogBrowser(self.root, self.catalog, self.selection)
        self.browser.pack(fill="both", expand=True)
        self.root.update_idletasks()

    def tearDown(self):
        self.browser.destroy()

    def test_navigation_is_folder_only_and_file_table_lists_direct_files(self):
        root_iid = self.browser.folder_tree.get_children()[0]
        self.assertEqual(self.browser.folder_tree.item(root_iid, "text"), "root")
        self.assertNotIn("loose.pdf", str(self.browser.folder_tree.item(root_iid)))
        self.browser.show_directory(self.folder)
        rows = self.browser.file_table.get_children()
        self.assertEqual([self.browser.file_table.set(iid, "name") for iid in rows], ["photo.jpg"])
        self.browser.show_directory(self.nested)
        rows = self.browser.file_table.get_children()
        self.assertEqual([self.browser.file_table.set(iid, "name") for iid in rows], ["report.pdf"])
        self.browser.show_directory(self.root_node)
        rows = self.browser.file_table.get_children()
        self.assertEqual([self.browser.file_table.set(iid, "name") for iid in rows], ["loose.pdf"])

    def test_folder_check_updates_descendants_and_partial_state(self):
        root_iid = self.browser.folder_tree.get_children()[0]
        self.browser.folder_tree.focus(root_iid)
        self.browser._folder_opened()
        folder_iid = self.browser.folder_tree.get_children(root_iid)[0]
        folder = self.browser._nodes_by_iid[folder_iid]
        self.selection.set_checked(folder, True)
        self.assertEqual(self.selection.selected_count, 2)
        self.assertEqual(self.browser.folder_tree.set(folder_iid, "pick"), CHECKED)
        self.assertEqual(self.browser.folder_tree.set(root_iid, "pick"), PARTIAL)

    def test_nested_folder_is_loaded_and_can_be_selected_independently(self):
        root_iid = self.browser.folder_tree.get_children()[0]
        event = SimpleNamespace(x=0, y=0)
        with patch.object(self.browser.folder_tree, "identify_row", return_value=root_iid), \
             patch.object(self.browser.folder_tree, "identify_column", return_value="#0"), \
             patch.object(self.browser.folder_tree, "identify_element", return_value="Treeitem.indicator"):
            self.browser._folder_click(event)
        folder_iid = self.browser.folder_tree.get_children(root_iid)[0]
        with patch.object(self.browser.folder_tree, "identify_row", return_value=folder_iid), \
             patch.object(self.browser.folder_tree, "identify_column", return_value="#0"), \
             patch.object(self.browser.folder_tree, "identify_element", return_value="Treeitem.indicator"):
            self.browser._folder_click(event)
        nested_iid = self.browser.folder_tree.get_children(folder_iid)[0]
        with patch.object(self.browser.folder_tree, "identify_row", return_value=nested_iid), \
             patch.object(self.browser.folder_tree, "identify_column", return_value="#1"), \
             patch.object(self.browser.folder_tree, "identify_element", return_value="Treeitem.text"):
            result = self.browser._folder_click(event)
        self.assertEqual(result, "break")
        self.assertEqual(self.selection.selected_nodes(), [self.pdf])
        self.assertEqual(self.browser.folder_tree.set(nested_iid, "pick"), CHECKED)

    def test_main_window_starts_without_opening_a_disk(self):
        code = ("from gui.main_window import RecoveryMainWindow; "
                "w=RecoveryMainWindow(); w.withdraw(); "
                "assert w.selection is None; "
                "assert str(w.recover_button.cget('state')) == 'disabled'; w.destroy()")
        environment = dict(os.environ)
        source = os.path.dirname(os.path.dirname(__file__))
        result = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {source!r}); {code}"],
                                capture_output=True, text=True, timeout=20, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_window_keeps_selected_physical_disk_and_partition_together(self):
        from disk.inventory import NTFSVolume, PhysicalDisk
        from gui.main_window import RecoveryMainWindow

        window = RecoveryMainWindow(workflow=object(), inventory=object())
        window.withdraw()
        try:
            disk = PhysicalDisk(3, "Recovery drive", 4 * 1024 ** 3)
            window._disks_ready([disk])
            window.disk_var.set(disk.display_name)
            window._disk_selected()

            volume = NTFSVolume(3, 2, 4096, 1024 * 1024, 512, 4096, 1024,
                                8192, 8192, ((12288, 8, 0),), "Lost volume")
            window._volumes_ready([volume])
            window.partition_var.set(volume.display_name)
            window._partition_selected()

            self.assertEqual(window.selected_disk.number, 3)
            self.assertEqual(window.selected_volume.disk_number, 3)
            self.assertEqual(str(window.scan_button.cget("state")), "normal")
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
