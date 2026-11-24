import ast
from pathlib import Path
import unittest


SRC_ROOT = Path(__file__).resolve().parents[1]
MODULES_ROOT = SRC_ROOT / "modules"
ALLOWED_MODULE_FILES = {
    "__init__.py", "entities.py", "dto.py", "service.py", "repository.py", "exceptions.py",
}


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_feature_modules_use_the_standard_file_layout(self):
        for feature in MODULES_ROOT.iterdir():
            if not feature.is_dir() or not (feature / "__init__.py").exists():
                continue
            unexpected = {
                path.name for path in feature.glob("*.py")
                if path.name not in ALLOWED_MODULE_FILES
            }
            with self.subTest(feature=feature.name):
                self.assertFalse(unexpected, f"Unexpected files: {sorted(unexpected)}")

    def test_feature_modules_do_not_import_infrastructure(self):
        violations = []
        for path in MODULES_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported = node.module if isinstance(node, ast.ImportFrom) else None
                names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
                if (imported and imported.startswith("infrastructure.")) or any(
                    name == "infrastructure" or name.startswith("infrastructure.")
                    for name in names
                ):
                    violations.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}")
        self.assertEqual([], violations)

    def test_feature_module_dependencies_are_acyclic(self):
        features = {
            path.name for path in MODULES_ROOT.iterdir()
            if path.is_dir() and (path / "__init__.py").exists()
        }
        graph = {feature: set() for feature in features}
        for path in MODULES_ROOT.rglob("*.py"):
            source_feature = path.relative_to(MODULES_ROOT).parts[0]
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported = node.module if isinstance(node, ast.ImportFrom) else None
                names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
                targets = ([imported] if imported else []) + names
                for target in targets:
                    parts = target.split(".")
                    if len(parts) > 1 and parts[0] == "modules" and parts[1] in features:
                        if parts[1] != source_feature:
                            graph[source_feature].add(parts[1])

        visiting = set()
        visited = set()

        def visit(feature):
            if feature in visiting:
                return False
            if feature in visited:
                return True
            visiting.add(feature)
            if not all(visit(dependency) for dependency in graph[feature]):
                return False
            visiting.remove(feature)
            visited.add(feature)
            return True

        self.assertTrue(all(visit(feature) for feature in graph), graph)

    def test_catalog_and_signature_validator_share_the_supported_format_contract(self):
        from infrastructure.formats.signature import (
            FileSignatureValidator,
        )
        from modules.catalog.service import CatalogService

        self.assertEqual(
            FileSignatureValidator.supported_extensions(),
            CatalogService.supported_extensions(),
        )

    def test_format_validators_do_not_import_discovery_or_filesystem_adapters(self):
        violations = []
        formats_root = SRC_ROOT / "infrastructure" / "formats"
        for path in formats_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported = node.module if isinstance(node, ast.ImportFrom) else None
                names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
                targets = ([imported] if imported else []) + names
                if any(
                    target.startswith(("infrastructure.carving", "infrastructure.filesystems"))
                    for target in targets
                ):
                    violations.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}")
        self.assertEqual([], violations)

    def test_storage_and_catalog_features_remain_filesystem_neutral(self):
        violations = []
        for feature in ("storage", "catalog"):
            root = MODULES_ROOT / feature
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    imported = node.module if isinstance(node, ast.ImportFrom) else None
                    names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
                    targets = ([imported] if imported else []) + names
                    if any(target.startswith((
                        "infrastructure.filesystems.ntfs", "modules.disk",
                        "modules.recovery",
                    )) for target in targets):
                        violations.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
