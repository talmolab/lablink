import json
import pytest
import re
import subprocess
from pathlib import Path


@pytest.fixture(scope="module")
def plan(fixture_dir):
    """
    Fixture to validate the Terraform plan using the provided fixtures.
    """
    # Find the Terraform directory in the package (not in tests)
    pkg_root = Path(__file__).parent.parent.parent.parent / "src/lablink_allocator_service"
    base_dir = pkg_root / "terraform"
    var_path = (Path(fixture_dir) / "plan.auto.tfvars").resolve()

    # Initialize and create the plan
    subprocess.run(
        ["terraform", "init", "-input=false", "-no-color"], cwd=base_dir, check=True
    )
    subprocess.run(
        ["terraform", "plan", f"-var-file={var_path}", "-out=plan.tfplan", "-no-color"],
        cwd=base_dir,
        check=True,
    )
    result = subprocess.run(
        ["terraform", "show", "-json", "plan.tfplan"],
        cwd=base_dir,
        check=True,
        capture_output=True,
    )
    tfplan = json.loads(result.stdout)

    yield tfplan


def test_variables(plan):
    """Test Terraform variables."""
    assert plan["variables"]["instance_count"]["value"] == 3
    assert plan["variables"]["allocator_ip"]["value"] == "10.0.0.1"
    assert plan["variables"]["machine_type"]["value"] == "t2.micro"
    assert plan["variables"]["image_name"]["value"] == "ghcr.io/test-image"
    assert (
        plan["variables"]["repository"]["value"]
        == "https://github.com/example/repo.git"
    )
    assert plan["variables"]["client_ami_id"]["value"] == "ami-067cc81f948e50e06"
    assert plan["variables"]["resource_suffix"]["value"] == "ci-test"
    assert plan["variables"]["subject_software"]["value"] == "test-software"
    assert plan["variables"]["gpu_support"]["value"] == "true"
    assert (
        plan["variables"]["cloud_init_output_log_group"]["value"]
        == "lablink-cloud-init-logs"
    )
    assert plan["variables"]["region"]["value"] == "us-west-2"
    assert plan["variables"]["ssh_user"]["value"] == "ubuntu"


def _resource_map(plan):
    """
    Flatten all resources into {address: resource_dict}.
    Handles root_module and any child_modules.
    """

    def collect(mod, acc):
        for r in mod.get("resources", []):
            acc[r["address"]] = r
        for cm in mod.get("child_modules", []):
            collect(cm, acc)
        return acc

    root = plan.get("planned_values", {}).get("root_module", {}) or {}
    return collect(root, {})


def _collect_resources(plan, type_name: str, name: str):
    """Return {full_address: resource_dict} for e.g. aws_instance.lablink_vm[0]."""
    prefix = f"{type_name}.{name}["
    rmap = _resource_map(plan)
    return {addr: r for addr, r in rmap.items() if addr.startswith(prefix)}


def _extract_index(address: str):
    """
    Returns the index/key inside [...] from a full address.
    - For count: '0', '1', ...
    - For for_each: '"foo"', '"bar"'
    """
    m = re.search(r"\[(.+)\]$", address)
    return m.group(1) if m else None


def _numeric_sort_key(address: str):
    """Sort by numeric index if possible, else by raw token."""
    idx = _extract_index(address)
    if idx is None:
        return (1, address)
    idx_clean = idx.strip("\"'")
    return (0, int(idx_clean)) if idx_clean.isdigit() else (1, idx_clean)


def test_vm_count(plan):
    """Test the number of VM instances."""
    instances = _collect_resources(plan, "aws_instance", "lablink_vm")
    assert len(instances) == plan["variables"]["instance_count"]["value"]


def test_lablink_vm(plan):
    """Test Terraform resources for EC2 instances."""
    instances = _collect_resources(plan, "aws_instance", "lablink_vm")

    sorted_instances = sorted(instances.items(), key=lambda x: _numeric_sort_key(x[0]))

    for i, (addr, resource) in enumerate(sorted_instances):
        assert resource["type"] == "aws_instance"
        assert resource["values"]["tags"]["Name"] == f"lablink-vm-ci-test-{i + 1}"
        assert resource["values"]["ami"] == plan["variables"]["client_ami_id"]["value"]
        instance_type = resource["values"]["instance_type"]
        assert instance_type == plan["variables"]["machine_type"]["value"]


def test_lablink_security_group(plan):
    rmap = _resource_map(plan)
    resource = rmap["aws_security_group.lablink_sg"]
    assert resource["type"] == "aws_security_group"
    v = resource["values"]

    assert v["name"] == "lablink_client_ci-test_sg"
    # Ingress SSH
    assert v["ingress"][0]["from_port"] == 22
    assert v["ingress"][0]["to_port"] == 22
    assert v["ingress"][0]["protocol"] == "tcp"
    assert v["ingress"][0]["cidr_blocks"] == ["0.0.0.0/0"]
    # Egress all
    assert v["egress"][0]["from_port"] == 0
    assert v["egress"][0]["to_port"] == 0
    assert v["egress"][0]["protocol"] == "-1"
    assert v["egress"][0]["cidr_blocks"] == ["0.0.0.0/0"]


def test_lablink_key_pair(plan):
    rmap = _resource_map(plan)
    resource = rmap["aws_key_pair.lablink_key_pair"]
    assert resource["type"] == "aws_key_pair"
    assert resource["values"]["key_name"] == "lablink_key_pair_client_ci-test"


def test_output(plan):
    """Test Terraform outputs exist in planned values."""
    outs = plan.get("planned_values", {}).get("outputs", {}) or {}
    # Just assert keys exist (values may be unknown at plan time)
    for k in [
        "vm_instance_ids",
        "vm_public_ips",
        "lablink_private_key_pem",
        "vm_instance_names",
        "startup_time_seconds_per_instance",
        "startup_time_hms_per_instance",
        "startup_time_avg_seconds",
        "startup_time_min_seconds",
        "startup_time_max_seconds",
    ]:
        assert k in outs
