"""AWSProvider — behavior-preserving wrapper over existing AWS utilities."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from lablink_allocator_service.providers.connectivity.allocator_proxied import (
    AllocatorProxiedClientConnectivity,
)
from lablink_allocator_service.providers.protocol import (
    ClientHandle,
    ProviderActionNotWired,
    ProvisionResult,
)
from lablink_allocator_service.utils.aws_utils import (
    check_support_nvidia,
    current_instance_security_group,
    NotOnEC2Error,
    stop_start_ec2_instance,
    upload_to_s3,
)
from lablink_allocator_service.utils.sg_audit import (
    SGAuditFailure,
    audit_terraform_plan,
)
from lablink_allocator_service.utils.terraform_utils import (
    get_instance_ids,
    get_instance_names,
    get_instance_timings,
)

# ANSI escape sequence stripper — moved from main.py to keep the
# provider self-contained for SR-F1.
_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class AWSProvider:
    name = "aws"
    can_provision_hosts = True
    can_destroy_hosts = True
    can_recover_hosts = True

    def __init__(self, *, region=None, terraform_dir=None, **_):
        self._region = region
        self._terraform_dir = terraform_dir
        self.client_connectivity = AllocatorProxiedClientConnectivity()

    def recover_hosts(self, handles: list[ClientHandle]) -> bool:
        # Verbatim of reboot.py's EC2 fallback: stop_start_ec2_instance.
        # Returns True iff EVERY recycle succeeded — the caller
        # (reboot.py) uses this to decide record_reboot vs error log,
        # so failure must NOT masquerade as success.
        all_ok = True
        for h in handles:
            region = h.provider_metadata.get("region", self._region)
            if not stop_start_ec2_instance(h.id, region=region):
                all_ok = False
        return all_ok

    def list_hosts(self) -> list[ClientHandle]:
        ids = get_instance_ids(terraform_dir=self._terraform_dir)
        names = get_instance_names(terraform_dir=self._terraform_dir)
        return [
            ClientHandle(id=i, hostname=n, provider_metadata={"region": self._region})
            for i, n in zip(ids, names)
        ]

    def provision_hosts(self, count: int, spec: dict) -> ProvisionResult:
        """Run `terraform plan + audit + apply` for `count` new client hosts.

        Moves the inline logic that used to live in main.py's /api/launch
        handler behind the provider seam (SR-F1). `spec` is a dict of
        runtime values that used to be assembled inline in the route.

        Raises:
            RuntimeError: if terraform_dir is None
            SGAuditFailure: propagated from audit_terraform_plan when
                the plan would expose :6080 / :7070 to the internet
            subprocess.CalledProcessError: propagated from any
                terraform invocation failure
        """
        if self._terraform_dir is None:
            raise RuntimeError(
                "AWSProvider not configured with terraform_dir — cannot provision."
            )
        terraform_dir = Path(self._terraform_dir)
        runtime_file = terraform_dir / "terraform.runtime.tfvars"

        # GPU detection (moved from main.py)
        gpu_support_bool = check_support_nvidia(
            machine_type=spec["machine_type"]
        )
        gpu_support = "true" if gpu_support_bool else "false"

        # Write runtime tfvars (moved verbatim from main.py)
        with runtime_file.open("w") as f:
            f.write(f'allocator_ip = "{spec["allocator_ip"]}"\n')
            f.write(f'allocator_url = "{spec["allocator_url"]}"\n')
            f.write(f'machine_type = "{spec["machine_type"]}"\n')
            f.write(f'image_name = "{spec["image_name"]}"\n')
            f.write(f'repository = "{spec["repository"]}"\n')
            f.write(f'client_ami_id = "{spec["client_ami_id"]}"\n')
            f.write(f'subject_software = "{spec["subject_software"]}"\n')
            f.write(f'resource_prefix = "{spec["resource_prefix"]}"\n')
            f.write(f'gpu_support = "{gpu_support}"\n')
            f.write(
                f'cloud_init_output_log_group = '
                f'"{spec["cloud_init_output_log_group"]}"\n'
            )
            f.write(f'region = "{self._region}"\n')
            f.write(f'startup_on_error = "{spec["startup_on_error"]}"\n')
            f.write(f'agent_token = "{spec["agent_token"]}"\n')
            f.write(f'register_token = "{spec["register_token"]}"\n')

        tf_vars = [
            "-var-file=terraform.runtime.tfvars",
            f"-var=instance_count={count}",
        ]
        try:
            sg_id = current_instance_security_group(region=self._region)
            tf_vars.append(f"-var=allocator_sg_id={sg_id}")
        except NotOnEC2Error:
            # Caller may log; we just skip the SG var.
            pass

        # Plan + audit + apply sequence (verbatim from main.py:542-602)
        plan_file = "tfplan.binary"
        plan_file_path = terraform_dir / plan_file
        try:
            subprocess.run(
                ["terraform", "plan", "-no-color", "-out", plan_file, *tf_vars],
                cwd=terraform_dir, check=True, capture_output=True, text=True,
            )
            show = subprocess.run(
                ["terraform", "show", "-json", plan_file],
                cwd=terraform_dir, check=True, capture_output=True, text=True,
            )
            plan_json = json.loads(show.stdout)
            audit_terraform_plan(plan_json)  # may raise SGAuditFailure
            apply_result = subprocess.run(
                ["terraform", "apply", "-auto-approve", plan_file],
                cwd=terraform_dir, check=True, capture_output=True, text=True,
            )
        finally:
            plan_file_path.unlink(missing_ok=True)

        clean_stdout = _ANSI_ESCAPE.sub("", apply_result.stdout)

        # Upload runtime tfvars to S3 (moved from main.py:614-620)
        upload_to_s3(
            local_path=runtime_file,
            env=spec["environment"],
            bucket_name=spec["bucket_name"],
            region=self._region,
            deployment_name=spec.get("deployment_name", "lablink"),
        )

        # Read back the freshly-created instances + timings
        ids = get_instance_ids(terraform_dir=str(terraform_dir))
        names = get_instance_names(terraform_dir=str(terraform_dir))
        timings = get_instance_timings(terraform_dir=str(terraform_dir))

        handles = [
            ClientHandle(
                id=i, hostname=n,
                provider_metadata={"region": self._region},
            )
            for i, n in zip(ids, names)
        ]
        return ProvisionResult(
            handles=handles, timings=timings, apply_stdout=clean_stdout,
        )

    def destroy_hosts(self, handles: list[ClientHandle]) -> None:
        # (unchanged stub — wired in Task 7)
        raise ProviderActionNotWired(
            "AWSProvider.destroy_hosts is not wired in PR B; Terraform "
            "destroy stays inline in main.destroy() until PR D5 Task 7-8."
        )
