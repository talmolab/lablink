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
    assert "resource_suffix" in plan.variables
    assert plan.variables["resource_suffix"] == "test"
