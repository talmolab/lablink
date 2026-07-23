"""MonitoringConfig defaults and structure."""

import ast
from pathlib import Path

from omegaconf import OmegaConf

from lablink_allocator_service.conf.structured_config import (
    Config,
    MonitoringConfig,
)


def test_monitoring_defaults_disabled():
    cfg = MonitoringConfig()
    assert cfg.enabled is False
    assert cfg.subject_window_patterns == []
    assert cfg.process_allowlist == [
        "sleap-train",
        "sleap-track",
        "sleap-label",
    ]
    assert cfg.watch_dir == "/home/client/Desktop"
    assert cfg.sample_interval_seconds == 2
    assert cfg.push_interval_seconds == 60


def test_config_includes_monitoring_field():
    cfg = Config()
    assert isinstance(cfg.monitoring, MonitoringConfig)
    assert cfg.monitoring.enabled is False


def test_monitoring_block_loads_from_yaml():
    raw = {
        "monitoring": {
            "enabled": True,
            "subject_window_patterns": ["deeplabcut"],
            "process_allowlist": ["custom-train"],
            "watch_dir": "/tmp/work",
            "sample_interval_seconds": 3,
            "push_interval_seconds": 30,
        }
    }
    schema = OmegaConf.structured(Config)
    merged = OmegaConf.merge(schema, OmegaConf.create(raw))
    assert merged.monitoring.enabled is True
    assert merged.monitoring.subject_window_patterns == ["deeplabcut"]
    assert merged.monitoring.process_allowlist == ["custom-train"]
    assert merged.monitoring.sample_interval_seconds == 3


def _monitoring_config_fields(source_path: Path) -> dict[str, tuple[str, str | None]]:
    """Extract (annotation, default) per field of a MonitoringConfig
    dataclass, via AST rather than import — lablink-allocator-service and
    lablink-client-service don't declare each other as a dependency, so a
    real import of the sibling package isn't available in either
    package's own CI test environment."""
    tree = ast.parse(source_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MonitoringConfig":
            result = {}
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    default = (
                        ast.unparse(stmt.value) if stmt.value is not None else None
                    )
                    result[stmt.target.id] = (ast.unparse(stmt.annotation), default)
            return result
    raise AssertionError(f"MonitoringConfig class not found in {source_path}")


def test_monitoring_config_matches_client_package():
    """allocator's and client's MonitoringConfig are independently
    maintained copies (issue: identified as duplication risk in a
    dead/duplicate-code audit). This guards against silent field drift
    between them — if it fails after an intentional change, update both
    dataclasses to match, don't just adjust this test.
    """
    repo_root = Path(__file__).resolve().parents[3]
    allocator_path = (
        repo_root
        / "packages/allocator/src/lablink_allocator_service/conf/structured_config.py"
    )
    client_path = (
        repo_root
        / "packages/client/src/lablink_client_service/conf/structured_config.py"
    )
    assert _monitoring_config_fields(allocator_path) == _monitoring_config_fields(
        client_path
    )
