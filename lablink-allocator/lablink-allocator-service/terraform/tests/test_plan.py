import os
import pytest
import tftest
import re


@pytest.fixture(scope="module")
def plan(fixture_dir):
    """
    Fixture to validate the Terraform plan using the provided fixtures.
    """
    base_dir = os.path.join(os.path.dirname(__file__), "..")
    tf = tftest.TerraformTest(tfdir=base_dir, basedir=base_dir)
    tf.setup(extra_files=["plan.auto.tfvars"])
    var_path = os.path.join(fixture_dir, "plan.auto.tfvars")
    return tf.plan(output=True, tf_var_file=var_path)


def test_variables(plan):
    """Test Terraform variables."""
    assert plan.variables["instance_count"] == 3
    assert plan.variables["allocator_ip"] == "10.0.0.1"
    assert plan.variables["machine_type"] == "t2.micro"
    assert plan.variables["image_name"] == "ghcr.io/test-image"
    assert plan.variables["repository"] == "https://github.com/example/repo.git"
    assert plan.variables["client_ami_id"] == "ami-067cc81f948e50e06"
    assert plan.variables["resource_suffix"] == "ci-test"
    assert plan.variables["subject_software"] == "test-software"
    assert plan.variables["gpu_support"] == "true"
    assert plan.variables["cloud_init_output_log_group"] == "lablink-cloud-init-logs"
    assert plan.variables["region"] == "us-west-2"
    assert plan.variables["ssh_user"] == "ubuntu"


def _collect_resources(plan, type_name: str, name: str):
    """Return {full_key: resource_dict} for resources like aws_instance.lablink_vm[0]."""
    prefix = f"{type_name}.{name}["
    return {k: v for k, v in plan.resources.items() if k.startswith(prefix)}


def _extract_index(resource_key: str):
    """
    Returns the index/key inside [...].
    - For count: '0', '1', ...
    - For for_each: '"foo"', '"bar"'
    """
    m = re.search(r"\[(.+)\]$", resource_key)
    return m.group(1) if m else None


def _numeric_sort_key(k: str):
    """Sort by numeric index if possible, else by raw token (handles for_each)."""
    idx = _extract_index(k)
    if idx is None:
        return (1, k)
    idx_clean = idx.strip("\"'")
    return (0, int(idx_clean)) if idx_clean.isdigit() else (1, idx_clean)


def test_vm_count(plan):
    """Test the number of VM instances."""
    assert (
        len(_collect_resources(plan, "aws_instance", "lablink_vm"))
        == plan.variables["instance_count"]
    )


def test_lablink_vm(plan):
    """Test Terraform resources."""
    resources = _collect_resources(plan, "aws_instance", "lablink_vm")

    for i, (key, resource) in enumerate(
        sorted(resources.items(), key=lambda x: _numeric_sort_key(x[0]))
    ):
        assert resource["type"] == "aws_instance"
        assert resource["values"]["tags"]["Name"] == f"lablink-vm-ci-test-{i + 1}"
        assert resource["values"]["ami"] == plan.variables["client_ami_id"]
        assert resource["values"]["instance_type"] == plan.variables["machine_type"]


def test_lablink_security_group(plan):
    resource = plan.resources["aws_security_group.lablink_sg"]
    assert resource["type"] == "aws_security_group"
    assert resource["values"]["name"] == "lablink_client_ci-test_sg"
    assert resource["values"]["ingress"][0]["from_port"] == 22
    assert resource["values"]["ingress"][0]["to_port"] == 22
    assert resource["values"]["ingress"][0]["protocol"] == "tcp"
    assert resource["values"]["ingress"][0]["cidr_blocks"] == ["0.0.0.0/0"]
    assert resource["values"]["egress"][0]["from_port"] == 0
    assert resource["values"]["egress"][0]["to_port"] == 0
    assert resource["values"]["egress"][0]["protocol"] == "-1"
    assert resource["values"]["egress"][0]["cidr_blocks"] == ["0.0.0.0/0"]


def test_lablink_key_pair(plan):
    resource = plan.resources["aws_key_pair.lablink_key_pair"]
    assert resource["type"] == "aws_key_pair"
    assert resource["values"]["key_name"] == "lablink_key_pair_client_ci-test"


def test_output(plan):
    """Test Terraform output."""
    assert "vm_instance_ids" in plan.outputs
    assert "vm_public_ips" in plan.outputs
    assert "lablink_private_key_pem" in plan.outputs
    assert "vm_instance_names" in plan.outputs
    assert "startup_time_seconds_per_instance" in plan.outputs
    assert "startup_time_hms_per_instance" in plan.outputs
    assert "startup_time_avg_seconds" in plan.outputs
    assert "startup_time_min_seconds" in plan.outputs
    assert "startup_time_max_seconds" in plan.outputs
