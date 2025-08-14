import os
import pytest
import tftest


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
    assert plan.variables["instance_count"] == 1
    assert plan.variables["resource_suffix"] == "test"
    assert plan.variables["allocator_ip"] == "10.0.0.1"
    assert plan.variables["machine_type"] == "t2.medium"
    assert plan.variables["image_name"] == "lablink-client-image"
    assert plan.variables["repository"] == "https://github.com/example/repo.git"
    assert plan.variables["client_ami_id"] == "ami-12345678"
    assert plan.variables["subject_software"] == "sleap"
    assert plan.variables["gpu_support"] == "true"
