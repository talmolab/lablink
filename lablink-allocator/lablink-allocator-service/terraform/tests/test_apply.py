import pytest
import tftest
import os


@pytest.fixture(scope="module")
def output(fixture_dir):
    base_dir = os.path.join(os.path.dirname(__file__), "..")
    tf = tftest.TerraformTest(tfdir=base_dir, basedir=base_dir)
    tf.setup(extra_files=["plan.auto.tfvars"])
    var_path = os.path.join(fixture_dir, "plan.auto.tfvars")
    tf.apply(tf_var_file=var_path, output=True, auto_approve=True)
    yield tf.output()
    tf.destroy(
        **{
            "auto_approve": True,
        },
        tf_var_file=var_path
    )


def test_apply(output):
    ids = output["vm_instance_ids"]
    vm_ips = output["vm_public_ips"]
    assert len(ids) == 3
    assert len(vm_ips) == 3
    assert output["lablink_private_key_pem"] is not None
